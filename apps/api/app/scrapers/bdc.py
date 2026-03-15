"""BDC (Banque Du Caire) scraper — ibanking.bdcbank.com.eg.

Login URL: https://ibanking.bdcbank.com.eg/

Scrape flow
-----------
1. Navigate to the login page.
2. Fill the username / customer number field.
3. Fill the password field.
4. Click the login / "Sign In" button.
5. Wait for the post-login dashboard to confirm authentication.
6. Extract account balance and account metadata from the account summary table.
7. Navigate to the Account Statement section.
8. Extract the last 30 transactions.
9. Return a ``ScraperResult``.

Portal notes
------------
- BDC's portal is served from ``ibanking.bdcbank.com.eg``.
- The login form typically uses an ASP.NET-style WebForms structure similar to
  NBE, with named ContentPlaceHolder IDs.
- Date format in statements: ``DD/MM/YYYY`` (primary).  Some views also emit
  ``DD-MM-YYYY``.  Both are handled by ``_parse_bdc_date``.
- Amounts use comma thousands-separators and may be prefixed with an Arabic
  "EGP" symbol or the Latin string "EGP".  The ``_parse_amount`` helper strips
  all non-numeric characters except ``.`` and ``-`` before Decimal conversion.
- The portal may display an "announcement" or session-warning modal after
  login.  The scraper dismisses it if present.

Selector strategy
-----------------
Every selector is tried as CSS first; if that times out, an XPath fallback is
attempted.  All selectors are commented with the element they target.
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

_LOGIN_URL = "https://ibanking.bdcbank.com.eg/"

# Default Playwright wait timeout in milliseconds.
_WAIT_TIMEOUT_MS = 30_000

# Maximum transactions to return per scrape run.
_MAX_TRANSACTIONS = 30

# ---------------------------------------------------------------------------
# Selector catalogue
# (CSS primary, XPath fallback, comment describing the target element)
# ---------------------------------------------------------------------------

# Login form — username / customer number field
_SEL_USERNAME_CSS = (
    "input[id*='UserName'], input[id*='username'], "
    "input[name*='username'], input[name*='UserName']"
)
_SEL_USERNAME_XPATH = (
    "//input[contains(@id,'UserName') or contains(@id,'username') "
    "or contains(@name,'username') or contains(@placeholder,'User') "
    "or contains(@placeholder,'Customer')]"
)

# Login form — password field
_SEL_PASSWORD_CSS = "input[type='password']"
_SEL_PASSWORD_XPATH = "//input[@type='password']"

# Login form — submit / sign-in button
_SEL_LOGIN_BTN_CSS = (
    "input[type='submit'], button[type='submit'], "
    "button[id*='Login'], input[id*='LoginButton']"
)
_SEL_LOGIN_BTN_XPATH = (
    "//input[@type='submit' or contains(@id,'Login')] | "
    "//button[@type='submit' or contains(@id,'login') "
    "or contains(text(),'Sign In') or contains(text(),'Login') "
    "or contains(text(),'تسجيل')]"
)

# Dashboard — element that confirms successful login (account summary table)
_SEL_DASHBOARD_CSS = (
    "table[id*='AccSummary'], table[id*='AccountSummary'], "
    ".account-summary, [class*='accountSummary']"
)
_SEL_DASHBOARD_XPATH = (
    "//table[contains(@id,'AccSummary') or contains(@id,'AccountSummary')] | "
    "//*[contains(@class,'account-summary') or contains(@class,'accountSummary')]"
)

# Login error — bad-credentials notification element
_SEL_LOGIN_ERROR_CSS = (
    ".failureNotification, .error-message, .alert-danger, "
    "[class*='loginError'], [class*='FailureText']"
)
_SEL_LOGIN_ERROR_XPATH = (
    "//*[contains(@class,'failureNotification') or contains(@class,'FailureText') "
    "or contains(@class,'error-message') or contains(@class,'alert-danger') "
    "or contains(@class,'loginError')]"
)

# Post-login modal / announcement close button (dismissed if present)
_SEL_MODAL_CLOSE_CSS = (
    ".modal .close, .modal-close, button[aria-label='Close'], "
    "[data-dismiss='modal'], .ui-dialog-titlebar-close"
)
_SEL_MODAL_CLOSE_XPATH = (
    "//button[@aria-label='Close' or @data-dismiss='modal' "
    "or contains(@class,'modal-close') or contains(@class,'ui-dialog-titlebar-close')]"
)

# Account statement / transaction history navigation link
_SEL_STMT_LINK_CSS = (
    "a[href*='AccountStatement'], a[href*='Statement'], "
    "a[href*='statement'], a[href*='Transactions']"
)
_SEL_STMT_LINK_XPATH = (
    "//a[contains(@href,'AccountStatement') or contains(@href,'Statement') "
    "or contains(@href,'statement') or contains(@href,'Transactions') "
    "or contains(text(),'Account Statement') or contains(text(),'Statement') "
    "or contains(text(),'كشف الحساب')]"
)

# Transaction table in the statement view
_SEL_TXN_TABLE_CSS = (
    "table[id*='TransactionList'], table[id*='transaction'], "
    "table[class*='transaction'], table[class*='statement']"
)
_SEL_TXN_TABLE_XPATH = (
    "//table[contains(@id,'TransactionList') or contains(@id,'transaction') "
    "or contains(@class,'transaction') or contains(@class,'statement')]"
)

# ---------------------------------------------------------------------------
# Sentinel UUID — replaced by pipeline layer
# ---------------------------------------------------------------------------
_ZERO_UUID = UUID("00000000-0000-0000-0000-000000000000")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_bdc_date(raw: str) -> Optional[date]:
    """Parse a date string from BDC's portal.

    Supported formats:
    - ``DD/MM/YYYY`` (primary)
    - ``DD-MM-YYYY``
    - ``D/M/YYYY`` (single-digit day/month variants)

    Returns ``None`` if no format matches so callers can decide whether to skip
    the row or raise ``ScraperParseError``.
    """
    raw = raw.strip()

    # Try strptime patterns first (fastest path)
    for fmt in ("%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue

    # Permissive split approach — handles D/M/YYYY and mixed separators
    parts = re.split(r"[/\-]", raw)
    if len(parts) == 3:
        try:
            day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
            return date(year, month, day)
        except (ValueError, TypeError):
            pass

    logger.debug("BDC: could not parse date string %r", raw)
    return None


def _parse_amount(raw: str) -> Optional[Decimal]:
    """Strip thousands-separators, currency symbols, and Arabic text; parse as Decimal.

    Handles inputs such as:
    - ``12,345.67``
    - ``EGP 12,345.67``
    - ``12,345.67 EGP``
    - Arabic-prefixed or suffixed currency labels

    Returns ``None`` if the string is empty, a dash, or otherwise not numeric.
    """
    # Remove known non-numeric prefixes/suffixes
    cleaned = raw.strip()
    cleaned = re.sub(r"[A-Za-z\u0600-\u06FF]", "", cleaned)  # strip Latin + Arabic letters
    cleaned = cleaned.replace(",", "").replace(" ", "")
    if not cleaned or cleaned in ("-", "—", "N/A"):
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        logger.debug("BDC: could not parse amount %r", raw)
        return None


def _make_external_id(txn_date: date, description: str, amount: Decimal) -> str:
    """Produce a stable SHA-256-based deduplication key (first 24 hex chars).

    The canonical string ``{date_iso}|{description_truncated}|{amount}`` is
    deterministic across repeated scrapes of the same transaction row.
    """
    canonical = f"{txn_date.isoformat()}|{description[:40].strip()}|{amount}"
    return hashlib.sha256(canonical.encode()).hexdigest()[:24]


def _normalise_account_type(raw: str) -> str:
    """Map a raw account-type string to one of the allowed DB values."""
    raw = raw.lower().strip()
    if "saving" in raw or "توفير" in raw:
        return "savings"
    if "credit" in raw or "ائتمان" in raw:
        return "credit"
    if "loan" in raw or "قرض" in raw:
        return "loan"
    return "current"


def _normalise_currency(raw: str) -> str:
    """Return a valid ISO 4217 code or fall back to EGP."""
    raw = raw.upper().strip()
    known = {"EGP", "USD", "EUR", "GBP", "SAR", "AED"}
    return raw if raw in known else "EGP"


def _resolve_txn_columns(headers: list[str]) -> dict[str, int]:
    """Map logical column names to zero-based indices from header strings.

    Returns a dict with keys: ``date``, ``value_date``, ``description``,
    ``debit``, ``credit``, ``balance``.  Unresolved columns map to ``-1``.
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
        h_lower = h.lower()
        if col["date"] == -1 and re.search(
            r"transaction\s*date|^date$|posting|تاريخ", h_lower
        ):
            col["date"] = i
        elif col["value_date"] == -1 and re.search(r"value\s*date", h_lower):
            col["value_date"] = i
        elif col["description"] == -1 and re.search(
            r"descri|narrat|detail|remark|particular|بيان", h_lower
        ):
            col["description"] = i
        elif col["debit"] == -1 and re.search(r"debit|withdraw|dr\b|مدين", h_lower):
            col["debit"] = i
        elif col["credit"] == -1 and re.search(r"credit|deposit|cr\b|دائن", h_lower):
            col["credit"] = i
        elif col["balance"] == -1 and re.search(r"^balance$|running\s*bal|رصيد", h_lower):
            col["balance"] = i

    # Positional defaults for any still-unresolved column
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
    """Convert a list of cell strings into a ``Transaction`` or return ``None`` to skip."""

    def cell(key: str) -> str:
        idx = col.get(key, -1)
        if idx == -1 or idx >= len(cells):
            return ""
        return cells[idx].strip()

    date_str = cell("date")
    if not date_str or date_str.lower() in ("date", "تاريخ", "-"):
        return None

    txn_date = _parse_bdc_date(date_str)
    if txn_date is None:
        return None

    value_date_str = cell("value_date")
    value_date: Optional[date] = (
        _parse_bdc_date(value_date_str) if value_date_str else None
    )

    description = cell("description") or "N/A"

    debit_amount = _parse_amount(cell("debit"))
    credit_amount = _parse_amount(cell("credit"))
    balance_after = _parse_amount(cell("balance"))

    if debit_amount and debit_amount > 0:
        transaction_type = "debit"
        amount = debit_amount
    elif credit_amount and credit_amount > 0:
        transaction_type = "credit"
        amount = credit_amount
    else:
        return None  # Row has no usable amount

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
            "source": "bdc",
        },
        is_categorized=False,
        created_at=now,
        updated_at=now,
    )


# ---------------------------------------------------------------------------
# BDC scraper
# ---------------------------------------------------------------------------


class BDCScraper(BankScraper):
    """Scraper for the Banque Du Caire internet banking portal.

    Portal: https://ibanking.bdcbank.com.eg/
    """

    bank_name: str = "BDC"

    async def scrape(self) -> ScraperResult:
        """Execute the full BDC scrape cycle.

        Returns:
            ``ScraperResult`` with account details and up to
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
            await self._dismiss_modal_if_present(page)

            # Capture dashboard HTML for audit trail
            raw_html["dashboard"] = await page.content()

            account = await self._extract_account(page)
            logger.info(
                "BDC: account extracted — masked=%s balance=%s %s",
                account.account_number_masked,
                account.balance,
                account.currency,
            )

            await self._navigate_to_statement(page)
            raw_html["transactions"] = await page.content()

            transactions = await self._extract_transactions(page, account)
            logger.info("BDC: extracted %d transactions", len(transactions))

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
                f"BDC page operation timed out: {exc}", bank_code="BDC"
            ) from exc

        except Exception as exc:
            await self._safe_screenshot(page, "unexpected_error")
            raise ScraperParseError(
                f"BDC unexpected error during scrape: {type(exc).__name__}: {exc}",
                bank_code="BDC",
            ) from exc

        finally:
            await self._close_browser(browser)

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    async def _navigate_to_login(self, page: Page) -> None:
        """Load the BDC login page and verify the username field is present."""
        logger.debug("BDC: navigating to login page %s", _LOGIN_URL)
        try:
            await page.goto(
                _LOGIN_URL, wait_until="domcontentloaded", timeout=_WAIT_TIMEOUT_MS
            )
        except PlaywrightTimeoutError as exc:
            raise ScraperTimeoutError(
                "BDC login page did not load within timeout", bank_code="BDC"
            ) from exc

        await self._wait_for_selector(
            page, _SEL_USERNAME_CSS, _SEL_USERNAME_XPATH, "username field"
        )

    async def _navigate_to_statement(self, page: Page) -> None:
        """Click the Account Statement link and wait for the transaction table."""
        logger.debug("BDC: navigating to account statement")
        await self._random_delay(1.5, 3.0)

        link = await self._try_selector(page, _SEL_STMT_LINK_CSS, _SEL_STMT_LINK_XPATH)
        if link is None:
            await self._safe_screenshot(page, "stmt_link_missing")
            raise ScraperParseError(
                "BDC: could not find Account Statement navigation link",
                bank_code="BDC",
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
        """Type credentials into the login form and submit.

        Credentials are deleted from local scope in the ``finally`` block.
        Neither username nor password is ever logged.
        """
        username = self._username
        password = self._password
        try:
            logger.debug("BDC: filling login form for user=***")
            await self._type_human(page, _SEL_USERNAME_CSS, username)
            await self._random_delay(0.8, 1.8)
            await self._type_human(page, _SEL_PASSWORD_CSS, password)
            await self._random_delay(1.0, 2.0)

            login_btn = await self._try_selector(
                page, _SEL_LOGIN_BTN_CSS, _SEL_LOGIN_BTN_XPATH
            )
            if login_btn is None:
                raise ScraperParseError(
                    "BDC: could not find login submit button", bank_code="BDC"
                )
            await login_btn.click()
            await self._random_delay(2.0, 4.0)
        finally:
            del username
            del password

    async def _wait_for_dashboard(self, page: Page) -> None:
        """Confirm successful authentication by waiting for the dashboard element.

        If a login-error message appears before the dashboard loads, raise
        ``ScraperLoginError``.
        """
        # Check for an immediate login error message
        try:
            error_el = await page.query_selector(_SEL_LOGIN_ERROR_CSS)
            if error_el is None:
                error_el = await page.query_selector(f"xpath={_SEL_LOGIN_ERROR_XPATH}")
            if error_el is not None:
                err_text = (await error_el.inner_text()).strip()
                logger.warning("BDC: login failure message detected: %r", err_text)
                raise ScraperLoginError(
                    "BDC: portal rejected credentials", bank_code="BDC"
                )
        except ScraperLoginError:
            raise
        except Exception:
            pass  # Absence of error element is expected; proceed

        # Wait for the dashboard account-summary element
        try:
            await self._wait_for_selector(
                page,
                _SEL_DASHBOARD_CSS,
                _SEL_DASHBOARD_XPATH,
                "dashboard account summary",
            )
        except ScraperTimeoutError:
            await self._safe_screenshot(page, "dashboard_timeout")
            raise

    async def _dismiss_modal_if_present(self, page: Page) -> None:
        """Close any announcement or session-warning modal blocking the dashboard.

        Non-fatal — if no modal is found the method returns silently.
        """
        try:
            close_btn = await self._try_selector(
                page, _SEL_MODAL_CLOSE_CSS, _SEL_MODAL_CLOSE_XPATH
            )
            if close_btn is not None:
                logger.debug("BDC: dismissing modal overlay")
                await close_btn.click()
                await self._random_delay(0.5, 1.5)
        except Exception as exc:
            logger.debug("BDC: modal dismiss error (ignored): %s", exc)

    # ------------------------------------------------------------------
    # Data extraction — account
    # ------------------------------------------------------------------

    async def _extract_account(self, page: Page) -> BankAccount:
        """Extract account metadata from the dashboard account-summary table.

        BDC's dashboard typically renders a GridView-style table with one row
        per account.  Expected columns (positional):
        0: Account Number | 1: Account Type | 2: Currency | 3: Balance

        Falls back to scanning all tables for a row that contains a recognisable
        balance figure if the primary table is not found by its ID.

        Returns a ``BankAccount`` with sentinel ``id``, ``user_id``,
        ``created_at``, ``updated_at`` that the pipeline layer will replace.
        """
        html = await page.content()
        soup = BeautifulSoup(html, "lxml")

        # Strategy 1: find by known ID patterns
        table = soup.find("table", id=re.compile(r"AccSummary|AccountSummary", re.I))
        if table is None:
            # Strategy 2: first table whose header row contains "account"
            for t in soup.find_all("table"):
                headers_text = " ".join(
                    th.get_text(strip=True).lower() for th in t.find_all(["th", "td"])
                )
                if "account" in headers_text or "حساب" in headers_text:
                    table = t
                    break

        if table is None:
            await self._safe_screenshot(page, "account_table_missing")
            raise ScraperParseError(
                "BDC: could not locate account summary table on dashboard",
                bank_code="BDC",
            )

        rows = table.find_all("tr")
        data_rows = [r for r in rows if r.find("td")]
        if not data_rows:
            raise ScraperParseError(
                "BDC: account summary table contains no data rows", bank_code="BDC"
            )

        cells = [td.get_text(strip=True) for td in data_rows[0].find_all("td")]
        logger.debug("BDC: account row cells: %r", cells)

        if len(cells) < 3:
            raise ScraperParseError(
                f"BDC: expected ≥3 columns in account row, got {len(cells)}",
                bank_code="BDC",
            )

        raw_account_number = cells[0] if len(cells) > 0 else ""
        account_type_raw = cells[1].lower() if len(cells) > 1 else "current"
        currency = cells[2].upper() if len(cells) > 2 else "EGP"
        balance_raw = cells[3] if len(cells) > 3 else "0.00"

        account_type = _normalise_account_type(account_type_raw)
        currency = _normalise_currency(currency)
        balance = _parse_amount(balance_raw) or Decimal("0.00")
        masked = (
            self._mask_account_number(raw_account_number)
            if raw_account_number
            else "****0000"
        )

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
        """Parse the account statement table and return Transaction objects.

        Expected columns (BDC format):
        Date | Value Date | Description | Debit | Credit | Balance

        Returns up to ``_MAX_TRANSACTIONS`` rows, most-recent first.
        """
        html = await page.content()
        soup = BeautifulSoup(html, "lxml")

        # Locate the transaction table
        table = soup.find("table", id=re.compile(r"TransactionList|transaction", re.I))
        if table is None:
            table = soup.find(
                "table", class_=re.compile(r"transaction|statement", re.I)
            )

        if table is None:
            # Last resort: find any table that mentions debit and credit in its headers
            for t in soup.find_all("table"):
                raw_text = t.get_text(separator=" ").lower()
                if ("debit" in raw_text or "مدين" in raw_text) and (
                    "credit" in raw_text or "دائن" in raw_text
                ):
                    table = t
                    break

        if table is None:
            await self._safe_screenshot(page, "txn_table_parse_error")
            raise ScraperParseError(
                "BDC: could not locate transaction table in statement page",
                bank_code="BDC",
            )

        # Resolve column indices from the header row
        header_row = table.find("tr")
        if header_row is None:
            raise ScraperParseError(
                "BDC: transaction table has no header row", bank_code="BDC"
            )

        headers = [
            th.get_text(strip=True).lower()
            for th in header_row.find_all(["th", "td"])
        ]
        logger.debug("BDC: transaction table headers: %r", headers)
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
                    "BDC: skipping row %d due to parse error: %s", row_idx, exc
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
        """Wait for a CSS selector, falling back to XPath on timeout.

        Raises ``ScraperTimeoutError`` if both selectors fail within their
        respective timeouts.

        Args:
            page: Active Playwright page.
            css: CSS selector string.
            xpath: XPath expression string.
            label: Human-readable name used only in error messages.
        """
        try:
            await page.wait_for_selector(css, timeout=_WAIT_TIMEOUT_MS)
            return
        except PlaywrightTimeoutError:
            logger.debug("BDC: CSS selector %r timed out, trying XPath", css)

        try:
            await page.wait_for_selector(f"xpath={xpath}", timeout=15_000)
        except PlaywrightTimeoutError as exc:
            raise ScraperTimeoutError(
                f"BDC: {label} not found within timeout (css={css!r})",
                bank_code="BDC",
            ) from exc

    async def _try_selector(self, page: Page, css: str, xpath: str):  # type: ignore[return]
        """Return the first element matching CSS or XPath, or ``None``."""
        el = await page.query_selector(css)
        if el is not None:
            return el
        return await page.query_selector(f"xpath={xpath}")
