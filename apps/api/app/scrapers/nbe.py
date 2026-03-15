"""NBE (National Bank of Egypt) scraper — ahly-net.com.

Login URL: https://www.ahly-net.com/NBE/

Scrape flow
-----------
1. Navigate to the login page.
2. Fill the username field (``#ContentPlaceHolder1_Login1_UserName`` or
   fallback XPath).
3. Fill the password field.
4. Click the login button.
5. Wait for the dashboard account-summary section to appear.
6. Extract account balance and account metadata.
7. Navigate to the transaction history / account statement page.
8. Extract the last 30 transactions.
9. Return a ``ScraperResult``.

Selector strategy
-----------------
Every selector is attempted as a CSS selector first.  If that raises
``TimeoutError`` a resilient XPath fallback is tried.  Each selector is
commented with the element it targets.

Date parsing
------------
NBE uses DD/MM/YYYY for transaction dates (e.g. ``15/03/2025``).  The parser
also handles DD-MM-YYYY and D/M/YYYY variants that occasionally appear in
statement exports.

Amount parsing
--------------
Amounts are formatted with comma thousands-separators and two decimal places
(e.g. ``12,345.67``).  Commas are stripped before Decimal conversion.
Debit/credit direction is inferred from the column the amount appears in or
from an explicit D/C indicator column where present.

External ID
-----------
Generated as ``f"{date_iso}_{description[:20].strip()}_{amount}"`` — this
string is stable across repeated scrapes of the same transaction and matches
the deduplication contract in ``models.db.Transaction``.
"""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional
from uuid import UUID

from bs4 import BeautifulSoup
from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from app.models.db import BankAccount, Transaction
from app.scrapers.base import (
    BankScraper,
    ScraperLoginError,
    ScraperParseError,
    ScraperResult,
    ScraperTimeoutError,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LOGIN_URL = "https://www.ahly-net.com/NBE/"

# Default Playwright wait timeout in milliseconds.
_WAIT_TIMEOUT_MS = 30_000

# Maximum number of transactions to return per scrape run.
_MAX_TRANSACTIONS = 30

# ---------------------------------------------------------------------------
# Selector catalogue
# (CSS primary, XPath fallback, comment describing the target element)
# ---------------------------------------------------------------------------

# Login form — username input
_SEL_USERNAME_CSS = "#ContentPlaceHolder1_Login1_UserName"
_SEL_USERNAME_XPATH = "//input[@type='text' and contains(@id,'UserName')]"

# Login form — password input
_SEL_PASSWORD_CSS = "#ContentPlaceHolder1_Login1_Password"
_SEL_PASSWORD_XPATH = "//input[@type='password' and contains(@id,'Password')]"

# Login form — submit button
_SEL_LOGIN_BTN_CSS = "#ContentPlaceHolder1_Login1_LoginButton"
_SEL_LOGIN_BTN_XPATH = "//input[@type='submit' and contains(@value,'Login')]"

# Dashboard — account summary container (presence confirms successful login)
_SEL_DASHBOARD_CSS = "#ContentPlaceHolder1_GridView_AccSummary"
_SEL_DASHBOARD_XPATH = "//table[contains(@id,'AccSummary')]"

# Dashboard — bad-credentials error message
_SEL_LOGIN_ERROR_CSS = ".failureNotification"
_SEL_LOGIN_ERROR_XPATH = "//*[contains(@class,'failureNotification')]"

# Transaction history navigation link
_SEL_TXN_LINK_CSS = "a[href*='AccountStatement']"
_SEL_TXN_LINK_XPATH = "//a[contains(@href,'AccountStatement') or contains(text(),'Statement')]"

# Transaction history — the data table
_SEL_TXN_TABLE_CSS = "#ContentPlaceHolder1_GridView_TransactionList"
_SEL_TXN_TABLE_XPATH = "//table[contains(@id,'TransactionList')]"


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


def _parse_nbe_date(raw: str) -> Optional[date]:
    """Parse a date string from NBE's various date formats.

    Tried formats:
    - ``DD/MM/YYYY`` (primary)
    - ``D/M/YYYY``
    - ``DD-MM-YYYY``

    Returns ``None`` if no format matches so callers can decide whether to skip
    the row or raise ``ScraperParseError``.
    """
    raw = raw.strip()
    for fmt in ("%d/%m/%Y", "%-d/%-m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    # Try a more permissive split approach as last resort
    parts = re.split(r"[/\-]", raw)
    if len(parts) == 3:
        try:
            day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
            return date(year, month, day)
        except (ValueError, TypeError):
            pass
    logger.debug("NBE: could not parse date string %r", raw)
    return None


def _parse_amount(raw: str) -> Optional[Decimal]:
    """Strip thousands separators and convert to Decimal.

    Returns ``None`` on parse failure so the caller can skip or flag the row.
    """
    cleaned = raw.strip().replace(",", "").replace(" ", "")
    if not cleaned or cleaned in ("-", "N/A", "—"):
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        logger.debug("NBE: could not parse amount %r", raw)
        return None


def _make_external_id(txn_date: date, description: str, amount: Decimal) -> str:
    """Produce a stable deduplication key for a transaction row.

    The key is the first 12 hex characters of the SHA-256 hash of the
    canonical string ``{date_iso}|{description_truncated}|{amount}``.
    This is compact, deterministic, and collision-resistant for banking data.
    """
    canonical = f"{txn_date.isoformat()}|{description[:40].strip()}|{amount}"
    return hashlib.sha256(canonical.encode()).hexdigest()[:24]


# ---------------------------------------------------------------------------
# Sentinel UUIDs used for scraper-layer Transaction objects
# (pipeline layer replaces these with real DB-assigned values)
# ---------------------------------------------------------------------------
_ZERO_UUID = UUID("00000000-0000-0000-0000-000000000000")


# ---------------------------------------------------------------------------
# NBE scraper
# ---------------------------------------------------------------------------


class NBEScraper(BankScraper):
    """Scraper for the National Bank of Egypt internet banking portal.

    Portal: https://www.ahly-net.com/NBE/
    """

    bank_name: str = "NBE"

    async def scrape(self) -> ScraperResult:
        """Execute the full NBE scrape cycle.

        Returns:
            ``ScraperResult`` containing account details and up to
            ``_MAX_TRANSACTIONS`` transaction rows.

        Raises:
            ScraperLoginError: If the portal rejects the credentials.
            ScraperTimeoutError: If any Playwright wait exceeds its deadline.
            ScraperParseError: If the HTML structure is not as expected.
        """
        browser, context, page = await self._launch_browser()
        raw_html: dict[str, str] = {}

        try:
            await self._navigate_to_login(page)
            await self._login(page)
            await self._wait_for_dashboard(page)

            # Capture dashboard HTML for audit trail
            raw_html["dashboard"] = await page.content()

            account = await self._extract_account(page)
            logger.info(
                "NBE: account extracted — masked=%s balance=%s %s",
                account.account_number_masked,
                account.balance,
                account.currency,
            )

            await self._navigate_to_transactions(page)
            raw_html["transactions"] = await page.content()

            transactions = await self._extract_transactions(page, account)
            logger.info("NBE: extracted %d transactions", len(transactions))

            return ScraperResult(
                account=account,
                transactions=transactions,
                raw_html=raw_html,
            )

        except (ScraperLoginError, ScraperTimeoutError, ScraperParseError):
            raise

        except PlaywrightTimeoutError as exc:
            await self._safe_screenshot(page, "timeout_error")
            raise ScraperTimeoutError(
                f"NBE page operation timed out: {exc}", bank_code="NBE"
            ) from exc

        except Exception as exc:
            await self._safe_screenshot(page, "unexpected_error")
            raise ScraperParseError(
                f"NBE unexpected error during scrape: {type(exc).__name__}: {exc}",
                bank_code="NBE",
            ) from exc

        finally:
            await self._close_browser(browser)

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    async def _navigate_to_login(self, page: Page) -> None:
        """Navigate to the NBE login page and wait for the username field."""
        logger.debug("NBE: navigating to login page %s", _LOGIN_URL)
        try:
            await page.goto(_LOGIN_URL, wait_until="domcontentloaded", timeout=_WAIT_TIMEOUT_MS)
        except PlaywrightTimeoutError as exc:
            raise ScraperTimeoutError(
                "NBE login page did not load within timeout", bank_code="NBE"
            ) from exc

        await self._wait_for_selector(page, _SEL_USERNAME_CSS, _SEL_USERNAME_XPATH, "username field")

    async def _navigate_to_transactions(self, page: Page) -> None:
        """Click the Account Statement link and wait for the transaction table."""
        logger.debug("NBE: navigating to transaction history")
        await self._random_delay(1.5, 3.0)

        link = await self._try_selector(page, _SEL_TXN_LINK_CSS, _SEL_TXN_LINK_XPATH)
        if link is None:
            await self._safe_screenshot(page, "txn_link_missing")
            raise ScraperParseError(
                "NBE: could not find Account Statement navigation link",
                bank_code="NBE",
            )

        await link.click()
        await self._random_delay(2.0, 4.0)

        try:
            await self._wait_for_selector(
                page, _SEL_TXN_TABLE_CSS, _SEL_TXN_TABLE_XPATH, "transaction table"
            )
        except ScraperTimeoutError:
            await self._safe_screenshot(page, "txn_table_missing")
            raise

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    async def _login(self, page: Page) -> None:
        """Fill the login form and submit it.

        Credentials are typed character-by-character via ``_type_human`` to
        mimic natural input.  Both credential variables are deleted from local
        scope in the ``finally`` block.
        """
        username = self._username  # plaintext — already decrypted by router
        password = self._password  # plaintext — already decrypted by router
        try:
            logger.debug("NBE: filling login form for user=***")
            await self._type_human(page, _SEL_USERNAME_CSS, username)
            await self._random_delay(0.8, 1.8)
            await self._type_human(page, _SEL_PASSWORD_CSS, password)
            await self._random_delay(1.0, 2.0)

            # Click the login button
            login_btn = await self._try_selector(
                page, _SEL_LOGIN_BTN_CSS, _SEL_LOGIN_BTN_XPATH
            )
            if login_btn is None:
                raise ScraperParseError(
                    "NBE: could not find login submit button", bank_code="NBE"
                )
            await login_btn.click()
            await self._random_delay(2.0, 4.0)
        finally:
            # Overwrite local references — actual credential values remain in
            # self._username / self._password per the router contract.
            del username
            del password

    async def _wait_for_dashboard(self, page: Page) -> None:
        """Wait for the account summary element that indicates successful login.

        If the error-notification element appears instead, raise
        ``ScraperLoginError``.
        """
        # First check if a login-error message appeared (bad credentials)
        try:
            error_el = await page.query_selector(_SEL_LOGIN_ERROR_CSS)
            if error_el is None:
                error_el = await page.query_selector(
                    f"xpath={_SEL_LOGIN_ERROR_XPATH}"
                )
            if error_el is not None:
                error_text = (await error_el.inner_text()).strip()
                logger.warning("NBE: login failure message detected: %r", error_text)
                raise ScraperLoginError(
                    "NBE: portal rejected credentials", bank_code="NBE"
                )
        except ScraperLoginError:
            raise
        except Exception:
            pass  # Absence of error element is expected; proceed

        # Wait for the dashboard account-summary table
        try:
            await self._wait_for_selector(
                page,
                _SEL_DASHBOARD_CSS,
                _SEL_DASHBOARD_XPATH,
                "dashboard account summary",
            )
        except ScraperTimeoutError:
            # If dashboard never appeared AND there's still no error element,
            # the portal may be showing an OTP page or maintenance message.
            await self._safe_screenshot(page, "dashboard_timeout")
            raise

    # ------------------------------------------------------------------
    # Data extraction — account
    # ------------------------------------------------------------------

    async def _extract_account(self, page: Page) -> BankAccount:
        """Extract account details from the dashboard account-summary table.

        The NBE dashboard shows a ``GridView`` table with one row per account.
        We target the first row (primary account).  Columns are:
        0: Account Number | 1: Account Type | 2: Currency | 3: Balance

        Returns a ``BankAccount`` with sentinel ``id``, ``user_id``,
        ``created_at``, ``updated_at`` that the pipeline layer will replace.
        """
        html = await page.content()
        soup = BeautifulSoup(html, "lxml")

        # Find the account summary table — try by known ID first
        table = soup.find("table", id=re.compile(r"AccSummary", re.I))
        if table is None:
            # Fallback: first table with an "Account Number" header
            for t in soup.find_all("table"):
                headers = [th.get_text(strip=True).lower() for th in t.find_all("th")]
                if any("account" in h for h in headers):
                    table = t
                    break

        if table is None:
            await self._safe_screenshot(page, "account_table_missing")
            raise ScraperParseError(
                "NBE: could not locate account summary table on dashboard",
                bank_code="NBE",
            )

        rows = table.find_all("tr")
        data_rows = [r for r in rows if r.find("td")]
        if not data_rows:
            raise ScraperParseError(
                "NBE: account summary table contains no data rows", bank_code="NBE"
            )

        cells = [td.get_text(strip=True) for td in data_rows[0].find_all("td")]
        logger.debug("NBE: account row cells: %r", cells)

        if len(cells) < 3:
            raise ScraperParseError(
                f"NBE: expected ≥3 columns in account row, got {len(cells)}",
                bank_code="NBE",
            )

        # Column mapping (positional — tolerant of extra columns)
        raw_account_number = cells[0] if len(cells) > 0 else ""
        account_type_raw = cells[1].lower() if len(cells) > 1 else "current"
        currency = cells[2].upper() if len(cells) > 2 else "EGP"
        balance_raw = cells[3] if len(cells) > 3 else "0.00"

        # Normalise account type to one of the allowed values
        account_type = _normalise_account_type(account_type_raw)
        currency = _normalise_currency(currency)

        balance = _parse_amount(balance_raw) or Decimal("0.00")
        masked = self._mask_account_number(raw_account_number)

        now = datetime.now(timezone.utc)
        return BankAccount(
            id=_ZERO_UUID,
            user_id=_ZERO_UUID,
            bank_name=self.bank_name,
            account_number_masked=masked,
            account_type=account_type,
            currency=currency,
            balance=balance,
            is_active=True,
            last_synced_at=now,
            created_at=now,
            updated_at=now,
        )

    # ------------------------------------------------------------------
    # Data extraction — transactions
    # ------------------------------------------------------------------

    async def _extract_transactions(
        self, page: Page, account: BankAccount
    ) -> list[Transaction]:
        """Parse the transaction history table and return Transaction objects.

        Expects a table with columns:
        Date | Value Date | Description | Debit | Credit | Balance

        Debit/Credit columns may be reversed or use a single Amount + D/C column
        on some portal versions.  The parser handles both layouts.

        Returns up to ``_MAX_TRANSACTIONS`` rows, most-recent first.
        """
        html = await page.content()
        soup = BeautifulSoup(html, "lxml")

        # Locate the transaction table
        table = soup.find("table", id=re.compile(r"TransactionList", re.I))
        if table is None:
            # Fallback: find a table whose headers mention "date" and "debit"
            for t in soup.find_all("table"):
                headers_text = t.get_text(separator=" ").lower()
                if "debit" in headers_text and "credit" in headers_text:
                    table = t
                    break

        if table is None:
            await self._safe_screenshot(page, "txn_table_parse_error")
            raise ScraperParseError(
                "NBE: could not locate transaction table", bank_code="NBE"
            )

        # Resolve column indices from the header row
        header_row = table.find("tr")
        if header_row is None:
            raise ScraperParseError(
                "NBE: transaction table has no header row", bank_code="NBE"
            )

        headers = [th.get_text(strip=True).lower() for th in header_row.find_all(["th", "td"])]
        logger.debug("NBE: transaction table headers: %r", headers)

        col = _resolve_txn_columns(headers)

        transactions: list[Transaction] = []
        now = datetime.now(timezone.utc)
        data_rows = [r for r in table.find_all("tr") if r.find("td")]

        for row_idx, row in enumerate(data_rows[:_MAX_TRANSACTIONS]):
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if not cells or len(cells) < 3:
                continue

            try:
                txn = _parse_transaction_row(cells, col, account, now)
            except Exception as exc:
                logger.debug(
                    "NBE: skipping row %d due to parse error: %s", row_idx, exc
                )
                continue

            if txn is not None:
                transactions.append(txn)

        return transactions

    # ------------------------------------------------------------------
    # Selector helpers
    # ------------------------------------------------------------------

    async def _wait_for_selector(
        self, page: Page, css: str, xpath: str, label: str
    ) -> None:
        """Wait for either the CSS or XPath selector to appear on the page.

        Tries the CSS selector first (30 s timeout).  If it times out, falls
        back to the XPath selector (additional 15 s).  Raises
        ``ScraperTimeoutError`` if both fail.

        Args:
            page: Active Playwright page.
            css: CSS selector string.
            xpath: XPath expression string (must not include leading ``//`` —
                pass the raw XPath; the method prepends ``xpath=`` as needed).
            label: Human-readable name used only in error messages.
        """
        try:
            await page.wait_for_selector(css, timeout=_WAIT_TIMEOUT_MS)
            return
        except PlaywrightTimeoutError:
            logger.debug("NBE: CSS selector %r timed out, trying XPath", css)

        try:
            await page.wait_for_selector(f"xpath={xpath}", timeout=15_000)
        except PlaywrightTimeoutError as exc:
            raise ScraperTimeoutError(
                f"NBE: {label} not found within timeout (css={css!r})", bank_code="NBE"
            ) from exc

    async def _try_selector(self, page: Page, css: str, xpath: str):  # type: ignore[return]
        """Return the first matching element or ``None``.

        Tries CSS first, then XPath.  Does not wait — returns immediately with
        whatever is currently in the DOM.
        """
        el = await page.query_selector(css)
        if el is not None:
            return el
        return await page.query_selector(f"xpath={xpath}")


# ---------------------------------------------------------------------------
# Module-level parsing helpers
# ---------------------------------------------------------------------------


def _normalise_account_type(raw: str) -> str:
    """Map a raw account-type string to one of the allowed DB values."""
    raw = raw.lower().strip()
    if "saving" in raw or "توفير" in raw:
        return "savings"
    if "credit" in raw or "ائتمان" in raw:
        return "credit"
    if "loan" in raw or "قرض" in raw:
        return "loan"
    return "current"  # default


def _normalise_currency(raw: str) -> str:
    """Return a valid ISO 4217 code or fall back to EGP."""
    raw = raw.upper().strip()
    known = {"EGP", "USD", "EUR", "GBP", "SAR", "AED"}
    return raw if raw in known else "EGP"


def _resolve_txn_columns(headers: list[str]) -> dict[str, int]:
    """Map logical column names to their zero-based indices.

    Falls back to positional defaults if headers cannot be matched.

    Returned keys: ``date``, ``value_date``, ``description``, ``debit``,
    ``credit``, ``balance``.  Any unresolved key maps to ``-1`` (caller must
    handle ``-1`` as "not available").
    """
    col: dict[str, int] = {
        "date": -1,
        "value_date": -1,
        "description": -1,
        "debit": -1,
        "credit": -1,
        "balance": -1,
    }

    for i, h in enumerate(headers):
        if col["date"] == -1 and re.search(r"\bdate\b|\btransaction date\b", h):
            col["date"] = i
        elif col["value_date"] == -1 and re.search(r"value\s*date", h):
            col["value_date"] = i
        elif col["description"] == -1 and re.search(r"descri|narrat|detail|remark", h):
            col["description"] = i
        elif col["debit"] == -1 and re.search(r"debit|withdraw|dr\b", h):
            col["debit"] = i
        elif col["credit"] == -1 and re.search(r"credit|deposit|cr\b", h):
            col["credit"] = i
        elif col["balance"] == -1 and re.search(r"balance|bal\b", h):
            col["balance"] = i

    # Apply positional defaults for any still-unresolved column
    defaults = {
        "date": 0,
        "value_date": 1,
        "description": 2,
        "debit": 3,
        "credit": 4,
        "balance": 5,
    }
    for key, default_idx in defaults.items():
        if col[key] == -1 and default_idx < len(headers):
            col[key] = default_idx

    return col


def _parse_transaction_row(
    cells: list[str],
    col: dict[str, int],
    account: BankAccount,
    now: datetime,
) -> Optional[Transaction]:
    """Convert a list of cell strings into a ``Transaction`` object.

    Returns ``None`` if the row is empty or a header repeat.
    """
    def cell(key: str) -> str:
        idx = col.get(key, -1)
        if idx == -1 or idx >= len(cells):
            return ""
        return cells[idx].strip()

    date_str = cell("date")
    if not date_str or date_str.lower() in ("date", "تاريخ", "-"):
        return None

    txn_date = _parse_nbe_date(date_str)
    if txn_date is None:
        return None

    value_date_str = cell("value_date")
    value_date: Optional[date] = _parse_nbe_date(value_date_str) if value_date_str else None

    description = cell("description") or "N/A"

    debit_str = cell("debit")
    credit_str = cell("credit")
    balance_str = cell("balance")

    debit_amount = _parse_amount(debit_str)
    credit_amount = _parse_amount(credit_str)
    balance_after = _parse_amount(balance_str)

    # Determine direction and amount
    if debit_amount and debit_amount > 0:
        transaction_type = "debit"
        amount = debit_amount
    elif credit_amount and credit_amount > 0:
        transaction_type = "credit"
        amount = credit_amount
    else:
        # Both columns empty — skip the row
        return None

    external_id = _make_external_id(txn_date, description, amount)

    return Transaction(
        id=uuid.UUID("00000000-0000-0000-0000-000000000000"),
        user_id=uuid.UUID("00000000-0000-0000-0000-000000000000"),
        account_id=uuid.UUID("00000000-0000-0000-0000-000000000000"),
        external_id=external_id,
        amount=amount,
        currency=account.currency,
        transaction_type=transaction_type,
        description=description,
        category=None,
        sub_category=None,
        transaction_date=txn_date,
        value_date=value_date,
        balance_after=balance_after,
        raw_data={
            "cells": cells,
            "source": "nbe",
        },
        is_categorized=False,
        created_at=now,
        updated_at=now,
    )
