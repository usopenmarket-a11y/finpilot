"""NBE (National Bank of Egypt) scraper — alahlynet.com.eg.

Login URL: https://www.alahlynet.com.eg/?page=home

Portal type
-----------
Oracle JET single-page application (SPA).  All navigation stays on the same
base URL — page state changes are indicated by the ``?page=`` query parameter
but the browser URL may not actually change between SPA views.  ``networkidle``
waits are used throughout to let AJAX settle before inspecting the DOM.

Scrape flow
-----------
1. Navigate to login page and wait for ``#login_username``.
2. Enter username → click ``#username-button`` (step 1 of 2-step login).
3. Wait for password field ``#login_password`` to appear (SPA renders it
   dynamically after step 1 completes).
4. Enter password → click ``button.btn-login``.
5. Confirm login by waiting for ``a:has-text('Logout')`` in the DOM.
6. Click the Accounts Summary widget ``li.CSA a`` to flip the account card
   and reveal the account list.
7. Locate the first ``li.flip-account-list__items`` row; extract account
   number and balance.
8. Click ``a.menu-icon`` (the 3-dots context menu on that account row).
9. Click ``span:has-text('Account Activity')`` from the context menu.
10. Wait for ``?page=demand-deposit-transactions`` to be reflected and for
    the filter panel to appear.
11. Click ``button:has-text('Apply')`` and wait for ``oj-table#ViewStatement1``
    rows to load via AJAX.
12. Parse transaction rows from ``td[id^="ViewStatement1:"]`` cells, grouping
    by row index.
13. Follow pagination (``button[title="Next Page"]``) until no more pages or
    ``_MAX_TRANSACTIONS`` is reached.
14. Return a ``ScraperResult``.

OTP handling
------------
If an OTP prompt appears after login (detected by ``#otpSection`` or
``input[id*='otp' i]``), ``ScraperOTPRequired`` is raised.  The API layer
must collect the OTP from the user and resume the scrape session.

Selector strategy
-----------------
Oracle JET components render custom elements (``oj-table``, ``oj-select-one``
etc.) that wrap standard HTML.  Inner cells are queried by the stable
``id="ViewStatement1:{row}_{col}"`` pattern which Oracle JET generates
deterministically from the data-bound ``<oj-table>`` definition.

Date parsing
------------
NBE alahlynet uses ``DD Mon YYYY`` for transaction dates (e.g. ``12 Mar 2026``).
The parser handles both abbreviated (``Mar``) and zero-padded day values.

Amount parsing
--------------
Amounts appear as ``EGP 10,100.00`` or ``USD 500.00``.  The currency prefix is
stripped and commas are removed before ``Decimal`` conversion.  An empty string
cell means the column is not applicable for that row (debit vs. credit).

External ID
-----------
Generated as ``SHA-256(date_iso|description[:40]|amount)[:24]`` — stable across
repeated scrapes of the same transaction, matching the deduplication contract
in ``models.db.Transaction``.
"""

from __future__ import annotations

import hashlib
import logging
import re
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
    ScraperOTPRequired,
    ScraperParseError,
    ScraperResult,
    ScraperTimeoutError,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LOGIN_URL = "https://www.alahlynet.com.eg/?page=home"

# Default Playwright wait timeout in milliseconds.
_WAIT_TIMEOUT_MS = 30_000

# Shorter timeout for optional / conditional element checks.
_SHORT_TIMEOUT_MS = 8_000

# Maximum number of transactions to return per scrape run.
_MAX_TRANSACTIONS = 50

# ---------------------------------------------------------------------------
# Selector catalogue (Oracle JET SPA — alahlynet.com.eg)
# ---------------------------------------------------------------------------

# Step 1 — username input and submit button
_SEL_USERNAME = "#login_username"
_SEL_USERNAME_BTN = "#username-button"

# Step 2 — password field (rendered dynamically by SPA after username step)
_SEL_PASSWORD = "#login_password"
_SEL_PASSWORD_BTN = "button.btn-login"

# Confirms successful login — Logout link present in the nav
_SEL_LOGOUT = "a:has-text('Logout')"

# OTP detection — either a dedicated OTP section or any OTP input
_SEL_OTP_SECTION = "#otpSection"
_SEL_OTP_INPUT = "input[id*='otp' i]"

# Accounts widget — click to flip the card and reveal account list
_SEL_ACCOUNTS_WIDGET = "li.CSA a"

# Account rows inside the flipped card
_SEL_ACCOUNT_ROWS = "li.flip-account-list__items"

# Context menu icon on each account row
_SEL_MENU_ICON = "a.menu-icon"

# "Account Activity" menu item inside the opened context menu
_SEL_ACCOUNT_ACTIVITY = "span:has-text('Account Activity')"

# Apply filter button on the Account Activity page
_SEL_APPLY_BTN = "button:has-text('Apply')"

# The Oracle JET transaction table
_SEL_TXN_TABLE = "oj-table#ViewStatement1"

# A loaded cell inside the table (used to confirm AJAX has settled)
_SEL_TXN_TABLE_CELL = "oj-table#ViewStatement1 td"

# Pagination — Next Page button
_SEL_NEXT_PAGE = "button[title='Next Page']"

# URL fragment that appears once Account Activity is loaded
_TXN_PAGE_URL_FRAGMENT = "demand-deposit-transactions"

# ---------------------------------------------------------------------------
# Transaction table column indices (0-based, fixed by Oracle JET binding)
# Col: 0=Txn Date | 1=Value Date | 2=Ref No | 3=Description | 4=Debit | 5=Credit | 6=Balance
# ---------------------------------------------------------------------------
_COL_TXN_DATE = 0
_COL_VALUE_DATE = 1
_COL_REFERENCE = 2
_COL_DESCRIPTION = 3
_COL_DEBIT = 4
_COL_CREDIT = 5
_COL_BALANCE = 6
_COL_COUNT = 7


# ---------------------------------------------------------------------------
# Sentinel UUIDs used for scraper-layer Transaction objects
# (pipeline layer replaces these with real DB-assigned values)
# ---------------------------------------------------------------------------
_ZERO_UUID = UUID("00000000-0000-0000-0000-000000000000")


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


def _parse_nbe_date(raw: str) -> date | None:
    """Parse a date string from NBE alahlynet's ``DD Mon YYYY`` format.

    Accepted formats:
    - ``DD Mon YYYY``  — primary (e.g. ``12 Mar 2026``)
    - ``D Mon YYYY``   — single-digit day variant
    - ``DD/MM/YYYY``   — legacy fallback (may appear in exports)
    - ``DD-MM-YYYY``   — legacy fallback

    Returns ``None`` if no format matches so callers can skip the row.
    """
    raw = raw.strip()
    if not raw:
        return None

    for fmt in ("%d %b %Y", "%-d %b %Y", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue

    # Permissive fallback: split on common separators
    parts = re.split(r"[\s/\-]", raw)
    if len(parts) == 3:
        try:
            day = int(parts[0])
            # parts[1] may be a month abbreviation or an integer
            try:
                month = datetime.strptime(parts[1][:3], "%b").month
            except ValueError:
                month = int(parts[1])
            year = int(parts[2])
            return date(year, month, day)
        except (ValueError, TypeError):
            pass

    logger.debug("NBE: could not parse date string %r", raw)
    return None


def _parse_amount(raw: str) -> Decimal | None:
    """Strip currency prefix, thousands separators and convert to Decimal.

    Handles inputs like:
    - ``EGP 10,100.00``
    - ``USD 500.00``
    - ``10,100.00``
    - `` `` (empty — no amount for this column)

    Returns ``None`` on parse failure or empty input.
    """
    # Strip known currency codes and surrounding whitespace
    cleaned = re.sub(r"^[A-Z]{3}\s*", "", raw.strip())
    cleaned = cleaned.replace(",", "").replace(" ", "")
    if not cleaned or cleaned in ("-", "N/A", "—"):
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        logger.debug("NBE: could not parse amount %r", raw)
        return None


def _make_external_id(txn_date: date, description: str, amount: Decimal) -> str:
    """Produce a stable deduplication key for a transaction row.

    The key is the first 24 hex characters of the SHA-256 hash of the
    canonical string ``{date_iso}|{description_truncated}|{amount}``.
    This is compact, deterministic, and collision-resistant for banking data.
    """
    canonical = f"{txn_date.isoformat()}|{description[:40].strip()}|{amount}"
    return hashlib.sha256(canonical.encode()).hexdigest()[:24]


# ---------------------------------------------------------------------------
# Module-level parsing helpers
# ---------------------------------------------------------------------------


def _normalise_account_type(raw: str) -> str:
    """Map a raw account-type string to one of the allowed DB values.

    Handles Arabic section headings (e.g. "الحسابات الجارية والتوفير") as
    well as English labels.
    """
    raw = raw.lower().strip()
    if "saving" in raw or "توفير" in raw:
        return "savings"
    if "credit" in raw or "ائتمان" in raw:
        return "credit"
    if "loan" in raw or "قرض" in raw:
        return "loan"
    return "current"  # default — covers "Current & Savings", "جارى"


def _normalise_currency(raw: str) -> str:
    """Return a valid ISO 4217 code or fall back to EGP."""
    raw = raw.upper().strip()
    known = {"EGP", "USD", "EUR", "GBP", "SAR", "AED"}
    return raw if raw in known else "EGP"


def _extract_currency_from_balance(balance_text: str) -> str:
    """Extract the ISO currency code from a balance string like ``EGP 0.00``.

    Returns ``"EGP"`` if no recognised code is present.
    """
    m = re.match(r"^([A-Z]{3})\s", balance_text.strip())
    if m:
        return _normalise_currency(m.group(1))
    return "EGP"


def _parse_oj_table_rows(html: str) -> list[list[str]]:
    """Extract cell text from an Oracle JET ``oj-table#ViewStatement1`` element.

    Oracle JET renders cells with ``id`` attributes following the pattern:
    ``ViewStatement1:{row_index}_{col_index}`` where the inner ``<span>``
    holds the display value.

    Returns a list of rows, each row being a list of cell text strings
    (length == ``_COL_COUNT``).  Rows with fewer than 3 populated cells
    are skipped as malformed.
    """
    soup = BeautifulSoup(html, "lxml")

    # Collect all cells whose id matches the ViewStatement1 pattern
    cell_pattern = re.compile(r"^ViewStatement1:(\d+)_(\d+)$")
    cell_map: dict[tuple[int, int], str] = {}

    for td in soup.find_all("td", id=cell_pattern):
        m = cell_pattern.match(td["id"])
        if m:
            row_idx = int(m.group(1))
            col_idx = int(m.group(2))
            span = td.find("span")
            text = span.get_text(strip=True) if span else td.get_text(strip=True)
            cell_map[(row_idx, col_idx)] = text

    if not cell_map:
        return []

    max_row = max(r for r, _ in cell_map) + 1
    rows: list[list[str]] = []
    for row_idx in range(max_row):
        row = [cell_map.get((row_idx, col_idx), "") for col_idx in range(_COL_COUNT)]
        # Skip rows that look completely empty (Oracle JET sometimes renders
        # placeholder rows during loading)
        if any(cell.strip() for cell in row[:4]):
            rows.append(row)

    return rows


def _parse_transaction_row(
    cells: list[str],
    account: BankAccount,
    now: datetime,
) -> Transaction | None:
    """Convert a list of cell strings (7 columns) into a ``Transaction``.

    Column order (fixed, from Oracle JET binding):
    0: Transaction Date | 1: Value Date | 2: Reference | 3: Description
    4: Debit | 5: Credit | 6: Balance

    Returns ``None`` for empty or header-repeat rows.
    """
    date_str = cells[_COL_TXN_DATE].strip() if len(cells) > _COL_TXN_DATE else ""
    if not date_str or date_str.lower() in ("date", "transaction date", "تاريخ", "-"):
        return None

    txn_date = _parse_nbe_date(date_str)
    if txn_date is None:
        return None

    value_date_str = cells[_COL_VALUE_DATE].strip() if len(cells) > _COL_VALUE_DATE else ""
    value_date: date | None = _parse_nbe_date(value_date_str) if value_date_str else None

    reference = cells[_COL_REFERENCE].strip() if len(cells) > _COL_REFERENCE else None
    description = (
        cells[_COL_DESCRIPTION].strip() if len(cells) > _COL_DESCRIPTION else ""
    ) or "N/A"

    debit_str = cells[_COL_DEBIT] if len(cells) > _COL_DEBIT else ""
    credit_str = cells[_COL_CREDIT] if len(cells) > _COL_CREDIT else ""
    balance_str = cells[_COL_BALANCE] if len(cells) > _COL_BALANCE else ""

    debit_amount = _parse_amount(debit_str)
    credit_amount = _parse_amount(credit_str)
    balance_after = _parse_amount(balance_str)

    # Determine direction and canonical amount
    if debit_amount is not None and debit_amount > 0:
        transaction_type = "debit"
        amount = debit_amount
    elif credit_amount is not None and credit_amount > 0:
        transaction_type = "credit"
        amount = credit_amount
    else:
        # Both columns empty — skip the row
        return None

    external_id = _make_external_id(txn_date, description, amount)
    reference_val: str | None = reference if reference else None

    return Transaction(
        id=_ZERO_UUID,
        user_id=_ZERO_UUID,
        account_id=_ZERO_UUID,
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
            "reference": reference_val,
            "source": "nbe",
        },
        is_categorized=False,
        created_at=now,
        updated_at=now,
    )


# ---------------------------------------------------------------------------
# NBE scraper
# ---------------------------------------------------------------------------


class NBEScraper(BankScraper):
    """Scraper for the National Bank of Egypt internet banking portal.

    Portal: https://www.alahlynet.com.eg/?page=home
    Engine: Oracle JET SPA
    Auth:   2-step (username → password), optional OTP via SMS
    """

    bank_name: str = "NBE"

    async def scrape(self) -> ScraperResult:
        """Execute the full NBE scrape cycle.

        Returns:
            ``ScraperResult`` containing account details and up to
            ``_MAX_TRANSACTIONS`` transaction rows.

        Raises:
            ScraperLoginError: If the portal rejects the credentials.
            ScraperOTPRequired: If an OTP challenge is detected after login.
            ScraperTimeoutError: If any Playwright wait exceeds its deadline.
            ScraperParseError: If the HTML structure is not as expected.
        """
        browser, context, page = await self._launch_browser()
        raw_html: dict[str, str] = {}

        try:
            await self._navigate_to_login(page)
            await self._login(page)
            await self._wait_for_dashboard(page)

            # Capture dashboard HTML for audit trail (post-auth — safe to screenshot)
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

        except (ScraperLoginError, ScraperOTPRequired, ScraperTimeoutError, ScraperParseError):
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
            await page.goto(
                _LOGIN_URL,
                wait_until="networkidle",
                timeout=_WAIT_TIMEOUT_MS,
            )
        except PlaywrightTimeoutError as exc:
            raise ScraperTimeoutError(
                "NBE login page did not load within timeout", bank_code="NBE"
            ) from exc

        try:
            await page.wait_for_selector(_SEL_USERNAME, timeout=_WAIT_TIMEOUT_MS)
        except PlaywrightTimeoutError as exc:
            raise ScraperTimeoutError(
                f"NBE: username field ({_SEL_USERNAME!r}) not found", bank_code="NBE"
            ) from exc

    async def _navigate_to_transactions(self, page: Page) -> None:
        """Navigate from the account list to the Account Activity page.

        Flow:
        1. Click the Accounts Summary widget to reveal the account list.
        2. Wait for account rows to appear.
        3. Click the 3-dots menu icon on the first account row.
        4. Click "Account Activity" from the context menu.
        5. Wait for the transaction filter panel and Apply button.
        6. Click Apply and wait for the transaction table rows to load.
        """
        logger.debug("NBE: navigating to Account Activity")
        await self._random_delay(1.5, 3.0)

        # 1. Flip the accounts card
        try:
            accounts_widget = await page.wait_for_selector(
                _SEL_ACCOUNTS_WIDGET, timeout=_WAIT_TIMEOUT_MS
            )
        except PlaywrightTimeoutError as exc:
            await self._safe_screenshot(page, "accounts_widget_missing")
            raise ScraperTimeoutError(
                f"NBE: accounts widget ({_SEL_ACCOUNTS_WIDGET!r}) not found",
                bank_code="NBE",
            ) from exc

        await accounts_widget.click()
        await self._random_delay(1.5, 3.0)

        # 2. Wait for at least one account row
        try:
            await page.wait_for_selector(_SEL_ACCOUNT_ROWS, timeout=_WAIT_TIMEOUT_MS)
        except PlaywrightTimeoutError as exc:
            await self._safe_screenshot(page, "account_rows_missing")
            raise ScraperTimeoutError(
                f"NBE: account rows ({_SEL_ACCOUNT_ROWS!r}) did not appear",
                bank_code="NBE",
            ) from exc

        # 3. Click the 3-dots context menu icon on the first account row
        first_row = await page.query_selector(_SEL_ACCOUNT_ROWS)
        if first_row is None:
            await self._safe_screenshot(page, "first_account_row_missing")
            raise ScraperParseError("NBE: could not locate first account row", bank_code="NBE")

        menu_icon = await first_row.query_selector(_SEL_MENU_ICON)
        if menu_icon is None:
            await self._safe_screenshot(page, "menu_icon_missing")
            raise ScraperParseError(
                "NBE: could not locate account context menu icon", bank_code="NBE"
            )

        await menu_icon.click()
        await self._random_delay(0.8, 1.5)

        # 4. Click "Account Activity"
        try:
            activity_item = await page.wait_for_selector(
                _SEL_ACCOUNT_ACTIVITY, timeout=_SHORT_TIMEOUT_MS
            )
        except PlaywrightTimeoutError as exc:
            await self._safe_screenshot(page, "account_activity_missing")
            raise ScraperTimeoutError(
                "NBE: 'Account Activity' menu item not found", bank_code="NBE"
            ) from exc

        await activity_item.click()
        await self._random_delay(2.0, 4.0)

        # 5. Wait for the Apply button (confirms Account Activity page has loaded)
        try:
            await page.wait_for_selector(_SEL_APPLY_BTN, timeout=_WAIT_TIMEOUT_MS)
        except PlaywrightTimeoutError as exc:
            await self._safe_screenshot(page, "apply_btn_missing")
            raise ScraperTimeoutError(
                "NBE: transaction filter 'Apply' button not found after navigation",
                bank_code="NBE",
            ) from exc

        # 6. Click Apply and wait for table cells to load (AJAX)
        apply_btn = await page.query_selector(_SEL_APPLY_BTN)
        if apply_btn is None:
            raise ScraperParseError("NBE: Apply button disappeared before click", bank_code="NBE")
        await apply_btn.click()
        await self._random_delay(2.0, 3.5)

        try:
            await page.wait_for_selector(_SEL_TXN_TABLE_CELL, timeout=_WAIT_TIMEOUT_MS)
        except PlaywrightTimeoutError as exc:
            await self._safe_screenshot(page, "txn_table_cells_missing")
            raise ScraperTimeoutError(
                "NBE: transaction table cells did not appear after Apply",
                bank_code="NBE",
            ) from exc

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    async def _login(self, page: Page) -> None:
        """Execute the 2-step login flow.

        Step 1: Enter username → click ``#username-button``.
        Step 2: Wait for password field → enter password → click ``.btn-login``.

        Credentials are typed character-by-character and deleted from local
        scope in the ``finally`` block.
        """
        username = self._username  # plaintext — already decrypted by router
        password = self._password  # plaintext — already decrypted by router
        try:
            logger.debug("NBE: filling login form — step 1 (username)")

            # Step 1 — username
            await self._type_human(page, _SEL_USERNAME, username)
            await self._random_delay(0.8, 1.5)

            username_btn = await page.query_selector(_SEL_USERNAME_BTN)
            if username_btn is None:
                raise ScraperParseError(
                    f"NBE: username submit button ({_SEL_USERNAME_BTN!r}) not found",
                    bank_code="NBE",
                )
            await username_btn.click()
            await self._random_delay(1.5, 3.0)

            # Step 2 — wait for password field to render
            try:
                await page.wait_for_selector(_SEL_PASSWORD, timeout=_WAIT_TIMEOUT_MS)
            except PlaywrightTimeoutError as exc:
                raise ScraperTimeoutError(
                    f"NBE: password field ({_SEL_PASSWORD!r}) did not appear after username step",
                    bank_code="NBE",
                ) from exc

            logger.debug("NBE: filling login form — step 2 (password)")
            await self._type_human(page, _SEL_PASSWORD, password)
            await self._random_delay(0.8, 1.5)

            password_btn = await page.query_selector(_SEL_PASSWORD_BTN)
            if password_btn is None:
                raise ScraperParseError(
                    f"NBE: login submit button ({_SEL_PASSWORD_BTN!r}) not found",
                    bank_code="NBE",
                )
            await password_btn.click()
            await self._random_delay(2.0, 4.0)

        finally:
            del username
            del password

    async def _wait_for_dashboard(self, page: Page) -> None:
        """Confirm login succeeded and handle OTP if required.

        Checks for:
        1. OTP prompt — raises ``ScraperOTPRequired`` immediately.
        2. ``a:has-text('Logout')`` appearing in DOM — confirms success.
        3. Timeout — raises ``ScraperTimeoutError``.

        Does NOT screenshot at this stage because the login form may still be
        partially visible while the SPA transitions.
        """
        # Check for OTP prompt before waiting for the dashboard
        otp_el = await page.query_selector(_SEL_OTP_SECTION)
        if otp_el is None:
            otp_el = await page.query_selector(_SEL_OTP_INPUT)
        if otp_el is not None:
            logger.info("NBE: OTP prompt detected")
            raise ScraperOTPRequired(
                "NBE: OTP required — submit via /scrapers/otp endpoint",
                bank_code="NBE",
                session_token="",  # Populated by API layer with real session token
            )

        # Wait for the Logout link which confirms a successful authenticated session
        try:
            await page.wait_for_selector(_SEL_LOGOUT, timeout=_WAIT_TIMEOUT_MS)
        except PlaywrightTimeoutError:
            # Before raising timeout, check if bad-credentials state is showing.
            # The NBE SPA may display an error modal or re-render the login form.
            page_text = ""
            try:
                page_text = await page.inner_text("body")
            except Exception:
                pass

            if any(
                phrase in page_text.lower()
                for phrase in ("invalid", "incorrect", "wrong", "خطأ", "غير صحيح")
            ):
                raise ScraperLoginError("NBE: portal rejected credentials", bank_code="NBE")

            await self._safe_screenshot(page, "dashboard_timeout")
            raise ScraperTimeoutError(
                "NBE: dashboard (Logout link) not found within timeout",
                bank_code="NBE",
            )

    # ------------------------------------------------------------------
    # Data extraction — account
    # ------------------------------------------------------------------

    async def _extract_account(self, page: Page) -> BankAccount:
        """Extract account metadata from the accounts list widget.

        Targets the first ``li.flip-account-list__items`` row which contains:
        - ``.account-no`` → raw account number
        - ``.account-name`` → account name / type (may be in Arabic)
        - ``.account-value`` or adjacent text → balance with currency prefix

        Returns a ``BankAccount`` with sentinel ``id`` / ``user_id`` /
        ``created_at`` / ``updated_at`` values that the pipeline layer replaces.
        """
        html = await page.content()
        soup = BeautifulSoup(html, "lxml")

        rows = soup.select(_SEL_ACCOUNT_ROWS)
        if not rows:
            await self._safe_screenshot(page, "account_rows_parse_missing")
            raise ScraperParseError("NBE: could not locate account rows in DOM", bank_code="NBE")

        first_row = rows[0]

        # Account number
        acc_no_el = first_row.select_one(".account-no")
        raw_account_number = acc_no_el.get_text(strip=True) if acc_no_el else ""
        logger.debug("NBE: raw account number %r", raw_account_number)

        # Account name / type
        acc_name_el = first_row.select_one(".account-name")
        account_type_raw = acc_name_el.get_text(strip=True) if acc_name_el else "current"
        account_type = _normalise_account_type(account_type_raw)

        # Balance — look for .account-value first, then fall back to any text
        # matching a currency+amount pattern inside the row
        balance_text = ""
        balance_el = first_row.select_one(".account-value")
        if balance_el:
            balance_text = balance_el.get_text(strip=True)
        else:
            # Scan all text nodes for a pattern like "EGP 12,345.00" or "-EGP 79,000.00"
            row_text = first_row.get_text(separator=" ")
            m = re.search(r"-?\s*(?:EGP|USD|EUR|GBP|SAR|AED)\s*[\d,.\-]+", row_text, re.I)
            if m:
                balance_text = m.group(0).replace(" ", "")

        currency = _extract_currency_from_balance(balance_text)
        # Strip currency code and leading minus for Decimal parsing
        balance_str = re.sub(r"^-?\s*[A-Z]{3}\s*", "", balance_text.strip())
        # Re-apply negative sign if balance was negative
        if balance_text.strip().startswith("-"):
            balance_str = "-" + balance_str
        balance = _parse_amount(balance_str) or Decimal("0.00")

        masked = self._mask_account_number(raw_account_number)
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
        """Parse transaction rows from the Oracle JET ``oj-table#ViewStatement1``.

        Handles pagination by clicking "Next Page" until no more pages exist or
        ``_MAX_TRANSACTIONS`` is reached.

        Returns up to ``_MAX_TRANSACTIONS`` Transaction objects.
        """
        transactions: list[Transaction] = []
        now = datetime.now(UTC)
        page_num = 0

        while len(transactions) < _MAX_TRANSACTIONS:
            page_num += 1
            logger.debug("NBE: parsing transaction table page %d", page_num)

            html = await page.content()
            rows = _parse_oj_table_rows(html)
            logger.debug("NBE: found %d rows on page %d", len(rows), page_num)

            if not rows and page_num == 1:
                await self._safe_screenshot(page, "txn_table_empty")
                raise ScraperParseError("NBE: transaction table rendered no rows", bank_code="NBE")

            for row_idx, cells in enumerate(rows):
                if len(transactions) >= _MAX_TRANSACTIONS:
                    break
                try:
                    txn = _parse_transaction_row(cells, account, now)
                except Exception as exc:
                    logger.debug(
                        "NBE: skipping row %d (page %d) due to parse error: %s",
                        row_idx,
                        page_num,
                        exc,
                    )
                    continue
                if txn is not None:
                    transactions.append(txn)

            # Check for a Next Page button — if absent or disabled, we're done
            next_btn = await page.query_selector(_SEL_NEXT_PAGE)
            if next_btn is None:
                break

            is_disabled = await next_btn.get_attribute("disabled")
            if is_disabled is not None:
                break

            # Navigate to the next page
            await next_btn.click()
            await self._random_delay(1.5, 3.0)
            try:
                await page.wait_for_selector(_SEL_TXN_TABLE_CELL, timeout=_WAIT_TIMEOUT_MS)
            except PlaywrightTimeoutError as exc:
                await self._safe_screenshot(page, "txn_next_page_timeout")
                raise ScraperTimeoutError(
                    f"NBE: transaction table did not reload after page {page_num} → {page_num + 1}",
                    bank_code="NBE",
                ) from exc

        return transactions
