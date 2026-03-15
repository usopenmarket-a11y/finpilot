"""Unit tests for M2 bank scrapers: base class, NBEScraper, and CIBScraper.

Coverage targets
----------------
- BankScraper._mask_account_number — various input shapes
- Exception hierarchy — bank_code attribute, subclass relationships
- NBE module helpers: _parse_nbe_date, _parse_amount, _make_external_id,
  _normalise_account_type, _normalise_currency, _resolve_txn_columns,
  _parse_transaction_row
- NBEScraper.scrape — happy path, ScraperLoginError on failure element,
  ScraperTimeoutError on Playwright timeout
- CIB module helpers: _parse_cib_date, _parse_amount, _make_external_id
- CIBScraper.scrape — happy path, ScraperLoginError on error element,
  ScraperTimeoutError on Playwright timeout

Mocking strategy
----------------
``async_playwright`` is patched at the import site in ``app.scrapers.base`` so
that NO real browser is ever launched.  All Playwright objects (Browser,
BrowserContext, Page, element handles) are AsyncMock / MagicMock instances.

HTML content used in integration-level scrape() tests is constructed as
minimal inline strings — no fixture files are required.  This keeps the tests
self-contained and avoids filesystem dependencies.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from app.models.db import BankAccount
from app.scrapers.base import (
    BankPortalUnreachableError,
    BankScraper,
    ScraperException,
    ScraperLoginError,
    ScraperOTPRequired,
    ScraperParseError,
    ScraperResult,
    ScraperTimeoutError,
)

# Import module-level helpers directly so we can unit-test them without
# instantiating the full scraper class.
from app.scrapers.nbe import (
    NBEScraper,
    _make_external_id as nbe_make_external_id,
    _normalise_account_type as nbe_normalise_account_type,
    _normalise_currency as nbe_normalise_currency,
    _parse_amount as nbe_parse_amount,
    _parse_nbe_date,
    _parse_transaction_row as nbe_parse_transaction_row,
    _resolve_txn_columns as nbe_resolve_txn_columns,
)
from app.scrapers.cib import (
    CIBScraper,
    _make_external_id as cib_make_external_id,
    _parse_cib_date,
    _parse_amount as cib_parse_amount,
)

# ---------------------------------------------------------------------------
# Shared sentinel values
# ---------------------------------------------------------------------------

_ZERO_UUID = UUID("00000000-0000-0000-0000-000000000000")
_NOW = datetime(2025, 3, 15, 12, 0, 0)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_bank_account(bank_name: str = "NBE") -> BankAccount:
    """Return a minimal BankAccount suitable for passing to row parsers."""
    return BankAccount(
        id=_ZERO_UUID,
        user_id=_ZERO_UUID,
        bank_name=bank_name,
        account_number_masked="****7890",
        account_type="current",
        currency="EGP",
        balance=Decimal("10000.00"),
        is_active=True,
        last_synced_at=_NOW,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _build_mock_playwright() -> tuple[MagicMock, MagicMock, AsyncMock, AsyncMock]:
    """Return (mock_playwright_cm, mock_pw, mock_browser, mock_page).

    Configures the full chain that _launch_browser traverses:
    async_playwright() -> .start() -> .chromium.launch() -> .new_context() ->
    .new_page()
    """
    mock_page = AsyncMock()
    mock_page.screenshot = AsyncMock(return_value=None)
    mock_page.query_selector = AsyncMock(return_value=None)
    mock_page.wait_for_selector = AsyncMock(return_value=None)
    mock_page.goto = AsyncMock(return_value=None)
    mock_page.click = AsyncMock(return_value=None)
    mock_page.keyboard = AsyncMock()
    mock_page.keyboard.type = AsyncMock(return_value=None)

    mock_context = AsyncMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)
    mock_context.add_init_script = AsyncMock(return_value=None)

    mock_browser = AsyncMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)
    mock_browser.close = AsyncMock(return_value=None)

    mock_chromium = AsyncMock()
    mock_chromium.launch = AsyncMock(return_value=mock_browser)

    mock_pw = MagicMock()
    mock_pw.chromium = mock_chromium
    mock_pw.stop = AsyncMock(return_value=None)

    # async_playwright() is used as an async context manager in some patterns
    # but _launch_browser calls .start() directly on the returned object.
    mock_playwright_cm = AsyncMock()
    mock_playwright_cm.start = AsyncMock(return_value=mock_pw)

    return mock_playwright_cm, mock_pw, mock_browser, mock_page


# ---------------------------------------------------------------------------
# Minimal HTML fixtures (inline strings)
# ---------------------------------------------------------------------------

# NBE dashboard HTML — includes an account-summary table.
_NBE_DASHBOARD_HTML = """
<html><body>
<table id="ContentPlaceHolder1_GridView_AccSummary">
  <tr><th>Account Number</th><th>Account Type</th><th>Currency</th><th>Balance</th></tr>
  <tr><td>1234567890</td><td>Current</td><td>EGP</td><td>15,250.75</td></tr>
</table>
</body></html>
"""

# NBE transaction history HTML — two rows: one debit, one credit.
_NBE_TRANSACTIONS_HTML = """
<html><body>
<table id="ContentPlaceHolder1_GridView_TransactionList">
  <tr>
    <th>Date</th><th>Value Date</th><th>Description</th>
    <th>Debit</th><th>Credit</th><th>Balance</th>
  </tr>
  <tr>
    <td>15/01/2025</td><td>15/01/2025</td><td>ATM Withdrawal</td>
    <td>500.00</td><td></td><td>14,750.75</td>
  </tr>
  <tr>
    <td>10/01/2025</td><td>10/01/2025</td><td>Salary Credit</td>
    <td></td><td>5,000.00</td><td>15,250.75</td>
  </tr>
</table>
</body></html>
"""

# NBE login error HTML — contains the .failureNotification element.
_NBE_LOGIN_ERROR_HTML = """
<html><body>
<span class="failureNotification">Your username or password is incorrect.</span>
</body></html>
"""

# CIB dashboard HTML — minimal account-summary card.
_CIB_DASHBOARD_HTML = """
<html><body>
<div class="account-summary">
  <span>1234567890</span>
  <span>EGP</span>
  <span>22,000.00</span>
</div>
</body></html>
"""

# CIB transaction history HTML.
_CIB_TRANSACTIONS_HTML = """
<html><body>
<table class="transaction-table">
  <tr>
    <th>Transaction Date</th><th>Value Date</th><th>Description</th>
    <th>Debit</th><th>Credit</th><th>Balance</th>
  </tr>
  <tr>
    <td>15-Jan-2025</td><td>15-Jan-2025</td><td>POS Purchase</td>
    <td>1,200.00</td><td></td><td>20,800.00</td>
  </tr>
  <tr>
    <td>05-Jan-2025</td><td>05-Jan-2025</td><td>Wire Transfer In</td>
    <td></td><td>3,000.00</td><td>22,000.00</td>
  </tr>
</table>
</body></html>
"""

# CIB login error HTML.
_CIB_LOGIN_ERROR_HTML = """
<html><body>
<div class="error-message">Invalid credentials. Please try again.</div>
</body></html>
"""


# ===========================================================================
# Section 1 — Base class tests
# ===========================================================================


class TestMaskAccountNumber:
    """BankScraper._mask_account_number — static method, no scraper needed."""

    def test_ten_digit_number_shows_last_four(self) -> None:
        assert BankScraper._mask_account_number("1234567890") == "****7890"

    def test_short_four_digit_number_shows_all(self) -> None:
        # Input has exactly 4 digits — tail is all 4, prefix is still ****
        assert BankScraper._mask_account_number("1234") == "****1234"

    def test_two_digit_number_appended_after_stars(self) -> None:
        # Fewer than 4 digits — all digits used as tail
        assert BankScraper._mask_account_number("12") == "****12"

    def test_number_with_hyphens_strips_hyphens(self) -> None:
        # Hyphens are stripped; only digits count
        assert BankScraper._mask_account_number("1234-5678-90") == "****7890"

    def test_number_with_spaces_strips_spaces(self) -> None:
        assert BankScraper._mask_account_number("1234 5678 9012") == "****9012"

    def test_sixteen_digit_number_shows_last_four(self) -> None:
        result = BankScraper._mask_account_number("1234567890123456")
        assert result == "****3456"

    def test_only_last_four_are_exposed(self) -> None:
        # Ensure the star prefix is always exactly four stars
        result = BankScraper._mask_account_number("9999999999")
        assert result.startswith("****")
        assert len(result) == 8  # 4 stars + 4 trailing digits


# ===========================================================================
# Section 2 — Exception hierarchy tests
# ===========================================================================


class TestExceptionHierarchy:
    """All custom exceptions inherit correctly and carry required attributes."""

    def test_scraper_login_error_is_scraper_exception(self) -> None:
        exc = ScraperLoginError("bad creds", bank_code="NBE")
        assert isinstance(exc, ScraperException)

    def test_scraper_timeout_error_is_scraper_exception(self) -> None:
        exc = ScraperTimeoutError("timed out", bank_code="CIB")
        assert isinstance(exc, ScraperException)

    def test_scraper_parse_error_is_scraper_exception(self) -> None:
        exc = ScraperParseError("bad html", bank_code="NBE")
        assert isinstance(exc, ScraperException)

    def test_scraper_otp_required_is_scraper_exception(self) -> None:
        exc = ScraperOTPRequired("otp needed", bank_code="NBE", session_token="abc123")
        assert isinstance(exc, ScraperException)

    def test_bank_portal_unreachable_is_scraper_exception(self) -> None:
        exc = BankPortalUnreachableError("network error", bank_code="BDC")
        assert isinstance(exc, ScraperException)

    def test_login_error_bank_code_attribute(self) -> None:
        exc = ScraperLoginError("bad creds", bank_code="NBE")
        assert exc.bank_code == "NBE"

    def test_timeout_error_bank_code_attribute(self) -> None:
        exc = ScraperTimeoutError("timed out", bank_code="CIB")
        assert exc.bank_code == "CIB"

    def test_scraper_exception_has_timestamp(self) -> None:
        import time
        before = time.time()
        exc = ScraperLoginError("msg", bank_code="NBE")
        after = time.time()
        assert before <= exc.timestamp <= after

    def test_otp_required_carries_session_token(self) -> None:
        exc = ScraperOTPRequired("otp needed", bank_code="NBE", session_token="token-xyz")
        assert exc.session_token == "token-xyz"
        assert exc.bank_code == "NBE"

    def test_all_exceptions_are_base_exception_subclasses(self) -> None:
        for cls in (
            ScraperLoginError,
            ScraperTimeoutError,
            ScraperParseError,
            ScraperOTPRequired,
            BankPortalUnreachableError,
        ):
            assert issubclass(cls, ScraperException)
            assert issubclass(cls, Exception)


# ===========================================================================
# Section 3 — NBE module-level helper tests
# ===========================================================================


class TestParseNbeDate:
    """_parse_nbe_date — handles all documented date formats."""

    def test_dd_slash_mm_slash_yyyy_primary_format(self) -> None:
        result = _parse_nbe_date("15/01/2025")
        assert result == date(2025, 1, 15)

    def test_single_digit_day_and_month(self) -> None:
        result = _parse_nbe_date("5/1/2025")
        assert result == date(2025, 1, 5)

    def test_dd_dash_mm_dash_yyyy_format(self) -> None:
        result = _parse_nbe_date("15-01-2025")
        assert result == date(2025, 1, 15)

    def test_leading_zero_day_and_month(self) -> None:
        result = _parse_nbe_date("03/07/2024")
        assert result == date(2024, 7, 3)

    def test_returns_none_for_unrecognised_format(self) -> None:
        result = _parse_nbe_date("not-a-date")
        assert result is None

    def test_returns_none_for_empty_string(self) -> None:
        result = _parse_nbe_date("")
        assert result is None

    def test_strips_surrounding_whitespace(self) -> None:
        result = _parse_nbe_date("  15/01/2025  ")
        assert result == date(2025, 1, 15)

    def test_end_of_year_date(self) -> None:
        result = _parse_nbe_date("31/12/2024")
        assert result == date(2024, 12, 31)


class TestNbeParseAmount:
    """nbe._parse_amount — handles comma separators and edge cases."""

    def test_plain_integer_string(self) -> None:
        assert nbe_parse_amount("500") == Decimal("500")

    def test_decimal_string(self) -> None:
        assert nbe_parse_amount("1234.56") == Decimal("1234.56")

    def test_comma_thousands_separator(self) -> None:
        assert nbe_parse_amount("1,234.56") == Decimal("1234.56")

    def test_large_amount_with_multiple_commas(self) -> None:
        assert nbe_parse_amount("1,234,567.89") == Decimal("1234567.89")

    def test_empty_string_returns_none(self) -> None:
        assert nbe_parse_amount("") is None

    def test_dash_returns_none(self) -> None:
        assert nbe_parse_amount("-") is None

    def test_na_returns_none(self) -> None:
        assert nbe_parse_amount("N/A") is None

    def test_em_dash_returns_none(self) -> None:
        assert nbe_parse_amount("—") is None

    def test_whitespace_only_returns_none(self) -> None:
        assert nbe_parse_amount("   ") is None

    def test_non_numeric_returns_none(self) -> None:
        assert nbe_parse_amount("abc") is None

    def test_strips_surrounding_whitespace(self) -> None:
        assert nbe_parse_amount("  500.00  ") == Decimal("500.00")


class TestNbeMakeExternalId:
    """nbe._make_external_id — stable, deterministic deduplication key."""

    def test_returns_24_hex_characters(self) -> None:
        result = nbe_make_external_id(date(2025, 1, 15), "ATM Withdrawal", Decimal("500.00"))
        assert len(result) == 24
        assert all(c in "0123456789abcdef" for c in result)

    def test_deterministic_for_same_inputs(self) -> None:
        d = date(2025, 1, 15)
        desc = "Salary Credit"
        amount = Decimal("5000.00")
        assert nbe_make_external_id(d, desc, amount) == nbe_make_external_id(d, desc, amount)

    def test_different_date_produces_different_id(self) -> None:
        desc = "Payment"
        amount = Decimal("100.00")
        id_a = nbe_make_external_id(date(2025, 1, 1), desc, amount)
        id_b = nbe_make_external_id(date(2025, 1, 2), desc, amount)
        assert id_a != id_b

    def test_different_description_produces_different_id(self) -> None:
        d = date(2025, 1, 15)
        amount = Decimal("100.00")
        id_a = nbe_make_external_id(d, "Transfer A", amount)
        id_b = nbe_make_external_id(d, "Transfer B", amount)
        assert id_a != id_b

    def test_different_amount_produces_different_id(self) -> None:
        d = date(2025, 1, 15)
        desc = "Purchase"
        id_a = nbe_make_external_id(d, desc, Decimal("100.00"))
        id_b = nbe_make_external_id(d, desc, Decimal("200.00"))
        assert id_a != id_b

    def test_sha256_canonical_format(self) -> None:
        """Verify the hash is computed from the documented canonical string."""
        d = date(2025, 1, 15)
        desc = "ATM"
        amount = Decimal("500.00")
        canonical = f"{d.isoformat()}|{desc[:40].strip()}|{amount}"
        expected = hashlib.sha256(canonical.encode()).hexdigest()[:24]
        assert nbe_make_external_id(d, desc, amount) == expected

    def test_long_description_truncated_to_40_chars(self) -> None:
        d = date(2025, 6, 1)
        amount = Decimal("1.00")
        long_desc = "A" * 80
        result = nbe_make_external_id(d, long_desc, amount)
        # Same result whether we pass 80 or 40 chars because both are truncated
        canonical = f"{d.isoformat()}|{'A' * 40}|{amount}"
        expected = hashlib.sha256(canonical.encode()).hexdigest()[:24]
        assert result == expected


class TestNbeNormaliseHelpers:
    """nbe._normalise_account_type and _normalise_currency."""

    def test_savings_keyword(self) -> None:
        assert nbe_normalise_account_type("savings account") == "savings"

    def test_arabic_savings_keyword(self) -> None:
        assert nbe_normalise_account_type("توفير") == "savings"

    def test_credit_keyword(self) -> None:
        assert nbe_normalise_account_type("credit card") == "credit"

    def test_loan_keyword(self) -> None:
        assert nbe_normalise_account_type("personal loan") == "loan"

    def test_unknown_defaults_to_current(self) -> None:
        assert nbe_normalise_account_type("cheque account") == "current"

    def test_currency_egp_passes_through(self) -> None:
        assert nbe_normalise_currency("EGP") == "EGP"

    def test_currency_usd_passes_through(self) -> None:
        assert nbe_normalise_currency("USD") == "USD"

    def test_unknown_currency_defaults_to_egp(self) -> None:
        assert nbe_normalise_currency("XYZ") == "EGP"

    def test_currency_lowercased_input_normalised(self) -> None:
        assert nbe_normalise_currency("usd") == "USD"


class TestNbeResolveTxnColumns:
    """nbe._resolve_txn_columns — header-to-index mapping."""

    def test_standard_nbe_headers(self) -> None:
        headers = ["date", "value date", "description", "debit", "credit", "balance"]
        col = nbe_resolve_txn_columns(headers)
        assert col["date"] == 0
        assert col["value_date"] == 1
        assert col["description"] == 2
        assert col["debit"] == 3
        assert col["credit"] == 4
        assert col["balance"] == 5

    def test_positional_defaults_used_when_headers_unrecognised(self) -> None:
        # If no header matches, positional defaults kick in.
        headers = ["col_a", "col_b", "col_c", "col_d", "col_e", "col_f"]
        col = nbe_resolve_txn_columns(headers)
        # Defaults: date=0, value_date=1, description=2, debit=3, credit=4, balance=5
        assert col["date"] == 0
        assert col["description"] == 2

    def test_partial_headers_resolved_where_possible(self) -> None:
        headers = ["transaction date", "description", "debit", "credit"]
        col = nbe_resolve_txn_columns(headers)
        assert col["date"] == 0
        assert col["description"] == 1
        assert col["debit"] == 2
        assert col["credit"] == 3


class TestNbeParseTransactionRow:
    """nbe._parse_transaction_row — debit/credit direction and amount parsing."""

    def _default_col(self) -> dict[str, int]:
        return {"date": 0, "value_date": 1, "description": 2, "debit": 3, "credit": 4, "balance": 5}

    def test_debit_row_parsed_correctly(self) -> None:
        account = _make_bank_account("NBE")
        cells = ["15/01/2025", "15/01/2025", "ATM Withdrawal", "500.00", "", "14,750.75"]
        txn = nbe_parse_transaction_row(cells, self._default_col(), account, _NOW)
        assert txn is not None
        assert txn.transaction_type == "debit"
        assert txn.amount == Decimal("500.00")
        assert txn.description == "ATM Withdrawal"
        assert txn.transaction_date == date(2025, 1, 15)

    def test_credit_row_parsed_correctly(self) -> None:
        account = _make_bank_account("NBE")
        cells = ["10/01/2025", "10/01/2025", "Salary Credit", "", "5,000.00", "15,250.75"]
        txn = nbe_parse_transaction_row(cells, self._default_col(), account, _NOW)
        assert txn is not None
        assert txn.transaction_type == "credit"
        assert txn.amount == Decimal("5000.00")

    def test_comma_separated_amount_parsed(self) -> None:
        account = _make_bank_account("NBE")
        cells = ["15/01/2025", "15/01/2025", "Purchase", "1,234.56", "", ""]
        txn = nbe_parse_transaction_row(cells, self._default_col(), account, _NOW)
        assert txn is not None
        assert txn.amount == Decimal("1234.56")

    def test_row_with_no_amount_returns_none(self) -> None:
        account = _make_bank_account("NBE")
        cells = ["15/01/2025", "15/01/2025", "Empty Row", "", "", ""]
        txn = nbe_parse_transaction_row(cells, self._default_col(), account, _NOW)
        assert txn is None

    def test_header_repeat_row_returns_none(self) -> None:
        account = _make_bank_account("NBE")
        cells = ["date", "value date", "description", "debit", "credit", "balance"]
        txn = nbe_parse_transaction_row(cells, self._default_col(), account, _NOW)
        assert txn is None

    def test_unparseable_date_returns_none(self) -> None:
        account = _make_bank_account("NBE")
        cells = ["not-a-date", "15/01/2025", "Purchase", "100.00", "", ""]
        txn = nbe_parse_transaction_row(cells, self._default_col(), account, _NOW)
        assert txn is None

    def test_external_id_is_deterministic(self) -> None:
        account = _make_bank_account("NBE")
        cells = ["15/01/2025", "15/01/2025", "ATM Withdrawal", "500.00", "", "14,750.75"]
        txn1 = nbe_parse_transaction_row(cells, self._default_col(), account, _NOW)
        txn2 = nbe_parse_transaction_row(cells, self._default_col(), account, _NOW)
        assert txn1 is not None
        assert txn2 is not None
        assert txn1.external_id == txn2.external_id

    def test_external_id_differs_for_different_rows(self) -> None:
        account = _make_bank_account("NBE")
        cells_a = ["15/01/2025", "", "Withdrawal A", "500.00", "", ""]
        cells_b = ["16/01/2025", "", "Withdrawal B", "600.00", "", ""]
        txn_a = nbe_parse_transaction_row(cells_a, self._default_col(), account, _NOW)
        txn_b = nbe_parse_transaction_row(cells_b, self._default_col(), account, _NOW)
        assert txn_a is not None
        assert txn_b is not None
        assert txn_a.external_id != txn_b.external_id

    def test_balance_after_parsed(self) -> None:
        account = _make_bank_account("NBE")
        cells = ["15/01/2025", "15/01/2025", "Purchase", "500.00", "", "14,500.00"]
        txn = nbe_parse_transaction_row(cells, self._default_col(), account, _NOW)
        assert txn is not None
        assert txn.balance_after == Decimal("14500.00")

    def test_sentinel_uuids_are_zero(self) -> None:
        account = _make_bank_account("NBE")
        cells = ["15/01/2025", "", "Transfer", "100.00", "", ""]
        txn = nbe_parse_transaction_row(cells, self._default_col(), account, _NOW)
        assert txn is not None
        assert txn.id == _ZERO_UUID
        assert txn.user_id == _ZERO_UUID
        assert txn.account_id == _ZERO_UUID

    def test_raw_data_contains_source_nbe(self) -> None:
        account = _make_bank_account("NBE")
        cells = ["15/01/2025", "", "Transfer", "100.00", "", ""]
        txn = nbe_parse_transaction_row(cells, self._default_col(), account, _NOW)
        assert txn is not None
        assert txn.raw_data.get("source") == "nbe"


# ===========================================================================
# Section 4 — CIB module-level helper tests
# ===========================================================================


class TestParseCibDate:
    """_parse_cib_date — handles all documented date formats."""

    def test_dd_mmm_yyyy_primary_format(self) -> None:
        assert _parse_cib_date("15-Jan-2025") == date(2025, 1, 15)

    def test_dd_mmm_yyyy_december(self) -> None:
        assert _parse_cib_date("31-Dec-2024") == date(2024, 12, 31)

    def test_dd_mmm_yyyy_case_insensitive(self) -> None:
        assert _parse_cib_date("05-jan-2025") == date(2025, 1, 5)

    def test_dd_slash_mm_slash_yyyy(self) -> None:
        assert _parse_cib_date("15/01/2025") == date(2025, 1, 15)

    def test_iso_format_fallback(self) -> None:
        assert _parse_cib_date("2025-01-15") == date(2025, 1, 15)

    def test_unrecognised_format_returns_none(self) -> None:
        assert _parse_cib_date("not-a-date") is None

    def test_empty_string_returns_none(self) -> None:
        assert _parse_cib_date("") is None

    def test_strips_whitespace(self) -> None:
        assert _parse_cib_date("  15-Jan-2025  ") == date(2025, 1, 15)

    def test_single_digit_day(self) -> None:
        assert _parse_cib_date("5-Mar-2025") == date(2025, 3, 5)


class TestCibParseAmount:
    """cib._parse_amount — mirrors NBE helper, tested independently."""

    def test_comma_thousands_separator(self) -> None:
        assert cib_parse_amount("10,250.00") == Decimal("10250.00")

    def test_plain_decimal(self) -> None:
        assert cib_parse_amount("1200.50") == Decimal("1200.50")

    def test_dash_returns_none(self) -> None:
        assert cib_parse_amount("-") is None

    def test_empty_returns_none(self) -> None:
        assert cib_parse_amount("") is None


class TestCibMakeExternalId:
    """cib._make_external_id — same contract as NBE version."""

    def test_returns_24_hex_characters(self) -> None:
        result = cib_make_external_id(date(2025, 1, 15), "POS Purchase", Decimal("1200.00"))
        assert len(result) == 24

    def test_deterministic(self) -> None:
        d = date(2025, 1, 15)
        desc = "Wire Transfer"
        amount = Decimal("3000.00")
        assert cib_make_external_id(d, desc, amount) == cib_make_external_id(d, desc, amount)

    def test_different_inputs_differ(self) -> None:
        d = date(2025, 1, 15)
        id_a = cib_make_external_id(d, "POS A", Decimal("100.00"))
        id_b = cib_make_external_id(d, "POS B", Decimal("100.00"))
        assert id_a != id_b


# ===========================================================================
# Section 5 — NBEScraper.scrape() integration tests (Playwright fully mocked)
# ===========================================================================


class TestNbeScraperScrape:
    """NBEScraper.scrape() — end-to-end flow with all I/O mocked."""

    @pytest.fixture
    def nbe_scraper(self) -> NBEScraper:
        return NBEScraper(username="test_user", password="test_password_123")

    async def test_happy_path_returns_scraper_result(self, nbe_scraper: NBEScraper) -> None:
        """scrape() returns ScraperResult with bank_name == 'NBE' and transactions."""
        mock_pw_cm, mock_pw, mock_browser, mock_page = _build_mock_playwright()

        mock_page.content = AsyncMock(
            side_effect=[
                _NBE_DASHBOARD_HTML,     # raw_html["dashboard"]
                _NBE_DASHBOARD_HTML,     # _extract_account -> page.content()
                _NBE_TRANSACTIONS_HTML,  # raw_html["transactions"]
                _NBE_TRANSACTIONS_HTML,  # _extract_transactions -> page.content()
            ]
        )

        # query_selector must return None for error-element selectors so
        # _wait_for_dashboard does NOT raise ScraperLoginError, but return a
        # real element for the login button and transaction link selectors.
        mock_element = AsyncMock()
        mock_element.click = AsyncMock(return_value=None)
        mock_element.inner_text = AsyncMock(return_value="")

        _ERROR_SELECTORS = {".failureNotification", "xpath=//*[contains(@class,'failureNotification')]"}

        async def _query_selector_nbe(selector: str) -> Any:
            return None if selector in _ERROR_SELECTORS else mock_element

        mock_page.query_selector = _query_selector_nbe  # type: ignore[assignment]

        with patch("app.scrapers.base.async_playwright", return_value=mock_pw_cm):
            result = await nbe_scraper.scrape()

        assert isinstance(result, ScraperResult)
        assert result.account.bank_name == "NBE"
        assert result.account.balance == Decimal("15250.75")
        assert len(result.transactions) == 2
        assert result.transactions[0].transaction_type == "debit"
        assert result.transactions[1].transaction_type == "credit"

    async def test_login_error_raises_scraper_login_error(self, nbe_scraper: NBEScraper) -> None:
        """scrape() raises ScraperLoginError when failureNotification is detected."""
        mock_pw_cm, mock_pw, mock_browser, mock_page = _build_mock_playwright()

        mock_page.content = AsyncMock(return_value=_NBE_LOGIN_ERROR_HTML)

        # Simulate error element found by query_selector
        mock_error_el = AsyncMock()
        mock_error_el.inner_text = AsyncMock(
            return_value="Your username or password is incorrect."
        )

        # First query_selector call (for _SEL_LOGIN_ERROR_CSS) returns the error element
        mock_page.query_selector = AsyncMock(return_value=mock_error_el)

        with patch("app.scrapers.base.async_playwright", return_value=mock_pw_cm):
            with pytest.raises(ScraperLoginError) as exc_info:
                await nbe_scraper.scrape()

        assert exc_info.value.bank_code == "NBE"

    async def test_playwright_timeout_raises_scraper_timeout_error(
        self, nbe_scraper: NBEScraper
    ) -> None:
        """scrape() wraps PlaywrightTimeoutError in ScraperTimeoutError."""
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError

        mock_pw_cm, mock_pw, mock_browser, mock_page = _build_mock_playwright()

        # No error element on login check
        mock_page.query_selector = AsyncMock(return_value=None)

        # wait_for_selector raises PlaywrightTimeoutError (both CSS and XPath attempts)
        mock_page.wait_for_selector = AsyncMock(
            side_effect=PlaywrightTimeoutError("Timeout exceeded")
        )

        with patch("app.scrapers.base.async_playwright", return_value=mock_pw_cm):
            with pytest.raises(ScraperTimeoutError) as exc_info:
                await nbe_scraper.scrape()

        assert exc_info.value.bank_code == "NBE"

    async def test_scrape_result_contains_raw_html_keys(self, nbe_scraper: NBEScraper) -> None:
        """ScraperResult.raw_html contains 'dashboard' and 'transactions' keys."""
        mock_pw_cm, mock_pw, mock_browser, mock_page = _build_mock_playwright()

        mock_page.content = AsyncMock(
            side_effect=[
                _NBE_DASHBOARD_HTML,
                _NBE_DASHBOARD_HTML,
                _NBE_TRANSACTIONS_HTML,
                _NBE_TRANSACTIONS_HTML,
            ]
        )
        mock_element = AsyncMock()
        mock_element.click = AsyncMock(return_value=None)
        mock_element.inner_text = AsyncMock(return_value="")

        _ERROR_SELECTORS = {".failureNotification", "xpath=//*[contains(@class,'failureNotification')]"}

        async def _query_selector_nbe(selector: str) -> Any:
            return None if selector in _ERROR_SELECTORS else mock_element

        mock_page.query_selector = _query_selector_nbe  # type: ignore[assignment]

        with patch("app.scrapers.base.async_playwright", return_value=mock_pw_cm):
            result = await nbe_scraper.scrape()

        assert "dashboard" in result.raw_html
        assert "transactions" in result.raw_html

    async def test_browser_is_always_closed(self, nbe_scraper: NBEScraper) -> None:
        """_close_browser is called even if scrape() raises an exception."""
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError

        mock_pw_cm, mock_pw, mock_browser, mock_page = _build_mock_playwright()
        mock_page.query_selector = AsyncMock(return_value=None)
        mock_page.wait_for_selector = AsyncMock(
            side_effect=PlaywrightTimeoutError("timeout")
        )

        with patch("app.scrapers.base.async_playwright", return_value=mock_pw_cm):
            with pytest.raises(ScraperTimeoutError):
                await nbe_scraper.scrape()

        # browser.close must have been awaited
        mock_browser.close.assert_awaited_once()

    async def test_account_number_is_masked_in_result(self, nbe_scraper: NBEScraper) -> None:
        """account_number_masked in result follows ****XXXX format."""
        mock_pw_cm, mock_pw, mock_browser, mock_page = _build_mock_playwright()

        mock_page.content = AsyncMock(
            side_effect=[
                _NBE_DASHBOARD_HTML,
                _NBE_DASHBOARD_HTML,
                _NBE_TRANSACTIONS_HTML,
                _NBE_TRANSACTIONS_HTML,
            ]
        )
        mock_element = AsyncMock()
        mock_element.click = AsyncMock(return_value=None)
        mock_element.inner_text = AsyncMock(return_value="")

        _ERROR_SELECTORS = {".failureNotification", "xpath=//*[contains(@class,'failureNotification')]"}

        async def _query_selector_nbe(selector: str) -> Any:
            return None if selector in _ERROR_SELECTORS else mock_element

        mock_page.query_selector = _query_selector_nbe  # type: ignore[assignment]

        with patch("app.scrapers.base.async_playwright", return_value=mock_pw_cm):
            result = await nbe_scraper.scrape()

        assert result.account.account_number_masked.startswith("****")


# ===========================================================================
# Section 6 — CIBScraper.scrape() integration tests (Playwright fully mocked)
# ===========================================================================


class TestCibScraperScrape:
    """CIBScraper.scrape() — end-to-end flow with all I/O mocked."""

    @pytest.fixture
    def cib_scraper(self) -> CIBScraper:
        return CIBScraper(username="cib_user", password="test_password_123")

    async def test_happy_path_returns_scraper_result(self, cib_scraper: CIBScraper) -> None:
        """scrape() returns ScraperResult with bank_name == 'CIB' and transactions."""
        mock_pw_cm, mock_pw, mock_browser, mock_page = _build_mock_playwright()

        mock_page.content = AsyncMock(
            side_effect=[
                _CIB_DASHBOARD_HTML,    # raw_html["dashboard"]
                _CIB_DASHBOARD_HTML,    # _extract_account -> page.content()
                _CIB_TRANSACTIONS_HTML, # raw_html["transactions"]
                _CIB_TRANSACTIONS_HTML, # _extract_transactions -> page.content()
            ]
        )

        mock_element = AsyncMock()
        mock_element.click = AsyncMock(return_value=None)
        mock_element.inner_text = AsyncMock(return_value="")

        # CIB error selectors — must return None so _wait_for_dashboard proceeds
        _CIB_ERROR_CSS = ".error-message, .alert-danger, [class*='loginError'], [class*='error-msg']"
        _CIB_ERROR_XPATH = (
            "xpath=//*[contains(@class,'error-message') or contains(@class,'alert-danger') "
            "or contains(@class,'loginError')]"
        )
        _cib_error_selectors = {_CIB_ERROR_CSS, _CIB_ERROR_XPATH}

        async def _query_selector_cib(selector: str) -> Any:
            return None if selector in _cib_error_selectors else mock_element

        mock_page.query_selector = _query_selector_cib  # type: ignore[assignment]

        with patch("app.scrapers.base.async_playwright", return_value=mock_pw_cm):
            result = await cib_scraper.scrape()

        assert isinstance(result, ScraperResult)
        assert result.account.bank_name == "CIB"
        assert len(result.transactions) == 2
        assert result.transactions[0].transaction_type == "debit"
        assert result.transactions[1].transaction_type == "credit"

    async def test_login_error_raises_scraper_login_error(
        self, cib_scraper: CIBScraper
    ) -> None:
        """scrape() raises ScraperLoginError when error-message element is found."""
        mock_pw_cm, mock_pw, mock_browser, mock_page = _build_mock_playwright()

        mock_page.content = AsyncMock(return_value=_CIB_LOGIN_ERROR_HTML)

        mock_error_el = AsyncMock()
        mock_error_el.inner_text = AsyncMock(
            return_value="Invalid credentials. Please try again."
        )
        mock_page.query_selector = AsyncMock(return_value=mock_error_el)

        with patch("app.scrapers.base.async_playwright", return_value=mock_pw_cm):
            with pytest.raises(ScraperLoginError) as exc_info:
                await cib_scraper.scrape()

        assert exc_info.value.bank_code == "CIB"

    async def test_playwright_timeout_raises_scraper_timeout_error(
        self, cib_scraper: CIBScraper
    ) -> None:
        """scrape() wraps PlaywrightTimeoutError in ScraperTimeoutError."""
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError

        mock_pw_cm, mock_pw, mock_browser, mock_page = _build_mock_playwright()

        mock_page.query_selector = AsyncMock(return_value=None)
        mock_page.wait_for_selector = AsyncMock(
            side_effect=PlaywrightTimeoutError("Timeout exceeded")
        )

        with patch("app.scrapers.base.async_playwright", return_value=mock_pw_cm):
            with pytest.raises(ScraperTimeoutError) as exc_info:
                await cib_scraper.scrape()

        assert exc_info.value.bank_code == "CIB"

    async def test_browser_closed_on_exception(self, cib_scraper: CIBScraper) -> None:
        """_close_browser is called in the finally block even on failure."""
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError

        mock_pw_cm, mock_pw, mock_browser, mock_page = _build_mock_playwright()
        mock_page.query_selector = AsyncMock(return_value=None)
        mock_page.wait_for_selector = AsyncMock(
            side_effect=PlaywrightTimeoutError("timeout")
        )

        with patch("app.scrapers.base.async_playwright", return_value=mock_pw_cm):
            with pytest.raises(ScraperTimeoutError):
                await cib_scraper.scrape()

        mock_browser.close.assert_awaited_once()

    async def test_cib_transactions_use_cib_date_format(
        self, cib_scraper: CIBScraper
    ) -> None:
        """Transactions parsed from CIB HTML use DD-MMM-YYYY dates correctly."""
        mock_pw_cm, mock_pw, mock_browser, mock_page = _build_mock_playwright()

        mock_page.content = AsyncMock(
            side_effect=[
                _CIB_DASHBOARD_HTML,
                _CIB_DASHBOARD_HTML,
                _CIB_TRANSACTIONS_HTML,
                _CIB_TRANSACTIONS_HTML,
            ]
        )
        mock_element = AsyncMock()
        mock_element.click = AsyncMock(return_value=None)
        mock_element.inner_text = AsyncMock(return_value="")

        _CIB_ERROR_CSS = ".error-message, .alert-danger, [class*='loginError'], [class*='error-msg']"
        _CIB_ERROR_XPATH = (
            "xpath=//*[contains(@class,'error-message') or contains(@class,'alert-danger') "
            "or contains(@class,'loginError')]"
        )
        _cib_error_selectors = {_CIB_ERROR_CSS, _CIB_ERROR_XPATH}

        async def _query_selector_cib(selector: str) -> Any:
            return None if selector in _cib_error_selectors else mock_element

        mock_page.query_selector = _query_selector_cib  # type: ignore[assignment]

        with patch("app.scrapers.base.async_playwright", return_value=mock_pw_cm):
            result = await cib_scraper.scrape()

        assert result.transactions[0].transaction_date == date(2025, 1, 15)
        assert result.transactions[1].transaction_date == date(2025, 1, 5)


# ===========================================================================
# Section 7 — ScraperResult dataclass tests
# ===========================================================================


class TestScraperResult:
    """ScraperResult — field defaults and construction."""

    def test_default_transactions_empty_list(self) -> None:
        account = _make_bank_account()
        result = ScraperResult(account=account)
        assert result.transactions == []

    def test_default_raw_html_empty_dict(self) -> None:
        account = _make_bank_account()
        result = ScraperResult(account=account)
        assert result.raw_html == {}

    def test_transactions_and_raw_html_stored(self) -> None:
        account = _make_bank_account()
        result = ScraperResult(
            account=account,
            transactions=[],
            raw_html={"dashboard": "<html/>"},
        )
        assert result.raw_html["dashboard"] == "<html/>"
