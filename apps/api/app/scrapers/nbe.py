"""NBE (National Bank of Egypt) scraper — alahlynet.com.eg.

Login URL: https://www.alahlynet.com.eg/?page=home

Portal type
-----------
Oracle Banking Digital Experience (OBDX) SPA backed by Oracle JET.  All
navigation stays on the same base URL — page state changes are indicated by
the ``?page=`` query parameter.  ``networkidle`` waits are used throughout to
let AJAX settle before inspecting the DOM.

Scrape flow
-----------
1. Navigate to login page and wait for ``#login_username``.
2. Enter username → click ``#username-button`` (step 1 of 2-step login).
   The button triggers an OAAM (Oracle Adaptive Access Manager) API call to
   ``getOAAMImageForMobile()`` which validates the username and returns the
   user's security image.  Only after this call succeeds does the SPA set
   ``userNameSubmitted(true)`` and render the password step.
3. Wait for password field ``#login_password`` to appear.  This field is
   dynamically injected into a ``loginContainer`` modal overlay by the SPA
   component after the OAAM call succeeds.  The field is technically an
   ``input[type="text"]`` with CSS ``text-security: disc`` applied to mask
   characters visually.
4. Enter password → click ``button.btn-login-2`` (the password-step submit).
   Note: ``#username-button`` carries class ``btn-login`` (step 1); the
   password step uses a *separate* button with class ``btn-login-2``.
5. Confirm login by waiting for ``li.loggedInUser`` (the logged-in username
   badge in the nav bar) — more reliable than ``a:has-text('Logout')`` since
   the logout anchor may be icon-only.
6. Click the Accounts Summary widget ``li.CSA a`` to flip the account card
   and reveal the account list.
7. Read ALL ``li.flip-account-list__items`` rows and extract a ``BankAccount``
   for each one (savings EGP, current EGP, savings USD, payroll, etc.).
8. For each account at index N:
   a. Re-reveal the accounts widget (navigate back if needed) so that
      ``li.flip-account-list__items`` rows are present.
   b. Click ``a.menu-icon`` on the Nth account row (by index, using
      ``page.locator(…).nth(N)`` to avoid stale handles across SPA re-renders).
   c. Click ``span:has-text('Account Activity')`` from the context menu.
   d. Wait for the filter panel / transaction table.
   e. Click ``button:has-text('Apply')`` and wait for ``oj-table#ViewStatement1``
      rows to load via AJAX.
   f. Parse transaction rows from ``td[id^="ViewStatement1:"]`` cells.
   g. Follow pagination until no more pages or ``_MAX_TRANSACTIONS`` reached.
   h. Navigate back to the dashboard (``page.go_back()`` then re-reveal widget)
      before processing the next account.
9. Return a ``ScraperResult`` with all accounts and all transactions combined.

OTP handling
------------
If an OTP prompt appears after login (detected by ``#otpSection`` or
``input[id*='otp' i]``), ``ScraperOTPRequired`` is raised.  The API layer
must collect the OTP from the user and resume the scrape session.

Selector strategy
-----------------
Selectors are verified against live HTML captured via ``recon_nbe.py`` (see
``/tmp/finpilot_debug/nbe_recon/login_page.html`` and ``dom_inputs.txt``).

Oracle JET renders inner cells with ``id="ViewStatement1:{row}_{col}"`` that
the transaction parser matches against a stable regex pattern.

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
import json
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

# Playwright timeout for page.goto() calls — longer to handle slow international
# connections from Render (Oregon, US West) to the NBE portal (Egypt).
_PAGE_LOAD_TIMEOUT_MS = 150_000

# Default Playwright wait timeout in milliseconds.
# Set high to handle Oregon→Egypt latency (~120-150ms RTT) for AJAX calls.
# Increased to 120s (was 90s) — OAAM auth flow from Render Oregon→Egypt can
# exceed 90s under load.
_WAIT_TIMEOUT_MS = 120_000

# Shorter timeout for optional / conditional element checks.
_SHORT_TIMEOUT_MS = 20_000

# Maximum number of transactions to return per scrape run.
_MAX_TRANSACTIONS = 50

# ---------------------------------------------------------------------------
# Selector catalogue (OBDX / Oracle JET SPA — alahlynet.com.eg)
#
# All selectors below were verified against live HTML captured by recon_nbe.py
# on 2026-03-17.  Re-run recon_nbe.py whenever portal changes are suspected.
# ---------------------------------------------------------------------------

# Step 1 — username input and submit button.
# Both elements are present in the initial page HTML (pre-JS render).
# Confirmed: id="login_username" type=text placeholder="User ID"
# Confirmed: id="username-button" class="btn-login action-button-primary"
_SEL_USERNAME = "#login_username"
_SEL_USERNAME_BTN = "#username-button"

# Step 2 — password field and submit button.
#
# These elements are NOT present in the initial page HTML.  After clicking
# #username-button the SPA calls OAAM's getOAAMImageForMobile() API, then
# sets userNameSubmitted(true) which injects a .loginContainer modal popup
# containing the password form.
#
# The password input: id="login_password", technically type=text with CSS
# text-security:disc masking (not type=password).
#
# The submit button: class="btn-login-2" (60%-width green button for step 2).
# NOTE: class "btn-login" belongs to #username-button (step 1 — full width).
# Using "button.btn-login" would match the WRONG button.
_SEL_PASSWORD = "#login_password"
_SEL_PASSWORD_BTN = "button.btn-login-2"
# Fallback chain tried in order if btn-login-2 is not found:
_SEL_PASSWORD_BTN_FALLBACKS = [
    ".loginContainer button.action-button-primary",
    "button:not(#username-button).btn-login",
]

# Confirms successful login.
# After login the nav bar renders a li.loggedInUser element with the
# welcome text / username.  The logout anchor uses class no-navigation-logout
# but may be icon-only (no reliable text).  li.loggedInUser is safer.
_SEL_LOGGED_IN = "li.loggedInUser"
# Legacy fallback kept for backward compatibility if CSS classes change:
_SEL_LOGOUT = "a.no-navigation-logout, a:has-text('Logout')"

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

# A loaded cell inside the table (used to confirm AJAX has settled).
# Primary selector for pagination waits (light DOM — cells are NOT inside Shadow DOM).
_SEL_TXN_TABLE_CELL = "oj-table#ViewStatement1 td"

# Alternate selector that works when the oj-table custom element wraps the td:
# Oracle JET stamps cell ids as ViewStatement1:{row}_{col}, which is queryable
# even if the ancestor is a custom element.  Used as the JS-based cell-count check.
_SEL_TXN_TABLE_CELL_ALT = "[id^='ViewStatement1:']"

# networkidle timeout after Apply click — generous to allow Oregon→Egypt AJAX RTT.
_APPLY_NETWORKIDLE_TIMEOUT_MS = 150_000

# Extra selector wait tried if networkidle settles but JS cell-count is still 0.
_APPLY_FALLBACK_WAIT_MS = 60_000

# Pagination — Next Page button
_SEL_NEXT_PAGE = "button[title='Next Page']"

# URL fragment that appears once Account Activity is loaded
_TXN_PAGE_URL_FRAGMENT = "demand-deposit-transactions"

# Certificates / Deposits widget selector
_SEL_CERTIFICATES_WIDGET = "li.TRD a"

# Credit Cards widget selector
_SEL_CREDIT_CARDS_WIDGET = "li.CCA a"

# CC statement page URL fragment (used in wait_for_url)
_CC_STATEMENT_URL_FRAGMENT = "card-statement"

# Number of months of CC statement history to scrape
_CC_STATEMENT_MONTHS = 7  # last 6 completed months + current (unbilled)

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
        return "credit_card"
    if "loan" in raw or "قرض" in raw:
        return "loan"
    if "payroll" in raw or "راتب" in raw or "مرتب" in raw:
        return "payroll"
    if any(
        k in raw
        for k in (
            "certificate",
            "شهادة",
            "cert",
            "deposit",
            "وديعة",
            "term",
            "platinum",
            "بلاتينية",
            "ذهبية",
            "gold",
        )
    ):
        return "certificate"
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
            # Account routing key — used by the pipeline layer to map each
            # transaction to the correct DB account_id after multi-account upsert.
            "account_number_masked": account.account_number_masked,
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
        """Execute the full NBE scrape cycle across ALL accounts.

        Discovers all accounts in the Accounts Summary widget and scrapes
        transaction history for each one in turn.  Accounts are processed
        in the order they appear in the ``li.flip-account-list__items`` list
        (typically: savings EGP, current EGP, savings USD, payroll).

        Returns:
            ``ScraperResult`` with a ``BankAccount`` per discovered account
            and up to ``_MAX_TRANSACTIONS`` transactions per account,
            combined in ``transactions``.

        Raises:
            ScraperLoginError: If the portal rejects the credentials.
            ScraperOTPRequired: If an OTP challenge is detected after login.
            ScraperTimeoutError: If any Playwright wait exceeds its deadline.
            ScraperParseError: If the HTML structure is not as expected.
        """
        # Retry once on dashboard timeout — NBE portal from Oregon is intermittently
        # slow to render li.loggedInUser after a successful login.  A fresh browser
        # session on the second attempt succeeds in most cases.
        _MAX_LOGIN_ATTEMPTS = 2
        for _attempt in range(1, _MAX_LOGIN_ATTEMPTS + 1):
            browser, context, page = await self._launch_browser()
            raw_html: dict[str, str] = {}
            _dashboard_ok = False
            try:
                await self._navigate_to_login(page)
                await self._login(page)
                await self._wait_for_dashboard(page)
                _dashboard_ok = True
            except ScraperTimeoutError:
                await self._close_browser(browser)
                if _attempt < _MAX_LOGIN_ATTEMPTS:
                    logger.warning(
                        "NBE: dashboard timed out on attempt %d/%d — retrying with fresh browser",
                        _attempt,
                        _MAX_LOGIN_ATTEMPTS,
                    )
                    continue
                raise  # exhausted retries
            except Exception:
                await self._close_browser(browser)
                raise

            if _dashboard_ok:
                break  # proceed with the open browser/page below

        try:
            # Capture dashboard HTML for audit trail (post-auth — safe to screenshot)
            raw_html["dashboard"] = await page.content()

            # ------------------------------------------------------------------
            # Scrape credit cards FIRST while the browser is fresh.
            # After scraping 4 demand-deposit accounts the Oracle JET SPA is
            # resource-constrained and li.CCA takes >120s to hydrate.
            # ------------------------------------------------------------------
            cc_accounts: list[BankAccount] = []
            try:
                cc_accounts = await self._scrape_credit_cards(page)
                if cc_accounts:
                    logger.info("NBE: found %d credit card account(s)", len(cc_accounts))
                    raw_html["credit_cards"] = await page.content()
            except Exception as cc_exc:
                logger.warning("NBE: credit card scraping failed (non-fatal): %s", cc_exc)

            try:
                cc_txns = await self._scrape_cc_transactions(page, cc_accounts)
                if cc_txns:
                    logger.info("NBE: scraped %d CC statement transaction(s)", len(cc_txns))
            except Exception as cc_txn_exc:
                logger.warning("NBE: CC transaction scraping failed (non-fatal): %s", cc_txn_exc)
                cc_txns = []

            # ------------------------------------------------------------------
            # Reveal the accounts card to enumerate demand-deposit accounts.
            # Navigate to a fresh dashboard first — the CC statement page may
            # be active after _scrape_cc_transactions, hiding the CSA widget.
            # ------------------------------------------------------------------
            try:
                await page.goto(
                    _LOGIN_URL,
                    wait_until="domcontentloaded",
                    timeout=_PAGE_LOAD_TIMEOUT_MS,
                )
                await self._random_delay(1.0, 2.0)
            except PlaywrightTimeoutError:
                logger.warning(
                    "NBE: dashboard re-navigation timed out before demand-deposit scrape — proceeding anyway"
                )

            await self._reveal_accounts_widget(page)

            accounts = await self._extract_all_accounts(page)
            total = len(accounts)
            logger.info("NBE: found %d account(s) in widget", total)

            all_transactions: list = list(cc_txns)

            for idx, account in enumerate(accounts):
                logger.info(
                    "NBE: scraping account %d/%d — masked=%s type=%s currency=%s",
                    idx + 1,
                    total,
                    account.account_number_masked,
                    account.account_type,
                    account.currency,
                )
                try:
                    # For accounts after the first we need to be back at the
                    # accounts list — re-reveal the widget (it is safe to call
                    # multiple times; it waits for the rows to be present).
                    if idx > 0:
                        await self._reveal_accounts_widget(page)

                    await self._navigate_to_transactions_for_account(page, idx)
                    raw_html[f"transactions_{idx}"] = await page.content()

                    txns = await self._extract_transactions(page, account)
                    logger.info(
                        "NBE: account %d/%d — extracted %d transactions",
                        idx + 1,
                        total,
                        len(txns),
                    )
                    all_transactions.extend(txns)

                    # Navigate back to the accounts list for the next iteration.
                    # page.go_back() returns to the dashboard; then re-reveal
                    # is handled at the top of the next loop iteration.
                    if idx < total - 1:
                        logger.info("NBE: navigating back to dashboard for next account")
                        try:
                            await page.go_back(
                                wait_until="domcontentloaded",
                                timeout=_PAGE_LOAD_TIMEOUT_MS,
                            )
                        except PlaywrightTimeoutError:
                            # go_back can time out on Oracle JET SPAs — the DOM
                            # content still loads; treat this as a soft warning
                            # and let _reveal_accounts_widget confirm readiness.
                            logger.warning(
                                "NBE: go_back() timed out for account %d — proceeding",
                                idx + 1,
                            )
                        await self._random_delay(0.8, 1.5)

                except (ScraperLoginError, ScraperOTPRequired):
                    raise  # fatal — abort the entire scrape
                except Exception as account_exc:
                    logger.warning(
                        "NBE: failed to scrape account %d/%d (masked=%s) — skipping. Error: %s: %s",
                        idx + 1,
                        total,
                        account.account_number_masked,
                        type(account_exc).__name__,
                        account_exc,
                    )
                    # Navigate back to login page for reliable state recovery.
                    # go_back() is unreliable on Oracle JET SPAs.  After goto()
                    # the session may be gone (OBDX logs out on navigation), so
                    # check for the login form and re-authenticate if needed.
                    try:
                        await page.goto(
                            _LOGIN_URL,
                            wait_until="domcontentloaded",
                            timeout=_PAGE_LOAD_TIMEOUT_MS,
                        )
                        await self._random_delay(1.0, 2.0)
                        # If the login username field is visible, the session
                        # was lost — re-login before the next account iteration.
                        login_field = await page.query_selector(_SEL_USERNAME)
                        if login_field is not None and await login_field.is_visible():
                            logger.info(
                                "NBE: session lost after account %d failure — re-logging in",
                                idx + 1,
                            )
                            await self._login(page)
                            await self._wait_for_dashboard(page)
                    except (ScraperLoginError, ScraperOTPRequired):
                        raise  # propagate auth failures — can't continue
                    except Exception as recovery_exc:
                        logger.warning(
                            "NBE: recovery re-login failed after account %d: %s",
                            idx + 1,
                            recovery_exc,
                        )
                    continue

            # ------------------------------------------------------------------
            # Scrape certificates LAST — after demand-deposit accounts so that
            # the CC + demand-deposit data is already captured even if the TRD
            # widget navigation triggers an OOM on memory-constrained instances.
            # li.TRD hydration is slow post-DD but acceptable since certs are
            # lower priority than the CC and demand-deposit data above.
            # ------------------------------------------------------------------
            cert_accounts: list[BankAccount] = []
            try:
                cert_accounts = await self._scrape_certificates(page)
                if cert_accounts:
                    logger.info("NBE: found %d certificate/deposit account(s)", len(cert_accounts))
                    raw_html["certificates"] = await page.content()
            except Exception as cert_exc:
                logger.warning("NBE: certificate scraping failed (non-fatal): %s", cert_exc)

            # Combine all account types: demand-deposit + credit cards + certificates
            accounts = accounts + cc_accounts + cert_accounts

            logger.info(
                "NBE: scrape complete — %d account(s), %d transaction(s) total",
                len(accounts),
                len(all_transactions),
            )

            return ScraperResult(
                accounts=accounts,
                transactions=all_transactions,
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
            # Capture diagnostic context so we can debug without re-running.
            # Log page URL and a safe snippet of the current HTML (first 500 chars
            # of body text, stripped of scripts/styles) — never log credentials.
            _diag_url = "<unknown>"
            _diag_html_snippet = "<unavailable>"
            try:
                _diag_url = page.url
            except Exception:
                pass
            try:
                _diag_html_snippet = (await page.inner_text("body"))[:500].replace("\n", " ")
            except Exception:
                try:
                    _raw = await page.content()
                    # Strip script/style blocks for a clean snippet
                    _clean = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", _raw, flags=re.S)
                    _diag_html_snippet = _clean[:500]
                except Exception:
                    pass

            logger.error(
                "NBE scrape failed — url=%r error=%s: %s | page_text_snippet=%r",
                _diag_url,
                type(exc).__name__,
                exc,
                _diag_html_snippet,
            )
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
        """Navigate to the NBE login page and wait for the username field.

        Uses ``domcontentloaded`` rather than ``networkidle`` for the initial
        goto because the NBE portal (Oracle JET SPA) keeps persistent XHR
        connections open that prevent ``networkidle`` from ever resolving when
        accessed from a geographically distant server.  A separate
        ``wait_for_selector`` on the username field confirms the SPA has
        rendered the login form before proceeding.
        """
        logger.info("NBE: navigating to login page %s", _LOGIN_URL)
        try:
            await page.goto(
                _LOGIN_URL,
                wait_until="domcontentloaded",
                timeout=_PAGE_LOAD_TIMEOUT_MS,
            )
        except PlaywrightTimeoutError as exc:
            raise ScraperTimeoutError(
                "NBE login page did not load within timeout", bank_code="NBE"
            ) from exc

        logger.info("NBE: DOM content loaded — waiting for username field %r", _SEL_USERNAME)
        try:
            await page.wait_for_selector(_SEL_USERNAME, timeout=_PAGE_LOAD_TIMEOUT_MS)
        except PlaywrightTimeoutError as exc:
            raise ScraperTimeoutError(
                f"NBE: username field ({_SEL_USERNAME!r}) not found", bank_code="NBE"
            ) from exc

        logger.info("NBE: login page ready — username field visible")

    async def _reveal_accounts_widget(self, page: Page) -> None:
        """Click the Accounts Summary widget and wait for account rows to appear.

        Must be called before ``_extract_account`` so that
        ``li.flip-account-list__items`` elements are present in the DOM.
        """
        logger.info("NBE: waiting for accounts widget %r", _SEL_ACCOUNTS_WIDGET)
        try:
            await page.wait_for_selector(_SEL_ACCOUNTS_WIDGET, timeout=_WAIT_TIMEOUT_MS)
        except PlaywrightTimeoutError as exc:
            await self._safe_screenshot(page, "accounts_widget_missing")
            raise ScraperTimeoutError(
                f"NBE: accounts widget ({_SEL_ACCOUNTS_WIDGET!r}) not found",
                bank_code="NBE",
            ) from exc

        logger.info("NBE: clicking accounts widget to reveal account list")
        # Use page.click() instead of handle.click() — the Oracle JET SPA re-renders
        # elements after interaction, which detaches stored ElementHandles.
        await page.click(_SEL_ACCOUNTS_WIDGET)
        await self._random_delay(0.8, 1.5)

        logger.info("NBE: waiting for account rows %r", _SEL_ACCOUNT_ROWS)
        try:
            await page.wait_for_selector(_SEL_ACCOUNT_ROWS, timeout=_WAIT_TIMEOUT_MS)
        except PlaywrightTimeoutError as exc:
            await self._safe_screenshot(page, "account_rows_missing")
            raise ScraperTimeoutError(
                f"NBE: account rows ({_SEL_ACCOUNT_ROWS!r}) did not appear",
                bank_code="NBE",
            ) from exc

        logger.info("NBE: account rows revealed")

    async def _navigate_to_transactions_for_account(self, page: Page, account_index: int) -> None:
        """Navigate from the already-revealed account list to the Account Activity page.

        Assumes ``_reveal_accounts_widget`` has already been called so that
        ``li.flip-account-list__items`` rows are present in the DOM.

        Uses ``page.locator(…).nth(account_index)`` to target the correct row
        without storing an ``ElementHandle`` across SPA re-renders.  The Oracle
        JET SPA detaches element handles on every DOM mutation, so all clicks
        must go through fresh locator queries.

        Args:
            page: The active Playwright page.
            account_index: Zero-based index of the account row to navigate into.

        Flow:
        1. Click the 3-dots menu icon on the Nth account row.
        2. Click "Account Activity" from the context menu.
        3. Wait for the transaction filter panel and Apply button.
        4. Click Apply and wait for the transaction table rows to load.
        """
        logger.info("NBE: navigating to Account Activity for account index %d", account_index)
        await self._random_delay(0.8, 1.5)

        # 1. Click the 3-dots context menu icon on the target account row.
        # page.locator().nth() is lazily evaluated — it re-queries the DOM at
        # click time, which is correct for Oracle JET SPAs that re-render after
        # every interaction.  We never store the ElementHandle.
        try:
            await (
                page.locator(_SEL_ACCOUNT_ROWS)
                .nth(account_index)
                .locator(_SEL_MENU_ICON)
                .click(timeout=_SHORT_TIMEOUT_MS)
            )
        except PlaywrightTimeoutError as exc:
            await self._safe_screenshot(page, f"menu_icon_missing_idx{account_index}")
            raise ScraperParseError(
                f"NBE: could not locate/click account context menu icon at index {account_index}",
                bank_code="NBE",
            ) from exc

        logger.info("NBE: clicked account context menu icon (index=%d)", account_index)
        await self._random_delay(0.8, 1.5)

        # 4. Click "Account Activity" — must target the VISIBLE menu item only.
        # "span:has-text('Account Activity')" matches one span per account row
        # (4 total), but only the one inside the currently-open context menu
        # popup is actually visible.  page.click() always picks the first DOM
        # match regardless of visibility, so for accounts 1-3 it always clicks
        # account 0's item instead of the open one.
        # We use locator().filter(has_text=...) with wait_for(state="visible")
        # which is Playwright's idiomatic way to target the visible instance.
        # After clicking the 3-dots menu icon, only ONE of the (up to 4) matching
        # "Account Activity" spans is visible — the one inside the popup that just
        # opened.  page.click() always picks the first DOM match regardless of
        # visibility; for accounts 1-3 this clicks account 0's hidden item and
        # no navigation occurs, causing a 30s timeout.
        #
        # Fix: wait for at least one match to become visible, then iterate all
        # matches and click the first visible one.  This is the idiomatic
        # Playwright approach when multiple elements share the same selector.
        logger.info("NBE: waiting for visible 'Account Activity' menu item")
        try:
            await page.wait_for_selector(
                _SEL_ACCOUNT_ACTIVITY, state="visible", timeout=_SHORT_TIMEOUT_MS
            )
        except PlaywrightTimeoutError as exc:
            await self._safe_screenshot(page, "account_activity_missing")
            raise ScraperTimeoutError(
                "NBE: 'Account Activity' menu item not found (visible)", bank_code="NBE"
            ) from exc

        # Iterate all matching spans and click the first visible one.
        logger.info("NBE: clicking visible 'Account Activity' — navigating to transactions page")
        clicked = False
        for loc in await page.locator(_SEL_ACCOUNT_ACTIVITY).all():
            if await loc.is_visible():
                await loc.click(timeout=_SHORT_TIMEOUT_MS)
                clicked = True
                break
        if not clicked:
            # Fallback: click by index 0 (should not happen after wait_for_selector above)
            await page.locator(_SEL_ACCOUNT_ACTIVITY).first.click(timeout=_SHORT_TIMEOUT_MS)

        # Confirm the SPA actually navigated to the transaction page URL.
        # Oracle JET SPAs change the ?page= query param on navigation; waiting
        # for the URL fragment ensures the click triggered real navigation and
        # we are not still on the dashboard / previous account's page.
        logger.info(
            "NBE: waiting for URL to contain %r (confirms navigation)", _TXN_PAGE_URL_FRAGMENT
        )
        try:
            await page.wait_for_url(f"**{_TXN_PAGE_URL_FRAGMENT}**", timeout=_WAIT_TIMEOUT_MS)
        except PlaywrightTimeoutError as exc:
            await self._safe_screenshot(page, "txn_page_url_missing")
            raise ScraperParseError(
                f"NBE: URL did not contain '{_TXN_PAGE_URL_FRAGMENT}' after Account Activity click "
                f"— SPA navigation may have failed (account_index={account_index})",
                bank_code="NBE",
            ) from exc
        logger.info("NBE: confirmed on transaction page URL")
        await self._random_delay(1.0, 2.0)

        # 5. Wait for the transaction table OR the Apply button — whichever arrives first.
        # On some NBE portal versions the table loads automatically without needing
        # to click Apply; on others the Apply button must be clicked first.
        logger.info("NBE: waiting for transaction table or Apply button (whichever comes first)")
        try:
            await page.wait_for_selector(
                f"{_SEL_TXN_TABLE_CELL}, {_SEL_APPLY_BTN}",
                timeout=_WAIT_TIMEOUT_MS,
            )
        except PlaywrightTimeoutError as exc:
            await self._safe_screenshot(page, "apply_btn_missing")
            raise ScraperTimeoutError(
                "NBE: neither transaction table nor Apply button appeared after Account Activity navigation",
                bank_code="NBE",
            ) from exc

        # If the Apply button is present, click it to trigger the default date-range query.
        apply_btn = await page.query_selector(_SEL_APPLY_BTN)
        if apply_btn is not None:
            logger.info("NBE: Apply button present — clicking to load transactions")
            await apply_btn.click()
            await self._random_delay(1.0, 1.8)

            # Wait for network to settle first.  This gives the Oregon→Egypt AJAX call
            # as much time as it needs rather than racing against a fixed element timeout.
            logger.info(
                "NBE: waiting for networkidle after Apply click (timeout=%dms)",
                _APPLY_NETWORKIDLE_TIMEOUT_MS,
            )
            try:
                await page.wait_for_load_state("networkidle", timeout=_APPLY_NETWORKIDLE_TIMEOUT_MS)
            except PlaywrightTimeoutError:
                # networkidle may never fire on Oracle JET SPAs that keep persistent
                # XHR connections open — proceed to the cell-count check regardless.
                logger.warning(
                    "NBE: networkidle timed out after Apply — proceeding to cell count check"
                )

            # Use JS to count cells by their stable id prefix.  This pierces any custom-
            # element wrapping without relying on the CSS descendant combinator, which can
            # fail against non-standard elements like oj-table when slots are used.
            cell_count: int = await page.evaluate(
                "() => document.querySelectorAll('[id^=\"ViewStatement1:\"]').length"
            )
            logger.info("NBE: cell count after networkidle = %d", cell_count)

            if cell_count == 0:
                # Cells not yet present — one more explicit wait using the alt selector.
                logger.info(
                    "NBE: cells not yet visible — waiting up to %dms for %r",
                    _APPLY_FALLBACK_WAIT_MS,
                    _SEL_TXN_TABLE_CELL_ALT,
                )
                try:
                    await page.wait_for_selector(
                        _SEL_TXN_TABLE_CELL_ALT, timeout=_APPLY_FALLBACK_WAIT_MS
                    )
                    cell_count = await page.evaluate(
                        "() => document.querySelectorAll('[id^=\"ViewStatement1:\"]').length"
                    )
                    logger.info("NBE: cell count after fallback wait = %d", cell_count)
                except PlaywrightTimeoutError:
                    pass  # cell_count remains 0 — error raised below

            if cell_count == 0:
                # Check whether the oj-table element itself exists — if it does,
                # the table loaded but has no rows (account has no transactions in
                # the default date range).  This is a valid result, not an error.
                table_exists: bool = await page.evaluate(
                    "() => document.querySelector('oj-table#ViewStatement1') !== null"
                )
                if table_exists:
                    logger.info(
                        "NBE: oj-table#ViewStatement1 present but empty "
                        "— account has no transactions in default date range"
                    )
                    # Return early — _extract_transactions will receive empty HTML
                    # and produce an empty list, which is correct.
                    return
                # Log the current page URL to help diagnose what went wrong.
                current_url = page.url
                logger.warning(
                    "NBE: oj-table#ViewStatement1 not found after Apply "
                    "(account_index=%d, url=%r) — treating as no transactions "
                    "(SPA may have rendered an error/empty state instead of the table)",
                    account_index,
                    current_url,
                )
                await self._safe_screenshot(page, "txn_table_cells_missing")
                # Treat as empty rather than fatal — the account may genuinely have
                # no transactions visible, or the SPA rendered a non-table state.
                # Raising here was causing all subsequent accounts to be skipped too.
                return
        else:
            logger.info("NBE: Apply button absent — table loaded automatically")

        logger.info("NBE: transaction table loaded successfully")

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    async def _login(self, page: Page) -> None:
        """Execute the 2-step login flow.

        Step 1: Enter username → click ``#username-button``.
          After the click the SPA calls OAAM's ``getOAAMImageForMobile()``
          API to validate the username.  Only on success does it set
          ``userNameSubmitted(true)`` and inject the password form.

        Step 2: Wait for ``#login_password`` → enter password → click
          ``button.btn-login-2`` (the 60%-width green submit for step 2).
          IMPORTANT: ``button.btn-login`` is the step-1 username button
          (full width, id="username-button").  Using it here would be wrong.

        Credentials are typed character-by-character and deleted from local
        scope in the ``finally`` block.
        """
        username = self._username  # plaintext — already decrypted by router
        password = self._password  # plaintext — already decrypted by router
        try:
            logger.info("NBE: login step 1 — typing username")

            # Step 1 — username
            await self._type_human(page, _SEL_USERNAME, username)
            await self._random_delay(0.8, 1.5)

            username_btn = await page.query_selector(_SEL_USERNAME_BTN)
            if username_btn is None:
                raise ScraperParseError(
                    f"NBE: username submit button ({_SEL_USERNAME_BTN!r}) not found",
                    bank_code="NBE",
                )
            logger.info("NBE: clicking username submit button — waiting for OAAM API call")
            await username_btn.click()
            # The OAAM API call can take several seconds — wait generously.
            await self._random_delay(1.2, 2.0)

            # Step 2 — wait for password field to render inside loginContainer popup.
            # The field uses id="login_password" with CSS text-security masking.
            logger.info("NBE: waiting for password field %r to appear", _SEL_PASSWORD)
            try:
                await page.wait_for_selector(_SEL_PASSWORD, timeout=_WAIT_TIMEOUT_MS)
            except PlaywrightTimeoutError as exc:
                raise ScraperTimeoutError(
                    f"NBE: password field ({_SEL_PASSWORD!r}) did not appear after username "
                    f"step — OAAM call may have failed or username is not recognised",
                    bank_code="NBE",
                ) from exc

            logger.info("NBE: login step 2 — typing password")
            await self._type_human(page, _SEL_PASSWORD, password)
            await self._random_delay(0.8, 1.5)

            # Find the password step submit button (class="btn-login-2").
            # Try primary selector first, then fallbacks in order.
            password_btn = await page.query_selector(_SEL_PASSWORD_BTN)
            if password_btn is None:
                logger.debug(
                    "NBE: %r not found — trying fallback password button selectors",
                    _SEL_PASSWORD_BTN,
                )
                for fallback_sel in _SEL_PASSWORD_BTN_FALLBACKS:
                    password_btn = await page.query_selector(fallback_sel)
                    if password_btn is not None:
                        logger.debug("NBE: password button found via fallback %r", fallback_sel)
                        break

            if password_btn is None:
                raise ScraperParseError(
                    f"NBE: password submit button not found "
                    f"(tried {_SEL_PASSWORD_BTN!r} and {_SEL_PASSWORD_BTN_FALLBACKS!r})",
                    bank_code="NBE",
                )
            logger.info("NBE: clicking password submit button")
            await password_btn.click()
            # Give OAAM more time to complete the auth handshake before
            # _wait_for_dashboard starts polling for li.loggedInUser.
            await self._random_delay(2.0, 3.0)

        finally:
            del username
            del password

    async def _wait_for_dashboard(self, page: Page) -> None:
        """Confirm login succeeded and handle OTP if required.

        Checks for:
        1. OTP prompt — raises ``ScraperOTPRequired`` immediately.
        2. ``li.loggedInUser`` appearing in DOM — confirms successful session.
           Falls back to ``a.no-navigation-logout`` if the primary selector
           is absent (portal CSS class changes).
        3. Timeout — raises ``ScraperTimeoutError``.

        Does NOT screenshot at this stage because the login form may still be
        partially visible while the SPA transitions.
        """
        # Check for OTP prompt before waiting for the dashboard
        logger.info("NBE: checking for OTP prompt")
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

        # Wait for the loggedInUser nav badge which confirms an authenticated session.
        # li.loggedInUser is more reliable than looking for Logout link text because
        # the logout anchor on alahlynet.com.eg may be icon-only (no visible text).
        logger.info("NBE: waiting for dashboard (loggedInUser selector)")
        _logged_in_found = False
        try:
            await page.wait_for_selector(_SEL_LOGGED_IN, timeout=_WAIT_TIMEOUT_MS)
            _logged_in_found = True
        except PlaywrightTimeoutError:
            # li.loggedInUser not found — try the logout link fallback before giving up
            logout_found = False
            try:
                await page.wait_for_selector(_SEL_LOGOUT, timeout=_SHORT_TIMEOUT_MS)
                logout_found = True
            except PlaywrightTimeoutError:
                pass

            if logout_found:
                logger.info("NBE: login confirmed via logout fallback selector")
                return

            # Neither CSS selector found — check if the SPA URL has moved away
            # from the login page.  After successful authentication the Oracle JET
            # SPA replaces the ?page=home fragment with the dashboard path.  If the
            # URL no longer contains "?page=home" (or contains no "?page=" at all),
            # the login succeeded even though the nav selectors are still rendering.
            try:
                current_url = page.url
                if isinstance(current_url, str) and (
                    "page=home" not in current_url or "?page=" not in current_url
                ):
                    logger.info("NBE: login confirmed via URL change — URL=%r", current_url)
                    return
            except Exception:
                pass

            # Neither selector found — check if bad-credentials state is showing.
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
                "NBE: dashboard (loggedInUser / logout selectors) not found within timeout",
                bank_code="NBE",
            )

        if _logged_in_found:
            logger.info("NBE: login confirmed — loggedInUser element visible in nav bar")

    # ------------------------------------------------------------------
    # Data extraction — accounts
    # ------------------------------------------------------------------

    async def _extract_all_accounts(self, page: Page) -> list[BankAccount]:
        """Extract account metadata for ALL accounts in the accounts list widget.

        Reads every ``li.flip-account-list__items`` row, extracting:
        - ``.account-no`` → raw account number
        - ``.account-name`` → account name / type (may be in Arabic)
        - ``.account-value`` or adjacent text → balance with currency prefix

        Returns a list of ``BankAccount`` objects (one per row) with sentinel
        ``id`` / ``user_id`` / ``created_at`` / ``updated_at`` values that the
        pipeline layer replaces.

        Raises:
            ScraperParseError: If no account rows are found in the DOM.
        """
        html = await page.content()
        soup = BeautifulSoup(html, "lxml")

        rows = soup.select(_SEL_ACCOUNT_ROWS)
        if not rows:
            await self._safe_screenshot(page, "account_rows_parse_missing")
            raise ScraperParseError("NBE: could not locate account rows in DOM", bank_code="NBE")

        logger.info("NBE: found %d account row(s) in widget HTML", len(rows))
        accounts: list[BankAccount] = []
        now = datetime.now(UTC)

        for row_idx, row in enumerate(rows):
            # Account number — prefer div.account-no (full account number),
            # fall back to span.account-name which also contains the account number.
            acc_no_el = row.find("div", class_="account-no") or row.select_one(".account-no")
            raw_account_number = acc_no_el.get_text(strip=True) if acc_no_el else ""
            logger.debug("NBE: row %d raw account number %r", row_idx, raw_account_number)

            # Account product name / type — use div.account-name (Arabic product
            # name like "توفير بعائد سنوي" or "مرتبات الموظفين").
            # The span.account-name contains the account NUMBER and must be skipped.
            acc_name_el = row.find("div", class_="account-name")
            account_type_raw = acc_name_el.get_text(strip=True) if acc_name_el else "current"
            account_type = _normalise_account_type(account_type_raw)

            # Balance — prefer .balance-amount (confirmed present in recon),
            # fall back to .account-value or regex scan of row text.
            balance_text = ""
            balance_el = row.select_one(".balance-amount") or row.select_one(".account-value")
            if balance_el:
                balance_text = balance_el.get_text(strip=True)
            else:
                # Scan all text nodes for a pattern like "EGP 12,345.00" or "-EGP 79,000.00"
                row_text = row.get_text(separator=" ")
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
            logger.debug(
                "NBE: row %d → masked=%s type=%s currency=%s balance=%s",
                row_idx,
                masked,
                account_type,
                currency,
                balance,
            )

            accounts.append(
                BankAccount(
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
            )

        return accounts

    # ------------------------------------------------------------------
    # Data extraction — transactions
    # ------------------------------------------------------------------

    async def _extract_transactions(self, page: Page, account: BankAccount) -> list[Transaction]:
        """Parse transaction rows from the Oracle JET ``oj-table#ViewStatement1``.

        Handles pagination by clicking "Next Page" until no more pages exist or
        ``_MAX_TRANSACTIONS`` is reached.

        Each returned ``Transaction`` has ``raw_data["account_number_masked"]``
        set to ``account.account_number_masked`` so the pipeline can route
        transactions to the correct DB account after multi-account upsert.

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
                # Table is absent or empty — _navigate_to_transactions_for_account
                # already logged a warning when it couldn't find the oj-table.
                # Return an empty list rather than raising so that the account is
                # recorded (with its balance) and subsequent accounts still run.
                logger.warning(
                    "NBE: _extract_transactions found no rows on page 1 — "
                    "returning empty list (account has no visible transactions)"
                )
                return transactions

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
            await self._random_delay(0.8, 1.5)
            try:
                await page.wait_for_selector(_SEL_TXN_TABLE_CELL, timeout=_WAIT_TIMEOUT_MS)
            except PlaywrightTimeoutError as exc:
                await self._safe_screenshot(page, "txn_next_page_timeout")
                raise ScraperTimeoutError(
                    f"NBE: transaction table did not reload after page {page_num} → {page_num + 1}",
                    bank_code="NBE",
                ) from exc

        return transactions

    # ------------------------------------------------------------------
    # Data extraction — credit cards
    # ------------------------------------------------------------------

    async def _scrape_credit_cards(self, page: Page) -> list[BankAccount]:
        """Navigate to the Credit Cards widget and extract account data.

        NBE shows credit cards in a ``li.CCA`` flip-card on the dashboard.
        Clicking ``li.CCA a`` reveals ``li.flip-account-list__items`` rows inside
        ``div.flip-account.CCA`` with:
        - ``.account-name``   — cardholder name (e.g. "FADY HABIB")
        - ``.balance-amount`` — available cash limit (NOT the billed amount)
        - ``.account-no``     — masked card number + expiry (e.g. "544111******1204 | 07/28")

        The click also triggers:
          GET /digx/v1/cz/creditcardList/creditcarddetails
        which returns the authoritative ``totalbilledamount`` (outstanding debt).
        We intercept this to use as the account balance.

        Returns:
            List of ``BankAccount`` objects with ``account_type='credit_card'``.
            Returns empty list if the CCA widget is not present.
        """
        logger.info("NBE: scraping credit cards via %r widget", _SEL_CREDIT_CARDS_WIDGET)

        # Navigate to the dashboard only if we are not already there.
        # CC is scraped right after login so we are usually already on the dashboard —
        # an unconditional goto wastes 30-90s waiting for domcontentloaded + loggedInUser.
        current_url = page.url
        on_dashboard = "page=home" in current_url or current_url.rstrip("/") == _LOGIN_URL.rstrip(
            "/"
        )
        logger.info(
            "NBE: navigating to dashboard for CC scrape (current url: %s, on_dashboard=%s)",
            current_url,
            on_dashboard,
        )
        if not on_dashboard:
            try:
                await page.goto(
                    _LOGIN_URL,
                    wait_until="domcontentloaded",
                    timeout=_PAGE_LOAD_TIMEOUT_MS,
                )
            except PlaywrightTimeoutError:
                logger.warning(
                    "NBE: dashboard navigation timed out before credit card scrape — skipping"
                )
                return []

            # Wait for login session to be confirmed after navigation.
            try:
                await page.wait_for_selector("li.loggedInUser", timeout=90_000)
            except PlaywrightTimeoutError:
                logger.warning("NBE: session lost after navigation — cannot scrape credit cards")
                return []

        # Wait for Oracle JET to hydrate the CCA widget.
        # Use 150s — after a fresh login the widget should appear quickly; this
        # gives headroom if the SPA is slow but avoids treating a timeout as
        # "no credit card" when the widget is just slow to hydrate.
        try:
            await page.wait_for_selector(_SEL_CREDIT_CARDS_WIDGET, timeout=150_000)
        except PlaywrightTimeoutError:
            logger.info("NBE: no CCA (credit cards) widget found — user has no credit cards")
            return []

        # Intercept the creditcarddetails API call to get authoritative billed amounts
        # Maps maskedcardno → {totalbilledamount, totalunbilledamount, creditlimit,
        #                       minamountdue, paymentduedate, currency}
        cc_api_data: dict[str, dict] = {}

        async def _capture_cc_details(resp: object) -> None:
            url = getattr(resp, "url", "")
            if "creditcarddetails" in url or "creditcardList" in url:
                try:
                    body = await resp.text()  # type: ignore[union-attr]
                    data = json.loads(body)
                    for card in data.get("creditcards2", []):
                        masked = str(card.get("maskedcardno", ""))
                        if masked:
                            cc_api_data[masked] = {
                                "totalbilledamount": card.get("totalbilledamount", "0"),
                                "totalunbilledamount": card.get("totalunbilledamount", "0"),
                                "creditlimit": card.get("creditlimit", "0"),
                                "currency": card.get("cardcurrency", "EGP"),
                                "accountreferenceno": card.get("accountreferenceno", ""),
                                "minamountdue": card.get("minamountdue", "0"),
                                "paymentduedate": card.get("paymentduedate", ""),
                            }
                            logger.info(
                                "NBE: CC details API → masked=%s billed=%s unbilled=%s "
                                "minamountdue=%s paymentduedate=%s",
                                masked,
                                card.get("totalbilledamount"),
                                card.get("totalunbilledamount"),
                                card.get("minamountdue"),
                                card.get("paymentduedate"),
                            )
                except Exception:
                    pass

        page.on("response", _capture_cc_details)
        _cc_rows_loaded = False
        try:
            await page.click(_SEL_CREDIT_CARDS_WIDGET)
            await self._random_delay(1.5, 2.5)
            # Keep listening until the account rows appear — the creditcarddetails API
            # response may arrive after the click delay.
            await page.wait_for_selector(_SEL_ACCOUNT_ROWS, timeout=_WAIT_TIMEOUT_MS)
            _cc_rows_loaded = True
        except PlaywrightTimeoutError:
            pass
        finally:
            page.remove_listener("response", _capture_cc_details)

        if not _cc_rows_loaded:
            logger.warning("NBE: credit card rows did not appear after clicking CCA widget")
            return []

        html = await page.content()
        soup = BeautifulSoup(html, "lxml")

        # Use the CCA-specific container to avoid mixing with demand-deposit rows.
        # If div.flip-account.CCA is absent the click did not reveal it — return empty.
        cca_container = soup.select_one("div.flip-account.CCA")
        if not cca_container:
            logger.info("NBE: no credit card rows found in CCA flip-card HTML")
            return []
        rows = cca_container.select(_SEL_ACCOUNT_ROWS)
        if not rows:
            logger.info("NBE: no credit card rows found in CCA flip-card HTML")
            return []

        logger.info(
            "NBE: found %d credit card row(s) | cc_api_data keys=%s",
            len(rows),
            list(cc_api_data.keys()),
        )
        accounts: list[BankAccount] = []
        now = datetime.now(UTC)

        for row_idx, row in enumerate(rows):
            # Card number is in .account-no (e.g. "544111******1204 | 07/28")
            acc_no_el = row.find("div", class_="account-no") or row.select_one(".account-no")
            raw_card_info = acc_no_el.get_text(strip=True) if acc_no_el else ""
            # Strip the expiry date portion: "544111******1204 | 07/28" → "544111******1204"
            raw_card_number = (
                raw_card_info.split("|")[0].strip() if "|" in raw_card_info else raw_card_info
            )

            # Try to get authoritative balance from the creditcarddetails API intercept.
            # The API uses maskedcardno format like "544111******1204" which matches raw_card_number.
            api_entry = cc_api_data.get(raw_card_number, {})
            if api_entry:
                # Use totalbilledamount (what the cardholder owes) as the balance
                billed = api_entry.get("totalbilledamount", "0")
                unbilled = api_entry.get("totalunbilledamount", "0")
                currency = _normalise_currency(api_entry.get("currency", "EGP"))
                try:
                    balance = Decimal(str(billed).replace(",", ""))
                    # Total outstanding = billed + unbilled
                    try:
                        balance += Decimal(str(unbilled).replace(",", ""))
                    except InvalidOperation:
                        pass
                except InvalidOperation:
                    balance = Decimal("0.00")
                logger.debug(
                    "NBE: CC row %d using API balance: billed=%s unbilled=%s total=%s",
                    row_idx,
                    billed,
                    unbilled,
                    balance,
                )
            else:
                # Fallback: parse from DOM (this gives available cash limit, not debt — less accurate)
                balance_el = row.select_one(".balance-amount") or row.select_one(".account-value")
                balance_text = balance_el.get_text(strip=True) if balance_el else ""
                currency = _extract_currency_from_balance(balance_text)
                balance_str = re.sub(r"^-?\s*[A-Z]{3}\s*", "", balance_text.strip())
                if balance_text.strip().startswith("-"):
                    balance_str = "-" + balance_str
                balance = _parse_amount(balance_str) or Decimal("0.00")
                logger.debug(
                    "NBE: CC row %d using DOM balance (API not captured): %s %s",
                    row_idx,
                    currency,
                    balance,
                )

            masked = self._mask_account_number(raw_card_number)

            # Populate individual billing detail fields from the API intercept.
            cc_credit_limit: Decimal | None = None
            cc_billed_amount: Decimal | None = None
            cc_unbilled_amount: Decimal | None = None
            cc_minimum_payment: Decimal | None = None
            cc_payment_due_date: date | None = None
            if api_entry:
                try:
                    cc_billed_amount = Decimal(
                        str(api_entry.get("totalbilledamount", "0")).replace(",", "")
                    )
                except InvalidOperation:
                    cc_billed_amount = None
                try:
                    cc_unbilled_amount = Decimal(
                        str(api_entry.get("totalunbilledamount", "0")).replace(",", "")
                    )
                except InvalidOperation:
                    cc_unbilled_amount = None
                try:
                    cc_credit_limit = Decimal(
                        str(api_entry.get("creditlimit", "0")).replace(",", "")
                    )
                except InvalidOperation:
                    cc_credit_limit = None
                try:
                    cc_minimum_payment = Decimal(
                        str(api_entry.get("minamountdue", "0")).replace(",", "")
                    )
                except InvalidOperation:
                    cc_minimum_payment = None
                raw_due = str(api_entry.get("paymentduedate", "")).strip()
                if raw_due:
                    try:
                        # NBE returns dates as "DD Mon YYYY" e.g. "27 Mar 2026"
                        cc_payment_due_date = datetime.strptime(raw_due, "%d %b %Y").date()
                    except ValueError:
                        try:
                            # Fallback: ISO format "YYYY-MM-DD"
                            cc_payment_due_date = date.fromisoformat(raw_due[:10])
                        except ValueError:
                            cc_payment_due_date = None

            accounts.append(
                BankAccount(
                    id=_ZERO_UUID,
                    user_id=_ZERO_UUID,
                    bank_name=self.bank_name,
                    account_number_masked=masked,
                    account_type="credit_card",
                    currency=currency,
                    balance=balance,
                    is_active=True,
                    last_synced_at=now,
                    credit_limit=cc_credit_limit,
                    billed_amount=cc_billed_amount,
                    unbilled_amount=cc_unbilled_amount,
                    minimum_payment=cc_minimum_payment,
                    payment_due_date=cc_payment_due_date,
                    created_at=now,
                    updated_at=now,
                )
            )

        return accounts

    # ------------------------------------------------------------------
    # Data extraction — credit card transactions (statement history)
    # ------------------------------------------------------------------

    async def _scrape_cc_transactions(
        self, page: Page, cc_accounts: list[BankAccount]
    ) -> list[Transaction]:
        """Scrape CC statement transactions for the last 6 months + current month.

        Uses the discovered API endpoint:
        GET /digx/v1/cz/creditcardList/listStatements/{accountreferenceno}/{month}/{year}

        The account reference number is the ``id`` attribute of the
        ``li.flip-account-list__items`` element for the CC card row.

        Flow for each month:
        1. Navigate to the CC statement page (CCA → hover → menu → Card Statement).
        2. Intercept all responses whose URL contains ``listStatements``.
        3. Select year + month using Oracle JET selects, click Submit.
        4. Parse the JSON response ``items[].statmentItems[]``.

        Args:
            page: Active Playwright page (must be logged in).
            cc_accounts: List of credit card BankAccount objects already scraped.

        Returns:
            List of Transaction objects for all CC statement items found.
        """
        if not cc_accounts:
            return []

        logger.info(
            "NBE: scraping CC statement transactions for last %d months", _CC_STATEMENT_MONTHS
        )

        # Months to try: last 6 completed + current, newest first
        now = datetime.now(UTC)
        months_to_try: list[tuple[int, int]] = []
        for delta in range(_CC_STATEMENT_MONTHS):
            # Walk back month by month
            m = now.month - delta
            y = now.year
            while m <= 0:
                m += 12
                y -= 1
            months_to_try.append((y, m))

        all_txns: list[Transaction] = []

        # Navigate to dashboard first
        try:
            await page.goto(
                _LOGIN_URL, wait_until="domcontentloaded", timeout=_PAGE_LOAD_TIMEOUT_MS
            )
        except PlaywrightTimeoutError:
            logger.warning("NBE: timed out navigating to dashboard for CC statement scrape")
            return []
        await self._random_delay(1.5, 2.5)

        # Confirm session is still active before waiting for widgets.
        try:
            await page.wait_for_selector("li.loggedInUser", timeout=90_000)
        except PlaywrightTimeoutError:
            logger.warning("NBE: session lost before CC transaction scrape — re-logging in")
            try:
                await self._navigate_to_login(page)
                await self._login(page)
                await self._wait_for_dashboard(page)
                logger.info("NBE: re-login successful — continuing CC transaction scrape")
            except Exception as relogin_exc:
                logger.warning("NBE: re-login failed — skipping CC transactions: %s", relogin_exc)
                return []

        # Wait for CCA widget to hydrate (Oracle JET SPA injects widgets after domcontentloaded).
        # After a heavy multi-account scrape the browser is resource-constrained — use 120s.
        try:
            await page.wait_for_selector(_SEL_CREDIT_CARDS_WIDGET, timeout=120_000)
        except PlaywrightTimeoutError:
            logger.info("NBE: no CCA widget — skipping CC transaction scrape")
            return []

        # Click CCA widget to reveal card rows
        await page.click(_SEL_CREDIT_CARDS_WIDGET)
        await self._random_delay(1.5, 2.5)

        try:
            await page.wait_for_selector(
                "div.flip-account.CCA li.flip-account-list__items, li.flip-account-list__items",
                timeout=_WAIT_TIMEOUT_MS,
            )
        except PlaywrightTimeoutError:
            logger.warning("NBE: CC card rows did not appear — skipping CC transaction scrape")
            return []

        # Get the account reference number from the id attribute of the CC row
        # The id attribute is used as the accountreferenceno in the API call
        account_ref = await page.evaluate("""() => {
            const ccRow = document.querySelector('div.flip-account.CCA li.flip-account-list__items')
                       || document.querySelector('li.flip-account-list__items');
            return ccRow ? ccRow.getAttribute('id') : null;
        }""")
        if not account_ref:
            logger.warning(
                "NBE: could not determine CC account reference number — skipping CC transactions"
            )
            return []
        logger.info("NBE: CC account reference number = %r", account_ref)

        # Hover over the first CC row to reveal the menu icon
        try:
            cc_row_loc = page.locator("div.flip-account.CCA li.flip-account-list__items").first
            if not await cc_row_loc.count():
                cc_row_loc = page.locator("li.flip-account-list__items").first
            await cc_row_loc.hover()
            await self._random_delay(0.8, 1.5)
        except Exception as e:
            logger.warning("NBE: could not hover CC row: %s", e)
            return []

        # Click the menu icon
        try:
            await page.locator("a.menu-icon").first.click(timeout=_SHORT_TIMEOUT_MS)
            await self._random_delay(0.8, 1.5)
        except PlaywrightTimeoutError:
            logger.warning("NBE: menu icon not found on CC row — skipping CC transactions")
            return []

        # Click "Card Statement"
        try:
            await page.click("span:has-text('Card Statement')", timeout=_SHORT_TIMEOUT_MS)
        except PlaywrightTimeoutError:
            logger.warning("NBE: 'Card Statement' menu item not found — skipping CC transactions")
            return []

        # Wait for the CC statement page to load
        await self._random_delay(3.0, 5.0)
        try:
            await page.wait_for_selector("#selectYear", timeout=_WAIT_TIMEOUT_MS)
        except PlaywrightTimeoutError:
            logger.warning("NBE: CC statement year selector not found — skipping CC transactions")
            return []
        logger.info("NBE: on CC statement page — year/month selectors ready")

        # Set up response interception ONCE — we'll collect responses across all month selections
        # Also intercepts unbilled/unsettled transaction API responses.
        captured_responses: dict[str, str] = {}  # url → body
        captured_ubt_uns: dict[str, str] = {}  # url → body for unbilled/unsettled

        async def _capture_statement_response(resp: object) -> None:
            url = getattr(resp, "url", "")
            if "listStatements" in url:
                try:
                    body = await resp.text()  # type: ignore[union-attr]
                    captured_responses[url] = body
                    logger.debug(
                        "NBE: captured listStatements response: %s (%d bytes)", url, len(body)
                    )
                except Exception as e:
                    logger.debug("NBE: could not read listStatements response body: %s", e)
            elif any(
                kw in url
                for kw in (
                    "unbilledTransaction",
                    "unsettledTransaction",
                    "listUnbilled",
                    "listUnsettled",
                    "creditcard",
                )
            ):
                try:
                    body = await resp.text()  # type: ignore[union-attr]
                    if body and len(body) > 50:
                        captured_ubt_uns[url] = body
                        logger.debug(
                            "NBE: captured UBT/UNS response: %s (%d bytes)", url, len(body)
                        )
                except Exception as e:
                    logger.debug("NBE: could not read UBT/UNS response body: %s", e)

        page.on("response", _capture_statement_response)

        try:
            for year, month in months_to_try:
                logger.info("NBE: requesting CC statement for %04d/%02d", year, month)
                year_str = str(year)

                try:
                    # Select year
                    await page.click("#oj-select-choice-selectYear")
                    await self._random_delay(0.5, 1.0)
                    year_opt = (
                        page.locator("#oj-listbox-results-selectYear li")
                        .filter(has_text=year_str)
                        .first
                    )
                    if not await year_opt.count():
                        logger.debug("NBE: CC statement year %s not available — skipping", year_str)
                        await page.keyboard.press("Escape")
                        await self._random_delay(0.3, 0.6)
                        continue
                    await year_opt.click()
                    await self._random_delay(0.5, 1.0)

                    # Select month (1=Jan, 2=Feb, etc.)
                    month_names = [
                        "Jan",
                        "Feb",
                        "Mar",
                        "Apr",
                        "May",
                        "Jun",
                        "Jul",
                        "Aug",
                        "Sep",
                        "Oct",
                        "Nov",
                        "Dec",
                    ]
                    month_name = month_names[month - 1]
                    await page.click("#oj-select-choice-selectMonth")
                    await self._random_delay(0.5, 1.0)
                    month_opt = (
                        page.locator("#oj-listbox-results-selectMonth li")
                        .filter(has_text=month_name)
                        .first
                    )
                    if not await month_opt.count():
                        logger.debug(
                            "NBE: CC statement month %s not available — skipping", month_name
                        )
                        await page.keyboard.press("Escape")
                        await self._random_delay(0.3, 0.6)
                        continue
                    await month_opt.click()
                    await self._random_delay(0.5, 1.0)

                    # Click Submit
                    await page.click("button:has-text('Submit')")
                    # Wait for the AJAX response (generous timeout for Egypt RTT)
                    await self._random_delay(5.0, 7.0)

                except PlaywrightTimeoutError as e:
                    logger.debug(
                        "NBE: timeout selecting CC statement %04d/%02d: %s", year, month, e
                    )
                    continue
                except Exception as e:
                    logger.debug("NBE: error selecting CC statement %04d/%02d: %s", year, month, e)
                    continue

            # --- Scrape Unbilled Transactions (UBT tab) and Unsettled (UNS tab) ---
            # The same card-statement page has a "View" select (#oj-select-1) with options:
            #   BT = Statement (monthly, already done above)
            #   UBT = Unbilled Transactions (current cycle, no date selector needed)
            #   UNS = Unsettled Transactions (pending auth, no date selector needed)
            for tab_code, tab_label in (("UBT", "Unbilled"), ("UNS", "Unsettled")):
                logger.info("NBE: selecting %s (%s Transactions) tab", tab_code, tab_label)
                try:
                    # Click the View dropdown (oj-select-1)
                    await page.click("#oj-select-choice-oj-select-1", timeout=_SHORT_TIMEOUT_MS)
                    await self._random_delay(0.5, 1.0)
                    tab_opt = (
                        page.locator("#oj-listbox-results-oj-select-1 li")
                        .filter(has_text=tab_label)
                        .first
                    )
                    if not await tab_opt.count():
                        logger.debug(
                            "NBE: %s tab option not found in dropdown — skipping", tab_code
                        )
                        await page.keyboard.press("Escape")
                        await self._random_delay(0.3, 0.6)
                        continue
                    await tab_opt.click()
                    # Wait for the AJAX response
                    await self._random_delay(5.0, 8.0)
                    logger.info("NBE: %s tab selected — waiting for API response", tab_code)
                except PlaywrightTimeoutError as e:
                    logger.debug("NBE: timeout selecting %s tab: %s", tab_code, e)
                except Exception as e:
                    logger.debug("NBE: error selecting %s tab: %s", tab_code, e)

            logger.info(
                "NBE: captured %d UBT/UNS API response(s)",
                len(captured_ubt_uns),
            )

            # Parse UBT/UNS responses
            for url, body in captured_ubt_uns.items():
                try:
                    data = json.loads(body)
                except json.JSONDecodeError:
                    logger.debug("NBE: could not parse UBT/UNS response as JSON: %r", body[:200])
                    continue

                # Determine tab type from URL
                is_ubt = "unbill" in url.lower() or "UBT" in url
                tab_type = "unbilled" if is_ubt else "unsettled"

                status = data.get("status", {}).get("result", "")
                if status not in ("SUCCESSFUL", ""):
                    logger.debug("NBE: %s response status=%r — skipping", tab_type, status)
                    continue

                # Try common response shapes for unbilled/unsettled
                # Shape 1: data.unbilledTransactions[] or data.unsettledTransactions[]
                txn_list = (
                    data.get("unbilledTransactions")
                    or data.get("unsettledTransactions")
                    or data.get("items")
                    or []
                )
                # Shape 2: items[].statmentItems[]
                if txn_list and isinstance(txn_list[0], dict) and "statmentItems" in txn_list[0]:
                    flat: list[dict] = []
                    for item in txn_list:
                        flat.extend(item.get("statmentItems", []))
                    txn_list = flat

                txn_time_inner = datetime.now(UTC)
                count_before = len(all_txns)
                for stmt in txn_list:
                    if not isinstance(stmt, dict):
                        continue
                    txn = self._parse_cc_statement_item(stmt, cc_accounts[0], txn_time_inner)
                    if txn is not None:
                        # Tag source in raw_data
                        if txn.raw_data is not None:
                            txn.raw_data["source"] = f"nbe_cc_{tab_type}"
                        all_txns.append(txn)
                logger.info(
                    "NBE: %s tab → %d transaction(s) added",
                    tab_type,
                    len(all_txns) - count_before,
                )

            # Now parse all captured API responses
            logger.info("NBE: captured %d listStatements API response(s)", len(captured_responses))
            txn_time = datetime.now(UTC)

            # Collect statement summaries keyed by (year, month) so we can pick
            # the most recent one to backfill closing balance / min payment / due date.
            stmt_summaries: dict[tuple[int, int], dict] = {}

            for url, body in captured_responses.items():
                # Extract month/year from URL for logging
                url_month, url_year = 0, 0
                m = re.search(r"/listStatements/[^/]+/(\d+)/(\d+)", url)
                if m:
                    url_month, url_year = int(m.group(1)), int(m.group(2))

                try:
                    data = json.loads(body)
                except json.JSONDecodeError:
                    logger.debug(
                        "NBE: could not parse CC statement response as JSON: %r", body[:200]
                    )
                    continue

                status = data.get("status", {}).get("result", "")
                if status != "SUCCESSFUL":
                    logger.debug(
                        "NBE: CC statement %04d/%02d status=%r — skipping",
                        url_year,
                        url_month,
                        status,
                    )
                    continue

                # Extract viewtxnSummary — contains closingbal, minamt, duedate, etc.
                summary = data.get("viewtxnSummary")
                if summary and url_year and url_month:
                    stmt_summaries[(url_year, url_month)] = summary
                    logger.info(
                        "NBE: CC statement %04d/%02d summary: closingbal=%s minamt=%s duedate=%s",
                        url_year,
                        url_month,
                        summary.get("closingbal"),
                        summary.get("minamt"),
                        summary.get("duedate"),
                    )

                items = data.get("items", [])
                if not items:
                    logger.debug(
                        "NBE: CC statement %04d/%02d — no items in response", url_year, url_month
                    )
                    continue

                for item in items:
                    stmt_items = item.get("statmentItems", [])
                    for stmt in stmt_items:
                        txn = self._parse_cc_statement_item(stmt, cc_accounts[0], txn_time)
                        if txn is not None:
                            all_txns.append(txn)

            # Backfill CC account with billing details from the most recent statement
            if stmt_summaries and cc_accounts:
                latest_key = max(stmt_summaries.keys())
                latest = stmt_summaries[latest_key]
                acc = cc_accounts[0]
                try:
                    acc.billed_amount = Decimal(str(latest["closingbal"]).replace(",", ""))
                except (KeyError, InvalidOperation):
                    pass
                try:
                    acc.minimum_payment = Decimal(str(latest["minamt"]).replace(",", ""))
                except (KeyError, InvalidOperation):
                    pass
                raw_due = str(latest.get("duedate", "")).strip()
                if raw_due:
                    try:
                        acc.payment_due_date = datetime.fromisoformat(raw_due[:10]).date()
                    except ValueError:
                        pass
                logger.info(
                    "NBE: CC account backfilled from statement %04d/%02d — "
                    "billed=%s min_payment=%s due=%s",
                    latest_key[0],
                    latest_key[1],
                    acc.billed_amount,
                    acc.minimum_payment,
                    acc.payment_due_date,
                )

                logger.info(
                    "NBE: CC statement %04d/%02d — parsed %d transaction(s) so far (total=%d)",
                    url_year,
                    url_month,
                    len(all_txns),
                    len(all_txns),
                )

        finally:
            page.remove_listener("response", _capture_statement_response)

        logger.info("NBE: CC statement scrape complete — %d total transaction(s)", len(all_txns))
        return all_txns

    def _parse_cc_statement_item(
        self,
        stmt: dict,
        cc_account: BankAccount,
        now: datetime,
    ) -> Transaction | None:
        """Parse a single CC statement item dict into a Transaction.

        Expected fields from NBE listStatements API:
        - ``description``: merchant/transaction description
        - ``crdrflag``: "D" = debit (purchase), "C" = credit (payment/refund)
        - ``originalamt``: amount as string (e.g. "60.80")
        - ``originalcurrency``: ISO code (e.g. "EGP")
        - ``txndate``: ISO datetime string (e.g. "2025-06-28T00:00:00")
        - ``postdate``: posting date
        - ``authcode``: authorisation code
        - ``cardno``: masked card number (e.g. "5441*********204")
        """
        description = str(stmt.get("description", "")).strip() or "N/A"
        crdrflag = str(stmt.get("crdrflag", "D")).upper()
        amount_str = str(stmt.get("originalamt", "0"))
        currency_raw = str(stmt.get("originalcurrency", "EGP"))
        txndate_str = str(stmt.get("txndate", ""))
        postdate_str = str(stmt.get("postdate", ""))
        authcode = str(stmt.get("authcode", ""))

        # Parse amount
        try:
            amount = Decimal(amount_str.replace(",", ""))
        except InvalidOperation:
            logger.debug("NBE: CC stmt — invalid amount %r — skipping", amount_str)
            return None

        if amount <= 0:
            return None

        # Parse dates — format from API: "2025-06-28T00:00:00"
        txn_date: date | None = None
        for ds in (txndate_str, postdate_str):
            if ds:
                try:
                    txn_date = datetime.fromisoformat(ds).date()
                    break
                except ValueError:
                    txn_date = _parse_nbe_date(ds)
                    if txn_date:
                        break

        if txn_date is None:
            logger.debug("NBE: CC stmt — unparseable date %r — skipping", txndate_str)
            return None

        # Map crdrflag to transaction_type
        transaction_type = "debit" if crdrflag == "D" else "credit"

        currency = _normalise_currency(currency_raw)
        external_id = _make_external_id(txn_date, description, amount)

        return Transaction(
            id=_ZERO_UUID,
            user_id=_ZERO_UUID,
            account_id=_ZERO_UUID,
            external_id=external_id,
            amount=amount,
            currency=currency,
            transaction_type=transaction_type,
            description=description,
            category=None,
            sub_category=None,
            transaction_date=txn_date,
            value_date=None,
            balance_after=None,
            raw_data={
                "source": "nbe_cc_statement",
                "authcode": authcode,
                "crdrflag": crdrflag,
                "account_number_masked": cc_account.account_number_masked,
            },
            is_categorized=False,
            created_at=now,
            updated_at=now,
        )

    # ------------------------------------------------------------------
    # Data extraction — certificates and deposits
    # ------------------------------------------------------------------

    async def _scrape_certificates(self, page: Page) -> list[BankAccount]:
        """Navigate to the Certificates/Deposits widget and extract account data.

        NBE shows certificates in a ``li.TRD`` flip-card on the dashboard.
        Clicking ``li.TRD a`` reveals ``li.flip-account-list__items`` rows with:
        - ``.account-name``   — certificate product name (may be Arabic)
        - ``.balance-amount`` — balance with currency prefix (e.g. "EGP 100,000.00")
        - ``.account-no``     — full account number

        Each row may also contain a detail line with
        ``Interest Rate X% | Maturing DD Mon YYYY | Opened Date DD Mon YYYY``.

        This method is called after demand-deposit scraping is complete.
        It navigates to the dashboard, clicks the TRD widget, parses the rows,
        then navigates back.  Non-fatal: caller catches and logs any exception.

        Returns:
            List of ``BankAccount`` objects with ``account_type='certificate'``.
            Returns an empty list if the TRD widget is not present (e.g. no certs).
        """
        logger.info("NBE: scraping certificates/deposits via %r widget", _SEL_CERTIFICATES_WIDGET)

        # Always navigate to dashboard for a clean SPA state — the CCA flip-card or CC
        # statement page may be active after _scrape_credit_cards, hiding the TRD widget.
        current_url = page.url
        logger.info(
            "NBE: navigating to dashboard for certificate scrape (current url: %s)", current_url
        )
        try:
            await page.goto(
                _LOGIN_URL,
                wait_until="domcontentloaded",
                timeout=_PAGE_LOAD_TIMEOUT_MS,
            )
        except PlaywrightTimeoutError:
            logger.warning(
                "NBE: dashboard navigation timed out before certificate scrape — skipping"
            )
            return []

        # Wait for session + widget hydration — same pattern as _scrape_credit_cards.
        try:
            await page.wait_for_selector("li.loggedInUser", timeout=90_000)
        except PlaywrightTimeoutError:
            logger.warning("NBE: session lost after navigation — cannot scrape certificates")
            return []

        try:
            await page.wait_for_selector(_SEL_CERTIFICATES_WIDGET, timeout=120_000)
        except PlaywrightTimeoutError:
            logger.info(
                "NBE: no TRD (certificates) widget found — user has no certificates/deposits"
            )
            return []

        # Click the widget to flip the card and reveal the list
        await page.click(_SEL_CERTIFICATES_WIDGET)
        await self._random_delay(1.5, 2.5)

        # Wait for the account rows to appear
        try:
            await page.wait_for_selector(_SEL_ACCOUNT_ROWS, timeout=_WAIT_TIMEOUT_MS)
        except PlaywrightTimeoutError:
            logger.warning("NBE: certificate rows did not appear after clicking TRD widget")
            return []

        # Parse the HTML
        html = await page.content()
        soup = BeautifulSoup(html, "lxml")

        # The TRD flip-card contains its own set of li.flip-account-list__items.
        # We need the rows that are inside the TRD card, not the demand-deposit card.
        # If div.flip-account.TRD is absent the click did not reveal it — return empty.
        trd_container = soup.select_one("div.flip-account.TRD")
        if not trd_container:
            logger.info("NBE: no certificate rows found in TRD flip-card HTML")
            return []
        rows = trd_container.select(_SEL_ACCOUNT_ROWS)
        if not rows:
            logger.info("NBE: no certificate rows found in TRD flip-card HTML")
            return []

        logger.info("NBE: found %d certificate row(s)", len(rows))
        accounts: list[BankAccount] = []
        now = datetime.now(UTC)

        for row_idx, row in enumerate(rows):
            # Account name (product name, may be Arabic)
            name_el = row.select_one(".account-name")
            raw_name = name_el.get_text(strip=True) if name_el else ""

            # Balance
            balance_el = row.select_one(".balance-amount")
            balance_text = ""
            if balance_el:
                balance_text = balance_el.get_text(strip=True)
            else:
                row_text = row.get_text(separator=" ")
                m = re.search(r"-?\s*(?:EGP|USD|EUR|GBP|SAR|AED)\s*[\d,.\-]+", row_text, re.I)
                if m:
                    balance_text = m.group(0).replace(" ", "")

            # Account number
            acc_no_el = row.select_one(".account-no")
            raw_account_number = acc_no_el.get_text(strip=True) if acc_no_el else ""

            currency = _extract_currency_from_balance(balance_text)
            balance_str = re.sub(r"^-?\s*[A-Z]{3}\s*", "", balance_text.strip())
            if balance_text.strip().startswith("-"):
                balance_str = "-" + balance_str
            balance = _parse_amount(balance_str) or Decimal("0.00")

            masked = self._mask_account_number(raw_account_number)

            # Parse interest rate and maturity date from the detail line.
            # NBE renders a detail span with text like:
            #   "Interest Rate 15% | Maturing 12 Mar 2027 | Opened Date 12 Mar 2026"
            # We search the full row text for both patterns.
            row_full_text = row.get_text(separator=" ")

            cert_interest_rate: Decimal | None = None
            rate_match = re.search(r"Interest\s+Rate\s+([\d.]+)\s*%", row_full_text, re.I)
            if rate_match:
                try:
                    # Convert percentage string to decimal fraction (e.g. "15" → 0.1500)
                    cert_interest_rate = Decimal(rate_match.group(1)) / Decimal("100")
                except InvalidOperation:
                    cert_interest_rate = None

            cert_maturity_date: date | None = None
            maturity_match = re.search(
                r"Maturing\s+(\d{1,2}\s+[A-Za-z]{3}\s+\d{4})", row_full_text, re.I
            )
            if maturity_match:
                cert_maturity_date = _parse_nbe_date(maturity_match.group(1).strip())

            logger.debug(
                "NBE: certificate row %d → masked=%s name=%r currency=%s balance=%s "
                "interest_rate=%s maturity_date=%s",
                row_idx,
                masked,
                raw_name,
                currency,
                balance,
                cert_interest_rate,
                cert_maturity_date,
            )

            accounts.append(
                BankAccount(
                    id=_ZERO_UUID,
                    user_id=_ZERO_UUID,
                    bank_name=self.bank_name,
                    account_number_masked=masked,
                    account_type="certificate",
                    currency=currency,
                    balance=balance,
                    is_active=True,
                    last_synced_at=now,
                    interest_rate=cert_interest_rate,
                    maturity_date=cert_maturity_date,
                    created_at=now,
                    updated_at=now,
                )
            )

        return accounts
