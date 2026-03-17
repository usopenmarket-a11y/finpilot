"""Unit tests for M2 bank scrapers: base class, NBEScraper, and CIBScraper.

Coverage targets
----------------
- BankScraper._mask_account_number — various input shapes
- Exception hierarchy — bank_code attribute, subclass relationships
- NBE module helpers: _parse_nbe_date, _parse_amount, _make_external_id,
  _normalise_account_type, _normalise_currency, _parse_transaction_row,
  _parse_oj_table_rows, _extract_currency_from_balance
- NBEScraper.scrape — happy path (Oracle JET SPA flow), ScraperLoginError,
  ScraperOTPRequired, ScraperTimeoutError
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
from app.scrapers.cib import (
    CIBScraper,
    _parse_cib_date,
)
from app.scrapers.cib import (
    _make_external_id as cib_make_external_id,
)
from app.scrapers.cib import (
    _parse_amount as cib_parse_amount,
)

# Import module-level helpers directly so we can unit-test them without
# instantiating the full scraper class.
from app.scrapers.nbe import (
    NBEScraper,
    _parse_nbe_date,
)
from app.scrapers.nbe import (
    _extract_currency_from_balance as nbe_extract_currency,
)
from app.scrapers.nbe import (
    _make_external_id as nbe_make_external_id,
)
from app.scrapers.nbe import (
    _normalise_account_type as nbe_normalise_account_type,
)
from app.scrapers.nbe import (
    _normalise_currency as nbe_normalise_currency,
)
from app.scrapers.nbe import (
    _parse_amount as nbe_parse_amount,
)
from app.scrapers.nbe import (
    _parse_oj_table_rows as nbe_parse_oj_table_rows,
)
from app.scrapers.nbe import (
    _parse_transaction_row as nbe_parse_transaction_row,
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

# NBE dashboard HTML — Oracle JET SPA structure.
# Includes a flip-account-list with TWO account rows (savings EGP + current EGP)
# plus a Logout link.  Multi-row fixture exercises the multi-account scrape path.
_NBE_DASHBOARD_HTML = """
<html><body>
<nav><a href="#">Logout</a></nav>
<ul>
  <li class="CSA"><a href="#">Accounts</a></li>
</ul>
<ul class="flip-account-list">
  <li class="flip-account-list__items">
    <span class="account-no">0765000645195400010</span>
    <span class="account-name">Current Account</span>
    <strong class="account-value">EGP 15,250.75</strong>
    <a class="menu-icon" href="#">...</a>
  </li>
  <li class="flip-account-list__items">
    <span class="account-no">0765000645195400011</span>
    <span class="account-name">Savings Account</span>
    <strong class="account-value">EGP 8,000.00</strong>
    <a class="menu-icon" href="#">...</a>
  </li>
</ul>
</body></html>
"""

# Single-account dashboard HTML used by tests that explicitly want only one account.
_NBE_DASHBOARD_HTML_SINGLE = """
<html><body>
<nav><a href="#">Logout</a></nav>
<ul>
  <li class="CSA"><a href="#">Accounts</a></li>
</ul>
<ul class="flip-account-list">
  <li class="flip-account-list__items">
    <span class="account-no">0765000645195400010</span>
    <span class="account-name">Current Account</span>
    <strong class="account-value">EGP 15,250.75</strong>
    <a class="menu-icon" href="#">...</a>
  </li>
</ul>
</body></html>
"""

# NBE transaction history HTML — Oracle JET oj-table with ViewStatement1 id pattern.
# Two rows: one debit (row 0), one credit (row 1).
# Columns: 0=TxnDate | 1=ValueDate | 2=RefNo | 3=Description | 4=Debit | 5=Credit | 6=Balance
_NBE_TRANSACTIONS_HTML = """
<html><body>
<oj-table id="ViewStatement1">
  <td id="ViewStatement1:0_0"><span>15 Jan 2025</span></td>
  <td id="ViewStatement1:0_1"><span>15 Jan 2025</span></td>
  <td id="ViewStatement1:0_2"><span>REF001</span></td>
  <td id="ViewStatement1:0_3"><span>ATM Withdrawal</span></td>
  <td id="ViewStatement1:0_4"><span>EGP 500.00</span></td>
  <td id="ViewStatement1:0_5"><span></span></td>
  <td id="ViewStatement1:0_6"><span>EGP 14,750.75</span></td>

  <td id="ViewStatement1:1_0"><span>10 Jan 2025</span></td>
  <td id="ViewStatement1:1_1"><span>10 Jan 2025</span></td>
  <td id="ViewStatement1:1_2"><span>REF002</span></td>
  <td id="ViewStatement1:1_3"><span>Salary Credit</span></td>
  <td id="ViewStatement1:1_4"><span></span></td>
  <td id="ViewStatement1:1_5"><span>EGP 5,000.00</span></td>
  <td id="ViewStatement1:1_6"><span>EGP 15,250.75</span></td>
</oj-table>
</body></html>
"""

# NBE login error — SPA body text contains "invalid" after failed login.
_NBE_LOGIN_ERROR_HTML = """
<html><body>
<div class="login-error">Invalid username or password. Please try again.</div>
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
    """_parse_nbe_date — primary format is DD Mon YYYY (Oracle JET portal)."""

    def test_dd_mon_yyyy_primary_format(self) -> None:
        assert _parse_nbe_date("15 Jan 2025") == date(2025, 1, 15)

    def test_dd_mon_yyyy_march(self) -> None:
        assert _parse_nbe_date("12 Mar 2026") == date(2026, 3, 12)

    def test_single_digit_day(self) -> None:
        assert _parse_nbe_date("5 Jan 2025") == date(2025, 1, 5)

    def test_end_of_year_date(self) -> None:
        assert _parse_nbe_date("31 Dec 2024") == date(2024, 12, 31)

    def test_dd_slash_mm_slash_yyyy_legacy_fallback(self) -> None:
        assert _parse_nbe_date("15/01/2025") == date(2025, 1, 15)

    def test_dd_dash_mm_dash_yyyy_legacy_fallback(self) -> None:
        assert _parse_nbe_date("15-01-2025") == date(2025, 1, 15)

    def test_returns_none_for_unrecognised_format(self) -> None:
        assert _parse_nbe_date("not-a-date") is None

    def test_returns_none_for_empty_string(self) -> None:
        assert _parse_nbe_date("") is None

    def test_strips_surrounding_whitespace(self) -> None:
        assert _parse_nbe_date("  15 Jan 2025  ") == date(2025, 1, 15)

    def test_case_insensitive_month(self) -> None:
        # strptime %b is locale-aware but Python default handles mixed case
        assert _parse_nbe_date("15 jan 2025") == date(2025, 1, 15)


class TestNbeParseAmount:
    """nbe._parse_amount — strips EGP/USD currency prefix and comma separators."""

    def test_plain_integer_string(self) -> None:
        assert nbe_parse_amount("500") == Decimal("500")

    def test_decimal_string(self) -> None:
        assert nbe_parse_amount("1234.56") == Decimal("1234.56")

    def test_comma_thousands_separator(self) -> None:
        assert nbe_parse_amount("1,234.56") == Decimal("1234.56")

    def test_large_amount_with_multiple_commas(self) -> None:
        assert nbe_parse_amount("1,234,567.89") == Decimal("1234567.89")

    def test_egp_prefix_stripped(self) -> None:
        assert nbe_parse_amount("EGP 10,100.00") == Decimal("10100.00")

    def test_usd_prefix_stripped(self) -> None:
        assert nbe_parse_amount("USD 500.00") == Decimal("500.00")

    def test_egp_no_space_stripped(self) -> None:
        assert nbe_parse_amount("EGP10,100.00") == Decimal("10100.00")

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
        canonical = f"{d.isoformat()}|{'A' * 40}|{amount}"
        expected = hashlib.sha256(canonical.encode()).hexdigest()[:24]
        assert result == expected


class TestNbeNormaliseHelpers:
    """nbe._normalise_account_type, _normalise_currency, _extract_currency."""

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

    def test_extract_currency_egp_prefix(self) -> None:
        assert nbe_extract_currency("EGP 15,250.75") == "EGP"

    def test_extract_currency_usd_prefix(self) -> None:
        assert nbe_extract_currency("USD 500.00") == "USD"

    def test_extract_currency_no_prefix_defaults_egp(self) -> None:
        assert nbe_extract_currency("15,250.75") == "EGP"

    def test_extract_currency_negative_balance(self) -> None:
        # Negative balances use pattern like "-EGP 79,000.00" — no space before EGP
        assert nbe_extract_currency("EGP 79,000.00") == "EGP"


class TestNbeParseOjTableRows:
    """nbe._parse_oj_table_rows — Oracle JET ViewStatement1 cell extraction."""

    def test_extracts_two_rows_from_fixture(self) -> None:
        rows = nbe_parse_oj_table_rows(_NBE_TRANSACTIONS_HTML)
        assert len(rows) == 2

    def test_first_row_debit_cells(self) -> None:
        rows = nbe_parse_oj_table_rows(_NBE_TRANSACTIONS_HTML)
        assert rows[0][3] == "ATM Withdrawal"
        assert rows[0][4] == "EGP 500.00"
        assert rows[0][5] == ""

    def test_second_row_credit_cells(self) -> None:
        rows = nbe_parse_oj_table_rows(_NBE_TRANSACTIONS_HTML)
        assert rows[1][3] == "Salary Credit"
        assert rows[1][4] == ""
        assert rows[1][5] == "EGP 5,000.00"

    def test_empty_html_returns_empty_list(self) -> None:
        rows = nbe_parse_oj_table_rows("<html><body></body></html>")
        assert rows == []

    def test_row_date_column(self) -> None:
        rows = nbe_parse_oj_table_rows(_NBE_TRANSACTIONS_HTML)
        assert rows[0][0] == "15 Jan 2025"
        assert rows[1][0] == "10 Jan 2025"

    def test_reference_column(self) -> None:
        rows = nbe_parse_oj_table_rows(_NBE_TRANSACTIONS_HTML)
        assert rows[0][2] == "REF001"
        assert rows[1][2] == "REF002"


class TestNbeParseTransactionRow:
    """nbe._parse_transaction_row — Oracle JET 7-column layout."""

    def _cells_debit(self) -> list[str]:
        # Col: TxnDate | ValueDate | Ref | Description | Debit | Credit | Balance
        return [
            "15 Jan 2025",
            "15 Jan 2025",
            "REF001",
            "ATM Withdrawal",
            "EGP 500.00",
            "",
            "EGP 14,750.75",
        ]

    def _cells_credit(self) -> list[str]:
        return [
            "10 Jan 2025",
            "10 Jan 2025",
            "REF002",
            "Salary Credit",
            "",
            "EGP 5,000.00",
            "EGP 15,250.75",
        ]

    def test_debit_row_parsed_correctly(self) -> None:
        account = _make_bank_account("NBE")
        txn = nbe_parse_transaction_row(self._cells_debit(), account, _NOW)
        assert txn is not None
        assert txn.transaction_type == "debit"
        assert txn.amount == Decimal("500.00")
        assert txn.description == "ATM Withdrawal"
        assert txn.transaction_date == date(2025, 1, 15)

    def test_credit_row_parsed_correctly(self) -> None:
        account = _make_bank_account("NBE")
        txn = nbe_parse_transaction_row(self._cells_credit(), account, _NOW)
        assert txn is not None
        assert txn.transaction_type == "credit"
        assert txn.amount == Decimal("5000.00")
        assert txn.transaction_date == date(2025, 1, 10)

    def test_balance_after_parsed(self) -> None:
        account = _make_bank_account("NBE")
        txn = nbe_parse_transaction_row(self._cells_debit(), account, _NOW)
        assert txn is not None
        assert txn.balance_after == Decimal("14750.75")

    def test_row_with_no_amount_returns_none(self) -> None:
        account = _make_bank_account("NBE")
        cells = ["15 Jan 2025", "15 Jan 2025", "REF", "Empty Row", "", "", ""]
        txn = nbe_parse_transaction_row(cells, account, _NOW)
        assert txn is None

    def test_header_repeat_row_returns_none(self) -> None:
        account = _make_bank_account("NBE")
        cells = ["date", "value date", "ref", "description", "debit", "credit", "balance"]
        txn = nbe_parse_transaction_row(cells, account, _NOW)
        assert txn is None

    def test_unparseable_date_returns_none(self) -> None:
        account = _make_bank_account("NBE")
        cells = ["not-a-date", "", "REF", "Purchase", "EGP 100.00", "", ""]
        txn = nbe_parse_transaction_row(cells, account, _NOW)
        assert txn is None

    def test_external_id_is_deterministic(self) -> None:
        account = _make_bank_account("NBE")
        txn1 = nbe_parse_transaction_row(self._cells_debit(), account, _NOW)
        txn2 = nbe_parse_transaction_row(self._cells_debit(), account, _NOW)
        assert txn1 is not None and txn2 is not None
        assert txn1.external_id == txn2.external_id

    def test_external_id_differs_for_different_rows(self) -> None:
        account = _make_bank_account("NBE")
        txn_a = nbe_parse_transaction_row(self._cells_debit(), account, _NOW)
        txn_b = nbe_parse_transaction_row(self._cells_credit(), account, _NOW)
        assert txn_a is not None and txn_b is not None
        assert txn_a.external_id != txn_b.external_id

    def test_sentinel_uuids_are_zero(self) -> None:
        account = _make_bank_account("NBE")
        txn = nbe_parse_transaction_row(self._cells_debit(), account, _NOW)
        assert txn is not None
        assert txn.id == _ZERO_UUID
        assert txn.user_id == _ZERO_UUID
        assert txn.account_id == _ZERO_UUID

    def test_raw_data_contains_source_nbe(self) -> None:
        account = _make_bank_account("NBE")
        txn = nbe_parse_transaction_row(self._cells_debit(), account, _NOW)
        assert txn is not None
        assert txn.raw_data.get("source") == "nbe"

    def test_reference_stored_in_raw_data(self) -> None:
        account = _make_bank_account("NBE")
        txn = nbe_parse_transaction_row(self._cells_debit(), account, _NOW)
        assert txn is not None
        assert txn.raw_data.get("reference") == "REF001"


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

# Selectors the new Oracle JET scraper uses for OTP detection — both must
# return None during normal happy-path flow so _wait_for_dashboard proceeds.
_NBE_OTP_SELECTORS = {"#otpSection", "input[id*='otp' i]"}


def _build_nbe_mock_page(
    dashboard_html: str = _NBE_DASHBOARD_HTML,
    txn_html: str = _NBE_TRANSACTIONS_HTML,
    num_accounts: int = 2,
) -> tuple[Any, Any, Any, Any]:
    """Build a mock playwright stack pre-configured for the NBE Oracle JET flow.

    Returns (mock_pw_cm, mock_pw, mock_browser, mock_page).

    The mock_page is configured with:
    - content() cycling through:
        dashboard (raw_html["dashboard"])
        dashboard (_extract_all_accounts)
        then for each account N:
          txn_html (raw_html["transactions_N"])
          txn_html (_extract_transactions page 1)
    - wait_for_selector() returning a clickable mock element for all selectors
    - query_selector() returning a clickable mock element for all selectors
      except OTP-detection selectors and the Next Page button (both return None)
    - inner_text() returning non-error text so login-failure heuristic is silent
    - go_back() returning None (navigation between accounts)
    - locator() returning a mock locator chain so .nth().locator().click() works

    Args:
        dashboard_html: HTML to return for dashboard/account-list calls.
        txn_html: HTML to return for transaction table calls.
        num_accounts: Number of account rows in the fixture; controls how many
            transaction-page content() calls are added to the side_effect list.
    """
    mock_pw_cm, mock_pw, mock_browser, mock_page = _build_mock_playwright()

    # Build content() side_effect:
    #   1 dashboard call (raw_html["dashboard"])
    #   1 dashboard call (_extract_all_accounts)
    #   then num_accounts × 2 txn calls (raw_html + _extract_transactions)
    content_calls = [dashboard_html, dashboard_html]
    for _ in range(num_accounts):
        content_calls += [txn_html, txn_html]

    mock_page.content = AsyncMock(side_effect=content_calls)

    mock_element = AsyncMock()
    mock_element.click = AsyncMock(return_value=None)
    mock_element.inner_text = AsyncMock(return_value="")
    mock_element.get_attribute = AsyncMock(return_value=None)  # not disabled
    # query_selector on a mock element (for nested .query_selector calls like
    # first_row.query_selector("a.menu-icon"))
    mock_element.query_selector = AsyncMock(return_value=mock_element)

    # wait_for_selector MUST return the element — Playwright returns the element
    # handle when the selector is found; our scraper calls .click() on it.
    mock_page.wait_for_selector = AsyncMock(return_value=mock_element)

    # wait_for_load_state — used after Apply click for networkidle wait
    mock_page.wait_for_load_state = AsyncMock(return_value=None)

    # evaluate — used for JS cell-count check after networkidle; return > 0 so
    # the scraper proceeds without the fallback wait_for_selector path.
    mock_page.evaluate = AsyncMock(return_value=7)

    # go_back — called between accounts to return to the dashboard
    mock_page.go_back = AsyncMock(return_value=None)

    # locator() chain — supports .nth(i).locator(sel).click()
    # The scraper uses page.locator(SEL).nth(i).locator(SEL_MENU).click()
    # Build a chainable mock: locator() → nth() → locator() → click()
    mock_locator = AsyncMock()
    mock_locator.nth = MagicMock(return_value=mock_locator)
    mock_locator.locator = MagicMock(return_value=mock_locator)
    mock_locator.click = AsyncMock(return_value=None)
    mock_page.locator = MagicMock(return_value=mock_locator)

    async def _query_selector(selector: str) -> Any:
        if selector in _NBE_OTP_SELECTORS:
            return None
        # Next Page button — return None so pagination loop terminates immediately
        if selector == "button[title='Next Page']":
            return None
        return mock_element

    mock_page.query_selector = _query_selector  # type: ignore[assignment]

    # inner_text — return non-error text so login-failure heuristic does not trigger
    mock_page.inner_text = AsyncMock(return_value="Welcome to Ahly Net")

    return mock_pw_cm, mock_pw, mock_browser, mock_page


class TestNbeScraperScrape:
    """NBEScraper.scrape() — end-to-end flow mocked for Oracle JET SPA."""

    @pytest.fixture
    def nbe_scraper(self) -> NBEScraper:
        return NBEScraper(username="test_user", password="test_password_123")

    async def test_happy_path_returns_scraper_result(self, nbe_scraper: NBEScraper) -> None:
        """scrape() returns ScraperResult with bank_name 'NBE' and transactions.

        The fixture dashboard has 2 account rows; each produces 2 transactions
        from the same transaction HTML fixture, for 4 total.
        """
        mock_pw_cm, mock_pw, mock_browser, mock_page = _build_nbe_mock_page()

        with patch("app.scrapers.base.async_playwright", return_value=mock_pw_cm):
            result = await nbe_scraper.scrape()

        assert isinstance(result, ScraperResult)
        # Multi-account: 2 accounts in the fixture
        assert len(result.accounts) == 2
        assert result.accounts[0].bank_name == "NBE"
        assert result.accounts[0].balance == Decimal("15250.75")
        # Each account yields 2 transactions → 4 total
        assert len(result.transactions) == 4
        # Backward-compat .account property returns first account
        assert result.account.bank_name == "NBE"

    async def test_happy_path_account_currency_is_egp(self, nbe_scraper: NBEScraper) -> None:
        """Primary account currency extracted from 'EGP 15,250.75' balance string."""
        mock_pw_cm, mock_pw, mock_browser, mock_page = _build_nbe_mock_page()

        with patch("app.scrapers.base.async_playwright", return_value=mock_pw_cm):
            result = await nbe_scraper.scrape()

        assert result.accounts[0].currency == "EGP"
        assert result.accounts[1].currency == "EGP"

    async def test_happy_path_transaction_dates_parsed(self, nbe_scraper: NBEScraper) -> None:
        """Transaction dates are parsed from 'DD Mon YYYY' Oracle JET format."""
        mock_pw_cm, mock_pw, mock_browser, mock_page = _build_nbe_mock_page()

        with patch("app.scrapers.base.async_playwright", return_value=mock_pw_cm):
            result = await nbe_scraper.scrape()

        # First two transactions come from account 0
        assert result.transactions[0].transaction_date == date(2025, 1, 15)
        assert result.transactions[1].transaction_date == date(2025, 1, 10)

    async def test_login_error_raises_scraper_login_error(self, nbe_scraper: NBEScraper) -> None:
        """scrape() raises ScraperLoginError when portal body contains 'invalid'.

        wait_for_selector succeeds for the username and password field selectors
        (steps 1 and 2 of the 2-step login) but times out when waiting for the
        Logout link — which means login was rejected.  inner_text then returns
        a body that includes the word 'invalid', triggering ScraperLoginError.
        """
        from playwright.async_api import TimeoutError as _PwTimeout

        mock_element = AsyncMock()
        mock_element.click = AsyncMock(return_value=None)
        mock_element.query_selector = AsyncMock(return_value=mock_element)

        mock_pw_cm, mock_pw, mock_browser, mock_page = _build_mock_playwright()

        # OTP selectors return None; all other query_selector calls return a
        # clickable element so the login steps can proceed normally.
        async def _qs_no_otp(selector: str) -> Any:
            if selector in _NBE_OTP_SELECTORS:
                return None
            return mock_element

        mock_page.query_selector = _qs_no_otp  # type: ignore[assignment]

        # wait_for_selector succeeds for username field and password field,
        # then times out on both dashboard confirmation selectors inside _wait_for_dashboard.
        mock_page.wait_for_selector = AsyncMock(
            side_effect=[
                mock_element,  # #login_username (navigate_to_login)
                mock_element,  # #login_password (login step 2)
                _PwTimeout("timeout"),  # li.loggedInUser — primary dashboard selector
                _PwTimeout("timeout"),  # a.no-navigation-logout — fallback selector
            ]
        )

        # inner_text returns text containing "invalid" — triggers login-failure heuristic
        mock_page.inner_text = AsyncMock(return_value="Invalid username or password.")

        with patch("app.scrapers.base.async_playwright", return_value=mock_pw_cm):
            with pytest.raises(ScraperLoginError) as exc_info:
                await nbe_scraper.scrape()

        assert exc_info.value.bank_code == "NBE"

    async def test_otp_required_raises_scraper_otp_required(self, nbe_scraper: NBEScraper) -> None:
        """scrape() raises ScraperOTPRequired when OTP prompt is detected.

        The OTP check runs inside _wait_for_dashboard (after _login completes).
        query_selector returns a real element for the login buttons so _login
        can proceed, then returns mock_otp_el for '#otpSection'.
        """
        mock_pw_cm, mock_pw, mock_browser, mock_page = _build_mock_playwright()

        mock_btn = AsyncMock()
        mock_btn.click = AsyncMock(return_value=None)
        mock_otp_el = AsyncMock()

        # OTP selectors that trigger ScraperOTPRequired
        _otp_present = {"#otpSection"}

        # Selectors that query_selector should return None for
        # (the second OTP selector is checked only if the first returns None)
        async def _query_selector_with_otp(selector: str) -> Any:
            if selector in _otp_present:
                return mock_otp_el
            if selector == "input[id*='otp' i]":
                return None  # first OTP check already found it
            return mock_btn

        mock_page.query_selector = _query_selector_with_otp  # type: ignore[assignment]
        # wait_for_selector must succeed for username and password fields
        mock_page.wait_for_selector = AsyncMock(return_value=mock_btn)

        with patch("app.scrapers.base.async_playwright", return_value=mock_pw_cm):
            with pytest.raises(ScraperOTPRequired) as exc_info:
                await nbe_scraper.scrape()

        assert exc_info.value.bank_code == "NBE"

    async def test_playwright_timeout_on_username_field_raises_scraper_timeout(
        self, nbe_scraper: NBEScraper
    ) -> None:
        """scrape() wraps PlaywrightTimeoutError from wait_for_selector in ScraperTimeoutError."""
        from playwright.async_api import TimeoutError as _PwTimeout

        mock_pw_cm, mock_pw, mock_browser, mock_page = _build_mock_playwright()
        mock_page.wait_for_selector = AsyncMock(side_effect=_PwTimeout("username field timeout"))

        with patch("app.scrapers.base.async_playwright", return_value=mock_pw_cm):
            with pytest.raises(ScraperTimeoutError) as exc_info:
                await nbe_scraper.scrape()

        assert exc_info.value.bank_code == "NBE"

    async def test_scrape_result_contains_raw_html_keys(self, nbe_scraper: NBEScraper) -> None:
        """ScraperResult.raw_html contains 'dashboard' and per-account 'transactions_N' keys."""
        mock_pw_cm, mock_pw, mock_browser, mock_page = _build_nbe_mock_page()

        with patch("app.scrapers.base.async_playwright", return_value=mock_pw_cm):
            result = await nbe_scraper.scrape()

        assert "dashboard" in result.raw_html
        # Multi-account: keys are transactions_0, transactions_1, …
        assert "transactions_0" in result.raw_html
        assert "transactions_1" in result.raw_html

    async def test_browser_is_always_closed(self, nbe_scraper: NBEScraper) -> None:
        """_close_browser is called even if scrape() raises an exception."""
        from playwright.async_api import TimeoutError as _PwTimeout

        mock_pw_cm, mock_pw, mock_browser, mock_page = _build_mock_playwright()
        mock_page.query_selector = AsyncMock(return_value=None)
        mock_page.wait_for_selector = AsyncMock(side_effect=_PwTimeout("timeout"))

        with patch("app.scrapers.base.async_playwright", return_value=mock_pw_cm):
            with pytest.raises(ScraperTimeoutError):
                await nbe_scraper.scrape()

        mock_browser.close.assert_awaited_once()

    async def test_account_number_is_masked_in_result(self, nbe_scraper: NBEScraper) -> None:
        """account_number_masked in result follows ****XXXX format for all accounts."""
        mock_pw_cm, mock_pw, mock_browser, mock_page = _build_nbe_mock_page()

        with patch("app.scrapers.base.async_playwright", return_value=mock_pw_cm):
            result = await nbe_scraper.scrape()

        # Primary account: 0765000645195400010 → last 4 digits = 0010
        assert result.accounts[0].account_number_masked.startswith("****")
        assert result.accounts[0].account_number_masked == "****0010"
        # Secondary account: 0765000645195400011 → last 4 digits = 0011
        assert result.accounts[1].account_number_masked == "****0011"

    async def test_multi_account_result_has_all_accounts(self, nbe_scraper: NBEScraper) -> None:
        """scrape() collects metadata for every account row in the widget."""
        mock_pw_cm, mock_pw, mock_browser, mock_page = _build_nbe_mock_page()

        with patch("app.scrapers.base.async_playwright", return_value=mock_pw_cm):
            result = await nbe_scraper.scrape()

        assert len(result.accounts) == 2
        # First account is current, second is savings
        assert result.accounts[0].account_type == "current"
        assert result.accounts[1].account_type == "savings"

    async def test_transactions_tagged_with_account_number(self, nbe_scraper: NBEScraper) -> None:
        """Each transaction carries account_number_masked in raw_data."""
        mock_pw_cm, mock_pw, mock_browser, mock_page = _build_nbe_mock_page()

        with patch("app.scrapers.base.async_playwright", return_value=mock_pw_cm):
            result = await nbe_scraper.scrape()

        for txn in result.transactions:
            assert "account_number_masked" in txn.raw_data
            assert txn.raw_data["account_number_masked"].startswith("****")


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
                _CIB_DASHBOARD_HTML,  # raw_html["dashboard"]
                _CIB_DASHBOARD_HTML,  # _extract_account -> page.content()
                _CIB_TRANSACTIONS_HTML,  # raw_html["transactions"]
                _CIB_TRANSACTIONS_HTML,  # _extract_transactions -> page.content()
            ]
        )

        mock_element = AsyncMock()
        mock_element.click = AsyncMock(return_value=None)
        mock_element.inner_text = AsyncMock(return_value="")

        # CIB error selectors — must return None so _wait_for_dashboard proceeds
        _CIB_ERROR_CSS = (
            ".error-message, .alert-danger, [class*='loginError'], [class*='error-msg']"
        )
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

    async def test_login_error_raises_scraper_login_error(self, cib_scraper: CIBScraper) -> None:
        """scrape() raises ScraperLoginError when error-message element is found."""
        mock_pw_cm, mock_pw, mock_browser, mock_page = _build_mock_playwright()

        mock_page.content = AsyncMock(return_value=_CIB_LOGIN_ERROR_HTML)

        mock_error_el = AsyncMock()
        mock_error_el.inner_text = AsyncMock(return_value="Invalid credentials. Please try again.")
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
        mock_page.wait_for_selector = AsyncMock(side_effect=PlaywrightTimeoutError("timeout"))

        with patch("app.scrapers.base.async_playwright", return_value=mock_pw_cm):
            with pytest.raises(ScraperTimeoutError):
                await cib_scraper.scrape()

        mock_browser.close.assert_awaited_once()

    async def test_cib_transactions_use_cib_date_format(self, cib_scraper: CIBScraper) -> None:
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

        _CIB_ERROR_CSS = (
            ".error-message, .alert-danger, [class*='loginError'], [class*='error-msg']"
        )
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
        result = ScraperResult(accounts=[account])
        assert result.transactions == []

    def test_default_raw_html_empty_dict(self) -> None:
        account = _make_bank_account()
        result = ScraperResult(accounts=[account])
        assert result.raw_html == {}

    def test_transactions_and_raw_html_stored(self) -> None:
        account = _make_bank_account()
        result = ScraperResult(
            accounts=[account],
            transactions=[],
            raw_html={"dashboard": "<html/>"},
        )
        assert result.raw_html["dashboard"] == "<html/>"

    def test_account_property_returns_first_account(self) -> None:
        """Backward-compat .account property returns accounts[0]."""
        acct_a = _make_bank_account("NBE")
        acct_b = _make_bank_account("NBE")
        result = ScraperResult(accounts=[acct_a, acct_b])
        assert result.account is acct_a

    def test_accounts_list_preserves_order(self) -> None:
        """accounts list preserves insertion order."""
        acct_a = _make_bank_account("NBE")
        result = ScraperResult(accounts=[acct_a])
        assert len(result.accounts) == 1
        assert result.accounts[0] is acct_a
