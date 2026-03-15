"""Unit tests for BDCScraper and UBScraper.

Coverage targets
----------------
- BankScraper._mask_account_number (inherited by both; exercised via BDCScraper)
- BDC module-level helpers: _parse_bdc_date, _parse_amount, _make_external_id,
  _normalise_account_type, _normalise_currency, _resolve_txn_columns,
  _parse_transaction_row
- BDCScraper.scrape() — happy path, ScraperLoginError on error element,
  ScraperTimeoutError on Playwright timeout
- UB module-level helpers: _parse_ub_date, _parse_amount, _make_external_id,
  _resolve_txn_columns (incl. single-Amount column detection)
- UBScraper.scrape() — happy path, ScraperLoginError on error element,
  ScraperTimeoutError on Playwright timeout
- Exception hierarchy: BDCScraper and UBScraper are subclasses of BankScraper;
  all exception classes carry bank_code

Mocking strategy
----------------
``async_playwright`` is patched at the import site in ``app.scrapers.base`` so
that NO real browser is ever launched.  The ``_build_mock_playwright()`` helper
from the existing NBE/CIB test file is replicated here to keep this module
self-contained.

``page.query_selector`` is replaced with a discriminating async function that
returns ``None`` for error-selector strings and a mock element otherwise — the
same pattern established for NBE/CIB (see project memory).

HTML fixtures are minimal inline strings — no filesystem dependencies.
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
    BankScraper,
    ScraperException,
    ScraperLoginError,
    ScraperParseError,
    ScraperResult,
    ScraperTimeoutError,
)
from app.scrapers.bdc import (
    BDCScraper,
    _make_external_id as bdc_make_external_id,
    _normalise_account_type as bdc_normalise_account_type,
    _normalise_currency as bdc_normalise_currency,
    _parse_amount as bdc_parse_amount,
    _parse_bdc_date,
    _parse_transaction_row as bdc_parse_transaction_row,
    _resolve_txn_columns as bdc_resolve_txn_columns,
)
from app.scrapers.ub import (
    UBScraper,
    _make_external_id as ub_make_external_id,
    _parse_amount as ub_parse_amount,
    _parse_ub_date,
    _parse_transaction_row as ub_parse_transaction_row,
    _resolve_txn_columns as ub_resolve_txn_columns,
)

# ---------------------------------------------------------------------------
# Shared sentinel values
# ---------------------------------------------------------------------------

_ZERO_UUID = UUID("00000000-0000-0000-0000-000000000000")
_NOW = datetime(2025, 3, 15, 12, 0, 0)


# ---------------------------------------------------------------------------
# Fixture / helper factories
# ---------------------------------------------------------------------------


def _make_bank_account(bank_name: str = "BDC") -> BankAccount:
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

    Replicates the helper from test_scrapers.py so this module is fully
    self-contained.  Configures the full chain that _launch_browser traverses:
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

    mock_playwright_cm = AsyncMock()
    mock_playwright_cm.start = AsyncMock(return_value=mock_pw)

    return mock_playwright_cm, mock_pw, mock_browser, mock_page


# ---------------------------------------------------------------------------
# Minimal inline HTML fixtures
# ---------------------------------------------------------------------------

# BDC dashboard HTML — includes an account-summary table with an ID matching
# the AccSummary pattern used in _extract_account.
_BDC_DASHBOARD_HTML = """
<html><body>
<table id="ContentPlaceHolder1_GridView_AccSummary">
  <tr><th>Account Number</th><th>Account Type</th><th>Currency</th><th>Balance</th></tr>
  <tr><td>9876543210</td><td>Current</td><td>EGP</td><td>20,500.00</td></tr>
</table>
</body></html>
"""

# BDC transaction history HTML — two rows: one debit, one credit.
_BDC_TRANSACTIONS_HTML = """
<html><body>
<table id="ContentPlaceHolder1_GridView_TransactionList">
  <tr>
    <th>Date</th><th>Value Date</th><th>Description</th>
    <th>Debit</th><th>Credit</th><th>Balance</th>
  </tr>
  <tr>
    <td>20/01/2025</td><td>20/01/2025</td><td>ATM Withdrawal BDC</td>
    <td>1,000.00</td><td></td><td>19,500.00</td>
  </tr>
  <tr>
    <td>15/01/2025</td><td>15/01/2025</td><td>Salary Deposit BDC</td>
    <td></td><td>8,000.00</td><td>20,500.00</td>
  </tr>
</table>
</body></html>
"""

# BDC login error HTML — the .failureNotification element triggers the login
# error detection branch in _wait_for_dashboard.
_BDC_LOGIN_ERROR_HTML = """
<html><body>
<span class="failureNotification">Invalid username or password.</span>
</body></html>
"""

# UB dashboard HTML — uses a WebForms-style AccSummary table (same as BDC).
_UB_DASHBOARD_HTML = """
<html><body>
<table id="ContentPlaceHolder1_GridView_AccSummary">
  <tr><th>Account Number</th><th>Account Type</th><th>Currency</th><th>Balance</th></tr>
  <tr><td>1122334455</td><td>Savings</td><td>EGP</td><td>33,750.50</td></tr>
</table>
</body></html>
"""

# UB transaction history HTML — standard split Debit/Credit column layout.
_UB_TRANSACTIONS_HTML = """
<html><body>
<table id="ContentPlaceHolder1_GridView_TransactionList">
  <tr>
    <th>Transaction Date</th><th>Value Date</th><th>Description</th>
    <th>Debit</th><th>Credit</th><th>Balance</th>
  </tr>
  <tr>
    <td>10-Jan-2025</td><td>10-Jan-2025</td><td>POS Purchase UB</td>
    <td>750.00</td><td></td><td>33,000.50</td>
  </tr>
  <tr>
    <td>05-Jan-2025</td><td>05-Jan-2025</td><td>Transfer In UB</td>
    <td></td><td>5,000.00</td><td>33,750.50</td>
  </tr>
</table>
</body></html>
"""

# UB transaction history HTML — compact single-Amount column with Dr/Cr suffix.
_UB_TRANSACTIONS_DRCR_HTML = """
<html><body>
<table id="ContentPlaceHolder1_GridView_TransactionList">
  <tr>
    <th>Date</th><th>Description</th><th>Amount</th><th>Balance</th>
  </tr>
  <tr>
    <td>12-Feb-2025</td><td>Card Payment</td><td>500.00 Dr</td><td>32,500.50</td>
  </tr>
  <tr>
    <td>08-Feb-2025</td><td>Cash Deposit</td><td>2,000.00 Cr</td><td>33,000.50</td>
  </tr>
</table>
</body></html>
"""

# UB login error HTML.
_UB_LOGIN_ERROR_HTML = """
<html><body>
<div class="failureNotification">Access denied. Please check your credentials.</div>
</body></html>
"""

# ---------------------------------------------------------------------------
# BDC error selectors (must return None in happy-path tests)
# ---------------------------------------------------------------------------
# These are the exact strings that _wait_for_dashboard passes to query_selector.
_BDC_ERROR_CSS = (
    ".failureNotification, .error-message, .alert-danger, "
    "[class*='loginError'], [class*='FailureText']"
)
_BDC_ERROR_XPATH = (
    "xpath=//*[contains(@class,'failureNotification') or contains(@class,'FailureText') "
    "or contains(@class,'error-message') or contains(@class,'alert-danger') "
    "or contains(@class,'loginError')]"
)
_BDC_ERROR_SELECTORS: frozenset[str] = frozenset({_BDC_ERROR_CSS, _BDC_ERROR_XPATH})

# ---------------------------------------------------------------------------
# UB error selectors (must return None in happy-path tests)
# ---------------------------------------------------------------------------
_UB_ERROR_CSS = (
    ".failureNotification, .error-message, .alert-danger, "
    "[class*='loginError'], [class*='FailureText'], [class*='error-msg']"
)
_UB_ERROR_XPATH = (
    "xpath=//*[contains(@class,'failureNotification') or contains(@class,'FailureText') "
    "or contains(@class,'error-message') or contains(@class,'alert-danger') "
    "or contains(@class,'loginError') or contains(@class,'error-msg')]"
)
_UB_ERROR_SELECTORS: frozenset[str] = frozenset({_UB_ERROR_CSS, _UB_ERROR_XPATH})


# ===========================================================================
# Section 1 — BankScraper._mask_account_number via BDCScraper
# ===========================================================================


class TestMaskAccountNumberViaBdc:
    """_mask_account_number is inherited from BankScraper; exercised here via BDCScraper.

    The existing test_scrapers.py already tests this thoroughly on the base
    class directly.  These tests verify the static method behaves identically
    when accessed through BDCScraper (confirming correct inheritance) and add
    a BDC-specific shaped account number.
    """

    def test_ten_digit_account_shows_last_four(self) -> None:
        assert BDCScraper._mask_account_number("9876543210") == "****3210"

    def test_sixteen_digit_account_shows_last_four(self) -> None:
        assert BDCScraper._mask_account_number("1234567890123456") == "****3456"

    def test_account_with_hyphens_strips_non_digits(self) -> None:
        # BDC portals sometimes emit account numbers formatted as groups
        assert BDCScraper._mask_account_number("1234-5678-9012") == "****9012"

    def test_short_account_number_uses_all_digits_as_tail(self) -> None:
        assert BDCScraper._mask_account_number("42") == "****42"

    def test_result_always_starts_with_four_stars(self) -> None:
        result = BDCScraper._mask_account_number("0000000001")
        assert result.startswith("****")

    def test_ub_inherits_same_implementation(self) -> None:
        # UBScraper must also inherit the static method unchanged
        assert UBScraper._mask_account_number("9876543210") == "****3210"
        assert UBScraper._mask_account_number("9876543210") == BDCScraper._mask_account_number(
            "9876543210"
        )


# ===========================================================================
# Section 2 — Exception hierarchy: BDC/UB subclass relationships
# ===========================================================================


class TestBdcUbExceptionHierarchy:
    """BDCScraper and UBScraper are BankScraper subclasses; exceptions carry bank_code."""

    def test_bdc_scraper_is_bank_scraper_subclass(self) -> None:
        assert issubclass(BDCScraper, BankScraper)

    def test_ub_scraper_is_bank_scraper_subclass(self) -> None:
        assert issubclass(UBScraper, BankScraper)

    def test_bdc_scraper_bank_name(self) -> None:
        scraper = BDCScraper(username="u", password="p")
        assert scraper.bank_name == "BDC"

    def test_ub_scraper_bank_name(self) -> None:
        scraper = UBScraper(username="u", password="p")
        assert scraper.bank_name == "UB"

    def test_scraper_login_error_carries_bdc_bank_code(self) -> None:
        exc = ScraperLoginError("bad creds", bank_code="BDC")
        assert exc.bank_code == "BDC"
        assert isinstance(exc, ScraperException)

    def test_scraper_timeout_error_carries_bdc_bank_code(self) -> None:
        exc = ScraperTimeoutError("timeout", bank_code="BDC")
        assert exc.bank_code == "BDC"
        assert isinstance(exc, ScraperException)

    def test_scraper_parse_error_carries_bdc_bank_code(self) -> None:
        exc = ScraperParseError("bad html", bank_code="BDC")
        assert exc.bank_code == "BDC"
        assert isinstance(exc, ScraperException)

    def test_scraper_login_error_carries_ub_bank_code(self) -> None:
        exc = ScraperLoginError("bad creds", bank_code="UB")
        assert exc.bank_code == "UB"

    def test_scraper_timeout_error_carries_ub_bank_code(self) -> None:
        exc = ScraperTimeoutError("timeout", bank_code="UB")
        assert exc.bank_code == "UB"

    def test_bdc_scraper_repr_hides_credentials(self) -> None:
        scraper = BDCScraper(username="secret_user", password="secret_pass")
        assert "secret_user" not in repr(scraper)
        assert "secret_pass" not in repr(scraper)
        assert "***" in repr(scraper)

    def test_ub_scraper_repr_hides_credentials(self) -> None:
        scraper = UBScraper(username="secret_user", password="secret_pass")
        assert "secret_user" not in repr(scraper)
        assert "secret_pass" not in repr(scraper)
        assert "***" in repr(scraper)


# ===========================================================================
# Section 3 — BDC module-level helper tests
# ===========================================================================


class TestParseBdcDate:
    """_parse_bdc_date — handles DD/MM/YYYY, DD-MM-YYYY, and edge cases."""

    def test_dd_slash_mm_slash_yyyy_primary_format(self) -> None:
        assert _parse_bdc_date("20/01/2025") == date(2025, 1, 20)

    def test_dd_dash_mm_dash_yyyy_secondary_format(self) -> None:
        assert _parse_bdc_date("20-01-2025") == date(2025, 1, 20)

    def test_single_digit_day_and_month(self) -> None:
        assert _parse_bdc_date("5/3/2025") == date(2025, 3, 5)

    def test_leading_zero_day_and_month(self) -> None:
        assert _parse_bdc_date("03/07/2024") == date(2024, 7, 3)

    def test_end_of_year_date(self) -> None:
        assert _parse_bdc_date("31/12/2024") == date(2024, 12, 31)

    def test_february_non_leap_year(self) -> None:
        assert _parse_bdc_date("28/02/2025") == date(2025, 2, 28)

    def test_february_leap_year(self) -> None:
        assert _parse_bdc_date("29/02/2024") == date(2024, 2, 29)

    def test_strips_surrounding_whitespace(self) -> None:
        assert _parse_bdc_date("  20/01/2025  ") == date(2025, 1, 20)

    def test_unrecognised_format_returns_none(self) -> None:
        assert _parse_bdc_date("not-a-date") is None

    def test_empty_string_returns_none(self) -> None:
        assert _parse_bdc_date("") is None

    def test_dd_mmm_yyyy_format_not_supported_returns_none(self) -> None:
        # BDC does not emit the Mon-abbreviation format (that is UB's format)
        assert _parse_bdc_date("20-Jan-2025") is None

    def test_mixed_separator_handled_by_permissive_split(self) -> None:
        # The fallback re.split path handles mixed separators
        result = _parse_bdc_date("5/3/2025")
        assert result == date(2025, 3, 5)

    def test_invalid_calendar_date_returns_none(self) -> None:
        # 30th of February is not a valid date
        assert _parse_bdc_date("30/02/2025") is None


class TestBdcParseAmount:
    """bdc._parse_amount — comma separators, currency symbols, Arabic text, negatives."""

    def test_plain_integer_string(self) -> None:
        assert bdc_parse_amount("1000") == Decimal("1000")

    def test_decimal_string(self) -> None:
        assert bdc_parse_amount("1234.56") == Decimal("1234.56")

    def test_comma_thousands_separator(self) -> None:
        assert bdc_parse_amount("1,234.56") == Decimal("1234.56")

    def test_large_amount_with_multiple_commas(self) -> None:
        assert bdc_parse_amount("1,234,567.89") == Decimal("1234567.89")

    def test_egp_prefix_stripped(self) -> None:
        assert bdc_parse_amount("EGP 1,234.56") == Decimal("1234.56")

    def test_egp_suffix_stripped(self) -> None:
        assert bdc_parse_amount("1,234.56 EGP") == Decimal("1234.56")

    def test_arabic_currency_symbol_stripped(self) -> None:
        # Arabic letters are stripped by the [A-Za-z\u0600-\u06FF] regex
        assert bdc_parse_amount("1234.56 جنيه") == Decimal("1234.56")

    def test_negative_amount_preserved(self) -> None:
        # A bare minus sign should survive (it is not in the Arabic/Latin range)
        assert bdc_parse_amount("-500.00") == Decimal("-500.00")

    def test_empty_string_returns_none(self) -> None:
        assert bdc_parse_amount("") is None

    def test_dash_returns_none(self) -> None:
        assert bdc_parse_amount("-") is None

    def test_em_dash_returns_none(self) -> None:
        assert bdc_parse_amount("—") is None

    def test_na_returns_none(self) -> None:
        assert bdc_parse_amount("N/A") is None

    def test_whitespace_only_returns_none(self) -> None:
        assert bdc_parse_amount("   ") is None

    def test_non_numeric_string_returns_none(self) -> None:
        assert bdc_parse_amount("abc") is None

    def test_strips_surrounding_whitespace(self) -> None:
        assert bdc_parse_amount("  500.00  ") == Decimal("500.00")

    def test_zero_amount(self) -> None:
        assert bdc_parse_amount("0.00") == Decimal("0.00")


class TestBdcMakeExternalId:
    """bdc._make_external_id — stable SHA-256-based deduplication key."""

    def test_returns_24_hex_characters(self) -> None:
        result = bdc_make_external_id(date(2025, 1, 20), "ATM Withdrawal BDC", Decimal("1000.00"))
        assert len(result) == 24
        assert all(c in "0123456789abcdef" for c in result)

    def test_deterministic_for_same_inputs(self) -> None:
        d = date(2025, 1, 20)
        desc = "Salary Deposit BDC"
        amount = Decimal("8000.00")
        assert bdc_make_external_id(d, desc, amount) == bdc_make_external_id(d, desc, amount)

    def test_different_date_produces_different_id(self) -> None:
        desc = "Payment"
        amount = Decimal("100.00")
        id_a = bdc_make_external_id(date(2025, 1, 1), desc, amount)
        id_b = bdc_make_external_id(date(2025, 1, 2), desc, amount)
        assert id_a != id_b

    def test_different_description_produces_different_id(self) -> None:
        d = date(2025, 1, 20)
        amount = Decimal("500.00")
        id_a = bdc_make_external_id(d, "Transfer A", amount)
        id_b = bdc_make_external_id(d, "Transfer B", amount)
        assert id_a != id_b

    def test_different_amount_produces_different_id(self) -> None:
        d = date(2025, 1, 20)
        desc = "Purchase"
        id_a = bdc_make_external_id(d, desc, Decimal("100.00"))
        id_b = bdc_make_external_id(d, desc, Decimal("200.00"))
        assert id_a != id_b

    def test_sha256_canonical_format(self) -> None:
        """Verify the hash is computed from the documented canonical string."""
        d = date(2025, 1, 20)
        desc = "ATM"
        amount = Decimal("1000.00")
        canonical = f"{d.isoformat()}|{desc[:40].strip()}|{amount}"
        expected = hashlib.sha256(canonical.encode()).hexdigest()[:24]
        assert bdc_make_external_id(d, desc, amount) == expected

    def test_long_description_truncated_to_40_chars(self) -> None:
        d = date(2025, 6, 1)
        amount = Decimal("1.00")
        long_desc = "B" * 80
        result = bdc_make_external_id(d, long_desc, amount)
        canonical = f"{d.isoformat()}|{'B' * 40}|{amount}"
        expected = hashlib.sha256(canonical.encode()).hexdigest()[:24]
        assert result == expected


class TestBdcResolveTxnColumns:
    """bdc._resolve_txn_columns — header-to-index mapping."""

    def test_standard_bdc_headers(self) -> None:
        headers = ["date", "value date", "description", "debit", "credit", "balance"]
        col = bdc_resolve_txn_columns(headers)
        assert col["date"] == 0
        assert col["value_date"] == 1
        assert col["description"] == 2
        assert col["debit"] == 3
        assert col["credit"] == 4
        assert col["balance"] == 5

    def test_transaction_date_header_matches_date_column(self) -> None:
        headers = ["transaction date", "value date", "description", "debit", "credit", "balance"]
        col = bdc_resolve_txn_columns(headers)
        assert col["date"] == 0

    def test_posting_header_matches_date_column(self) -> None:
        headers = ["posting", "value date", "description", "debit", "credit", "balance"]
        col = bdc_resolve_txn_columns(headers)
        assert col["date"] == 0

    def test_arabic_date_header_matches(self) -> None:
        headers = ["تاريخ", "قيمة", "بيان", "مدين", "دائن", "رصيد"]
        col = bdc_resolve_txn_columns(headers)
        assert col["date"] == 0
        assert col["description"] == 2
        assert col["debit"] == 3
        assert col["credit"] == 4
        assert col["balance"] == 5

    def test_positional_defaults_used_when_headers_unrecognised(self) -> None:
        headers = ["col_a", "col_b", "col_c", "col_d", "col_e", "col_f"]
        col = bdc_resolve_txn_columns(headers)
        assert col["date"] == 0
        assert col["description"] == 2

    def test_partial_headers_resolved_where_possible(self) -> None:
        headers = ["transaction date", "description", "debit", "credit"]
        col = bdc_resolve_txn_columns(headers)
        assert col["date"] == 0
        assert col["description"] == 1
        assert col["debit"] == 2
        assert col["credit"] == 3

    def test_withdraw_header_maps_to_debit(self) -> None:
        headers = ["date", "value date", "description", "withdraw", "deposit", "balance"]
        col = bdc_resolve_txn_columns(headers)
        assert col["debit"] == 3
        assert col["credit"] == 4


class TestBdcParseTransactionRow:
    """bdc._parse_transaction_row — debit/credit direction and amount parsing."""

    def _default_col(self) -> dict[str, int]:
        return {
            "date": 0,
            "value_date": 1,
            "description": 2,
            "debit": 3,
            "credit": 4,
            "balance": 5,
        }

    def test_debit_row_parsed_correctly(self) -> None:
        account = _make_bank_account("BDC")
        cells = ["20/01/2025", "20/01/2025", "ATM Withdrawal BDC", "1,000.00", "", "19,500.00"]
        txn = bdc_parse_transaction_row(cells, self._default_col(), account, _NOW)
        assert txn is not None
        assert txn.transaction_type == "debit"
        assert txn.amount == Decimal("1000.00")
        assert txn.description == "ATM Withdrawal BDC"
        assert txn.transaction_date == date(2025, 1, 20)

    def test_credit_row_parsed_correctly(self) -> None:
        account = _make_bank_account("BDC")
        cells = ["15/01/2025", "15/01/2025", "Salary Deposit BDC", "", "8,000.00", "20,500.00"]
        txn = bdc_parse_transaction_row(cells, self._default_col(), account, _NOW)
        assert txn is not None
        assert txn.transaction_type == "credit"
        assert txn.amount == Decimal("8000.00")

    def test_balance_after_parsed_correctly(self) -> None:
        account = _make_bank_account("BDC")
        cells = ["20/01/2025", "20/01/2025", "Purchase", "500.00", "", "19,000.00"]
        txn = bdc_parse_transaction_row(cells, self._default_col(), account, _NOW)
        assert txn is not None
        assert txn.balance_after == Decimal("19000.00")

    def test_row_with_no_amount_returns_none(self) -> None:
        account = _make_bank_account("BDC")
        cells = ["20/01/2025", "20/01/2025", "Empty Row", "", "", ""]
        txn = bdc_parse_transaction_row(cells, self._default_col(), account, _NOW)
        assert txn is None

    def test_header_repeat_row_returns_none(self) -> None:
        account = _make_bank_account("BDC")
        cells = ["date", "value date", "description", "debit", "credit", "balance"]
        txn = bdc_parse_transaction_row(cells, self._default_col(), account, _NOW)
        assert txn is None

    def test_unparseable_date_returns_none(self) -> None:
        account = _make_bank_account("BDC")
        cells = ["not-a-date", "20/01/2025", "Purchase", "100.00", "", ""]
        txn = bdc_parse_transaction_row(cells, self._default_col(), account, _NOW)
        assert txn is None

    def test_arabic_date_sentinel_returns_none(self) -> None:
        account = _make_bank_account("BDC")
        cells = ["تاريخ", "20/01/2025", "Purchase", "100.00", "", ""]
        txn = bdc_parse_transaction_row(cells, self._default_col(), account, _NOW)
        assert txn is None

    def test_external_id_is_deterministic(self) -> None:
        account = _make_bank_account("BDC")
        cells = ["20/01/2025", "20/01/2025", "ATM Withdrawal BDC", "1,000.00", "", "19,500.00"]
        txn1 = bdc_parse_transaction_row(cells, self._default_col(), account, _NOW)
        txn2 = bdc_parse_transaction_row(cells, self._default_col(), account, _NOW)
        assert txn1 is not None
        assert txn2 is not None
        assert txn1.external_id == txn2.external_id

    def test_external_id_differs_for_different_rows(self) -> None:
        account = _make_bank_account("BDC")
        cells_a = ["20/01/2025", "", "Withdrawal A", "500.00", "", ""]
        cells_b = ["21/01/2025", "", "Withdrawal B", "600.00", "", ""]
        txn_a = bdc_parse_transaction_row(cells_a, self._default_col(), account, _NOW)
        txn_b = bdc_parse_transaction_row(cells_b, self._default_col(), account, _NOW)
        assert txn_a is not None
        assert txn_b is not None
        assert txn_a.external_id != txn_b.external_id

    def test_sentinel_uuids_are_zero(self) -> None:
        account = _make_bank_account("BDC")
        cells = ["20/01/2025", "", "Transfer", "100.00", "", ""]
        txn = bdc_parse_transaction_row(cells, self._default_col(), account, _NOW)
        assert txn is not None
        assert txn.id == _ZERO_UUID
        assert txn.user_id == _ZERO_UUID
        assert txn.account_id == _ZERO_UUID

    def test_raw_data_contains_source_bdc(self) -> None:
        account = _make_bank_account("BDC")
        cells = ["20/01/2025", "", "Transfer", "100.00", "", ""]
        txn = bdc_parse_transaction_row(cells, self._default_col(), account, _NOW)
        assert txn is not None
        assert txn.raw_data.get("source") == "bdc"

    def test_currency_inherited_from_account(self) -> None:
        account = _make_bank_account("BDC")
        cells = ["20/01/2025", "", "Transfer", "100.00", "", ""]
        txn = bdc_parse_transaction_row(cells, self._default_col(), account, _NOW)
        assert txn is not None
        assert txn.currency == "EGP"

    def test_dash_date_returns_none(self) -> None:
        account = _make_bank_account("BDC")
        cells = ["-", "20/01/2025", "Transfer", "100.00", "", ""]
        txn = bdc_parse_transaction_row(cells, self._default_col(), account, _NOW)
        assert txn is None


# ===========================================================================
# Section 4 — UB module-level helper tests
# ===========================================================================


class TestParseUbDate:
    """_parse_ub_date — handles DD-MMM-YYYY, DD/MM/YYYY, DD-MM-YYYY, YYYY-MM-DD."""

    def test_dd_mmm_yyyy_primary_format(self) -> None:
        assert _parse_ub_date("15-Jan-2025") == date(2025, 1, 15)

    def test_dd_mmm_yyyy_december(self) -> None:
        assert _parse_ub_date("31-Dec-2024") == date(2024, 12, 31)

    def test_dd_mmm_yyyy_case_insensitive(self) -> None:
        assert _parse_ub_date("05-jan-2025") == date(2025, 1, 5)

    def test_dd_mmm_yyyy_uppercase(self) -> None:
        assert _parse_ub_date("10-FEB-2025") == date(2025, 2, 10)

    def test_dd_mmm_yyyy_all_months(self) -> None:
        months = [
            ("Jan", 1), ("Feb", 2), ("Mar", 3), ("Apr", 4),
            ("May", 5), ("Jun", 6), ("Jul", 7), ("Aug", 8),
            ("Sep", 9), ("Oct", 10), ("Nov", 11), ("Dec", 12),
        ]
        for abbr, month_num in months:
            result = _parse_ub_date(f"15-{abbr}-2025")
            assert result == date(2025, month_num, 15), f"Failed for month {abbr}"

    def test_dd_slash_mm_slash_yyyy(self) -> None:
        assert _parse_ub_date("15/01/2025") == date(2025, 1, 15)

    def test_dd_dash_mm_dash_yyyy(self) -> None:
        assert _parse_ub_date("15-01-2025") == date(2025, 1, 15)

    def test_single_digit_day(self) -> None:
        assert _parse_ub_date("5-Mar-2025") == date(2025, 3, 5)

    def test_single_digit_day_and_month_slash(self) -> None:
        assert _parse_ub_date("5/3/2025") == date(2025, 3, 5)

    def test_iso_format_yyyy_mm_dd(self) -> None:
        assert _parse_ub_date("2025-01-15") == date(2025, 1, 15)

    def test_strips_surrounding_whitespace(self) -> None:
        assert _parse_ub_date("  15-Jan-2025  ") == date(2025, 1, 15)

    def test_unrecognised_format_returns_none(self) -> None:
        assert _parse_ub_date("not-a-date") is None

    def test_empty_string_returns_none(self) -> None:
        assert _parse_ub_date("") is None

    def test_invalid_month_abbreviation_returns_none(self) -> None:
        # "Xxx" is not a recognised month abbreviation
        assert _parse_ub_date("15-Xxx-2025") is None

    def test_invalid_calendar_date_returns_none(self) -> None:
        # February 30 is not a valid date
        assert _parse_ub_date("30-Feb-2025") is None

    def test_end_of_year(self) -> None:
        assert _parse_ub_date("31/12/2024") == date(2024, 12, 31)


class TestUbParseAmount:
    """ub._parse_amount — comma separators, Dr/Cr suffixes, currency symbols."""

    def test_plain_decimal(self) -> None:
        assert ub_parse_amount("1234.56") == Decimal("1234.56")

    def test_comma_thousands_separator(self) -> None:
        assert ub_parse_amount("1,234.56") == Decimal("1234.56")

    def test_large_amount_with_multiple_commas(self) -> None:
        assert ub_parse_amount("1,234,567.89") == Decimal("1234567.89")

    def test_dr_suffix_stripped_positive_result(self) -> None:
        # UB uses Dr suffix for debit direction; _parse_amount strips it and
        # returns a positive value — the caller interprets direction.
        assert ub_parse_amount("500.00 Dr") == Decimal("500.00")

    def test_cr_suffix_stripped_positive_result(self) -> None:
        assert ub_parse_amount("2,000.00 Cr") == Decimal("2000.00")

    def test_dr_dot_suffix_stripped(self) -> None:
        assert ub_parse_amount("750.00 Dr.") == Decimal("750.00")

    def test_cr_dot_suffix_stripped(self) -> None:
        assert ub_parse_amount("1,500.00 Cr.") == Decimal("1500.00")

    def test_dr_suffix_case_insensitive(self) -> None:
        assert ub_parse_amount("300.00 dr") == Decimal("300.00")

    def test_egp_prefix_stripped(self) -> None:
        assert ub_parse_amount("EGP 1,234.56") == Decimal("1234.56")

    def test_arabic_currency_symbol_stripped(self) -> None:
        assert ub_parse_amount("1234.56 جنيه") == Decimal("1234.56")

    def test_empty_string_returns_none(self) -> None:
        assert ub_parse_amount("") is None

    def test_dash_returns_none(self) -> None:
        assert ub_parse_amount("-") is None

    def test_em_dash_returns_none(self) -> None:
        assert ub_parse_amount("—") is None

    def test_na_returns_none(self) -> None:
        assert ub_parse_amount("N/A") is None

    def test_whitespace_only_returns_none(self) -> None:
        assert ub_parse_amount("   ") is None

    def test_non_numeric_returns_none(self) -> None:
        assert ub_parse_amount("abc") is None

    def test_strips_surrounding_whitespace(self) -> None:
        assert ub_parse_amount("  500.00  ") == Decimal("500.00")

    def test_zero_amount(self) -> None:
        assert ub_parse_amount("0.00") == Decimal("0.00")


class TestUbMakeExternalId:
    """ub._make_external_id — same contract as BDC/NBE/CIB versions."""

    def test_returns_24_hex_characters(self) -> None:
        result = ub_make_external_id(date(2025, 1, 10), "POS Purchase UB", Decimal("750.00"))
        assert len(result) == 24
        assert all(c in "0123456789abcdef" for c in result)

    def test_deterministic_for_same_inputs(self) -> None:
        d = date(2025, 1, 10)
        desc = "Transfer In UB"
        amount = Decimal("5000.00")
        assert ub_make_external_id(d, desc, amount) == ub_make_external_id(d, desc, amount)

    def test_different_inputs_differ(self) -> None:
        d = date(2025, 1, 10)
        id_a = ub_make_external_id(d, "POS A", Decimal("100.00"))
        id_b = ub_make_external_id(d, "POS B", Decimal("100.00"))
        assert id_a != id_b

    def test_sha256_canonical_format(self) -> None:
        d = date(2025, 1, 10)
        desc = "POS"
        amount = Decimal("750.00")
        canonical = f"{d.isoformat()}|{desc[:40].strip()}|{amount}"
        expected = hashlib.sha256(canonical.encode()).hexdigest()[:24]
        assert ub_make_external_id(d, desc, amount) == expected


class TestUbResolveTxnColumns:
    """ub._resolve_txn_columns — includes single-Amount column detection."""

    def test_standard_split_layout(self) -> None:
        headers = ["transaction date", "value date", "description", "debit", "credit", "balance"]
        col = ub_resolve_txn_columns(headers)
        assert col["date"] == 0
        assert col["value_date"] == 1
        assert col["description"] == 2
        assert col["debit"] == 3
        assert col["credit"] == 4
        assert col["balance"] == 5
        assert col["amount"] == -1  # not present in split layout

    def test_compact_amount_column_detected(self) -> None:
        headers = ["date", "description", "amount", "balance"]
        col = ub_resolve_txn_columns(headers)
        assert col["date"] == 0
        assert col["description"] == 1
        assert col["amount"] == 2
        assert col["balance"] == 3

    def test_arabic_amount_header(self) -> None:
        headers = ["تاريخ", "بيان", "مبلغ", "رصيد"]
        col = ub_resolve_txn_columns(headers)
        assert col["date"] == 0
        assert col["description"] == 1
        assert col["amount"] == 2
        assert col["balance"] == 3

    def test_positional_defaults_used_when_headers_unrecognised(self) -> None:
        headers = ["col_a", "col_b", "col_c", "col_d", "col_e", "col_f"]
        col = ub_resolve_txn_columns(headers)
        assert col["date"] == 0
        assert col["description"] == 2

    def test_all_keys_present_in_result(self) -> None:
        headers = ["date", "value date", "description", "debit", "credit", "balance"]
        col = ub_resolve_txn_columns(headers)
        for key in ("date", "value_date", "description", "debit", "credit", "balance", "amount"):
            assert key in col


class TestUbParseTransactionRow:
    """ub._parse_transaction_row — split Debit/Credit and Dr/Cr single-Amount layouts."""

    def _default_col(self) -> dict[str, int]:
        return {
            "date": 0,
            "value_date": 1,
            "description": 2,
            "debit": 3,
            "credit": 4,
            "balance": 5,
            "amount": -1,
        }

    def _drcr_col(self) -> dict[str, int]:
        """Column map for compact single-Amount layout."""
        return {
            "date": 0,
            "value_date": -1,
            "description": 1,
            "debit": -1,
            "credit": -1,
            "balance": 3,
            "amount": 2,
        }

    def test_split_layout_debit_row(self) -> None:
        account = _make_bank_account("UB")
        cells = ["10-Jan-2025", "10-Jan-2025", "POS Purchase UB", "750.00", "", "33,000.50"]
        txn = ub_parse_transaction_row(cells, self._default_col(), account, _NOW)
        assert txn is not None
        assert txn.transaction_type == "debit"
        assert txn.amount == Decimal("750.00")
        assert txn.transaction_date == date(2025, 1, 10)

    def test_split_layout_credit_row(self) -> None:
        account = _make_bank_account("UB")
        cells = ["05-Jan-2025", "05-Jan-2025", "Transfer In UB", "", "5,000.00", "33,750.50"]
        txn = ub_parse_transaction_row(cells, self._default_col(), account, _NOW)
        assert txn is not None
        assert txn.transaction_type == "credit"
        assert txn.amount == Decimal("5000.00")

    def test_drcr_layout_dr_suffix_is_debit(self) -> None:
        account = _make_bank_account("UB")
        cells = ["12-Feb-2025", "Card Payment", "500.00 Dr", "32,500.50"]
        txn = ub_parse_transaction_row(cells, self._drcr_col(), account, _NOW)
        assert txn is not None
        assert txn.transaction_type == "debit"
        assert txn.amount == Decimal("500.00")

    def test_drcr_layout_cr_suffix_is_credit(self) -> None:
        account = _make_bank_account("UB")
        cells = ["08-Feb-2025", "Cash Deposit", "2,000.00 Cr", "33,000.50"]
        txn = ub_parse_transaction_row(cells, self._drcr_col(), account, _NOW)
        assert txn is not None
        assert txn.transaction_type == "credit"
        assert txn.amount == Decimal("2000.00")

    def test_drcr_layout_no_suffix_defaults_to_debit(self) -> None:
        account = _make_bank_account("UB")
        cells = ["12-Feb-2025", "Unknown Direction", "300.00", "32,700.50"]
        txn = ub_parse_transaction_row(cells, self._drcr_col(), account, _NOW)
        assert txn is not None
        assert txn.transaction_type == "debit"

    def test_row_with_no_amount_returns_none(self) -> None:
        account = _make_bank_account("UB")
        cells = ["10-Jan-2025", "10-Jan-2025", "Empty Row", "", "", ""]
        txn = ub_parse_transaction_row(cells, self._default_col(), account, _NOW)
        assert txn is None

    def test_header_repeat_row_returns_none(self) -> None:
        account = _make_bank_account("UB")
        cells = ["date", "value date", "description", "debit", "credit", "balance"]
        txn = ub_parse_transaction_row(cells, self._default_col(), account, _NOW)
        assert txn is None

    def test_unparseable_date_returns_none(self) -> None:
        account = _make_bank_account("UB")
        cells = ["not-a-date", "10-Jan-2025", "Purchase", "100.00", "", ""]
        txn = ub_parse_transaction_row(cells, self._default_col(), account, _NOW)
        assert txn is None

    def test_external_id_is_deterministic(self) -> None:
        account = _make_bank_account("UB")
        cells = ["10-Jan-2025", "10-Jan-2025", "POS Purchase UB", "750.00", "", "33,000.50"]
        txn1 = ub_parse_transaction_row(cells, self._default_col(), account, _NOW)
        txn2 = ub_parse_transaction_row(cells, self._default_col(), account, _NOW)
        assert txn1 is not None
        assert txn2 is not None
        assert txn1.external_id == txn2.external_id

    def test_raw_data_contains_source_ub(self) -> None:
        account = _make_bank_account("UB")
        cells = ["10-Jan-2025", "", "Transfer", "100.00", "", ""]
        txn = ub_parse_transaction_row(cells, self._default_col(), account, _NOW)
        assert txn is not None
        assert txn.raw_data.get("source") == "ub"

    def test_sentinel_uuids_are_zero(self) -> None:
        account = _make_bank_account("UB")
        cells = ["10-Jan-2025", "", "Transfer", "100.00", "", ""]
        txn = ub_parse_transaction_row(cells, self._default_col(), account, _NOW)
        assert txn is not None
        assert txn.id == _ZERO_UUID
        assert txn.user_id == _ZERO_UUID
        assert txn.account_id == _ZERO_UUID

    def test_iso_date_format_parsed(self) -> None:
        account = _make_bank_account("UB")
        cells = ["2025-01-10", "", "ISO Date Transfer", "100.00", "", ""]
        txn = ub_parse_transaction_row(cells, self._default_col(), account, _NOW)
        assert txn is not None
        assert txn.transaction_date == date(2025, 1, 10)


# ===========================================================================
# Section 5 — BDCScraper.scrape() integration tests (Playwright fully mocked)
# ===========================================================================


class TestBdcScraperScrape:
    """BDCScraper.scrape() — end-to-end flow with all I/O mocked."""

    @pytest.fixture
    def bdc_scraper(self) -> BDCScraper:
        return BDCScraper(username="bdc_test_user", password="test_password_123")

    @pytest.mark.asyncio
    async def test_happy_path_returns_scraper_result(
        self, bdc_scraper: BDCScraper
    ) -> None:
        """scrape() returns ScraperResult with bank_name == 'BDC' and transactions."""
        mock_pw_cm, mock_pw, mock_browser, mock_page = _build_mock_playwright()

        # page.content() is called 4 times in the BDC happy path (same as NBE/CIB):
        # 1. raw_html["dashboard"]
        # 2. _extract_account -> page.content()
        # 3. raw_html["transactions"]
        # 4. _extract_transactions -> page.content()
        mock_page.content = AsyncMock(
            side_effect=[
                _BDC_DASHBOARD_HTML,
                _BDC_DASHBOARD_HTML,
                _BDC_TRANSACTIONS_HTML,
                _BDC_TRANSACTIONS_HTML,
            ]
        )

        mock_element = AsyncMock()
        mock_element.click = AsyncMock(return_value=None)
        mock_element.inner_text = AsyncMock(return_value="")

        async def _query_selector_bdc(selector: str) -> Any:
            return None if selector in _BDC_ERROR_SELECTORS else mock_element

        mock_page.query_selector = _query_selector_bdc  # type: ignore[assignment]

        with patch("app.scrapers.base.async_playwright", return_value=mock_pw_cm):
            result = await bdc_scraper.scrape()

        assert isinstance(result, ScraperResult)
        assert result.account.bank_name == "BDC"
        assert result.account.balance == Decimal("20500.00")
        assert len(result.transactions) == 2
        assert result.transactions[0].transaction_type == "debit"
        assert result.transactions[1].transaction_type == "credit"

    @pytest.mark.asyncio
    async def test_happy_path_account_number_masked(
        self, bdc_scraper: BDCScraper
    ) -> None:
        """account_number_masked follows ****XXXX format."""
        mock_pw_cm, mock_pw, mock_browser, mock_page = _build_mock_playwright()
        mock_page.content = AsyncMock(
            side_effect=[
                _BDC_DASHBOARD_HTML,
                _BDC_DASHBOARD_HTML,
                _BDC_TRANSACTIONS_HTML,
                _BDC_TRANSACTIONS_HTML,
            ]
        )
        mock_element = AsyncMock()
        mock_element.click = AsyncMock(return_value=None)
        mock_element.inner_text = AsyncMock(return_value="")

        async def _query_selector_bdc(selector: str) -> Any:
            return None if selector in _BDC_ERROR_SELECTORS else mock_element

        mock_page.query_selector = _query_selector_bdc  # type: ignore[assignment]

        with patch("app.scrapers.base.async_playwright", return_value=mock_pw_cm):
            result = await bdc_scraper.scrape()

        assert result.account.account_number_masked.startswith("****")

    @pytest.mark.asyncio
    async def test_happy_path_raw_html_keys_present(
        self, bdc_scraper: BDCScraper
    ) -> None:
        """ScraperResult.raw_html must contain 'dashboard' and 'transactions' keys."""
        mock_pw_cm, mock_pw, mock_browser, mock_page = _build_mock_playwright()
        mock_page.content = AsyncMock(
            side_effect=[
                _BDC_DASHBOARD_HTML,
                _BDC_DASHBOARD_HTML,
                _BDC_TRANSACTIONS_HTML,
                _BDC_TRANSACTIONS_HTML,
            ]
        )
        mock_element = AsyncMock()
        mock_element.click = AsyncMock(return_value=None)
        mock_element.inner_text = AsyncMock(return_value="")

        async def _query_selector_bdc(selector: str) -> Any:
            return None if selector in _BDC_ERROR_SELECTORS else mock_element

        mock_page.query_selector = _query_selector_bdc  # type: ignore[assignment]

        with patch("app.scrapers.base.async_playwright", return_value=mock_pw_cm):
            result = await bdc_scraper.scrape()

        assert "dashboard" in result.raw_html
        assert "transactions" in result.raw_html

    @pytest.mark.asyncio
    async def test_login_error_raises_scraper_login_error(
        self, bdc_scraper: BDCScraper
    ) -> None:
        """scrape() raises ScraperLoginError when failureNotification element detected."""
        mock_pw_cm, mock_pw, mock_browser, mock_page = _build_mock_playwright()

        mock_page.content = AsyncMock(return_value=_BDC_LOGIN_ERROR_HTML)

        mock_error_el = AsyncMock()
        mock_error_el.inner_text = AsyncMock(
            return_value="Invalid username or password."
        )
        # All query_selector calls return the error element — simulates the
        # portal presenting the failure notification on the first CSS check.
        mock_page.query_selector = AsyncMock(return_value=mock_error_el)

        with patch("app.scrapers.base.async_playwright", return_value=mock_pw_cm):
            with pytest.raises(ScraperLoginError) as exc_info:
                await bdc_scraper.scrape()

        assert exc_info.value.bank_code == "BDC"

    @pytest.mark.asyncio
    async def test_playwright_timeout_raises_scraper_timeout_error(
        self, bdc_scraper: BDCScraper
    ) -> None:
        """scrape() wraps PlaywrightTimeoutError in ScraperTimeoutError."""
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError

        mock_pw_cm, mock_pw, mock_browser, mock_page = _build_mock_playwright()

        # No error element — login check passes
        mock_page.query_selector = AsyncMock(return_value=None)
        # Both CSS and XPath selector waits time out
        mock_page.wait_for_selector = AsyncMock(
            side_effect=PlaywrightTimeoutError("Timeout exceeded")
        )

        with patch("app.scrapers.base.async_playwright", return_value=mock_pw_cm):
            with pytest.raises(ScraperTimeoutError) as exc_info:
                await bdc_scraper.scrape()

        assert exc_info.value.bank_code == "BDC"

    @pytest.mark.asyncio
    async def test_browser_is_always_closed_on_login_error(
        self, bdc_scraper: BDCScraper
    ) -> None:
        """browser.close() is called in finally even when ScraperLoginError is raised."""
        mock_pw_cm, mock_pw, mock_browser, mock_page = _build_mock_playwright()

        mock_page.content = AsyncMock(return_value=_BDC_LOGIN_ERROR_HTML)
        mock_error_el = AsyncMock()
        mock_error_el.inner_text = AsyncMock(return_value="Invalid username or password.")
        mock_page.query_selector = AsyncMock(return_value=mock_error_el)

        with patch("app.scrapers.base.async_playwright", return_value=mock_pw_cm):
            with pytest.raises(ScraperLoginError):
                await bdc_scraper.scrape()

        mock_browser.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_browser_is_always_closed_on_timeout(
        self, bdc_scraper: BDCScraper
    ) -> None:
        """browser.close() is called in finally even when ScraperTimeoutError is raised."""
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError

        mock_pw_cm, mock_pw, mock_browser, mock_page = _build_mock_playwright()
        mock_page.query_selector = AsyncMock(return_value=None)
        mock_page.wait_for_selector = AsyncMock(
            side_effect=PlaywrightTimeoutError("timeout")
        )

        with patch("app.scrapers.base.async_playwright", return_value=mock_pw_cm):
            with pytest.raises(ScraperTimeoutError):
                await bdc_scraper.scrape()

        mock_browser.close.assert_awaited_once()


# ===========================================================================
# Section 6 — UBScraper.scrape() integration tests (Playwright fully mocked)
# ===========================================================================


class TestUbScraperScrape:
    """UBScraper.scrape() — end-to-end flow with all I/O mocked."""

    @pytest.fixture
    def ub_scraper(self) -> UBScraper:
        return UBScraper(username="ub_test_user", password="test_password_123")

    @pytest.mark.asyncio
    async def test_happy_path_returns_scraper_result(
        self, ub_scraper: UBScraper
    ) -> None:
        """scrape() returns ScraperResult with bank_name == 'UB' and transactions."""
        mock_pw_cm, mock_pw, mock_browser, mock_page = _build_mock_playwright()

        mock_page.content = AsyncMock(
            side_effect=[
                _UB_DASHBOARD_HTML,
                _UB_DASHBOARD_HTML,
                _UB_TRANSACTIONS_HTML,
                _UB_TRANSACTIONS_HTML,
            ]
        )

        mock_element = AsyncMock()
        mock_element.click = AsyncMock(return_value=None)
        mock_element.inner_text = AsyncMock(return_value="")

        async def _query_selector_ub(selector: str) -> Any:
            return None if selector in _UB_ERROR_SELECTORS else mock_element

        mock_page.query_selector = _query_selector_ub  # type: ignore[assignment]

        with patch("app.scrapers.base.async_playwright", return_value=mock_pw_cm):
            result = await ub_scraper.scrape()

        assert isinstance(result, ScraperResult)
        assert result.account.bank_name == "UB"
        assert result.account.account_type == "savings"
        assert result.account.balance == Decimal("33750.50")
        assert len(result.transactions) == 2
        assert result.transactions[0].transaction_type == "debit"
        assert result.transactions[1].transaction_type == "credit"

    @pytest.mark.asyncio
    async def test_happy_path_transactions_use_ub_date_format(
        self, ub_scraper: UBScraper
    ) -> None:
        """Transactions parsed from UB HTML use DD-MMM-YYYY dates correctly."""
        mock_pw_cm, mock_pw, mock_browser, mock_page = _build_mock_playwright()

        mock_page.content = AsyncMock(
            side_effect=[
                _UB_DASHBOARD_HTML,
                _UB_DASHBOARD_HTML,
                _UB_TRANSACTIONS_HTML,
                _UB_TRANSACTIONS_HTML,
            ]
        )
        mock_element = AsyncMock()
        mock_element.click = AsyncMock(return_value=None)
        mock_element.inner_text = AsyncMock(return_value="")

        async def _query_selector_ub(selector: str) -> Any:
            return None if selector in _UB_ERROR_SELECTORS else mock_element

        mock_page.query_selector = _query_selector_ub  # type: ignore[assignment]

        with patch("app.scrapers.base.async_playwright", return_value=mock_pw_cm):
            result = await ub_scraper.scrape()

        assert result.transactions[0].transaction_date == date(2025, 1, 10)
        assert result.transactions[1].transaction_date == date(2025, 1, 5)

    @pytest.mark.asyncio
    async def test_happy_path_raw_html_keys_present(
        self, ub_scraper: UBScraper
    ) -> None:
        """ScraperResult.raw_html must contain 'dashboard' and 'transactions' keys."""
        mock_pw_cm, mock_pw, mock_browser, mock_page = _build_mock_playwright()
        mock_page.content = AsyncMock(
            side_effect=[
                _UB_DASHBOARD_HTML,
                _UB_DASHBOARD_HTML,
                _UB_TRANSACTIONS_HTML,
                _UB_TRANSACTIONS_HTML,
            ]
        )
        mock_element = AsyncMock()
        mock_element.click = AsyncMock(return_value=None)
        mock_element.inner_text = AsyncMock(return_value="")

        async def _query_selector_ub(selector: str) -> Any:
            return None if selector in _UB_ERROR_SELECTORS else mock_element

        mock_page.query_selector = _query_selector_ub  # type: ignore[assignment]

        with patch("app.scrapers.base.async_playwright", return_value=mock_pw_cm):
            result = await ub_scraper.scrape()

        assert "dashboard" in result.raw_html
        assert "transactions" in result.raw_html

    @pytest.mark.asyncio
    async def test_login_error_raises_scraper_login_error(
        self, ub_scraper: UBScraper
    ) -> None:
        """scrape() raises ScraperLoginError when error element detected."""
        mock_pw_cm, mock_pw, mock_browser, mock_page = _build_mock_playwright()

        mock_page.content = AsyncMock(return_value=_UB_LOGIN_ERROR_HTML)

        mock_error_el = AsyncMock()
        mock_error_el.inner_text = AsyncMock(
            return_value="Access denied. Please check your credentials."
        )
        mock_page.query_selector = AsyncMock(return_value=mock_error_el)

        with patch("app.scrapers.base.async_playwright", return_value=mock_pw_cm):
            with pytest.raises(ScraperLoginError) as exc_info:
                await ub_scraper.scrape()

        assert exc_info.value.bank_code == "UB"

    @pytest.mark.asyncio
    async def test_playwright_timeout_raises_scraper_timeout_error(
        self, ub_scraper: UBScraper
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
                await ub_scraper.scrape()

        assert exc_info.value.bank_code == "UB"

    @pytest.mark.asyncio
    async def test_browser_is_always_closed_on_login_error(
        self, ub_scraper: UBScraper
    ) -> None:
        """browser.close() is called in finally even when ScraperLoginError is raised."""
        mock_pw_cm, mock_pw, mock_browser, mock_page = _build_mock_playwright()

        mock_page.content = AsyncMock(return_value=_UB_LOGIN_ERROR_HTML)
        mock_error_el = AsyncMock()
        mock_error_el.inner_text = AsyncMock(
            return_value="Access denied. Please check your credentials."
        )
        mock_page.query_selector = AsyncMock(return_value=mock_error_el)

        with patch("app.scrapers.base.async_playwright", return_value=mock_pw_cm):
            with pytest.raises(ScraperLoginError):
                await ub_scraper.scrape()

        mock_browser.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_browser_is_always_closed_on_timeout(
        self, ub_scraper: UBScraper
    ) -> None:
        """browser.close() is called in finally even when ScraperTimeoutError is raised."""
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError

        mock_pw_cm, mock_pw, mock_browser, mock_page = _build_mock_playwright()
        mock_page.query_selector = AsyncMock(return_value=None)
        mock_page.wait_for_selector = AsyncMock(
            side_effect=PlaywrightTimeoutError("timeout")
        )

        with patch("app.scrapers.base.async_playwright", return_value=mock_pw_cm):
            with pytest.raises(ScraperTimeoutError):
                await ub_scraper.scrape()

        mock_browser.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_happy_path_account_number_masked(
        self, ub_scraper: UBScraper
    ) -> None:
        """account_number_masked follows ****XXXX format."""
        mock_pw_cm, mock_pw, mock_browser, mock_page = _build_mock_playwright()
        mock_page.content = AsyncMock(
            side_effect=[
                _UB_DASHBOARD_HTML,
                _UB_DASHBOARD_HTML,
                _UB_TRANSACTIONS_HTML,
                _UB_TRANSACTIONS_HTML,
            ]
        )
        mock_element = AsyncMock()
        mock_element.click = AsyncMock(return_value=None)
        mock_element.inner_text = AsyncMock(return_value="")

        async def _query_selector_ub(selector: str) -> Any:
            return None if selector in _UB_ERROR_SELECTORS else mock_element

        mock_page.query_selector = _query_selector_ub  # type: ignore[assignment]

        with patch("app.scrapers.base.async_playwright", return_value=mock_pw_cm):
            result = await ub_scraper.scrape()

        assert result.account.account_number_masked.startswith("****")
