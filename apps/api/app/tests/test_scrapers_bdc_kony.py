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
- card transaction history → Transaction mapping (JSON content type, no PAN stored)
- exception hierarchy + bank_code
"""

from __future__ import annotations

import asyncio
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
    ScraperTimeoutError,
    ScraperUnavailableError,
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
            "maskedCardNumber": "000000******1234",
            "embossingName": "TEST USER",
            "product": "MasterCard",
            "currency": "EGP",
            "closingBalance": "20621.37",
            "CurrentBalance": "70495.99",
            "outstandingBalance": "43904.01",
            "availableBalance": "43904.01",
            "approvedLimit": "104000.00",
            "utilizedAmount": "55000",
            "holdAmount": "5095.99",
            "minimumDue": "1500.00",
            "currMinPayment": "1500.00",
            "dueDate": "2026-07-30",
            "settelmentDate": "2026-07-30",
            "cardStatus": "ACTIVE",
            "accountName": "MC_CR_CRP_3316688606",
            "cardNumber": "0000001111111234",
        }
    ],
}

# getAllActiveCards: called first to prepare the card history session.
_ACTIVE_CARDS: dict[str, Any] = {"status": 200, "text": '{"Cards": [{}], "opstatus": 0}'}

# Trimmed getCreditTransactionsHistory rows (shape captured live 2026-09-26).
_CARD_TXNS_JSON = {
    "opstatus": 0,
    "Transaction": [
        {
            "Id": "100000000001",
            "TranNumber": "200000000001",
            "txnDate": "2026-09-25",
            "TranTime": "2026-09-25T22:20:28",
            "txnDetails": "GEIDEAE*COFFEE",
            "TermOwner": "GEIDEAE*COFFEE",
            "txnDescription": "Purchase",
            "txnStatus": "Approved",
            "txnAmount": "234.5",
            "AmountAcct": "234.5",
            "txnCurrecy": "EGP",
            "TermCity": "CAIRO",
            "TermCountryName": "EGYPT",
            "TermSIC": "5814",
            "PAN": "0000001111111234",
            "Track2": "0000001111111234",
            "FromAcct": "MC_CR_CRP_3316688606",
        },
        {
            "Id": "100000000002",
            "txnDate": "2026-09-24",
            "TranTime": "2026-09-24T16:35:51",
            "txnDetails": "IPN",
            "txnDescription": "Payment",
            "txnStatus": "Approved",
            "txnAmount": "60000",
            "AmountAcct": "60000",
            "txnCurrecy": "EGP",
        },
        {
            "Id": "100000000003",
            "txnDate": "2026-08-10",
            "TranTime": "2026-08-10T12:00:00",
            "txnDetails": "ISTANBUL SHOP",
            "txnDescription": "Purchase",
            "txnStatus": "Approved",
            "txnAmount": "100",
            "AmountAcct": "125.40",
            "txnCurrecy": "TRY",
        },
        {
            "Id": "100000000004",
            "txnDate": "2026-08-09",
            "txnDetails": "DECLINED SHOP",
            "txnDescription": "Purchase",
            "txnStatus": "Declined",
            "txnAmount": "50",
            "AmountAcct": "50",
            "txnCurrecy": "EGP",
        },
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
        assert _mask("000000******1234") == "****1234"

    def test_short_id_uses_tail(self) -> None:
        assert _mask("12").startswith("****")

    def test_always_prefixed(self) -> None:
        assert _mask("12345678").startswith("****")


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

    async def test_stalled_api_call_times_out(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import app.scrapers.bdc_kony as mod

        async def never_returns(*_args: Any, **_kwargs: Any) -> None:
            await asyncio.Event().wait()

        monkeypatch.setattr(mod, "_API_EVALUATE_TIMEOUT_S", 0.01)
        s = BDCKonyScraper(username="u", password="p")
        page = MagicMock()
        page.evaluate = AsyncMock(side_effect=never_returns)
        with pytest.raises(ScraperTimeoutError):
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

    async def test_api_failure_raises(self) -> None:
        s = BDCKonyScraper(username="u", password="p")
        page = _fake_page([{"status": 500, "text": ""}])
        with pytest.raises(ScraperParseError):
            await s._fetch_accounts(page, datetime.now(UTC))

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
        page = _fake_page(
            [
                _ACTIVE_CARDS,
                {"status": 200, "text": _json(_CARDS_JSON)},
                {"status": 200, "text": _json(_CARD_TXNS_JSON)},
            ]
        )
        now = datetime.now(UTC)
        cards, txns = await s._fetch_cards(page, now, {})
        assert len(cards) == 1
        card = cards[0]
        assert card.account_type == "credit_card"
        assert card.account_number_masked == "****1234"
        # Owed = utilizedAmount + holdAmount, not outstandingBalance (which
        # the portal sets to the available credit).
        assert card.balance == Decimal("60095.99")
        assert card.credit_limit == Decimal("104000.00")
        assert card.minimum_payment == Decimal("1500.00")
        assert card.billed_amount == Decimal("20621.37")  # closingBalance
        assert card.payment_due_date == date(2026, 7, 30)
        assert card.product_name == "TEST USER"
        assert card.is_active is True
        assert len(txns) == 3  # declined row skipped

    async def test_owed_falls_back_to_limit_minus_available(self) -> None:
        s = BDCKonyScraper(username="u", password="p")
        card_json = {"Cards": [{**_CARDS_JSON["Cards"][0]}]}
        del card_json["Cards"][0]["utilizedAmount"]
        page = _fake_page(
            [
                _ACTIVE_CARDS,
                {"status": 200, "text": _json(card_json)},
                {"status": 200, "text": _json(_CARD_TXNS_JSON)},
            ]
        )
        cards, _ = await s._fetch_cards(page, datetime.now(UTC), {})
        assert cards[0].balance == Decimal("60095.99")

    async def test_history_uses_json_content_type_and_card_number(self) -> None:
        s = BDCKonyScraper(username="u", password="p")
        page = _fake_page(
            [
                _ACTIVE_CARDS,
                {"status": 200, "text": _json(_CARDS_JSON)},
                {"status": 200, "text": _json(_CARD_TXNS_JSON)},
            ]
        )
        await s._fetch_cards(page, datetime.now(UTC), {})
        active_args, list_args, history_args = (c.args[1] for c in page.evaluate.await_args_list)
        assert active_args["url"].endswith("/Cards/getAllActiveCards")
        assert active_args["contentType"] == "application/json"
        assert list_args["contentType"] == "application/x-www-form-urlencoded"
        assert history_args["contentType"] == "application/json"
        assert history_args["url"].endswith("/Cards/getCreditTransactionsHistory")
        assert "0000001111111234" in history_args["body"]

    async def test_history_failure_raises(self) -> None:
        s = BDCKonyScraper(username="u", password="p")
        page = _fake_page(
            [
                _ACTIVE_CARDS,
                {"status": 200, "text": _json(_CARDS_JSON)},
                {"status": 500, "text": ""},
                {"status": 500, "text": ""},
            ]
        )
        with pytest.raises(ScraperParseError):
            await s._fetch_cards(page, datetime.now(UTC), {})

    async def test_history_retries_once(self) -> None:
        s = BDCKonyScraper(username="u", password="p")
        page = _fake_page(
            [
                _ACTIVE_CARDS,
                {"status": 200, "text": _json(_CARDS_JSON)},
                {"status": 0, "text": "", "error": "AbortError"},
                {"status": 200, "text": _json(_CARD_TXNS_JSON)},
            ]
        )
        _, txns = await s._fetch_cards(page, datetime.now(UTC), {})
        assert len(txns) == 3

    async def test_active_cards_failure_is_not_fatal(self) -> None:
        s = BDCKonyScraper(username="u", password="p")
        page = _fake_page(
            [
                {"status": 500, "text": ""},
                {"status": 200, "text": _json(_CARDS_JSON)},
                {"status": 200, "text": _json(_CARD_TXNS_JSON)},
            ]
        )
        cards, txns = await s._fetch_cards(page, datetime.now(UTC), {})
        assert len(cards) == 1
        assert len(txns) == 3

    async def test_missing_card_number_raises(self) -> None:
        s = BDCKonyScraper(username="u", password="p")
        card_json = {"Cards": [{**_CARDS_JSON["Cards"][0], "cardNumber": ""}]}
        page = _fake_page([_ACTIVE_CARDS, {"status": 200, "text": _json(card_json)}])
        with pytest.raises(ScraperParseError):
            await s._fetch_cards(page, datetime.now(UTC), {})

    async def test_empty_history_returns_card_without_transactions(self) -> None:
        s = BDCKonyScraper(username="u", password="p")
        page = _fake_page(
            [
                _ACTIVE_CARDS,
                {"status": 200, "text": _json(_CARDS_JSON)},
                {"status": 200, "text": '{"Transaction": [], "opstatus": 0}'},
            ]
        )
        cards, txns = await s._fetch_cards(page, datetime.now(UTC), {})
        assert len(cards) == 1
        assert txns == []


@pytest.mark.asyncio
class TestCardTransactions:
    async def _txns(self) -> list[Any]:
        s = BDCKonyScraper(username="u", password="p")
        page = _fake_page(
            [
                _ACTIVE_CARDS,
                {"status": 200, "text": _json(_CARDS_JSON)},
                {"status": 200, "text": _json(_CARD_TXNS_JSON)},
            ]
        )
        _, txns = await s._fetch_cards(page, datetime.now(UTC), {})
        return txns

    async def test_purchase_maps_to_debit(self) -> None:
        t = (await self._txns())[0]
        assert t.transaction_type == "debit"
        assert t.amount == Decimal("234.5")
        assert t.currency == "EGP"
        assert t.description == "GEIDEAE*COFFEE"
        assert t.transaction_date == date(2026, 9, 25)
        assert t.external_id == "bdc:100000000001"

    async def test_payment_maps_to_credit(self) -> None:
        t = (await self._txns())[1]
        assert t.transaction_type == "credit"
        assert t.amount == Decimal("60000")

    async def test_foreign_purchase_uses_billed_egp_amount(self) -> None:
        t = (await self._txns())[2]
        assert t.amount == Decimal("125.40")
        assert t.currency == "EGP"
        assert t.raw_data["original_amount"] == "100"
        assert t.raw_data["original_currency"] == "TRY"

    async def test_declined_rows_are_skipped(self) -> None:
        descriptions = {t.description for t in await self._txns()}
        assert "DECLINED SHOP" not in descriptions

    async def test_raw_data_excludes_card_and_account_numbers(self) -> None:
        for t in await self._txns():
            assert t.raw_data["source"] == "bdc_kony_card"
            dumped = _json(t.raw_data)
            assert "0000001111111234" not in dumped
            assert "MC_CR_CRP_3316688606" not in dumped

    async def test_missing_bank_id_uses_hash(self) -> None:
        s = BDCKonyScraper(username="u", password="p")
        rows = {"Transaction": [{**_CARD_TXNS_JSON["Transaction"][0], "Id": "", "TranNumber": ""}]}
        page = _fake_page(
            [
                _ACTIVE_CARDS,
                {"status": 200, "text": _json(_CARDS_JSON)},
                {"status": 200, "text": _json(rows)},
            ]
        )
        _, txns = await s._fetch_cards(page, datetime.now(UTC), {})
        assert len(txns[0].external_id) == 32

    async def test_invalid_date_raises(self) -> None:
        s = BDCKonyScraper(username="u", password="p")
        rows = {
            "Transaction": [{**_CARD_TXNS_JSON["Transaction"][0], "txnDate": "", "TranTime": ""}]
        }
        page = _fake_page(
            [
                _ACTIVE_CARDS,
                {"status": 200, "text": _json(_CARDS_JSON)},
                {"status": 200, "text": _json(rows)},
            ]
        )
        with pytest.raises(ScraperParseError):
            await s._fetch_cards(page, datetime.now(UTC), {})

    async def test_card_api_failure_raises(self) -> None:
        s = BDCKonyScraper(username="u", password="p")
        page = _fake_page([_ACTIVE_CARDS, {"status": 500, "text": ""}])
        with pytest.raises(ScraperParseError):
            await s._fetch_cards(page, datetime.now(UTC), {})


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
    async def test_card_api_failure_does_not_report_partial_success(self) -> None:
        s = BDCKonyScraper(username="u", password="p")
        page = _fake_page(
            [
                {"status": 200, "text": _json(_ACCOUNTS_JSON)},
                _ACTIVE_CARDS,
                {"status": 500, "text": ""},
            ]
        )
        _install_mock_browser(s, page)
        with pytest.raises(ScraperParseError):
            await s.scrape()

    async def test_scrape_returns_account_and_card(self) -> None:
        s = BDCKonyScraper(username="u", password="p")
        page = _fake_page(
            [
                {"status": 200, "text": _json(_ACCOUNTS_JSON)},
                _ACTIVE_CARDS,
                {"status": 200, "text": _json(_CARDS_JSON)},
                {"status": 200, "text": _json(_CARD_TXNS_JSON)},
            ]
        )
        _install_mock_browser(s, page)
        result = await s.scrape()
        assert isinstance(result, ScraperResult)
        assert len(result.accounts) == 2
        types = {a.account_type for a in result.accounts}
        assert types == {"current", "credit_card"}
        assert len(result.transactions) == 3
        assert {t.raw_data["account_number_masked"] for t in result.transactions} == {"****1234"}

    async def test_scrape_raises_when_nothing_returned(self) -> None:
        s = BDCKonyScraper(username="u", password="p")
        page = _fake_page(
            [
                {"status": 200, "text": '{"Accounts": []}'},
                _ACTIVE_CARDS,
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


def _login_page(
    *,
    iframe: bool = True,
    dashboard: bool = True,
    reject: bool = False,
    typed_length: int = 1,
    frame_error: str = "",
):
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
    password_field = MagicMock()
    password_field.press_sequentially = AsyncMock(return_value=None)
    frame.locator = MagicMock(return_value=password_field)

    async def _frame_evaluate(script: str, *_args: Any) -> Any:
        # Password length check vs. visible login error text.
        return typed_length if "value.length" in script else frame_error

    frame.evaluate = AsyncMock(side_effect=_frame_evaluate)
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
        # Password is typed key by key (masked-input script), never fill()ed.
        frame = page.frames[0]
        frame.locator.return_value.press_sequentially.assert_awaited_once()
        assert frame.locator.return_value.press_sequentially.await_args.args[0] == "p"
        assert all(c.args[0] != "#passwordInput" for c in frame.fill.await_args_list)

    async def test_password_not_accepted_raises_parse_error(self) -> None:
        s = BDCKonyScraper(username="u", password="pass")
        s._safe_screenshot = AsyncMock(return_value=None)  # type: ignore[method-assign]
        page = _login_page(typed_length=1)
        with pytest.raises(ScraperParseError):
            await s._login_and_capture_auth(page)
        page.frames[0].click.assert_awaited_once()  # focus only; never submitted

    async def test_visible_iframe_error_raises_login_error(self) -> None:
        from app.scrapers.base import ScraperLoginError

        s = BDCKonyScraper(username="u", password="p")
        s._safe_screenshot = AsyncMock(return_value=None)  # type: ignore[method-assign]
        page = _login_page(
            dashboard=False, frame_error="invalid username or password. please try again."
        )
        with pytest.raises(ScraperLoginError):
            await s._login_and_capture_auth(page)

    async def test_no_iframe_reloads_then_raises_timeout(self) -> None:
        from app.scrapers.bdc_kony import _LOGIN_PAGE_ATTEMPTS

        s = BDCKonyScraper(username="u", password="p")
        s._safe_screenshot = AsyncMock(return_value=None)  # type: ignore[method-assign]
        page = _login_page(iframe=False)
        # A portal that never renders the form is not a credential rejection.
        with pytest.raises(ScraperTimeoutError):
            await s._login_and_capture_auth(page)
        assert page.goto.await_count == _LOGIN_PAGE_ATTEMPTS

    async def test_reload_recovers_when_first_load_stalls(self) -> None:
        s = BDCKonyScraper(username="u", password="p")
        s._safe_screenshot = AsyncMock(return_value=None)  # type: ignore[method-assign]
        page = _login_page()
        frame = page.frames[0]
        page.frames = []

        async def _goto(*_a: Any, **_k: Any) -> None:
            # First load never renders the login iframe; the reload does.
            if page.goto.await_count >= 2:
                page.frames = [frame]

        page.goto = AsyncMock(side_effect=_goto)
        await s._login_and_capture_auth(page)
        assert page.goto.await_count == 2
        frame.locator.return_value.press_sequentially.assert_awaited_once()

    async def test_dashboard_stall_raises_timeout(self) -> None:
        from app.scrapers.base import ScraperTimeoutError

        s = BDCKonyScraper(username="u", password="p")
        s._safe_screenshot = AsyncMock(return_value=None)  # type: ignore[method-assign]
        page = _login_page(dashboard=False)
        with pytest.raises(ScraperTimeoutError):
            await s._login_and_capture_auth(page)

    async def test_login_form_timeout_reloads_then_raises_timeout(self) -> None:
        from patchright._impl._errors import TimeoutError as _PT

        from app.scrapers.base import ScraperTimeoutError
        from app.scrapers.bdc_kony import _LOGIN_FORM_ATTEMPTS

        s = BDCKonyScraper(username="u", password="p")
        s._safe_screenshot = AsyncMock(return_value=None)  # type: ignore[method-assign]
        page = _login_page()
        page.frames[0].fill = AsyncMock(side_effect=_PT("timeout"))
        with pytest.raises(ScraperTimeoutError, match="username"):
            await s._login_and_capture_auth(page)
        assert page.goto.await_count == _LOGIN_FORM_ATTEMPTS
        # Never submitted: only the password field was clicked (focus).
        clicked = [c.args[0] for c in page.frames[0].click.await_args_list]
        assert "button.login-btn" not in clicked

    async def test_form_step_timeout_recovers_on_reload(self) -> None:
        from patchright._impl._errors import TimeoutError as _PT

        s = BDCKonyScraper(username="u", password="p")
        s._safe_screenshot = AsyncMock(return_value=None)  # type: ignore[method-assign]
        page = _login_page()
        frame = page.frames[0]
        frame.fill = AsyncMock(side_effect=[_PT("timeout"), None])
        await s._login_and_capture_auth(page)
        assert page.goto.await_count == 2
        clicked = [c.args[0] for c in frame.click.await_args_list]
        assert clicked.count("button.login-btn") == 1

    async def test_sign_in_click_timeout_uses_button_handler(self) -> None:
        from patchright._impl._errors import TimeoutError as _PT

        s = BDCKonyScraper(username="u", password="p")
        s._safe_screenshot = AsyncMock(return_value=None)  # type: ignore[method-assign]
        page = _login_page()
        frame = page.frames[0]

        async def _click(selector: str, **_kw: Any) -> None:
            if selector == "button.login-btn":
                raise _PT("timeout")

        frame.click = AsyncMock(side_effect=_click)
        frame.evaluate = AsyncMock(side_effect=[1, True])  # password length, button clicked
        await s._login_and_capture_auth(page)
        assert "b.click()" in frame.evaluate.await_args_list[1].args[0]
        assert page.goto.await_count == 1  # not resubmitted on a new page

    async def test_bad_credentials_raises_login_error(self) -> None:
        from app.scrapers.base import ScraperLoginError

        s = BDCKonyScraper(username="u", password="p")
        s._safe_screenshot = AsyncMock(return_value=None)  # type: ignore[method-assign]
        page = _login_page(dashboard=False, reject=True)
        with pytest.raises(ScraperLoginError):
            await s._login_and_capture_auth(page)


# ---------------------------------------------------------------------------
# Hosted-backend guard: BDC is EG-only + no patchright browser on Render.
# _launch_browser must fail fast with ScraperUnavailableError on the hosted
# backend BEFORE trying to launch a browser (which would crash or hang).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestHostedBackendGuard:
    async def test_app_env_production_raises_without_browser_dir(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """On Render (APP_ENV=production) the guard must fire even when the
        Playwright browsers dir is absent — the filesystem check is unreliable
        at runtime, so it must not be the sole signal."""
        import app.scrapers.bdc_kony as mod

        # Simulate Render env but a MISSING browsers dir (the failure mode that
        # let the guard fall through to a crashing/hanging browser launch).
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setattr(mod.os.path, "isdir", lambda _p: False)

        s = BDCKonyScraper(username="u", password="p")
        with pytest.raises(ScraperUnavailableError):
            await s._launch_browser()

    async def test_browser_dir_present_still_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Existing signal (Render browsers dir present) keeps working."""
        import app.scrapers.bdc_kony as mod

        monkeypatch.delenv("APP_ENV", raising=False)
        monkeypatch.setattr(mod.os.path, "isdir", lambda _p: True)

        s = BDCKonyScraper(username="u", password="p")
        with pytest.raises(ScraperUnavailableError):
            await s._launch_browser()

    async def test_direct_connection_setting_skips_required_proxy(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A production host inside Egypt may opt out of the mandatory proxy."""
        import app.scrapers.bdc_kony as mod

        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setattr(mod.os.path, "isdir", lambda _p: False)
        monkeypatch.setattr(mod.settings, "bdc_direct_connection", True)
        seen: list[bool] = []

        def fake_proxy(*, required: bool = False) -> None:
            seen.append(required)
            raise RuntimeError("stop before launching a browser")

        monkeypatch.setattr(mod, "get_bdc_proxy", fake_proxy)
        s = BDCKonyScraper(username="u", password="p")
        with pytest.raises(RuntimeError, match="stop before"):
            await s._launch_browser()
        assert seen == [False]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _json(obj: Any) -> str:
    import json

    return json.dumps(obj)
