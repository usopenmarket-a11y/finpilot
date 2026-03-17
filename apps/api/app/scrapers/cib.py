"""CIB (Commercial International Bank) scraper — online.cibeg.com.

Login URL: https://online.cibeg.com/

Scrape flow
-----------
1. Navigate to the login page.
2. Fill the username/customer-ID field.
3. Fill the password field.
4. Click the login / "Sign In" button.
5. Wait for the post-login dashboard to confirm authentication.
6. Extract account balance and account metadata from the account summary widget.
7. Navigate to the Account Statement section.
8. Extract the last 30 transactions.
9. Return a ``ScraperResult``.

Portal notes (recorded from live observation)
---------------------------------------------
- CIB's portal is a single-page application served from ``online.cibeg.com``.
  The login form is on the home page; after authentication the URL typically
  stays the same but the DOM re-renders with dashboard content.
- The account statement section is reached via a sidebar/menu link that
  contains the text "Account Statement" or navigates to a URL fragment
  containing ``#account-statement`` or ``/accounts/statement``.
- Date format in statements: ``DD-MMM-YYYY`` (e.g. ``15-Jan-2025``).
  Occasionally ``DD/MM/YYYY`` appears in exported CSV-table views.
- Amounts use comma thousands-separators, e.g. ``10,250.00``.
- The portal sometimes displays a one-time "announcement" modal on first login;
  the scraper dismisses it by clicking the modal's close button if present.

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
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from uuid import UUID

from bs4 import BeautifulSoup
from playwright.async_api import Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

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

_LOGIN_URL = "https://online.cibeg.com/"

# Default Playwright wait timeout in milliseconds.
_WAIT_TIMEOUT_MS = 30_000

# Maximum transactions to return per scrape run.
_MAX_TRANSACTIONS = 30

# ---------------------------------------------------------------------------
# Selector catalogue
# ---------------------------------------------------------------------------

# Login form — username / customer ID field
_SEL_USERNAME_CSS = "input[id*='username'], input[id*='Username'], input[name*='username']"
_SEL_USERNAME_XPATH = "//input[contains(@id,'username') or contains(@name,'username') or contains(@placeholder,'User') or contains(@placeholder,'Customer')]"

# Login form — password field
_SEL_PASSWORD_CSS = "input[type='password']"
_SEL_PASSWORD_XPATH = "//input[@type='password']"

# Login form — submit / sign-in button
_SEL_LOGIN_BTN_CSS = (
    "button[type='submit'], input[type='submit'], button[id*='login'], button[id*='Login']"
)
_SEL_LOGIN_BTN_XPATH = "//button[@type='submit' or contains(@id,'login') or contains(text(),'Sign In') or contains(text(),'Login')]"

# Dashboard — any element that confirms a successful login
# CIB typically renders an account balance widget or a welcome greeting
_SEL_DASHBOARD_CSS = (
    ".account-summary, .accounts-list, [class*='accountSummary'], [class*='account-widget']"
)
_SEL_DASHBOARD_XPATH = (
    "//*[contains(@class,'account-summary') or contains(@class,'accounts-list') "
    "or contains(@class,'accountSummary') or contains(@class,'account-widget')]"
)

# Login error indicator
_SEL_LOGIN_ERROR_CSS = ".error-message, .alert-danger, [class*='loginError'], [class*='error-msg']"
_SEL_LOGIN_ERROR_XPATH = (
    "//*[contains(@class,'error-message') or contains(@class,'alert-danger') "
    "or contains(@class,'loginError')]"
)

# Announcement/welcome modal close button (dismissed if present)
_SEL_MODAL_CLOSE_CSS = (
    ".modal .close, .modal-close, button[aria-label='Close'], [data-dismiss='modal']"
)
_SEL_MODAL_CLOSE_XPATH = (
    "//button[@aria-label='Close' or @data-dismiss='modal' or contains(@class,'modal-close')]"
)

# Account Statement navigation link
_SEL_STMT_LINK_CSS = "a[href*='statement'], a[href*='Statement']"
_SEL_STMT_LINK_XPATH = "//a[contains(@href,'statement') or contains(@href,'Statement') or contains(text(),'Account Statement')]"

# Transaction table in the statement view
_SEL_TXN_TABLE_CSS = (
    "table[class*='transaction'], table[id*='transaction'], table[class*='statement']"
)
_SEL_TXN_TABLE_XPATH = (
    "//table[contains(@class,'transaction') or contains(@id,'transaction') "
    "or contains(@class,'statement')]"
)

# ---------------------------------------------------------------------------
# Month-name abbreviation mapping for DD-MMM-YYYY parsing
# ---------------------------------------------------------------------------

_MONTH_ABBR: dict[str, int] = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


# ---------------------------------------------------------------------------
# Sentinel UUID — replaced by pipeline layer
# ---------------------------------------------------------------------------
_ZERO_UUID = UUID("00000000-0000-0000-0000-000000000000")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_cib_date(raw: str) -> date | None:
    """Parse a date string from CIB's portal.

    Supported formats:
    - ``DD-MMM-YYYY`` (primary, e.g. ``15-Jan-2025``)
    - ``DD/MM/YYYY``
    - ``D/M/YYYY``

    Returns ``None`` if no format matches.
    """
    raw = raw.strip()

    # DD-MMM-YYYY — most common CIB format
    m = re.match(r"^(\d{1,2})-([A-Za-z]{3})-(\d{4})$", raw)
    if m:
        day, mon_abbr, year = int(m.group(1)), m.group(2).lower(), int(m.group(3))
        month = _MONTH_ABBR.get(mon_abbr)
        if month:
            try:
                return date(year, month, day)
            except ValueError:
                pass

    # DD/MM/YYYY or D/M/YYYY
    m2 = re.match(r"^(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})$", raw)
    if m2:
        try:
            return date(int(m2.group(3)), int(m2.group(2)), int(m2.group(1)))
        except ValueError:
            pass

    # ISO format fallback
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        pass

    logger.debug("CIB: could not parse date string %r", raw)
    return None


def _parse_amount(raw: str) -> Decimal | None:
    """Strip thousands-separators and parse as Decimal.

    Returns ``None`` if the string is empty, a dash, or otherwise not numeric.
    """
    cleaned = raw.strip().replace(",", "").replace(" ", "")
    if not cleaned or cleaned in ("-", "N/A", "—", ""):
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        logger.debug("CIB: could not parse amount %r", raw)
        return None


def _make_external_id(txn_date: date, description: str, amount: Decimal) -> str:
    """Stable SHA-256-based deduplication key (first 24 hex chars)."""
    canonical = f"{txn_date.isoformat()}|{description[:40].strip()}|{amount}"
    return hashlib.sha256(canonical.encode()).hexdigest()[:24]


def _normalise_account_type(raw: str) -> str:
    raw = raw.lower().strip()
    if "saving" in raw:
        return "savings"
    if "credit" in raw:
        return "credit"
    if "loan" in raw:
        return "loan"
    return "current"


def _normalise_currency(raw: str) -> str:
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
        if col["date"] == -1 and re.search(r"transaction\s*date|^date$|posting", h_lower):
            col["date"] = i
        elif col["value_date"] == -1 and re.search(r"value\s*date", h_lower):
            col["value_date"] = i
        elif col["description"] == -1 and re.search(
            r"descri|narrat|detail|remark|particular", h_lower
        ):
            col["description"] = i
        elif col["debit"] == -1 and re.search(r"debit|withdraw|dr\b", h_lower):
            col["debit"] = i
        elif col["credit"] == -1 and re.search(r"credit|deposit|cr\b", h_lower):
            col["credit"] = i
        elif col["balance"] == -1 and re.search(r"^balance$|running\s*bal", h_lower):
            col["balance"] = i

    # Positional defaults for any unresolved column
    defaults = {"date": 0, "value_date": 1, "description": 2, "debit": 3, "credit": 4, "balance": 5}
    for key, default_idx in defaults.items():
        if col[key] == -1 and default_idx < len(headers):
            col[key] = default_idx

    return col


def _parse_transaction_row(
    cells: list[str],
    col: dict[str, int],
    account: BankAccount,
    now: datetime,
) -> Transaction | None:
    """Convert cell strings into a ``Transaction`` or return ``None`` to skip."""

    def cell(key: str) -> str:
        idx = col.get(key, -1)
        if idx == -1 or idx >= len(cells):
            return ""
        return cells[idx].strip()

    date_str = cell("date")
    if not date_str or date_str.lower() in ("date", "-", "transaction date"):
        return None

    txn_date = _parse_cib_date(date_str)
    if txn_date is None:
        return None

    value_date_str = cell("value_date")
    value_date: date | None = _parse_cib_date(value_date_str) if value_date_str else None

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
            "source": "cib",
        },
        is_categorized=False,
        created_at=now,
        updated_at=now,
    )


# ---------------------------------------------------------------------------
# CIB scraper
# ---------------------------------------------------------------------------


class CIBScraper(BankScraper):
    """Scraper for the Commercial International Bank internet banking portal.

    Portal: https://online.cibeg.com/
    """

    bank_name: str = "CIB"

    async def scrape(self) -> ScraperResult:
        """Execute the full CIB scrape cycle.

        Returns:
            ``ScraperResult`` with account details and up to
            ``_MAX_TRANSACTIONS`` transaction rows.

        Raises:
            ScraperLoginError: If the portal rejects credentials.
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

            raw_html["dashboard"] = await page.content()

            account = await self._extract_account(page)
            logger.info(
                "CIB: account extracted — masked=%s balance=%s %s",
                account.account_number_masked,
                account.balance,
                account.currency,
            )

            await self._navigate_to_statement(page)
            raw_html["transactions"] = await page.content()

            transactions = await self._extract_transactions(page, account)
            logger.info("CIB: extracted %d transactions", len(transactions))

            return ScraperResult(
                accounts=[account],
                transactions=transactions,
                raw_html=raw_html,
            )

        except (ScraperLoginError, ScraperTimeoutError, ScraperParseError):
            raise

        except PlaywrightTimeoutError as exc:
            await self._safe_screenshot(page, "timeout_error")
            raise ScraperTimeoutError(
                f"CIB page operation timed out: {exc}", bank_code="CIB"
            ) from exc

        except Exception as exc:
            await self._safe_screenshot(page, "unexpected_error")
            raise ScraperParseError(
                f"CIB unexpected error during scrape: {type(exc).__name__}: {exc}",
                bank_code="CIB",
            ) from exc

        finally:
            await self._close_browser(browser)

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    async def _navigate_to_login(self, page: Page) -> None:
        """Load the CIB login page and verify the username field is present."""
        logger.debug("CIB: navigating to login page %s", _LOGIN_URL)
        try:
            await page.goto(_LOGIN_URL, wait_until="networkidle", timeout=_WAIT_TIMEOUT_MS)
        except PlaywrightTimeoutError:
            # networkidle can be flaky on SPAs — retry with domcontentloaded
            logger.debug("CIB: networkidle timed out, retrying with domcontentloaded")
            try:
                await page.goto(_LOGIN_URL, wait_until="domcontentloaded", timeout=_WAIT_TIMEOUT_MS)
            except PlaywrightTimeoutError as exc:
                raise ScraperTimeoutError(
                    "CIB login page did not load within timeout", bank_code="CIB"
                ) from exc

        await self._wait_for_selector(
            page, _SEL_USERNAME_CSS, _SEL_USERNAME_XPATH, "username field"
        )

    async def _navigate_to_statement(self, page: Page) -> None:
        """Click the Account Statement link and wait for the transaction table."""
        logger.debug("CIB: navigating to account statement")
        await self._random_delay(1.5, 3.0)

        link = await self._try_selector(page, _SEL_STMT_LINK_CSS, _SEL_STMT_LINK_XPATH)
        if link is None:
            await self._safe_screenshot(page, "stmt_link_missing")
            raise ScraperParseError(
                "CIB: could not find Account Statement navigation link",
                bank_code="CIB",
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
            logger.debug("CIB: filling login form for user=***")
            await self._type_human(page, _SEL_USERNAME_CSS, username)
            await self._random_delay(0.8, 1.8)
            await self._type_human(page, _SEL_PASSWORD_CSS, password)
            await self._random_delay(1.0, 2.0)

            login_btn = await self._try_selector(page, _SEL_LOGIN_BTN_CSS, _SEL_LOGIN_BTN_XPATH)
            if login_btn is None:
                raise ScraperParseError("CIB: could not find login submit button", bank_code="CIB")
            await login_btn.click()
            await self._random_delay(2.5, 5.0)
        finally:
            del username
            del password

    async def _wait_for_dashboard(self, page: Page) -> None:
        """Confirm successful authentication by waiting for the dashboard element.

        If a login-error message appears before the dashboard loads, raise
        ``ScraperLoginError``.
        """
        # Check for immediate login error
        try:
            error_el = await page.query_selector(_SEL_LOGIN_ERROR_CSS)
            if error_el is None:
                error_el = await page.query_selector(f"xpath={_SEL_LOGIN_ERROR_XPATH}")
            if error_el is not None:
                err_text = (await error_el.inner_text()).strip()
                logger.warning("CIB: login failure message detected: %r", err_text)
                raise ScraperLoginError("CIB: portal rejected credentials", bank_code="CIB")
        except ScraperLoginError:
            raise
        except Exception:
            pass

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
        """Close any announcement or welcome modal that blocks the dashboard.

        Non-fatal — if no modal is found the method returns silently.
        """
        try:
            close_btn = await self._try_selector(page, _SEL_MODAL_CLOSE_CSS, _SEL_MODAL_CLOSE_XPATH)
            if close_btn is not None:
                logger.debug("CIB: dismissing modal overlay")
                await close_btn.click()
                await self._random_delay(0.5, 1.5)
        except Exception as exc:
            logger.debug("CIB: modal dismiss error (ignored): %s", exc)

    # ------------------------------------------------------------------
    # Data extraction — account
    # ------------------------------------------------------------------

    async def _extract_account(self, page: Page) -> BankAccount:
        """Extract account metadata from the dashboard account-summary widget.

        CIB's SPA renders account information in a summary card / widget.
        Expected elements (by class or aria-label):
        - Account number (masked or partial)
        - Account type label
        - Currency indicator
        - Current balance figure

        Falls back to scraping the first visible balance figure if the
        structured widget is not found.
        """
        html = await page.content()
        soup = BeautifulSoup(html, "lxml")

        # Strategy 1: find a dedicated account-summary card
        account_node = soup.find(
            class_=re.compile(r"account.?summary|account.?widget|account.?card", re.I)
        ) or soup.find(attrs={"data-testid": re.compile(r"account", re.I)})

        raw_account_number = ""
        account_type_raw = "current"
        currency = "EGP"
        balance_raw = "0.00"

        if account_node:
            # Try to extract individual fields from the card's text content
            text = account_node.get_text(separator="|", strip=True)
            logger.debug("CIB: account card text: %r", text[:200])
            parts = [p.strip() for p in text.split("|") if p.strip()]

            for part in parts:
                # Account number pattern: 10–16 digits possibly with dashes/spaces
                if re.match(r"^[\d\s\-]{10,20}$", part):
                    raw_account_number = part
                # Currency code
                elif part.upper() in ("EGP", "USD", "EUR", "GBP"):
                    currency = part.upper()
                # Balance — numeric with optional commas
                elif re.match(r"^[\d,]+\.\d{2}$", part):
                    balance_raw = part
                # Account type keywords
                elif any(kw in part.lower() for kw in ("saving", "current", "credit", "loan")):
                    account_type_raw = part
        else:
            # Strategy 2: find the first table with balance data
            for table in soup.find_all("table"):
                rows = table.find_all("tr")
                for row in rows:
                    cells = [td.get_text(strip=True) for td in row.find_all("td")]
                    if len(cells) >= 3:
                        # Heuristic: row with a number that looks like a balance
                        for cell_text in cells:
                            if re.match(r"^[\d,]+\.\d{2}$", cell_text):
                                balance_raw = cell_text
                                raw_account_number = cells[0] if cells else ""
                                break
                    if balance_raw != "0.00":
                        break
                if balance_raw != "0.00":
                    break

        account_type = _normalise_account_type(account_type_raw)
        currency = _normalise_currency(currency)
        balance = _parse_amount(balance_raw) or Decimal("0.00")
        masked = self._mask_account_number(raw_account_number) if raw_account_number else "****0000"

        now = datetime.now(UTC)
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

    async def _extract_transactions(self, page: Page, account: BankAccount) -> list[Transaction]:
        """Parse the account statement table and return Transaction objects.

        Expected columns (CIB format):
        Posting Date | Value Date | Description | Debit | Credit | Balance

        Returns up to ``_MAX_TRANSACTIONS`` rows, most-recent first.
        """
        html = await page.content()
        soup = BeautifulSoup(html, "lxml")

        # Locate the transaction table
        table = soup.find(
            "table",
            class_=re.compile(r"transaction|statement", re.I),
        )
        if table is None:
            table = soup.find("table", id=re.compile(r"transaction|statement", re.I))

        if table is None:
            # Last resort: find any table with debit/credit in its headers
            for t in soup.find_all("table"):
                raw_text = t.get_text(separator=" ").lower()
                if "debit" in raw_text and "credit" in raw_text:
                    table = t
                    break

        if table is None:
            await self._safe_screenshot(page, "txn_table_parse_error")
            raise ScraperParseError(
                "CIB: could not locate transaction table in statement page",
                bank_code="CIB",
            )

        # Resolve column indices
        header_row = table.find("tr")
        if header_row is None:
            raise ScraperParseError("CIB: transaction table has no header row", bank_code="CIB")

        headers = [th.get_text(strip=True).lower() for th in header_row.find_all(["th", "td"])]
        logger.debug("CIB: transaction table headers: %r", headers)
        col = _resolve_txn_columns(headers)

        transactions: list[Transaction] = []
        now = datetime.now(UTC)
        data_rows = [r for r in table.find_all("tr") if r.find("td")]

        for row_idx, row in enumerate(data_rows[:_MAX_TRANSACTIONS]):
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if not cells or len(cells) < 3:
                continue

            try:
                txn = _parse_transaction_row(cells, col, account, now)
            except Exception as exc:
                logger.debug("CIB: skipping row %d due to parse error: %s", row_idx, exc)
                continue

            if txn is not None:
                transactions.append(txn)

        return transactions

    # ------------------------------------------------------------------
    # Selector helpers (identical pattern to NBE, defined per-class for clarity)
    # ------------------------------------------------------------------

    async def _wait_for_selector(self, page: Page, css: str, xpath: str, label: str) -> None:
        """Wait for a CSS selector, falling back to XPath on timeout.

        Raises ``ScraperTimeoutError`` if both selectors fail within their
        respective timeouts.
        """
        try:
            await page.wait_for_selector(css, timeout=_WAIT_TIMEOUT_MS)
            return
        except PlaywrightTimeoutError:
            logger.debug("CIB: CSS selector %r timed out, trying XPath", css)

        try:
            await page.wait_for_selector(f"xpath={xpath}", timeout=15_000)
        except PlaywrightTimeoutError as exc:
            raise ScraperTimeoutError(
                f"CIB: {label} not found within timeout (css={css!r})", bank_code="CIB"
            ) from exc

    async def _try_selector(self, page: Page, css: str, xpath: str):  # type: ignore[return]
        """Return the first element matching CSS or XPath, or ``None``."""
        el = await page.query_selector(css)
        if el is not None:
            return el
        return await page.query_selector(f"xpath={xpath}")
