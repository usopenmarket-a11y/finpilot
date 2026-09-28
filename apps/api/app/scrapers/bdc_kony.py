"""BDC (Banque du Caire) NEW online-banking scraper — Kony / Temenos Infinity.

The bank replaced the old T24 ``BDCRetail/servletcontroller`` portal (see
``app.scrapers.bdc_retail.BDCRetailScraper``) with a Kony / Temenos Infinity
single-page app at::

    https://bdconline.com.eg/apps/onlinebanking/

This scraper uses a **hybrid** strategy proven by live capture 2026-07-27
(see project memory ``bdc_new_kony_portal``):

1.  **Browser login** via patchright — the Kony JS encrypts the credentials
    (``userid``/``Password`` are RSA/AES-encrypted client-side, so we cannot
    replay the ``/authService/.../login`` call ourselves) and handles any
    captcha / MFA. patchright's stealth avoids the automation blocks.
2.  Once authenticated, we **sniff the session token** — the RS256 JWT that
    Kony sends as the ``x-kony-authorization`` header (plus ``x-kony-deviceid``)
    — off the live network traffic.
3.  We then call the Kony **JSON API directly** using the page's own request
    context (same cookies + headers), which returns clean JSON — no HTML or
    widget parsing::

        POST /services/data/v1/Holdings/operations/DigitalArrangements/getList
        (accounts; body ``jsondata={}``)

    Credit-card details come from ``_CARD_LIST_OP`` and each card's history
    from ``_CARD_TXN_OP`` (both confirmed live 2026-09-26).

``BDC_RETAIL`` routes to this scraper. Hosted deployments require an Egyptian
HTTP(S) proxy configured with a sticky session through ``BDC_PROXY_*`` settings,
plus the matching Patchright Chromium installation. The existing local runner
can still connect directly from Egypt.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import tempfile
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, ClassVar
from urllib.parse import quote
from uuid import UUID

from app.config import settings
from app.models.db import BankAccount, Transaction
from app.scrapers.base import (
    BankPortalUnreachableError,
    BankScraper,
    ScraperLoginError,
    ScraperParseError,
    ScraperResult,
    ScraperTimeoutError,
    ScraperUnavailableError,
)
from app.scrapers.bdc_proxy import get_bdc_proxy

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BASE = "https://bdconline.com.eg"
_APP_URL = f"{_BASE}/apps/onlinebanking/"
_CARDS_ROUTE = f"{_BASE}/apps/onlinebanking/#/CardsMA/frmCardManagement"

# Login iframe + widget selectors (captured live 2026-07-27).
_LOGIN_IFRAME_MARKER = "LoginPage.html"
_SEL_USERNAME = "#usernameInput"
_SEL_PASSWORD = "#passwordInput"  # NOTE: type=text, not type=password
_SEL_LOGIN_BTN = "button.login-btn"
_SEL_LOGIN_ERROR = "#errorMsg"
# The redesigned login page (2026-09) masks the password with a script that
# records keystrokes from ``beforeinput`` events and submits that recorded
# value, so the password must be typed key by key, not set with fill().
_PASSWORD_KEY_DELAY_MS = 40

# Kony DBX JSON API operations (POST, body ``jsondata=<url-encoded json>``).
_ACCOUNTS_OP = "/services/data/v1/Holdings/operations/DigitalArrangements/getList"
_CARD_LIST_OP = "/services/data/v1/CreditCard/operations/CreditCardModel/fetchCreditCards"
# Opening Cards in the portal calls this first. Without it, the first history
# call of a session stalled past the request timeout (live, 2026-09-26); after
# it, history returned in ~2 s.
_CARD_ACTIVE_OP = "/services/data/v1/BDC_CardsManagement/operations/Cards/getAllActiveCards"
# Cards → Credit → (card) → Transaction History; body ``{"PAN": <cardNumber>}``.
# Returns the card's whole available history in one ``Transaction`` list.
_CARD_TXN_OP = "/services/data/v1/BDC_CardsManagement/operations/Cards/getCreditTransactionsHistory"
# The portal sends every call with this content type. The card history
# operation requires it: a form content type returns HTTP 200 with an empty
# ``Transaction`` list.
_JSON_CONTENT_TYPE = "application/json"
_FORM_CONTENT_TYPE = "application/x-www-form-urlencoded"

# Map Kony ``accountType`` strings to the values allowed by the DB
# ``bank_accounts_account_type_check`` constraint (savings/current/payroll/
# credit/credit_card/loan/certificate/deposit/prepaid_card). Kony calls a
# chequing account "Checking", which the schema does not permit — it uses
# "current". Unknown types fall back to "current" (a generic deposit account).
_ACCOUNT_TYPE_MAP = {
    "checking": "current",
    "current": "current",
    "chequing": "current",
    "savings": "savings",
    "saving": "savings",
    "deposit": "deposit",
    "term deposit": "deposit",
    "certificate": "certificate",
    "loan": "loan",
    "credit": "credit",
    "credit card": "credit_card",
    "creditcard": "credit_card",
    "prepaid": "prepaid_card",
    "prepaid card": "prepaid_card",
}
_DEFAULT_ACCOUNT_TYPE = "current"

_ZERO_UUID = UUID("00000000-0000-0000-0000-000000000000")

_NAV_TIMEOUT_MS = 120_000
# Each load polls 10 times (2 s apart, plus up to 2 s per selector wait) for
# the login iframe before the page is reloaded.
_LOGIN_RENDER_POLLS = 10
_LOGIN_PAGE_ATTEMPTS = 4
# Each form step normally takes <1 s. Steps before Sign In are retried on a
# fresh page load; nothing has been submitted at that point.
_FORM_STEP_TIMEOUT_MS = 15_000
_LOGIN_FORM_ATTEMPTS = 2
_DASHBOARD_TIMEOUT_MS = 60_000
_API_EVALUATE_TIMEOUT_S = 75


# ---------------------------------------------------------------------------
# Small parsing helpers
# ---------------------------------------------------------------------------


def _to_decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    """Coerce a Kony string/number field to Decimal, tolerating '', None, commas."""
    if value is None:
        return default
    s = str(value).strip().replace(",", "")
    if not s:
        return default
    try:
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return default


def _mask(account_id: str) -> str:
    """Return a masked identifier (last 4) for display/routing."""
    digits = "".join(ch for ch in str(account_id) if ch.isdigit())
    return f"****{digits[-4:]}" if len(digits) >= 4 else f"****{account_id[-4:]}"


def _make_external_id(txn_date: date | None, description: str, amount: Decimal) -> str:
    """Stable dedup key for a transaction (mirrors bdc_retail convention)."""
    basis = f"{txn_date.isoformat() if txn_date else '?'}|{description}|{amount}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:32]


def _parse_kony_date(value: Any) -> date | None:
    """Parse the Kony transaction date. Format confirmed at card-capture time.

    Kony DBX commonly returns ``MM/DD/YYYY`` or an epoch-millis string; try the
    common shapes and fall back to None so the pipeline can still store the txn.
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%b %d, %Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    # Epoch millis?
    if s.isdigit() and len(s) >= 12:
        try:
            return datetime.fromtimestamp(int(s) / 1000, tz=UTC).date()
        except (ValueError, OSError):
            return None
    return None


_CARD_CREDIT_KINDS = {"payment", "refund", "reversal", "credit"}


def _card_amount_owed(card: dict, limit: Decimal) -> Decimal:
    """Return what the cardholder owes, including pending authorisations."""
    utilized = card.get("utilizedAmount")
    if utilized not in (None, ""):
        return _to_decimal(utilized) + _to_decimal(card.get("holdAmount"))
    if limit > 0 and card.get("availableBalance") not in (None, ""):
        return max(limit - _to_decimal(card.get("availableBalance")), Decimal("0"))
    return _to_decimal(card.get("closingBalance"))


# ---------------------------------------------------------------------------
# Scraper
# ---------------------------------------------------------------------------


class BDCKonyScraper(BankScraper):
    """Scraper for the new BDC Kony / Temenos Infinity online-banking portal."""

    bank_name: ClassVar[str] = "BDC_RETAIL"  # same logical bank as the T24 one

    async def _launch_browser(self):  # type: ignore[override]
        """Launch patchright, routing the whole BDC session through its proxy.

        Hosted deployments require an Egyptian proxy. Local development may
        still connect directly. Avoid custom UA, args and request interception
        so the existing patchright login behaviour is preserved.
        """
        on_hosted_backend = (
            settings.app_env.lower() == "production"
            or os.environ.get("APP_ENV", "").lower() == "production"
            or os.environ.get("RENDER", "").lower() == "true"
            or os.path.isdir("/opt/render/project/src/.playwright-browsers")
        )
        proxy = get_bdc_proxy(required=on_hosted_backend and not settings.bdc_direct_connection)

        from patchright.async_api import async_playwright as patchright_playwright

        context = None
        try:
            playwright = await patchright_playwright().start()
            self._playwright = playwright
            self._bdc_profile_dir = tempfile.mkdtemp(prefix="bdc_kony_profile_")
            context = await playwright.chromium.launch_persistent_context(
                user_data_dir=self._bdc_profile_dir,
                headless=True,
                channel="chromium",
                viewport={"width": 1440, "height": 900},
                locale="en-US",
                timezone_id="Africa/Cairo",
                **({"proxy": proxy} if proxy else {}),
            )
            page = context.pages[0] if context.pages else await context.new_page()
            logger.info("BDC_KONY browser launched (proxy configured=%s)", proxy is not None)
            return context, context, page
        except BaseException as exc:
            # Launch happens before scrape()'s finally block. Release the driver
            # and profile even on launch failure/cancellation. Do not expose raw
            # browser exceptions, which may contain proxy configuration.
            await self._close_browser(context)
            if not isinstance(exc, Exception):
                raise
            raise ScraperUnavailableError(
                "BDC browser could not start. Ensure the backend build installs "
                "Patchright Chromium and check its available memory and proxy configuration.",
                bank_code=self.bank_name,
            ) from None

    async def _close_browser(self, browser) -> None:  # type: ignore[override]
        await super()._close_browser(browser)
        profile_dir = getattr(self, "_bdc_profile_dir", None)
        if profile_dir:
            import shutil

            shutil.rmtree(profile_dir, ignore_errors=True)

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    async def scrape(self) -> ScraperResult:
        """Full scrape: login, read accounts + credit cards + card transactions."""
        browser, context, page = await self._launch_browser()
        try:
            auth = await self._login_and_capture_auth(page)
            self._kony_auth = auth
            now = datetime.now(UTC)

            accounts: list[BankAccount] = []
            transactions: list[Transaction] = []

            # 1. Deposit/checking accounts (JSON API).
            accounts.extend(await self._fetch_accounts(page, now))

            # 2. Credit cards + their transactions (JSON API) — only if the card
            #    operations have been confirmed from the capture.
            card_accounts, card_txns = await self._fetch_cards(page, now, auth)
            accounts.extend(card_accounts)
            transactions.extend(card_txns)

            if not accounts:
                raise ScraperParseError(
                    "BDC_KONY: login succeeded but no accounts or cards were returned",
                    bank_code=self.bank_name,
                )

            logger.info(
                "BDC_KONY: scrape complete — %d account(s), %d transaction(s)",
                len(accounts),
                len(transactions),
            )
            return ScraperResult(accounts=accounts, transactions=transactions)

        except (
            BankPortalUnreachableError,
            ScraperLoginError,
            ScraperTimeoutError,
            ScraperParseError,
        ):
            raise
        except Exception as exc:  # pragma: no cover - defensive
            await self._safe_screenshot(page, "kony_unexpected_error")
            raise ScraperParseError(
                f"BDC_KONY unexpected error during scrape: {type(exc).__name__}: {exc}",
                bank_code=self.bank_name,
            ) from exc
        finally:
            await self._close_browser(browser)

    async def scrape_accounts(self) -> ScraperResult:
        """Accounts only (no card transactions) — faster balance refresh."""
        browser, context, page = await self._launch_browser()
        try:
            self._kony_auth = await self._login_and_capture_auth(page)
            now = datetime.now(UTC)
            accounts = await self._fetch_accounts(page, now)
            return ScraperResult(accounts=accounts, transactions=[])
        except (ScraperLoginError, ScraperTimeoutError, ScraperParseError):
            raise
        finally:
            await self._close_browser(browser)

    # ------------------------------------------------------------------
    # Login + auth capture
    # ------------------------------------------------------------------

    async def _login_and_capture_auth(self, page) -> dict[str, str]:
        """Drive the iframe login and sniff the Kony auth headers.

        Returns a dict with ``jwt`` (x-kony-authorization) and ``deviceid``
        (x-kony-deviceid) captured from the first authenticated request.

        Raises:
            ScraperLoginError: credentials rejected / login form never rendered.
            ScraperTimeoutError: the dashboard never became ready (often the
                portal rate-limiting after too many rapid logins).
        """
        # The browser is patchright, which raises its OWN TimeoutError class
        # (not playwright's). Catch both so a rate-limit stall surfaces as our
        # clear ScraperTimeoutError instead of an opaque parse error.
        from patchright.async_api import TimeoutError as _PatchrightTimeout
        from playwright.async_api import TimeoutError as _PlaywrightTimeout

        PlaywrightTimeoutError = (_PlaywrightTimeout, _PatchrightTimeout)

        # Kony refreshes the JWT through the session, so keep the LATEST one the
        # SPA sends (not just the first). Stored on the instance so _api_post
        # always uses the freshest token, and the listener stays attached for the
        # rest of the scrape.
        auth: dict[str, str] = {}
        self._kony_auth = auth

        def _on_request(req) -> None:  # noqa: ANN001
            if "/services/" not in req.url:
                return
            h = req.headers
            jwt = h.get("x-kony-authorization")
            if jwt:
                auth["jwt"] = jwt
                auth["deviceid"] = h.get("x-kony-deviceid", auth.get("deviceid", ""))
                auth["reportingparams"] = h.get(
                    "x-kony-reportingparams", auth.get("reportingparams", "")
                )

        page.on("request", _on_request)

        username = self._username
        password = self._password
        try:
            # Form steps before Sign In are safe to repeat on a fresh load:
            # nothing has been submitted, so no failed login is recorded.
            login_frame = None
            for form_attempt in range(1, _LOGIN_FORM_ATTEMPTS + 1):
                login_frame = await self._open_login_form(page)
                step = "username"
                try:
                    await login_frame.fill(_SEL_USERNAME, username, timeout=_FORM_STEP_TIMEOUT_MS)
                    step = "password focus"
                    await login_frame.click(_SEL_PASSWORD, timeout=_FORM_STEP_TIMEOUT_MS)
                    step = "password typing"
                    await login_frame.locator(_SEL_PASSWORD).press_sequentially(
                        password, delay=_PASSWORD_KEY_DELAY_MS, timeout=_FORM_STEP_TIMEOUT_MS
                    )
                except PlaywrightTimeoutError as exc:
                    logger.warning(
                        "BDC_KONY: login form step '%s' timed out (attempt %d/%d)",
                        step,
                        form_attempt,
                        _LOGIN_FORM_ATTEMPTS,
                    )
                    if form_attempt == _LOGIN_FORM_ATTEMPTS:
                        await self._safe_screenshot(page, "kony_login_form_timeout")
                        raise ScraperTimeoutError(
                            f"BDC_KONY: login form did not respond within timeout ({step})",
                            bank_code=self.bank_name,
                        ) from exc
                    continue
                break
            assert login_frame is not None

            typed = await login_frame.evaluate(
                "(sel) => document.querySelector(sel).value.length", _SEL_PASSWORD
            )
            if typed != len(password):
                raise ScraperParseError(
                    "BDC_KONY: login form did not accept the password input",
                    bank_code=self.bank_name,
                )

            # Submit once. A click that times out never reached the button, so
            # fall back to the button's own handler rather than failing.
            try:
                await login_frame.click(
                    _SEL_LOGIN_BTN, timeout=_FORM_STEP_TIMEOUT_MS, no_wait_after=True
                )
            except PlaywrightTimeoutError as exc:
                logger.warning("BDC_KONY: Sign In click timed out; triggering the button directly")
                clicked = await login_frame.evaluate(
                    """(sel) => {
                        const b = document.querySelector(sel);
                        if (!b) return false;
                        b.click();
                        return true;
                    }""",
                    _SEL_LOGIN_BTN,
                )
                if not clicked:
                    await self._safe_screenshot(page, "kony_login_button_missing")
                    raise ScraperTimeoutError(
                        "BDC_KONY: login form did not respond within timeout (sign in)",
                        bank_code=self.bank_name,
                    ) from exc
            logger.info("BDC_KONY: submitted login — waiting for dashboard")
        finally:
            del username
            del password

        # Wait for an authenticated signal: either the JWT was sniffed, or the
        # app shell shows post-login content.
        try:
            await page.wait_for_function(
                """() => {
                    const t = document.body ? (document.body.innerText || '') : '';
                    return t.includes('Available Balance') || t.includes('Accounts')
                        || t.includes('Cards') || t.includes('Last login');
                }""",
                timeout=_DASHBOARD_TIMEOUT_MS,
            )
        except PlaywrightTimeoutError as exc:
            # Distinguish a credential rejection from a rate-limit stall.
            body = ""
            try:
                body = await page.evaluate("() => (document.body.innerText||'').toLowerCase()")
            except Exception:
                pass
            # The login iframe always contains a hidden error element; only a
            # visible one means the portal rejected the attempt.
            try:
                login_error = await login_frame.evaluate(
                    """(sel) => {
                        const e = document.querySelector(sel);
                        return e && e.offsetHeight ? (e.innerText || '').toLowerCase() : '';
                    }""",
                    _SEL_LOGIN_ERROR,
                )
            except Exception:
                login_error = ""
            if isinstance(login_error, str):
                body = f"{body} {login_error}"
            if any(p in body for p in ("invalid", "incorrect", "not match", "locked")):
                await self._safe_screenshot(page, "kony_login_rejected")
                raise ScraperLoginError(
                    "BDC_KONY: portal rejected credentials", bank_code=self.bank_name
                ) from exc
            await self._safe_screenshot(page, "kony_dashboard_stalled")
            raise ScraperTimeoutError(
                "BDC_KONY: dashboard did not render after login — the portal may be "
                "rate-limiting (space out attempts) or an MFA/OTP step appeared",
                bank_code=self.bank_name,
            ) from exc

        # Wait for the JWT to be sniffed, then let the SPA finish its own
        # post-login data calls (it fetches accounts/cards itself). This warms
        # the session so our subsequent fetch() reuses a valid, current token —
        # calling too early races the token setup and gets a 401.
        for _ in range(20):
            if auth.get("jwt"):
                break
            await page.wait_for_timeout(1_000)
        # Let the SPA's own authenticated XHRs complete (also refreshes token).
        await page.wait_for_timeout(6_000)

        if not auth.get("jwt"):
            logger.warning(
                "BDC_KONY: authenticated but x-kony-authorization not captured yet; "
                "will rely on the page request context for API calls"
            )
        else:
            logger.info("BDC_KONY: captured session JWT + deviceid")
        return auth

    async def _open_login_form(self, page):  # noqa: ANN001, ANN202
        """Load the portal and return the login iframe, reloading if needed.

        The portal intermittently resets the connection for its main app
        script or stalls before rendering the login iframe; a fresh load
        normally renders it in ~10 s, so reload instead of waiting longer.
        """
        from patchright.async_api import Error as _PatchrightError
        from patchright.async_api import TimeoutError as _PatchrightTimeout
        from playwright.async_api import TimeoutError as _PlaywrightTimeout

        for attempt in range(1, _LOGIN_PAGE_ATTEMPTS + 1):
            try:
                await page.goto(_APP_URL, wait_until="domcontentloaded", timeout=_NAV_TIMEOUT_MS)
            except (_PlaywrightTimeout, _PatchrightTimeout) as exc:
                raise ScraperTimeoutError(
                    "BDC_KONY: portal did not load within timeout", bank_code=self.bank_name
                ) from exc
            except _PatchrightError:
                raise BankPortalUnreachableError(
                    "BDC portal could not be reached. Check the proxy connection, Egyptian "
                    "location, and provider access to bdconline.com.eg.",
                    bank_code=self.bank_name,
                ) from None

            login_frame = await self._wait_for_login_frame(page)
            if login_frame is not None:
                return login_frame
            logger.warning(
                "BDC_KONY: login form not rendered (attempt %d/%d)",
                attempt,
                _LOGIN_PAGE_ATTEMPTS,
            )

        await self._safe_screenshot(page, "kony_no_login_iframe")
        raise ScraperTimeoutError(
            "BDC_KONY: login form never rendered after reloading the portal",
            bank_code=self.bank_name,
        )

    async def _wait_for_login_frame(self, page):  # noqa: ANN001, ANN202
        """Return the login iframe once its password field exists, else None."""
        for _ in range(_LOGIN_RENDER_POLLS):
            for fr in page.frames:
                if _LOGIN_IFRAME_MARKER in (fr.url or ""):
                    try:
                        await fr.wait_for_selector(_SEL_PASSWORD, timeout=2_000)
                        return fr
                    except Exception:
                        break
            await page.wait_for_timeout(2_000)
        return None

    # ------------------------------------------------------------------
    # JSON API calls (via the page's own request context = same session)
    # ------------------------------------------------------------------

    async def _api_post(
        self,
        page,
        op_path: str,
        payload: dict | None = None,
        _retrying: bool = False,
        content_type: str = _FORM_CONTENT_TYPE,
    ) -> dict:
        """POST a Kony data operation from *inside the page* and return the JSON.

        Runs ``fetch()`` in the page context so the request carries the live
        session cookies AND the Kony auth headers (``x-kony-authorization`` etc.)
        exactly as the SPA's own XHRs do — the browser attaches them itself.
        (We avoid ``page.request`` because its APIRequestContext rejects some
        characters in the auto-forwarded session cookie.)
        """
        auth = getattr(self, "_kony_auth", {}) or {}
        evaluation = page.evaluate(
            """async ({url, body, auth, contentType}) => {
                const headers = {'content-type': contentType};
                if (auth.jwt) headers['x-kony-authorization'] = auth.jwt;
                if (auth.deviceid) headers['x-kony-deviceid'] = auth.deviceid;
                if (auth.reportingparams) headers['x-kony-reportingparams'] = auth.reportingparams;
                const controller = new AbortController();
                const timer = setTimeout(() => controller.abort(), 60000);
                try {
                    const r = await fetch(url, {method:'POST', headers, body,
                                               credentials:'include', signal:controller.signal});
                    const text = await r.text();
                    return {status: r.status, text};
                } catch (e) {
                    return {status: 0, text: '', error: String(e)};
                } finally {
                    clearTimeout(timer);
                }
            }""",
            {
                "url": _BASE + op_path,
                "body": "jsondata=" + quote(json.dumps(payload or {})),
                "auth": auth,
                "contentType": content_type,
            },
        )
        try:
            result = await asyncio.wait_for(evaluation, timeout=_API_EVALUATE_TIMEOUT_S)
        except TimeoutError as exc:
            raise ScraperTimeoutError(
                "BDC_KONY: API request timed out", bank_code=self.bank_name
            ) from exc
        if result.get("error") or not result.get("status"):
            raise ScraperParseError(
                f"BDC_KONY: API {op_path} fetch failed: {result.get('error')}",
                bank_code=self.bank_name,
            )
        if result["status"] == 401 and not _retrying:
            # Token may have just refreshed — wait for the SPA to emit a fresh
            # request (updates self._kony_auth via the listener) and retry once.
            logger.info("BDC_KONY: API %s got 401 — refreshing token and retrying", op_path)
            await page.wait_for_timeout(3_000)
            return await self._api_post(
                page, op_path, payload, _retrying=True, content_type=content_type
            )
        if result["status"] >= 400:
            raise ScraperParseError(
                f"BDC_KONY: API {op_path} returned HTTP {result['status']}",
                bank_code=self.bank_name,
            )
        try:
            return json.loads(result["text"])
        except (ValueError, TypeError) as exc:
            raise ScraperParseError(
                f"BDC_KONY: API {op_path} returned non-JSON body",
                bank_code=self.bank_name,
            ) from exc

    async def _fetch_accounts(self, page, now: datetime) -> list[BankAccount]:
        """Fetch deposit/checking accounts via the Holdings API."""
        try:
            data = await self._api_post(page, _ACCOUNTS_OP)
        except ScraperParseError:
            logger.warning("BDC_KONY: accounts API call failed")
            raise

        raw_accounts = data.get("Accounts") or []
        accounts: list[BankAccount] = []
        for a in raw_accounts:
            account_id = str(a.get("accountID") or a.get("account_id") or "")
            balance = _to_decimal(a.get("availableBalance", a.get("currentBalance")))
            raw_type = (a.get("accountType") or "").strip().lower()
            account_type = _ACCOUNT_TYPE_MAP.get(raw_type, _DEFAULT_ACCOUNT_TYPE)
            accounts.append(
                BankAccount(
                    id=_ZERO_UUID,
                    user_id=_ZERO_UUID,
                    bank_name=self.bank_name,
                    account_number_masked=_mask(account_id),
                    account_type=account_type,
                    currency=(a.get("currencyCode") or "EGP").strip() or "EGP",
                    balance=balance,
                    is_active=True,
                    last_synced_at=now,
                    product_name=a.get("displayName") or a.get("nickName"),
                    created_at=now,
                    updated_at=now,
                )
            )
        logger.info("BDC_KONY: fetched %d deposit account(s)", len(accounts))
        return accounts

    async def _fetch_cards(
        self, page, now: datetime, auth: dict[str, str]
    ) -> tuple[list[BankAccount], list[Transaction]]:
        """Fetch credit cards and each card's transactions via the Cards API.

        A failed card list or history call fails the scrape rather than
        reporting a card without its transactions.
        """
        accounts: list[BankAccount] = []
        transactions: list[Transaction] = []
        try:
            await self._api_post(page, _CARD_ACTIVE_OP, content_type=_JSON_CONTENT_TYPE)
        except ScraperParseError:
            logger.warning("BDC_KONY: active-cards call failed; continuing with card list")
        try:
            card_data = await self._api_post(page, _CARD_LIST_OP)
        except ScraperParseError:
            logger.warning("BDC_KONY: card list API call failed")
            raise

        # Field names confirmed from the live fetchCreditCards response
        # (2026-09-26). ``outstandingBalance`` equals ``availableBalance`` —
        # the unused credit — so it is not the amount owed. The portal's
        # figures satisfy availableBalance + utilizedAmount + holdAmount =
        # approvedLimit, where holdAmount is pending authorisations.
        for c in card_data.get("Cards", card_data.get("cards", [])):
            card_no = str(c.get("maskedCardNumber") or c.get("cardNumber") or "")
            limit = _to_decimal(c.get("approvedLimit"), Decimal("0"))
            account = BankAccount(
                id=_ZERO_UUID,
                user_id=_ZERO_UUID,
                bank_name=self.bank_name,
                account_number_masked=_mask(card_no),
                account_type="credit_card",
                currency=(c.get("currency") or c.get("currencyCode") or "EGP").strip() or "EGP",
                balance=_card_amount_owed(c, limit),
                is_active=(str(c.get("cardStatus", "")).upper() == "ACTIVE"),
                last_synced_at=now,
                credit_limit=limit or None,
                # closingBalance = last statement (billed) balance.
                billed_amount=_to_decimal(c.get("closingBalance"), Decimal("0")) or None,
                minimum_payment=_to_decimal(
                    c.get("currMinPayment", c.get("minimumDue")), Decimal("0")
                )
                or None,
                payment_due_date=_parse_kony_date(c.get("dueDate") or c.get("settelmentDate")),
                product_name=c.get("embossingName") or c.get("product"),
                created_at=now,
                updated_at=now,
            )
            accounts.append(account)
            transactions.extend(await self._fetch_card_transactions(page, account, c, now))

        logger.info(
            "BDC_KONY: fetched %d card(s), %d card transaction(s)",
            len(accounts),
            len(transactions),
        )
        return accounts, transactions

    async def _fetch_card_transactions(
        self, page, account: BankAccount, card: dict, now: datetime
    ) -> list[Transaction]:
        """Fetch one credit card's transaction history.

        The operation is keyed by the full card number, which is sent to the
        portal only and never stored or logged.
        """
        pan = str(card.get("cardNumber") or "").strip()
        if not pan.isdigit():
            raise ScraperParseError(
                f"BDC_KONY: card {account.account_number_masked} has no card number "
                "for its transaction history",
                bank_code=self.bank_name,
            )
        try:
            for attempt in (1, 2):
                try:
                    data = await self._api_post(
                        page, _CARD_TXN_OP, {"PAN": pan}, content_type=_JSON_CONTENT_TYPE
                    )
                    break
                except ScraperParseError:
                    logger.warning(
                        "BDC_KONY: card txn API call failed for %s (attempt %d/2)",
                        account.account_number_masked,
                        attempt,
                    )
                    if attempt == 2:
                        raise
        finally:
            del pan

        rows = data.get("Transaction", data.get("Transactions", [])) or []
        if not rows:
            logger.warning(
                "BDC_KONY: card %s returned no transactions", account.account_number_masked
            )

        txns: list[Transaction] = []
        for r in rows:
            txn = self._parse_card_transaction(r, account, now)
            if txn is not None:
                txns.append(txn)
        return txns

    def _parse_card_transaction(
        self, r: dict, account: BankAccount, now: datetime
    ) -> Transaction | None:
        """Map one ``getCreditTransactionsHistory`` row to a Transaction.

        Returns None for rows that did not move money (declined or zero).
        """
        status = str(r.get("txnStatus") or "").strip().lower()
        if status and status != "approved":
            return None
        # AmountAcct is in the card's billing currency (EGP for foreign
        # purchases too); txnAmount is in the merchant's currency.
        amount = _to_decimal(r.get("AmountAcct") or r.get("txnAmount"))
        if amount <= 0:
            return None
        txn_date = _parse_kony_date(r.get("txnDate") or str(r.get("TranTime") or "")[:10])
        if txn_date is None:
            raise ScraperParseError(
                "BDC card transaction has an invalid date", bank_code=self.bank_name
            )
        description = (
            str(r.get("txnDetails") or r.get("TermOwner") or "").strip()
            or str(r.get("txnDescription") or "").strip()
            or "N/A"
        )
        # txnDescription is "Purchase" (money spent) or "Payment" (money paid
        # to the card, TranCode 50).
        kind = str(r.get("txnDescription") or "").strip()
        txn_type = "credit" if kind.lower() in _CARD_CREDIT_KINDS else "debit"
        bank_id = str(r.get("Id") or r.get("TranNumber") or "").strip()
        external_id = (
            f"bdc:{bank_id}" if bank_id else _make_external_id(txn_date, description, amount)
        )
        original_currency = str(r.get("txnCurrecy") or "").strip()
        return Transaction(
            id=_ZERO_UUID,
            user_id=_ZERO_UUID,
            account_id=_ZERO_UUID,
            external_id=external_id,
            amount=amount,
            currency=account.currency,
            transaction_type=txn_type,
            description=description,
            category=None,
            sub_category=None,
            transaction_date=txn_date,
            value_date=None,
            balance_after=None,
            # Keep only non-sensitive fields: rows also carry the full card
            # number, track data and the linked account number.
            raw_data={
                "source": "bdc_kony_card",
                "account_number_masked": account.account_number_masked,
                "bank_transaction_id": bank_id or None,
                "kind": kind or None,
                "time": r.get("TranTime"),
                "original_amount": r.get("txnAmount"),
                "original_currency": original_currency or None,
                "city": r.get("TermCity"),
                "country": r.get("TermCountryName"),
                "merchant_category_code": r.get("TermSIC"),
            },
            is_categorized=False,
            created_at=now,
            updated_at=now,
        )
