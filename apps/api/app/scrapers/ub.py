"""UB (United Bank) scraper — ibanking.ub.com.eg.

Login URL: https://ibanking.ub.com.eg/

Scrape flow
-----------
1. Navigate to the login page.
2. Fill the username / customer ID field.
3. Fill the password field.
4. Click the login / "Sign In" button.
5. Wait for the post-login dashboard to confirm authentication.
6. Extract account balance and account metadata from the account summary widget.
7. Navigate to the Account Statement section.
8. Extract the last 30 transactions.
9. Return a ``ScraperResult``.

Portal notes
------------
- United Bank's portal is served from ``ibanking.ub.com.eg``.
- The portal may use a SPA layout (React or Angular) similar to CIB, or a
  WebForms structure similar to NBE.  Selectors cover both patterns.
- Date format in statements: ``DD-MMM-YYYY`` (e.g. ``15-Jan-2025``) is the
  primary format.  ``DD/MM/YYYY`` also appears in some tabular views.
  Both are handled by ``_parse_ub_date``.
- Amounts use comma thousands-separators, e.g. ``10,250.00``.  The
  ``_parse_amount`` helper strips commas and any currency symbol before
  Decimal conversion.
- The portal may show an announcement modal after login.  The scraper
  dismisses it if present.
- Some portal versions display amounts with a trailing ``Dr`` / ``Cr``
  indicator rather than separate Debit/Credit columns.  ``_resolve_txn_columns``
  detects the single-amount layout and ``_parse_transaction_row`` handles
  the Dr/Cr suffix.

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

_LOGIN_URL = "https://ibanking.ub.com.eg/"

# Default Playwright wait timeout in milliseconds.
_WAIT_TIMEOUT_MS = 30_000

# Maximum transactions to return per scrape run.
_MAX_TRANSACTIONS = 30

# ---------------------------------------------------------------------------
# Selector catalogue
# (CSS primary, XPath fallback, comment describing the target element)
# ---------------------------------------------------------------------------

# Login form — username / customer ID field
_SEL_USERNAME_CSS = (
    "input[id*='UserName'], input[id*='username'], input[id*='customerId'], "
    "input[name*='username'], input[name*='UserName'], input[name*='customerId']"
)
_SEL_USERNAME_XPATH = (
    "//input[contains(@id,'UserName') or contains(@id,'username') "
    "or contains(@id,'customerId') or contains(@name,'username') "
    "or contains(@placeholder,'User') or contains(@placeholder,'Customer')]"
)

# Login form — password field
_SEL_PASSWORD_CSS = "input[type='password']"
_SEL_PASSWORD_XPATH = "//input[@type='password']"

# Login form — submit / sign-in button
_SEL_LOGIN_BTN_CSS = (
    "input[type='submit'], button[type='submit'], "
    "button[id*='Login'], input[id*='LoginButton'], "
    "button[id*='login'], a[id*='login']"
)
_SEL_LOGIN_BTN_XPATH = (
    "//input[@type='submit' or contains(@id,'Login')] | "
    "//button[@type='submit' or contains(@id,'login') or contains(@id,'Login') "
    "or contains(text(),'Sign In') or contains(text(),'Login') "
    "or contains(text(),'تسجيل الدخول')]"
)

# Dashboard — element that confirms successful login
# UB may render an account balance widget or a welcome section
_SEL_DASHBOARD_CSS = (
    "table[id*='AccSummary'], table[id*='AccountSummary'], "
    ".account-summary, .accounts-list, [class*='accountSummary'], "
    "[class*='account-widget'], [class*='account-card']"
)
_SEL_DASHBOARD_XPATH = (
    "//table[contains(@id,'AccSummary') or contains(@id,'AccountSummary')] | "
    "//*[contains(@class,'account-summary') or contains(@class,'accounts-list') "
    "or contains(@class,'accountSummary') or contains(@class,'account-widget') "
    "or contains(@class,'account-card')]"
)

# Login error — bad-credentials notification element
_SEL_LOGIN_ERROR_CSS = (
    ".failureNotification, .error-message, .alert-danger, "
    "[class*='loginError'], [class*='FailureText'], [class*='error-msg']"
)
_SEL_LOGIN_ERROR_XPATH = (
    "//*[contains(@class,'failureNotification') or contains(@class,'FailureText') "
    "or contains(@class,'error-message') or contains(@class,'alert-danger') "
    "or contains(@class,'loginError') or contains(@class,'error-msg')]"
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
    "a[href*='statement'], a[href*='Transactions'], a[href*='transactions']"
)
_SEL_STMT_LINK_XPATH = (
    "//a[contains(@href,'AccountStatement') or contains(@href,'Statement') "
    "or contains(@href,'statement') or contains(@href,'Transactions') "
    "or contains(@href,'transactions') "
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


def _parse_ub_date(raw: str) -> date | None:
    """Parse a date string from UB's portal.

    Supported formats:
    - ``DD-MMM-YYYY`` (primary, e.g. ``15-Jan-2025``)
    - ``DD/MM/YYYY``
    - ``DD-MM-YYYY``
    - ``D/M/YYYY`` (single-digit day/month variants)

    Returns ``None`` if no format matches so callers can decide whether to skip
    the row or raise ``ScraperParseError``.
    """
    raw = raw.strip()

    # DD-MMM-YYYY — primary UB format
    m = re.match(r"^(\d{1,2})-([A-Za-z]{3})-(\d{4})$", raw)
    if m:
        day, mon_abbr, year = int(m.group(1)), m.group(2).lower(), int(m.group(3))
        month = _MONTH_ABBR.get(mon_abbr)
        if month:
            try:
                return date(year, month, day)
            except ValueError:
                pass

    # DD/MM/YYYY, D/M/YYYY, or DD-MM-YYYY
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

    logger.debug("UB: could not parse date string %r", raw)
    return None


def _parse_amount(raw: str) -> Decimal | None:
    """Strip thousands-separators, Dr/Cr suffixes, and currency symbols; parse as Decimal.

    Handles inputs such as:
    - ``12,345.67``
    - ``12,345.67 Dr``
    - ``12,345.67 Cr``
    - ``EGP 12,345.67``
    - Arabic-prefixed or suffixed currency labels

    Returns ``None`` if the string is empty, a dash, or otherwise not numeric.
    The caller is responsible for interpreting Dr/Cr direction — this function
    always returns a positive Decimal (the Dr/Cr suffix is stripped, not negated).
    """
    cleaned = raw.strip()
    # Remove Dr/Cr directional suffixes (case-insensitive)
    cleaned = re.sub(r"\s*[DC]r\.?$", "", cleaned, flags=re.IGNORECASE)
    # Remove Latin and Arabic letter currency labels
    cleaned = re.sub(r"[A-Za-z\u0600-\u06FF]", "", cleaned)
    cleaned = cleaned.replace(",", "").replace(" ", "")
    if not cleaned or cleaned in ("-", "—", "N/A"):
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        logger.debug("UB: could not parse amount %r", raw)
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

    In addition to the standard Debit/Credit split layout, this function also
    detects a single-Amount layout where direction is indicated by a Dr/Cr
    suffix in the cell value.  In that case, the ``amount`` key is set to the
    column index and ``debit``/``credit`` remain ``-1``.

    Returned keys: ``date``, ``value_date``, ``description``, ``debit``,
    ``credit``, ``balance``, ``amount``.  Unresolved keys map to ``-1``.
    """
    col: dict[str, int] = {
        "date": -1,
        "value_date": -1,
        "description": -1,
        "debit": -1,
        "credit": -1,
        "balance": -1,
        "amount": -1,
    }

    for i, h in enumerate(headers):
        h_lower = h.lower()
        if col["date"] == -1 and re.search(r"transaction\s*date|^date$|posting|تاريخ", h_lower):
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
        elif col["amount"] == -1 and re.search(r"^amount$|مبلغ", h_lower):
            col["amount"] = i

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
) -> Transaction | None:
    """Convert a list of cell strings into a ``Transaction`` or return ``None`` to skip.

    Handles two layouts:
    1. Split Debit/Credit columns — standard layout used by most Egyptian bank portals.
    2. Single Amount column with a Dr/Cr suffix — used by some UB portal versions.
    """

    def cell(key: str) -> str:
        idx = col.get(key, -1)
        if idx == -1 or idx >= len(cells):
            return ""
        return cells[idx].strip()

    date_str = cell("date")
    if not date_str or date_str.lower() in ("date", "تاريخ", "-"):
        return None

    txn_date = _parse_ub_date(date_str)
    if txn_date is None:
        return None

    value_date_str = cell("value_date")
    value_date: date | None = _parse_ub_date(value_date_str) if value_date_str else None

    description = cell("description") or "N/A"
    balance_after = _parse_amount(cell("balance"))

    # --- Determine direction and amount ---

    # Layout 1: separate Debit / Credit columns
    debit_raw = cell("debit")
    credit_raw = cell("credit")
    debit_amount = _parse_amount(debit_raw)
    credit_amount = _parse_amount(credit_raw)

    if debit_amount and debit_amount > 0:
        transaction_type = "debit"
        amount = debit_amount
    elif credit_amount and credit_amount > 0:
        transaction_type = "credit"
        amount = credit_amount
    else:
        # Layout 2: single Amount column with Dr/Cr suffix
        amount_raw = cell("amount")
        if not amount_raw:
            return None  # No usable amount in any column

        parsed_amount = _parse_amount(amount_raw)
        if parsed_amount is None or parsed_amount == 0:
            return None

        # Infer direction from the Dr/Cr suffix present in the original cell text
        if re.search(r"\bDr\.?\b", amount_raw, re.IGNORECASE):
            transaction_type = "debit"
        elif re.search(r"\bCr\.?\b", amount_raw, re.IGNORECASE):
            transaction_type = "credit"
        else:
            # No suffix — cannot determine direction; default to debit
            logger.debug("UB: amount %r has no Dr/Cr suffix, defaulting to debit", amount_raw)
            transaction_type = "debit"

        amount = parsed_amount

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
            "source": "ub",
        },
        is_categorized=False,
        created_at=now,
        updated_at=now,
    )


# ---------------------------------------------------------------------------
# UB scraper
# ---------------------------------------------------------------------------


class UBScraper(BankScraper):
    """Scraper for the United Bank internet banking portal.

    Portal: https://ibanking.ub.com.eg/
    """

    bank_name: str = "UB"

    async def scrape(self) -> ScraperResult:
        """Execute the full UB scrape cycle.

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
                "UB: account extracted — masked=%s balance=%s %s",
                account.account_number_masked,
                account.balance,
                account.currency,
            )

            await self._navigate_to_statement(page)
            raw_html["transactions"] = await page.content()

            transactions = await self._extract_transactions(page, account)
            logger.info("UB: extracted %d transactions", len(transactions))

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
                f"UB page operation timed out: {exc}", bank_code="UB"
            ) from exc

        except Exception as exc:
            await self._safe_screenshot(page, "unexpected_error")
            raise ScraperParseError(
                f"UB unexpected error during scrape: {type(exc).__name__}: {exc}",
                bank_code="UB",
            ) from exc

        finally:
            await self._close_browser(browser)

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    async def _navigate_to_login(self, page: Page) -> None:
        """Load the UB login page and verify the username field is present.

        Tries ``networkidle`` first (SPA-friendly); falls back to
        ``domcontentloaded`` if that times out.
        """
        logger.debug("UB: navigating to login page %s", _LOGIN_URL)
        try:
            await page.goto(_LOGIN_URL, wait_until="networkidle", timeout=_WAIT_TIMEOUT_MS)
        except PlaywrightTimeoutError:
            # networkidle can be flaky on SPAs — retry with domcontentloaded
            logger.debug("UB: networkidle timed out, retrying with domcontentloaded")
            try:
                await page.goto(
                    _LOGIN_URL,
                    wait_until="domcontentloaded",
                    timeout=_WAIT_TIMEOUT_MS,
                )
            except PlaywrightTimeoutError as exc:
                raise ScraperTimeoutError(
                    "UB login page did not load within timeout", bank_code="UB"
                ) from exc

        await self._wait_for_selector(
            page, _SEL_USERNAME_CSS, _SEL_USERNAME_XPATH, "username field"
        )

    async def _navigate_to_statement(self, page: Page) -> None:
        """Click the Account Statement link and wait for the transaction table."""
        logger.debug("UB: navigating to account statement")
        await self._random_delay(1.5, 3.0)

        link = await self._try_selector(page, _SEL_STMT_LINK_CSS, _SEL_STMT_LINK_XPATH)
        if link is None:
            await self._safe_screenshot(page, "stmt_link_missing")
            raise ScraperParseError(
                "UB: could not find Account Statement navigation link",
                bank_code="UB",
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
            logger.debug("UB: filling login form for user=***")
            await self._type_human(page, _SEL_USERNAME_CSS, username)
            await self._random_delay(0.8, 1.8)
            await self._type_human(page, _SEL_PASSWORD_CSS, password)
            await self._random_delay(1.0, 2.0)

            login_btn = await self._try_selector(page, _SEL_LOGIN_BTN_CSS, _SEL_LOGIN_BTN_XPATH)
            if login_btn is None:
                raise ScraperParseError("UB: could not find login submit button", bank_code="UB")
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
        # Check for an immediate login error message
        try:
            error_el = await page.query_selector(_SEL_LOGIN_ERROR_CSS)
            if error_el is None:
                error_el = await page.query_selector(f"xpath={_SEL_LOGIN_ERROR_XPATH}")
            if error_el is not None:
                err_text = (await error_el.inner_text()).strip()
                logger.warning("UB: login failure message detected: %r", err_text)
                raise ScraperLoginError("UB: portal rejected credentials", bank_code="UB")
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
            close_btn = await self._try_selector(page, _SEL_MODAL_CLOSE_CSS, _SEL_MODAL_CLOSE_XPATH)
            if close_btn is not None:
                logger.debug("UB: dismissing modal overlay")
                await close_btn.click()
                await self._random_delay(0.5, 1.5)
        except Exception as exc:
            logger.debug("UB: modal dismiss error (ignored): %s", exc)

    # ------------------------------------------------------------------
    # Data extraction — account
    # ------------------------------------------------------------------

    async def _extract_account(self, page: Page) -> BankAccount:
        """Extract account metadata from the dashboard.

        UB may render account information in a summary card (SPA) or a
        GridView-style table (WebForms).  Both layouts are attempted.

        Strategy 1: Find a dedicated account-summary card by class name.
        Strategy 2: Find a table with an AccSummary-style ID.
        Strategy 3: Scan all tables for a row containing a recognisable
            balance figure.

        Returns a ``BankAccount`` with sentinel ``id``, ``user_id``,
        ``created_at``, ``updated_at`` that the pipeline layer will replace.
        """
        html = await page.content()
        soup = BeautifulSoup(html, "lxml")

        raw_account_number = ""
        account_type_raw = "current"
        currency = "EGP"
        balance_raw = "0.00"

        # Strategy 1: SPA-style account summary card
        account_node = soup.find(
            class_=re.compile(r"account.?summary|account.?widget|account.?card", re.I)
        ) or soup.find(attrs={"data-testid": re.compile(r"account", re.I)})

        if account_node:
            text = account_node.get_text(separator="|", strip=True)
            logger.debug("UB: account card text: %r", text[:200])
            parts = [p.strip() for p in text.split("|") if p.strip()]

            for part in parts:
                if re.match(r"^[\d\s\-]{10,20}$", part):
                    raw_account_number = part
                elif part.upper() in ("EGP", "USD", "EUR", "GBP"):
                    currency = part.upper()
                elif re.match(r"^[\d,]+\.\d{2}$", part):
                    balance_raw = part
                elif any(kw in part.lower() for kw in ("saving", "current", "credit", "loan")):
                    account_type_raw = part
        else:
            # Strategy 2: WebForms-style AccSummary table
            table = soup.find("table", id=re.compile(r"AccSummary|AccountSummary", re.I))
            if table is None:
                # Strategy 3: any table whose text contains "account"
                for t in soup.find_all("table"):
                    headers_text = " ".join(
                        th.get_text(strip=True).lower() for th in t.find_all(["th", "td"])
                    )
                    if "account" in headers_text or "حساب" in headers_text:
                        table = t
                        break

            if table is not None:
                rows = table.find_all("tr")
                data_rows = [r for r in rows if r.find("td")]
                if data_rows:
                    cells = [td.get_text(strip=True) for td in data_rows[0].find_all("td")]
                    logger.debug("UB: account row cells: %r", cells)
                    if len(cells) >= 3:
                        raw_account_number = cells[0]
                        account_type_raw = cells[1].lower()
                        currency = cells[2].upper()
                        balance_raw = cells[3] if len(cells) > 3 else "0.00"

        if not raw_account_number and balance_raw == "0.00":
            await self._safe_screenshot(page, "account_data_missing")
            raise ScraperParseError(
                "UB: could not extract account data from dashboard",
                bank_code="UB",
            )

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

        Handles two table layouts:
        1. Standard: Date | Value Date | Description | Debit | Credit | Balance
        2. Compact: Date | Description | Amount (Dr/Cr suffix) | Balance

        Returns up to ``_MAX_TRANSACTIONS`` rows, most-recent first.
        """
        html = await page.content()
        soup = BeautifulSoup(html, "lxml")

        # Locate the transaction table
        table = soup.find("table", id=re.compile(r"TransactionList|transaction", re.I))
        if table is None:
            table = soup.find("table", class_=re.compile(r"transaction|statement", re.I))

        if table is None:
            # Last resort: find a table that mentions debit/credit or Dr/Cr in its headers
            for t in soup.find_all("table"):
                raw_text = t.get_text(separator=" ").lower()
                if ("debit" in raw_text or "مدين" in raw_text or " dr" in raw_text) and (
                    "credit" in raw_text or "دائن" in raw_text or " cr" in raw_text
                ):
                    table = t
                    break

        if table is None:
            await self._safe_screenshot(page, "txn_table_parse_error")
            raise ScraperParseError(
                "UB: could not locate transaction table in statement page",
                bank_code="UB",
            )

        # Resolve column indices
        header_row = table.find("tr")
        if header_row is None:
            raise ScraperParseError("UB: transaction table has no header row", bank_code="UB")

        headers = [th.get_text(strip=True).lower() for th in header_row.find_all(["th", "td"])]
        logger.debug("UB: transaction table headers: %r", headers)
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
                logger.debug("UB: skipping row %d due to parse error: %s", row_idx, exc)
                continue

            if txn is not None:
                transactions.append(txn)

        return transactions

    # ------------------------------------------------------------------
    # Selector helpers
    # ------------------------------------------------------------------

    async def _wait_for_selector(self, page: Page, css: str, xpath: str, label: str) -> None:
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
            logger.debug("UB: CSS selector %r timed out, trying XPath", css)

        try:
            await page.wait_for_selector(f"xpath={xpath}", timeout=15_000)
        except PlaywrightTimeoutError as exc:
            raise ScraperTimeoutError(
                f"UB: {label} not found within timeout (css={css!r})",
                bank_code="UB",
            ) from exc

    async def _try_selector(self, page: Page, css: str, xpath: str):  # type: ignore[return]
        """Return the first element matching CSS or XPath, or ``None``."""
        el = await page.query_selector(css)
        if el is not None:
            return el
        return await page.query_selector(f"xpath={xpath}")
