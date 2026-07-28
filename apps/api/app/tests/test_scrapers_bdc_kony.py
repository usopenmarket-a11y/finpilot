"""Unit tests for BDCKonyScraper (new BDC Kony/Temenos Infinity portal).

No real browser is launched. The scraper's browser + login are mocked; the
JSON-mapping logic (``_fetch_accounts`` / ``_fetch_cards``) is exercised against
the real captured Kony API response shapes, and ``_api_post`` is driven with a
fake ``page`` whose ``evaluate`` returns canned ``{status, text}`` payloads.

Coverage targets
----------------
- module helpers: _to_decimal, _mask, _make_external_id, _parse_kony_date
- BDCKonyScraper.scrape() / scrape_accounts() happy path (login mocked)
- _api_post: JSON success, HTTP error, 401 retry, non-JSON body, fetch error
- _fetch_accounts / _fetch_cards JSON → BankAccount mapping
- exception hierarchy + bank_code
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.db import BankAccount
from app.scrapers.base import (
    BankScraper,
    ScraperParseError,
    ScraperResult,
)
from app.scrapers.bdc_kony import (
    BDCKonyScraper,
    _make_external_id,
    _mask,
    _parse_kony_date,
    _to_decimal,
)

# Real captured API bodies (trimmed) from the live Kony portal 2026-07-27.
_ACCOUNTS_JSON = {
    "Accounts": [
        {
            "accountID": "999999917692898",
            "accountType": "Checking",
            "displayName": "DUMMY ACCOUNT",
            "availableBalance": "0",
            "currentBalance": "0",
            "currencyCode": "EGP",
            "IBAN": "99999991017692898",
            "nickName": "DUMMY ACCOUNT17692898",
        }
    ],
    "opstatus": 0,
}

_CARDS_JSON = {
    "opstatus": 0,
    "Cards": [
        {
            "maskedCardNumber": "553592******9208",
            "embossingName": "FADY ADEL",
            "product": "MasterCard",
            "currency": "EGP",
            "closingBalance": "20621.37",
            "CurrentBalance": "70495.99",
            "outstandingBalance": "43904.01",
            "availableBalance": "43904.01",
            "dueDate": "2026-07-30",
            "settelmentDate": "2026-07-30",
            "cardStatus": "ACTIVE",
            "accountName": "MC_CR_CRP_3316688606",
        }
    ],
}


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


class TestToDecimal:
    def test_plain_number_string(self) -> None:
        assert _to_decimal("123.45") == Decimal("123.45")

    def test_strips_commas(self) -> None:
        assert _to_decimal("104,000.00") == Decimal("104000.00")

    def test_none_returns_default(self) -> None:
        assert _to_decimal(None) == Decimal("0")

    def test_empty_string_returns_default(self) -> None:
        assert _to_decimal("") == Decimal("0")

    def test_custom_default(self) -> None:
        assert _to_decimal(None, Decimal("5")) == Decimal("5")

    def test_garbage_returns_default(self) -> None:
        assert _to_decimal("not-a-number") == Decimal("0")

    def test_numeric_input(self) -> None:
        assert _to_decimal(42) == Decimal("42")


class TestMask:
    def test_last_four_of_long_id(self) -> None:
        assert _mask("999999917692898") == "****2898"

    def test_masked_card_number_digits_only(self) -> None:
        assert _mask("553592******9208") == "****9208"

    def test_short_id_uses_tail(self) -> None:
        assert _mask("12").startswith("****")

    def test_always_prefixed(self) -> None:
        assert _mask("55359209").startswith("****")


class TestMakeExternalId:
    def test_deterministic(self) -> None:
        a = _make_external_id(date(2026, 6, 29), "MY FAWRY", Decimal("5050"))
        b = _make_external_id(date(2026, 6, 29), "MY FAWRY", Decimal("5050"))
        assert a == b

    def test_differs_on_amount(self) -> None:
        a = _make_external_id(date(2026, 6, 29), "MY FAWRY", Decimal("5050"))
        b = _make_external_id(date(2026, 6, 29), "MY FAWRY", Decimal("10100"))
        assert a != b

    def test_handles_none_date(self) -> None:
        assert _make_external_id(None, "X", Decimal("1")) != ""

    def test_length_is_32(self) -> None:
        assert len(_make_external_id(date(2026, 1, 1), "X", Decimal("1"))) == 32


class TestParseKonyDate:
    def test_iso_format(self) -> None:
        assert _parse_kony_date("2026-07-30") == date(2026, 7, 30)

    def test_mm_dd_yyyy(self) -> None:
        assert _parse_kony_date("07/30/2026") == date(2026, 7, 30)

    def test_none_returns_none(self) -> None:
        assert _parse_kony_date(None) is None

    def test_empty_returns_none(self) -> None:
        assert _parse_kony_date("") is None

    def test_unrecognised_returns_none(self) -> None:
        assert _parse_kony_date("garbage") is None

    def test_epoch_millis(self) -> None:
        # 2026-07-30 ~ epoch ms
        ms = int(datetime(2026, 7, 30, tzinfo=UTC).timestamp() * 1000)
        assert _parse_kony_date(str(ms)) == date(2026, 7, 30)


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


class TestKonyExceptionHierarchy:
    def test_is_bank_scraper_subclass(self) -> None:
        assert issubclass(BDCKonyScraper, BankScraper)

    def test_bank_name_is_bdc_retail(self) -> None:
        s = BDCKonyScraper(username="u", password="p")
        assert s.bank_name == "BDC_RETAIL"

    def test_repr_hides_credentials(self) -> None:
        s = BDCKonyScraper(username="secret_user", password="secret_pass")
        assert "secret_pass" not in repr(s)


# ---------------------------------------------------------------------------
# _api_post — fake page whose evaluate returns canned fetch results
# ---------------------------------------------------------------------------


def _fake_page(evaluate_returns: list[dict[str, Any]]) -> MagicMock:
    """Build a fake Playwright page whose evaluate() yields queued results."""
    page = MagicMock()
    results = list(evaluate_returns)

    async def _evaluate(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return results.pop(0)

    page.evaluate = AsyncMock(side_effect=_evaluate)
    page.wait_for_timeout = AsyncMock(return_value=None)
    return page


@pytest.mark.asyncio
class TestApiPost:
    async def test_returns_parsed_json(self) -> None:
        s = BDCKonyScraper(username="u", password="p")
        page = _fake_page([{"status": 200, "text": '{"opstatus": 0, "x": 1}'}])
        data = await s._api_post(page, "/services/data/v1/x")
        assert data == {"opstatus": 0, "x": 1}

    async def test_http_error_raises(self) -> None:
        s = BDCKonyScraper(username="u", password="p")
        page = _fake_page([{"status": 500, "text": ""}])
        with pytest.raises(ScraperParseError):
            await s._api_post(page, "/services/data/v1/x")

    async def test_fetch_error_raises(self) -> None:
        s = BDCKonyScraper(username="u", password="p")
        page = _fake_page([{"status": 0, "text": "", "error": "NetworkError"}])
        with pytest.raises(ScraperParseError):
            await s._api_post(page, "/services/data/v1/x")

    async def test_non_json_raises(self) -> None:
        s = BDCKonyScraper(username="u", password="p")
        page = _fake_page([{"status": 200, "text": "<html>not json</html>"}])
        with pytest.raises(ScraperParseError):
            await s._api_post(page, "/services/data/v1/x")

    async def test_401_retries_then_succeeds(self) -> None:
        s = BDCKonyScraper(username="u", password="p")
        page = _fake_page(
            [
                {"status": 401, "text": ""},
                {"status": 200, "text": '{"ok": true}'},
            ]
        )
        data = await s._api_post(page, "/services/data/v1/x")
        assert data == {"ok": True}
        # first call + retry
        assert page.evaluate.await_count == 2


# ---------------------------------------------------------------------------
# _fetch_accounts / _fetch_cards mapping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestFetchAccounts:
    async def test_maps_checking_account(self) -> None:
        s = BDCKonyScraper(username="u", password="p")
        page = _fake_page([{"status": 200, "text": _json(_ACCOUNTS_JSON)}])
        now = datetime.now(UTC)
        accounts = await s._fetch_accounts(page, now)
        assert len(accounts) == 1
        acct = accounts[0]
        assert isinstance(acct, BankAccount)
        assert acct.account_number_masked == "****2898"
        # Kony "Checking" maps to the DB-allowed "current" type.
        assert acct.account_type == "current"
        assert acct.currency == "EGP"
        assert acct.balance == Decimal("0")
        assert acct.product_name == "DUMMY ACCOUNT"

    async def test_api_failure_returns_empty(self) -> None:
        s = BDCKonyScraper(username="u", password="p")
        page = _fake_page([{"status": 500, "text": ""}])
        accounts = await s._fetch_accounts(page, datetime.now(UTC))
        assert accounts == []

    async def test_empty_accounts_list(self) -> None:
        s = BDCKonyScraper(username="u", password="p")
        page = _fake_page([{"status": 200, "text": '{"Accounts": []}'}])
        assert await s._fetch_accounts(page, datetime.now(UTC)) == []

    async def test_savings_type_mapped(self) -> None:
        s = BDCKonyScraper(username="u", password="p")
        body = '{"Accounts": [{"accountID": "111122223333", "accountType": "Savings", "currencyCode": "EGP", "availableBalance": "10"}]}'
        page = _fake_page([{"status": 200, "text": body}])
        accounts = await s._fetch_accounts(page, datetime.now(UTC))
        assert accounts[0].account_type == "savings"

    async def test_unknown_type_defaults_to_current(self) -> None:
        s = BDCKonyScraper(username="u", password="p")
        body = '{"Accounts": [{"accountID": "111122223333", "accountType": "Weird", "currencyCode": "EGP", "availableBalance": "10"}]}'
        page = _fake_page([{"status": 200, "text": body}])
        accounts = await s._fetch_accounts(page, datetime.now(UTC))
        assert accounts[0].account_type == "current"


@pytest.mark.asyncio
class TestFetchCards:
    async def test_maps_credit_card(self) -> None:
        s = BDCKonyScraper(username="u", password="p")
        page = _fake_page([{"status": 200, "text": _json(_CARDS_JSON)}])
        now = datetime.now(UTC)
        cards, txns = await s._fetch_cards(page, now, {})
        assert len(cards) == 1
        card = cards[0]
        assert card.account_type == "credit_card"
        assert card.account_number_masked == "****9208"
        assert card.balance == Decimal("43904.01")  # outstanding
        assert card.billed_amount == Decimal("20621.37")  # closingBalance
        assert card.payment_due_date == date(2026, 7, 30)
        assert card.product_name == "FADY ADEL"
        assert card.is_active is True
        assert txns == []  # _CARD_TXN_OP is stubbed

    async def test_card_api_failure_returns_empty(self) -> None:
        s = BDCKonyScraper(username="u", password="p")
        page = _fake_page([{"status": 500, "text": ""}])
        cards, txns = await s._fetch_cards(page, datetime.now(UTC), {})
        assert cards == [] and txns == []


# ---------------------------------------------------------------------------
# scrape() / scrape_accounts() orchestration (login + browser mocked)
# ---------------------------------------------------------------------------


def _install_mock_browser(scraper: BDCKonyScraper, page: MagicMock) -> None:
    """Patch _launch_browser/_close_browser/_login_and_capture_auth on instance."""

    async def _launch() -> tuple[MagicMock, MagicMock, MagicMock]:
        return (MagicMock(), MagicMock(), page)

    async def _close(_browser: Any) -> None:
        return None

    async def _login(_page: Any) -> dict[str, str]:
        scraper._kony_auth = {"jwt": "fake.jwt", "deviceid": "d"}
        return scraper._kony_auth

    scraper._launch_browser = _launch  # type: ignore[method-assign]
    scraper._close_browser = _close  # type: ignore[method-assign]
    scraper._login_and_capture_auth = _login  # type: ignore[method-assign]


@pytest.mark.asyncio
class TestScrape:
    async def test_scrape_returns_account_and_card(self) -> None:
        s = BDCKonyScraper(username="u", password="p")
        page = _fake_page(
            [
                {"status": 200, "text": _json(_ACCOUNTS_JSON)},
                {"status": 200, "text": _json(_CARDS_JSON)},
            ]
        )
        _install_mock_browser(s, page)
        result = await s.scrape()
        assert isinstance(result, ScraperResult)
        assert len(result.accounts) == 2
        types = {a.account_type for a in result.accounts}
        assert types == {"current", "credit_card"}

    async def test_scrape_raises_when_nothing_returned(self) -> None:
        s = BDCKonyScraper(username="u", password="p")
        page = _fake_page(
            [
                {"status": 200, "text": '{"Accounts": []}'},
                {"status": 200, "text": '{"Cards": []}'},
            ]
        )
        _install_mock_browser(s, page)
        with pytest.raises(ScraperParseError):
            await s.scrape()

    async def test_scrape_accounts_only(self) -> None:
        s = BDCKonyScraper(username="u", password="p")
        page = _fake_page([{"status": 200, "text": _json(_ACCOUNTS_JSON)}])
        _install_mock_browser(s, page)
        result = await s.scrape_accounts()
        assert len(result.accounts) == 1
        assert result.transactions == []


# ---------------------------------------------------------------------------
# _login_and_capture_auth — fully mocked page + login iframe
# ---------------------------------------------------------------------------


def _login_page(*, iframe: bool = True, dashboard: bool = True, reject: bool = False):
    """Build a mock page for _login_and_capture_auth.

    Captures the request listener so tests can simulate the SPA emitting an
    authenticated request that carries the JWT.
    """
    page = MagicMock()
    listeners: dict[str, Any] = {}

    def _on(event: str, cb: Any) -> None:
        listeners[event] = cb

    page.on = MagicMock(side_effect=_on)
    page.goto = AsyncMock(return_value=None)
    page.wait_for_timeout = AsyncMock(return_value=None)
    page.wait_for_function = AsyncMock(return_value=None)

    if dashboard:
        page.evaluate = AsyncMock(return_value="")
    elif reject:
        # dashboard wait raises, and body text signals bad credentials
        from patchright._impl._errors import TimeoutError as _PT

        page.wait_for_function = AsyncMock(side_effect=_PT("timeout"))
        page.evaluate = AsyncMock(return_value="invalid username or password")
    else:
        from patchright._impl._errors import TimeoutError as _PT

        page.wait_for_function = AsyncMock(side_effect=_PT("timeout"))
        page.evaluate = AsyncMock(return_value="")

    frame = MagicMock()
    frame.url = "https://bdconline.com.eg/.../LoginPage.html" if iframe else "about:blank"
    frame.wait_for_selector = AsyncMock(return_value=MagicMock())
    frame.fill = AsyncMock(return_value=None)
    frame.click = AsyncMock(return_value=None)
    page.frames = [frame] if iframe else []
    page._listeners = listeners  # expose for the test
    return page


@pytest.mark.asyncio
class TestLoginAndCaptureAuth:
    async def test_happy_path_captures_jwt(self) -> None:
        s = BDCKonyScraper(username="u", password="p")
        s._safe_screenshot = AsyncMock(return_value=None)  # type: ignore[method-assign]
        page = _login_page()

        # After goto, simulate the SPA emitting an authed request (sets JWT).
        req = MagicMock()
        req.url = "https://bdconline.com.eg/services/data/v1/x"
        req.headers = {"x-kony-authorization": "fake.jwt", "x-kony-deviceid": "dev"}

        orig_goto = page.goto

        async def _goto_then_emit(*a: Any, **k: Any) -> None:
            await orig_goto(*a, **k)
            page._listeners["request"](req)

        page.goto = AsyncMock(side_effect=_goto_then_emit)

        auth = await s._login_and_capture_auth(page)
        assert auth.get("jwt") == "fake.jwt"
        assert auth.get("deviceid") == "dev"

    async def test_no_iframe_raises_login_error(self) -> None:
        from app.scrapers.base import ScraperLoginError

        s = BDCKonyScraper(username="u", password="p")
        s._safe_screenshot = AsyncMock(return_value=None)  # type: ignore[method-assign]
        page = _login_page(iframe=False)
        with pytest.raises(ScraperLoginError):
            await s._login_and_capture_auth(page)

    async def test_dashboard_stall_raises_timeout(self) -> None:
        from app.scrapers.base import ScraperTimeoutError

        s = BDCKonyScraper(username="u", password="p")
        s._safe_screenshot = AsyncMock(return_value=None)  # type: ignore[method-assign]
        page = _login_page(dashboard=False)
        with pytest.raises(ScraperTimeoutError):
            await s._login_and_capture_auth(page)

    async def test_bad_credentials_raises_login_error(self) -> None:
        from app.scrapers.base import ScraperLoginError

        s = BDCKonyScraper(username="u", password="p")
        s._safe_screenshot = AsyncMock(return_value=None)  # type: ignore[method-assign]
        page = _login_page(dashboard=False, reject=True)
        with pytest.raises(ScraperLoginError):
            await s._login_and_capture_auth(page)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _json(obj: Any) -> str:
    import json

    return json.dumps(obj)
