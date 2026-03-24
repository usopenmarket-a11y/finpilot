"""BDC Retail scraper — bdconline.com.eg (Temenos T24 / EdgeConnect portal).

Login URL: https://www.bdconline.com.eg/BDCRetail/servletcontroller

Portal type
-----------
Temenos T24 / Temenos EdgeConnect.  The login form uses RSA public-key
encryption: the ``Sign In`` button's ``onclick`` handler calls a JS
``encrypt()`` function which reads the visible password field, encrypts it
with a public key loaded into ``C2__C1__GENERATEKEYS[1].PUBKEY``, and writes
the ciphertext into ``C2__C1__LOGIN[1].ENCRYPTEDPASSWORD`` before submitting
the form via POST to ``servletcontroller``.

Scrape flow
-----------
1. Navigate to the login URL and wait for the username field to appear.
2. Fill the username field by ID ``C2__C1__USER_NAME``.
3. Find and fill the visible password field (``input[type="password"]`` — its
   ID is randomised on each page load).
4. Click the Sign In button by ID ``C2__C1__BUT_9BD7C5B3E72A5180154807``.
   The browser-side JS ``encrypt()`` function fires, populates the encrypted
   password hidden field, and submits the form.
5. Wait for the post-login page.  Success is confirmed by the disappearance of
   the username field OR the presence of a navigation element typical of the
   T24 authenticated shell.
6. Log the full page structure (title, visible text, table headers) so portal
   behaviour can be understood from Render logs without needing to replay the
   scrape manually.
7. Extract account balances from whatever table or list the portal renders on
   the dashboard.
8. Attempt to navigate to an account statement / transaction history view and
   extract up to ``_MAX_TRANSACTIONS`` rows.
9. Return a ``ScraperResult``.

RSA encryption note
-------------------
We do NOT reimplement the RSA encryption in Python.  Instead we let the
browser execute the portal's own ``encrypt()`` JS by clicking the Sign In
button and allowing the browser to submit the form normally.  Playwright
waits for the resulting navigation / DOM change.

OTP / 2FA
---------
If the portal presents an OTP challenge after login, ``ScraperOTPRequired``
is raised.  The API layer must collect the OTP from the user and resume.

Date parsing
------------
Temenos T24 portals typically use ``DD/MM/YYYY`` or ``DD Mon YYYY`` formats.
Both are handled by ``_parse_t24_date``.

Amount parsing
--------------
Amounts may carry comma thousands-separators and an ``EGP`` prefix/suffix.
``_parse_amount`` strips all non-numeric characters before ``Decimal``
conversion.

External ID
-----------
SHA-256(``{date_iso}:{description[:40]}:{amount}``)[:24] — stable across
repeated scrapes of the same transaction row.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import ClassVar
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

_LOGIN_URL = "https://www.bdconline.com.eg/BDCRetail/servletcontroller"

_WAIT_TIMEOUT_MS = 90_000  # BDC portal is very slow — needs extended timeout
_POST_LOGIN_TIMEOUT_MS = 90_000
_NAV_TIMEOUT_MS = 120_000  # initial page load can take >60s

_MAX_TRANSACTIONS = 30

# ---------------------------------------------------------------------------
# Selector catalogue (confirmed via Puppeteer inspection 2026-03-24)
# ---------------------------------------------------------------------------

# Username field — stable ID (type=search on this portal)
_SEL_USERNAME = "#C2__C1__USER_NAME"

# Password field — name is stable; ID changes per session; type is "text" (not "password")
_SEL_PASSWORD = "input[name='C2__C1__LOGIN[1].PASSWORD']"

# Sign In button — try stable name-based selector first, then visible image inputs
# The ID suffix changes; the name pattern is stable across sessions
_SEL_LOGIN_BTN = "input[type='image'][id*='BUT_']"

# Post-login presence indicators (try several patterns; log which matched)
_SEL_POST_LOGIN_CANDIDATES = [
    # Navigation items typical of T24 authenticated shell
    "a[onclick*='goNavItem']",
    # T24 font class used in many views
    ".tc-global-font",
    # Absence check: if username field is gone → login succeeded
]

# OTP / 2FA patterns
_SEL_OTP_CANDIDATES = [
    "input[id*='otp' i]",
    "input[name*='otp' i]",
    "#otpSection",
    "input[id*='OTP']",
]

# Login error message patterns
_SEL_LOGIN_ERROR_CSS = (
    ".error-message, .alert-danger, [class*='loginError'], "
    "[class*='ErrorMessage'], [class*='FailureText'], "
    ".failureNotification"
)

# ---------------------------------------------------------------------------
# Sentinel UUID — replaced by the pipeline layer
# ---------------------------------------------------------------------------
_ZERO_UUID = UUID("00000000-0000-0000-0000-000000000000")

# ---------------------------------------------------------------------------
# Date / amount / ID helpers
# ---------------------------------------------------------------------------

# Month abbreviation map for "DD Mon YYYY" format
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


def _parse_t24_date(raw: str) -> date | None:
    """Parse a date string from a Temenos T24 portal.

    Supported formats:
    - ``DD/MM/YYYY`` or ``D/M/YYYY``
    - ``DD-MM-YYYY`` or ``D-M-YYYY``
    - ``DD Mon YYYY`` (e.g. ``12 Mar 2026``)

    Returns ``None`` if no format matches.
    """
    raw = raw.strip()
    if not raw:
        return None

    # DD/MM/YYYY or DD-MM-YYYY
    parts = re.split(r"[/\-]", raw)
    if len(parts) == 3:
        try:
            day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
            return date(year, month, day)
        except (ValueError, TypeError):
            pass

    # DD Mon YYYY (e.g. "12 Mar 2026")
    m = re.match(r"(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})", raw)
    if m:
        try:
            day = int(m.group(1))
            month = _MONTH_ABBR.get(m.group(2).lower(), 0)
            year = int(m.group(3))
            if month:
                return date(year, month, day)
        except (ValueError, TypeError):
            pass

    logger.debug("BDC_RETAIL: could not parse date %r", raw)
    return None


def _parse_amount(raw: str) -> Decimal | None:
    """Strip currency symbols, thousands separators, and whitespace; parse as Decimal.

    Returns ``None`` for empty, dash, or non-numeric strings.
    """
    cleaned = raw.strip()
    # Remove Latin + Arabic letters (currency codes, labels)
    cleaned = re.sub(r"[A-Za-z\u0600-\u06FF]", "", cleaned)
    cleaned = cleaned.replace(",", "").replace(" ", "").replace("\xa0", "")
    if not cleaned or cleaned in ("-", "—", "N/A", "--"):
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        logger.debug("BDC_RETAIL: could not parse amount %r", raw)
        return None


def _make_external_id(txn_date: date, description: str, amount: Decimal) -> str:
    """Produce a stable 24-char SHA-256-based deduplication key.

    Canonical string: ``{date_iso}:{description[:40].strip()}:{amount}``
    """
    canonical = f"{txn_date.isoformat()}:{description[:40].strip()}:{amount}"
    return hashlib.sha256(canonical.encode()).hexdigest()[:24]


def _normalise_account_type(raw: str) -> str:
    """Map a raw account-type string to one of the allowed DB values."""
    raw_lower = raw.lower().strip()
    if "saving" in raw_lower or "توفير" in raw_lower:
        return "savings"
    if "credit" in raw_lower or "ائتمان" in raw_lower:
        return "credit"
    if "loan" in raw_lower or "قرض" in raw_lower:
        return "loan"
    return "current"


def _normalise_currency(raw: str) -> str:
    """Return a valid ISO 4217 code or fall back to EGP."""
    raw_upper = raw.upper().strip()
    known = {"EGP", "USD", "EUR", "GBP", "SAR", "AED"}
    return raw_upper if raw_upper in known else "EGP"


def _resolve_txn_columns(headers: list[str]) -> dict[str, int]:
    """Map logical column names to zero-based indices derived from header strings.

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
            r"transaction\s*date|posting\s*date|^date$|value\s*date|تاريخ", h_lower
        ):
            # Prefer "transaction date" or bare "date" over value date
            if "value" not in h_lower:
                col["date"] = i
        if col["value_date"] == -1 and re.search(r"value\s*date", h_lower):
            col["value_date"] = i
        if col["description"] == -1 and re.search(
            r"descri|narrat|detail|remark|particular|reference|بيان|وصف", h_lower
        ):
            col["description"] = i
        if col["debit"] == -1 and re.search(r"debit|withdraw|dr\b|مدين", h_lower):
            col["debit"] = i
        if col["credit"] == -1 and re.search(r"credit|deposit|cr\b|دائن", h_lower):
            col["credit"] = i
        if col["balance"] == -1 and re.search(r"^balance$|running\s*bal|رصيد", h_lower):
            col["balance"] = i

    # Positional defaults for any still-unresolved column
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
    """Convert a list of raw cell strings into a ``Transaction`` or ``None`` to skip."""

    def cell(key: str) -> str:
        idx = col.get(key, -1)
        if idx == -1 or idx >= len(cells):
            return ""
        return cells[idx].strip()

    date_str = cell("date")
    if not date_str or date_str.lower() in ("date", "تاريخ", "-", "--"):
        return None

    txn_date = _parse_t24_date(date_str)
    if txn_date is None:
        return None

    value_date_str = cell("value_date")
    value_date: date | None = _parse_t24_date(value_date_str) if value_date_str else None

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
        return None  # Row carries no usable amount

    external_id = _make_external_id(txn_date, description, amount)

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
            "source": "bdc_retail",
        },
        is_categorized=False,
        created_at=now,
        updated_at=now,
    )


# ---------------------------------------------------------------------------
# BDCRetail scraper
# ---------------------------------------------------------------------------


class BDCRetailScraper(BankScraper):
    """Scraper for the BDC Retail internet banking portal (Temenos T24).

    Portal: https://www.bdconline.com.eg/BDCRetail/servletcontroller
    """

    bank_name: ClassVar[str] = "BDC_RETAIL"

    async def scrape(self) -> ScraperResult:
        """Execute the full BDC Retail scrape cycle.

        Returns:
            ``ScraperResult`` with account details and up to
            ``_MAX_TRANSACTIONS`` transaction rows.

        Raises:
            ScraperLoginError: If the portal rejects the credentials.
            ScraperOTPRequired: If the portal presents an OTP challenge.
            ScraperTimeoutError: If any Playwright wait exceeds its deadline.
            ScraperParseError: If the HTML structure is not as expected.
        """
        browser, context, page = await self._launch_browser()
        raw_html: dict[str, str] = {}

        try:
            await self._navigate_to_login(page)
            await self._login(page)
            await self._wait_for_post_login(page)

            # Capture and log dashboard structure for debugging
            dashboard_html = await page.content()
            raw_html["dashboard"] = dashboard_html
            await self._log_page_structure(page, dashboard_html, "dashboard")

            account = await self._extract_account(page)
            logger.info(
                "BDC_RETAIL: account extracted — masked=%s balance=%s %s",
                account.account_number_masked,
                account.balance,
                account.currency,
            )

            # Attempt transaction extraction — non-fatal if the portal
            # does not present a transaction view on the first landing page.
            transactions: list[Transaction] = []
            try:
                await self._navigate_to_statement(page)
                stmt_html = await page.content()
                raw_html["transactions"] = stmt_html
                await self._log_page_structure(page, stmt_html, "statement")
                transactions = await self._extract_transactions(page, account)
                logger.info("BDC_RETAIL: extracted %d transactions", len(transactions))
            except (ScraperTimeoutError, ScraperParseError) as exc:
                logger.warning(
                    "BDC_RETAIL: transaction extraction skipped — %s: %s",
                    type(exc).__name__,
                    exc,
                )

            return ScraperResult(
                accounts=[account],
                transactions=transactions,
                raw_html=raw_html,
            )

        except (ScraperLoginError, ScraperOTPRequired, ScraperTimeoutError, ScraperParseError):
            raise

        except PlaywrightTimeoutError as exc:
            await self._safe_screenshot(page, "timeout_error")
            raise ScraperTimeoutError(
                f"BDC_RETAIL page operation timed out: {exc}", bank_code="BDC_RETAIL"
            ) from exc

        except Exception as exc:
            await self._safe_screenshot(page, "unexpected_error")
            raise ScraperParseError(
                f"BDC_RETAIL unexpected error during scrape: {type(exc).__name__}: {exc}",
                bank_code="BDC_RETAIL",
            ) from exc

        finally:
            await self._close_browser(browser)

    async def scrape_accounts(self) -> ScraperResult:
        """Scrape account balances only — no transaction history.

        Logs in, extracts the account summary, and returns without
        navigating to the statements view.  Faster than ``scrape()``
        and appropriate when only balance data is needed.

        Returns:
            ``ScraperResult`` with ``accounts`` populated and
            ``transactions`` empty.
        """
        browser, context, page = await self._launch_browser()
        raw_html: dict[str, str] = {}

        try:
            await self._navigate_to_login(page)
            await self._login(page)
            await self._wait_for_post_login(page)

            dashboard_html = await page.content()
            raw_html["dashboard"] = dashboard_html
            await self._log_page_structure(page, dashboard_html, "dashboard")

            account = await self._extract_account(page)
            logger.info(
                "BDC_RETAIL: accounts-only — masked=%s balance=%s %s",
                account.account_number_masked,
                account.balance,
                account.currency,
            )

            return ScraperResult(
                accounts=[account],
                transactions=[],
                raw_html=raw_html,
            )

        except (ScraperLoginError, ScraperOTPRequired, ScraperTimeoutError, ScraperParseError):
            raise

        except PlaywrightTimeoutError as exc:
            await self._safe_screenshot(page, "accounts_timeout")
            raise ScraperTimeoutError(
                f"BDC_RETAIL accounts-only scrape timed out: {exc}", bank_code="BDC_RETAIL"
            ) from exc

        except Exception as exc:
            await self._safe_screenshot(page, "accounts_unexpected_error")
            raise ScraperParseError(
                f"BDC_RETAIL unexpected error during accounts-only scrape: {type(exc).__name__}: {exc}",
                bank_code="BDC_RETAIL",
            ) from exc

        finally:
            await self._close_browser(browser)

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    async def _navigate_to_login(self, page: Page) -> None:
        """Load the BDC Retail login page and verify the username field is visible."""
        logger.debug("BDC_RETAIL: navigating to %s", _LOGIN_URL)
        try:
            await page.goto(_LOGIN_URL, wait_until="domcontentloaded", timeout=_NAV_TIMEOUT_MS)
        except PlaywrightTimeoutError as exc:
            raise ScraperTimeoutError(
                "BDC_RETAIL: login page did not load within timeout",
                bank_code="BDC_RETAIL",
            ) from exc

        # Confirm the username field is present before attempting to fill it.
        try:
            await page.wait_for_selector(_SEL_USERNAME, timeout=_WAIT_TIMEOUT_MS)
        except PlaywrightTimeoutError as exc:
            await self._safe_screenshot(page, "login_page_no_username_field")
            raise ScraperTimeoutError(
                "BDC_RETAIL: username field not found on login page",
                bank_code="BDC_RETAIL",
            ) from exc

        logger.debug("BDC_RETAIL: login page loaded, username field present")

    async def _navigate_to_statement(self, page: Page) -> None:
        """Attempt to navigate to the account statement / transaction history view.

        Tries several link patterns typical of Temenos T24 portals in sequence.
        Raises ``ScraperParseError`` if no statement link can be located.
        """
        logger.debug("BDC_RETAIL: looking for statement navigation link")
        await self._random_delay(1.5, 3.0)

        # Candidate link selectors for T24 statement navigation
        statement_link_selectors = [
            "a[onclick*='goNavItem'][onclick*='tatement']",  # Statement goNavItem
            "a[onclick*='goNavItem'][onclick*='Account']",  # Account activity
            "a[href*='tatement']",
            "a[href*='statement']",
            "a[href*='Transaction']",
            "a[href*='transaction']",
        ]
        # XPath for text-content matching
        statement_link_xpath = (
            "//a[contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ',"
            "'abcdefghijklmnopqrstuvwxyz'),'statement') or "
            "contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ',"
            "'abcdefghijklmnopqrstuvwxyz'),'transaction') or "
            "contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ',"
            "'abcdefghijklmnopqrstuvwxyz'),'account activity') or "
            "contains(text(),'كشف') or contains(text(),'حركات')]"
        )

        link = None
        for sel in statement_link_selectors:
            link = await page.query_selector(sel)
            if link is not None:
                logger.debug("BDC_RETAIL: found statement link via selector %r", sel)
                break

        if link is None:
            link = await page.query_selector(f"xpath={statement_link_xpath}")
            if link is not None:
                logger.debug("BDC_RETAIL: found statement link via XPath fallback")

        if link is None:
            await self._safe_screenshot(page, "stmt_link_missing")
            raise ScraperParseError(
                "BDC_RETAIL: could not find statement navigation link on dashboard",
                bank_code="BDC_RETAIL",
            )

        await link.click()
        await self._random_delay(2.0, 4.0)
        logger.debug("BDC_RETAIL: clicked statement link, waiting for table")

        # Wait for any table to appear — T24 renders statement data in tables
        try:
            await page.wait_for_selector("table", timeout=_WAIT_TIMEOUT_MS)
        except PlaywrightTimeoutError as exc:
            await self._safe_screenshot(page, "stmt_table_missing")
            raise ScraperTimeoutError(
                "BDC_RETAIL: no table appeared after clicking statement link",
                bank_code="BDC_RETAIL",
            ) from exc

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    async def _login(self, page: Page) -> None:
        """Fill the login form and click Sign In.

        The Sign In button's ``onclick`` handler calls ``encrypt()`` which
        uses the portal's own JS to RSA-encrypt the password and place it
        into the hidden ``ENCRYPTEDPASSWORD`` field.  We then wait for the
        resulting form submission to navigate away from the login page.

        Credentials are removed from local scope in the ``finally`` block.
        Neither username nor password is ever logged.
        """
        username = self._username
        password = self._password
        try:
            logger.debug("BDC_RETAIL: filling login form for user=***")

            # Fill username by stable ID
            await self._type_human(page, _SEL_USERNAME, username)
            await self._random_delay(0.8, 1.5)

            # Fill the password field (type=text, name-based stable selector).
            # The T24 portal keeps this field hidden until after username interaction —
            # wait for DOM attachment only, then force-fill bypassing visibility check.
            await page.wait_for_selector(_SEL_PASSWORD, state="attached", timeout=_WAIT_TIMEOUT_MS)
            await page.fill(_SEL_PASSWORD, password, force=True)
            await self._random_delay(1.0, 2.0)

            # Click Sign In — find the visible image button (ID suffix changes)
            # Prefer a button whose ID contains the LOGIN context ("C2__C1__BUT_")
            login_btn = await page.query_selector("input[type='image'][id^='C2__C1__BUT_']")
            if login_btn is None:
                # Fallback: any visible image input
                for el in await page.query_selector_all(_SEL_LOGIN_BTN):
                    if await el.is_visible():
                        login_btn = el
                        break
            if login_btn is None:
                raise ScraperParseError(
                    "BDC_RETAIL: Sign In button not found", bank_code="BDC_RETAIL"
                )
            await login_btn.click()

            # Wait for the page to change (either navigation or DOM mutation)
            await self._random_delay(2.5, 4.0)

        finally:
            del username
            del password

    async def _wait_for_post_login(self, page: Page) -> None:
        """Confirm successful authentication by inspecting post-login DOM state.

        Checks for OTP prompts first, then login error messages, then looks
        for positive post-login indicators.

        Raises:
            ScraperOTPRequired: If an OTP/2FA prompt is detected.
            ScraperLoginError: If a login error message appears.
            ScraperTimeoutError: If no post-login indicator appears in time.
        """
        # 1. Check for OTP prompt
        for sel in _SEL_OTP_CANDIDATES:
            otp_el = await page.query_selector(sel)
            if otp_el is not None:
                logger.info("BDC_RETAIL: OTP prompt detected")
                raise ScraperOTPRequired(
                    "BDC_RETAIL: OTP required. Submit via /scrapers/otp endpoint.",
                    bank_code="BDC_RETAIL",
                    session_token="bdc_retail_otp_pending",
                )

        # 2. Check for login error message
        error_el = await page.query_selector(_SEL_LOGIN_ERROR_CSS)
        if error_el is not None:
            try:
                err_text = (await error_el.inner_text()).strip()
                logger.warning("BDC_RETAIL: login failure message: %r", err_text[:200])
            except Exception:
                pass
            raise ScraperLoginError(
                "BDC_RETAIL: portal rejected credentials", bank_code="BDC_RETAIL"
            )

        # 3. Look for positive post-login indicators
        # Check absence of username field as primary indicator (most reliable)
        username_still_present = await page.query_selector(_SEL_USERNAME)
        if username_still_present is None:
            logger.info("BDC_RETAIL: login successful — username field no longer present")
            return

        # Try positive T24 post-login selectors
        for sel in _SEL_POST_LOGIN_CANDIDATES:
            try:
                await page.wait_for_selector(sel, timeout=8_000)
                logger.info("BDC_RETAIL: login successful — found post-login indicator %r", sel)
                return
            except PlaywrightTimeoutError:
                continue

        # Last resort: wait for username field to disappear
        try:
            await page.wait_for_selector(
                _SEL_USERNAME, state="hidden", timeout=_POST_LOGIN_TIMEOUT_MS
            )
            logger.info("BDC_RETAIL: login successful — username field hidden")
            return
        except PlaywrightTimeoutError:
            pass

        # If we reach here, we cannot confirm login state — log and raise
        await self._safe_screenshot(page, "post_login_ambiguous")
        raise ScraperTimeoutError(
            "BDC_RETAIL: could not confirm successful login within timeout",
            bank_code="BDC_RETAIL",
        )

    # ------------------------------------------------------------------
    # Debug logging helpers
    # ------------------------------------------------------------------

    async def _log_page_structure(self, page: Page, html: str, label: str) -> None:
        """Log key page structure details to aid selector discovery.

        Logs:
        - Page title
        - First 2000 characters of visible text content
        - All table headers (th / td in first row of each table)
        - All link texts and hrefs
        - All element IDs containing ``C2__``

        This output is intentionally verbose because it is the primary
        mechanism for understanding the T24 portal's DOM without replaying
        the full scrape locally.  All logging is at INFO level so it
        appears in Render logs.

        Security: This helper is ONLY called on post-authentication pages.
        Credentials are never present in the rendered HTML after login.
        """
        try:
            title = await page.title()
            logger.info("BDC_RETAIL [%s]: page title = %r", label, title)
        except Exception as exc:
            logger.info("BDC_RETAIL [%s]: could not get page title: %s", label, exc)

        soup = BeautifulSoup(html, "lxml")

        # Visible text (truncated)
        text_content = soup.get_text(separator=" ", strip=True)
        logger.info(
            "BDC_RETAIL [%s]: page text (first 2000 chars): %s",
            label,
            text_content[:2000],
        )

        # Table headers
        tables = soup.find_all("table")
        logger.info("BDC_RETAIL [%s]: found %d table(s)", label, len(tables))
        for t_idx, table in enumerate(tables[:10]):  # cap at 10 tables
            rows = table.find_all("tr")
            if rows:
                first_row = rows[0]
                headers = [th.get_text(strip=True) for th in first_row.find_all(["th", "td"])]
                logger.info(
                    "BDC_RETAIL [%s]: table[%d] headers: %r",
                    label,
                    t_idx,
                    headers,
                )

        # All navigation links
        links = soup.find_all("a", href=True)
        onclick_links = soup.find_all("a", onclick=True)
        link_info = [f"{a.get_text(strip=True)!r} href={a.get('href')!r}" for a in links[:30]]
        onclick_info = [
            f"{a.get_text(strip=True)!r} onclick={str(a.get('onclick'))[:80]!r}"
            for a in onclick_links[:30]
        ]
        logger.info("BDC_RETAIL [%s]: href links: %s", label, link_info)
        logger.info("BDC_RETAIL [%s]: onclick links: %s", label, onclick_info)

        # Elements with C2__ in their IDs (T24 component IDs)
        t24_elements = soup.find_all(id=re.compile(r"C2__"))
        id_list = [
            f"{el.name}#{{el.get('id')}} text={el.get_text(strip=True)[:40]!r}"
            for el in t24_elements[:50]
        ]
        logger.info("BDC_RETAIL [%s]: T24 element IDs: %s", label, id_list)

    # ------------------------------------------------------------------
    # Data extraction — account
    # ------------------------------------------------------------------

    async def _extract_account(self, page: Page) -> BankAccount:
        """Extract account metadata from the dashboard.

        Temenos T24 portals vary in their dashboard layout.  This method
        attempts several strategies in order:

        1. Look for elements whose ID contains ``ACCOUNTNO`` or ``BALANCE``
           (T24-style component IDs).
        2. Scan all tables for a row containing recognisable account data
           (account number pattern + numeric balance).
        3. Fall back to scanning visible text for a 10-digit account number
           and a numeric balance.

        Returns a ``BankAccount`` with sentinel UUIDs that the pipeline layer
        will replace.
        """
        html = await page.content()
        soup = BeautifulSoup(html, "lxml")
        now = datetime.now(UTC)

        # Strategy 1: T24 component IDs for account number and balance
        raw_account_number = ""
        raw_balance = ""
        raw_currency = ""
        raw_account_type = ""

        # Account number: look for elements whose ID contains ACCOUNTNO
        acct_el = soup.find(id=re.compile(r"ACCOUNTNO|ACCTNO|ACCOUNT_NO", re.I))
        if acct_el:
            raw_account_number = acct_el.get_text(strip=True)
            logger.debug("BDC_RETAIL: found account number via T24 ID: %r", raw_account_number)

        # Balance: look for elements whose ID contains WORKINGBAL or BALANCE
        bal_el = soup.find(
            id=re.compile(r"WORKINGBAL|WORKING_BAL|AVAILBAL|AVAIL_BAL|BALANCE", re.I)
        )
        if bal_el:
            raw_balance = bal_el.get_text(strip=True)
            logger.debug("BDC_RETAIL: found balance via T24 ID: %r", raw_balance)

        # Currency: look for elements whose ID contains CURRENCY or CCY
        ccy_el = soup.find(id=re.compile(r"CURRENCY|CCY", re.I))
        if ccy_el:
            raw_currency = ccy_el.get_text(strip=True)
            logger.debug("BDC_RETAIL: found currency via T24 ID: %r", raw_currency)

        # Account type: look for elements whose ID contains PRODNAME or ACCOUNTTYPE
        type_el = soup.find(id=re.compile(r"PRODNAME|ACCOUNTTYPE|ACCTTYPE|PRODUCT", re.I))
        if type_el:
            raw_account_type = type_el.get_text(strip=True)
            logger.debug("BDC_RETAIL: found account type via T24 ID: %r", raw_account_type)

        # Strategy 2: scan tables for account data
        if not raw_account_number:
            for table in soup.find_all("table"):
                rows = [r for r in table.find_all("tr") if r.find("td")]
                for row in rows:
                    cells = [td.get_text(strip=True) for td in row.find_all("td")]
                    for cell in cells:
                        # Match 10–16 digit strings (typical T24 account numbers)
                        if re.match(r"^\d{10,16}$", cell.replace("-", "").replace(" ", "")):
                            raw_account_number = cell
                            # Look for a balance in adjacent cells
                            for c in cells:
                                if _parse_amount(c) is not None and c != cell:
                                    raw_balance = c
                                    break
                            logger.debug(
                                "BDC_RETAIL: found account number in table: %r", raw_account_number
                            )
                            break
                    if raw_account_number:
                        break

        # Strategy 3: text scan for account number pattern
        if not raw_account_number:
            full_text = soup.get_text()
            m = re.search(r"\b(\d{10,16})\b", full_text)
            if m:
                raw_account_number = m.group(1)
                logger.debug(
                    "BDC_RETAIL: account number found via text scan: %r", raw_account_number
                )

        if not raw_account_number:
            logger.warning("BDC_RETAIL: could not extract account number — using placeholder")
            raw_account_number = "0000000000"

        # Parse and normalise fields
        balance = _parse_amount(raw_balance) if raw_balance else None
        if balance is None:
            logger.warning(
                "BDC_RETAIL: could not parse balance %r — defaulting to 0.00", raw_balance
            )
            balance = Decimal("0.00")

        currency = _normalise_currency(raw_currency) if raw_currency else "EGP"
        account_type = _normalise_account_type(raw_account_type) if raw_account_type else "current"
        masked = self._mask_account_number(raw_account_number)

        logger.info(
            "BDC_RETAIL: account — masked=%s type=%s currency=%s balance=%s",
            masked,
            account_type,
            currency,
            balance,
        )

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

        Temenos T24 typically renders statements in an HTML table with
        class ``tc-table`` or an ID containing ``STATEMENT`` or ``TRANS``.
        The column layout usually follows:
        Date | Value Date | Description | Debit | Credit | Balance

        Returns up to ``_MAX_TRANSACTIONS`` rows in the order they appear
        on the page (most-recent first on most T24 deployments).
        """
        html = await page.content()
        soup = BeautifulSoup(html, "lxml")
        now = datetime.now(UTC)

        # Strategy 1: find by T24 CSS class
        table = soup.find("table", class_=re.compile(r"tc-table|tc_table", re.I))
        if table is None:
            # Strategy 2: find by ID patterns
            table = soup.find("table", id=re.compile(r"STATEMENT|TRANS|ACTIVITY", re.I))

        if table is None:
            # Strategy 3: find any table with debit+credit columns in headers
            for t in soup.find_all("table"):
                raw_text = t.get_text(separator=" ").lower()
                if ("debit" in raw_text or "مدين" in raw_text) and (
                    "credit" in raw_text or "دائن" in raw_text
                ):
                    table = t
                    break

        if table is None:
            # Strategy 4: pick the largest table on the page (most rows)
            all_tables = soup.find_all("table")
            if all_tables:
                table = max(all_tables, key=lambda t: len(t.find_all("tr")))
                logger.debug(
                    "BDC_RETAIL: using largest table (%d rows) as fallback",
                    len(table.find_all("tr")),
                )

        if table is None:
            raise ScraperParseError(
                "BDC_RETAIL: could not locate transaction table in statement page",
                bank_code="BDC_RETAIL",
            )

        # Resolve column indices from the header row
        header_row = table.find("tr")
        if header_row is None:
            raise ScraperParseError(
                "BDC_RETAIL: transaction table has no rows", bank_code="BDC_RETAIL"
            )

        headers = [th.get_text(strip=True) for th in header_row.find_all(["th", "td"])]
        logger.info("BDC_RETAIL: transaction table headers: %r", headers)
        col = _resolve_txn_columns(headers)
        logger.info("BDC_RETAIL: resolved column map: %r", col)

        transactions: list[Transaction] = []
        data_rows = [r for r in table.find_all("tr") if r.find("td")]

        for row_idx, row in enumerate(data_rows[:_MAX_TRANSACTIONS]):
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if not cells or len(cells) < 3:
                continue
            logger.debug("BDC_RETAIL: row[%d] cells: %r", row_idx, cells)

            try:
                txn = _parse_transaction_row(cells, col, account, now)
            except Exception as exc:
                logger.debug("BDC_RETAIL: skipping row %d: %s", row_idx, exc)
                continue

            if txn is not None:
                transactions.append(txn)

        return transactions
