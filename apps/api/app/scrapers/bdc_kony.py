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

    Credit-card + card-transaction operations are wired through
    ``_CARD_LIST_OP`` / ``_CARD_TXN_OP`` — **fill these in from the pending
    card-section capture** (Cards tab → Credit → expand arrow). Until then the
    card methods no-op and only accounts are returned.

This scraper is built **alongside** ``BDCRetailScraper``; ``BDC_RETAIL`` is not
switched over until this one is verified writing real transactions.

BDC is reachable only from an Egyptian IP (Render is geo-blocked), so this runs
locally via ``run_bdc_local.py`` — same operational constraint as the T24 one.
"""

from __future__ import annotations

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

from app.models.db import BankAccount, Transaction
from app.scrapers.base import (
    BankScraper,
    ScraperLoginError,
    ScraperParseError,
    ScraperResult,
    ScraperTimeoutError,
    ScraperUnavailableError,
)

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

# Kony DBX JSON API operations (POST, form body ``jsondata=<url-encoded json>``).
# All confirmed live 2026-07-27 except _CARD_TXN_OP (see below).
_ACCOUNTS_OP = "/services/data/v1/Holdings/operations/DigitalArrangements/getList"
_CARD_LIST_OP = "/services/data/v1/CreditCard/operations/CreditCardModel/fetchCreditCards"
# TODO(card-txn-capture): the card-transactions/statement operation fires when a
# card is opened from Cards → Credit → (card). Not yet captured; leave falsy so
# card *details* (balance/limit/due) sync while transactions are pending.
_CARD_TXN_OP = ""

_ZERO_UUID = UUID("00000000-0000-0000-0000-000000000000")

_NAV_TIMEOUT_MS = 120_000
_LOGIN_RENDER_TIMEOUT_MS = 60_000
_DASHBOARD_TIMEOUT_MS = 60_000


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


# ---------------------------------------------------------------------------
# Scraper
# ---------------------------------------------------------------------------


class BDCKonyScraper(BankScraper):
    """Scraper for the new BDC Kony / Temenos Infinity online-banking portal."""

    bank_name: ClassVar[str] = "BDC_RETAIL"  # same logical bank as the T24 one

    async def _launch_browser(self):  # type: ignore[override]
        """Launch Chromium via patchright (undetected) — same recipe as T24.

        Pass ONLY headless/channel/viewport/locale/timezone. Custom args, UA, or
        request routing break patchright's stealth (see bdc_new_kony_portal).

        Raises:
            ScraperUnavailableError: on Render — BDC is EG-only and patchright's
                browser is not installed there; fail fast with an actionable
                message instead of a cryptic launch crash.
        """
        # Render is geo-blocked by BDC and lacks patchright's Chromium. Same
        # environment signal as base.py / the T24 scraper.
        if os.path.isdir("/opt/render/project/src/.playwright-browsers"):
            raise ScraperUnavailableError(
                "BDC_RETAIL cannot be synced from the hosted backend: Banque du "
                "Caire blocks non-Egyptian IPs and the headless browser is not "
                "available in this environment. Run the BDC sync locally from the "
                "Egyptian machine (apps/api/run_bdc_local.py).",
                bank_code=self.bank_name,
            )

        from patchright.async_api import async_playwright as patchright_playwright

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
        )
        page = context.pages[0] if context.pages else await context.new_page()
        logger.info("BDC_KONY browser launched via patchright (persistent context, stealth)")
        return context, context, page

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

        except (ScraperLoginError, ScraperTimeoutError, ScraperParseError):
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
        from patchright._impl._errors import TimeoutError as _PatchrightTimeout
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

        try:
            await page.goto(_APP_URL, wait_until="domcontentloaded", timeout=_NAV_TIMEOUT_MS)
        except PlaywrightTimeoutError as exc:
            raise ScraperTimeoutError(
                "BDC_KONY: portal did not load within timeout", bank_code=self.bank_name
            ) from exc

        # Locate the login iframe and wait for the password field.
        login_frame = None
        for _ in range(30):
            for fr in page.frames:
                if _LOGIN_IFRAME_MARKER in (fr.url or ""):
                    login_frame = fr
                    break
            if login_frame:
                try:
                    await login_frame.wait_for_selector(_SEL_PASSWORD, timeout=2_000)
                    break
                except Exception:
                    pass
            await page.wait_for_timeout(2_000)

        if login_frame is None:
            await self._safe_screenshot(page, "kony_no_login_iframe")
            raise ScraperLoginError(
                "BDC_KONY: login form (iframe) never rendered", bank_code=self.bank_name
            )

        username = self._username
        password = self._password
        try:
            await login_frame.fill(_SEL_USERNAME, username)
            await login_frame.fill(_SEL_PASSWORD, password)
            await login_frame.click(_SEL_LOGIN_BTN)
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

    # ------------------------------------------------------------------
    # JSON API calls (via the page's own request context = same session)
    # ------------------------------------------------------------------

    async def _api_post(
        self, page, op_path: str, payload: dict | None = None, _retrying: bool = False
    ) -> dict:
        """POST a Kony data operation from *inside the page* and return the JSON.

        Runs ``fetch()`` in the page context so the request carries the live
        session cookies AND the Kony auth headers (``x-kony-authorization`` etc.)
        exactly as the SPA's own XHRs do — the browser attaches them itself.
        (We avoid ``page.request`` because its APIRequestContext rejects some
        characters in the auto-forwarded session cookie.)
        """
        auth = getattr(self, "_kony_auth", {}) or {}
        result = await page.evaluate(
            """async ({url, body, auth}) => {
                const headers = {'content-type': 'application/x-www-form-urlencoded'};
                if (auth.jwt) headers['x-kony-authorization'] = auth.jwt;
                if (auth.deviceid) headers['x-kony-deviceid'] = auth.deviceid;
                if (auth.reportingparams) headers['x-kony-reportingparams'] = auth.reportingparams;
                try {
                    const r = await fetch(url, {method:'POST', headers, body,
                                               credentials:'include'});
                    const text = await r.text();
                    return {status: r.status, text};
                } catch (e) {
                    return {status: 0, text: '', error: String(e)};
                }
            }""",
            {
                "url": _BASE + op_path,
                "body": "jsondata=" + quote(json.dumps(payload or {})),
                "auth": auth,
            },
        )
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
            return await self._api_post(page, op_path, payload, _retrying=True)
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
            logger.warning("BDC_KONY: accounts API call failed", exc_info=True)
            return []

        raw_accounts = data.get("Accounts") or []
        accounts: list[BankAccount] = []
        for a in raw_accounts:
            account_id = str(a.get("accountID") or a.get("account_id") or "")
            balance = _to_decimal(a.get("availableBalance", a.get("currentBalance")))
            account_type = (a.get("accountType") or "checking").strip().lower()
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
        """Fetch credit cards + their transactions via the Cards API.

        Wired but inert until ``_CARD_LIST_OP`` / ``_CARD_TXN_OP`` are confirmed
        from the pending Cards-section capture (Cards → Credit → expand arrow).
        Returns empty lists until then so accounts still sync.
        """
        accounts: list[BankAccount] = []
        transactions: list[Transaction] = []
        try:
            card_data = await self._api_post(page, _CARD_LIST_OP)
        except ScraperParseError:
            logger.warning("BDC_KONY: card list API call failed", exc_info=True)
            return [], []

        # Field names confirmed from the live fetchCreditCards response
        # (bdc_new_kony_portal): maskedCardNumber, embossingName, product,
        # currency, closingBalance (billed/statement), CurrentBalance,
        # outstandingBalance, availableBalance, dueDate, accountName (card ref).
        for c in card_data.get("Cards", card_data.get("cards", [])):
            card_no = str(c.get("maskedCardNumber") or c.get("cardNumber") or "")
            # Balance shown as the outstanding/current amount owed on the card.
            balance = _to_decimal(
                c.get("outstandingBalance", c.get("CurrentBalance", c.get("closingBalance")))
            )
            account = BankAccount(
                id=_ZERO_UUID,
                user_id=_ZERO_UUID,
                bank_name=self.bank_name,
                account_number_masked=_mask(card_no),
                account_type="credit_card",
                currency=(c.get("currency") or c.get("currencyCode") or "EGP").strip() or "EGP",
                balance=balance,
                is_active=(str(c.get("cardStatus", "")).upper() == "ACTIVE"),
                last_synced_at=now,
                # closingBalance = last statement (billed) balance.
                billed_amount=_to_decimal(c.get("closingBalance"), Decimal("0")) or None,
                payment_due_date=_parse_kony_date(c.get("dueDate") or c.get("settelmentDate")),
                product_name=c.get("embossingName") or c.get("product"),
                created_at=now,
                updated_at=now,
            )
            accounts.append(account)

            if _CARD_TXN_OP:
                transactions.extend(
                    await self._fetch_card_transactions(page, account, c, now)
                )

        logger.info(
            "BDC_KONY: fetched %d card(s), %d card transaction(s)",
            len(accounts),
            len(transactions),
        )
        return accounts, transactions

    async def _fetch_card_transactions(
        self, page, account: BankAccount, card: dict, now: datetime
    ) -> list[Transaction]:
        """Fetch one card's transactions. Payload shape confirmed at capture."""
        card_ref = card.get("cardReferenceId") or card.get("cardId") or card.get("cardNumber")
        try:
            data = await self._api_post(page, _CARD_TXN_OP, {"cardRef": card_ref})
        except ScraperParseError:
            logger.warning("BDC_KONY: card txn API call failed for %s", account.account_number_masked)
            return []

        txns: list[Transaction] = []
        rows = data.get("Transactions", data.get("transactions", []))
        for r in rows:
            amount = _to_decimal(r.get("amount"))
            if amount <= 0:
                continue
            txn_date = _parse_kony_date(r.get("transactionDate") or r.get("date"))
            description = (r.get("description") or r.get("transactionDetails") or "N/A").strip()
            # Category text like "Card Payment" (credit) vs "Purchase" (debit).
            cat = (r.get("transactionCategory") or "").lower()
            txn_type = "credit" if ("payment" in cat or "credit" in cat) else "debit"
            txns.append(
                Transaction(
                    id=_ZERO_UUID,
                    user_id=_ZERO_UUID,
                    account_id=_ZERO_UUID,
                    external_id=_make_external_id(txn_date, description, amount),
                    amount=amount,
                    currency=account.currency,
                    transaction_type=txn_type,
                    description=description,
                    category=None,
                    sub_category=None,
                    transaction_date=txn_date,
                    value_date=None,
                    balance_after=None,
                    raw_data={
                        "source": "bdc_kony_card",
                        "account_number_masked": account.account_number_masked,
                        "row": r,
                    },
                    is_categorized=False,
                    created_at=now,
                    updated_at=now,
                )
            )
        return txns
