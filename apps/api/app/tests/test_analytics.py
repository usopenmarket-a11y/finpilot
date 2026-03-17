"""Unit tests for the M4 Analytics Engine.

Covers:
- app.analytics.categorizer  (rule-based + AI path)
- app.analytics.spending     (compute_spending_breakdown)
- app.analytics.trends       (compute_trends)
- app.analytics.credit       (compute_credit_report)

No real Anthropic API calls are made.  All external I/O is mocked via
unittest.mock.  The tests are pure unit tests — no ASGI app, no DB.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from app.models.db import BankAccount, Loan, Transaction

# ---------------------------------------------------------------------------
# Shared datetime helper
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(tz=UTC)


# ---------------------------------------------------------------------------
# Fixture factory helpers
# ---------------------------------------------------------------------------


def make_transaction(
    amount: Decimal | str | float = "100.00",
    transaction_type: str = "debit",
    description: str = "Test transaction",
    category: str | None = None,
    transaction_date: date | None = None,
    currency: str = "EGP",
) -> Transaction:
    """Build a minimal valid Transaction for testing."""
    return Transaction(
        id=uuid4(),
        user_id=uuid4(),
        account_id=uuid4(),
        external_id=f"EXT-{uuid4().hex[:8]}",
        amount=Decimal(str(amount)),
        currency=currency,
        transaction_type=transaction_type,
        description=description,
        category=category,
        transaction_date=transaction_date or date(2026, 1, 15),
        created_at=_now(),
        updated_at=_now(),
    )


def make_bank_account(
    account_type: str = "savings",
    balance: Decimal | str | float = "10000.00",
    bank_name: str = "NBE",
) -> BankAccount:
    """Build a minimal valid BankAccount for testing."""
    return BankAccount(
        id=uuid4(),
        user_id=uuid4(),
        bank_name=bank_name,
        account_number_masked="****1234",
        account_type=account_type,
        balance=Decimal(str(balance)),
        created_at=_now(),
        updated_at=_now(),
    )


def make_loan(
    outstanding: Decimal | str | float = "60000.00",
    installment: Decimal | str | float = "2000.00",
    interest_rate: Decimal | str | float = "0.1850",
    loan_type: str = "personal",
    next_payment_date: date | None = None,
) -> Loan:
    """Build a minimal valid Loan for testing."""
    return Loan(
        id=uuid4(),
        user_id=uuid4(),
        account_id=uuid4(),
        loan_type=loan_type,
        principal_amount=Decimal("100000.00"),
        outstanding_balance=Decimal(str(outstanding)),
        interest_rate=Decimal(str(interest_rate)),
        monthly_installment=Decimal(str(installment)),
        next_payment_date=next_payment_date,
        created_at=_now(),
        updated_at=_now(),
    )


@pytest.fixture
def mock_anthropic_client() -> MagicMock:
    """Return a fully mocked AsyncAnthropic client with no API key.

    Tests that need an active API key should set client._api_key directly.
    """
    client = MagicMock()
    # No API key by default — categorizer skips AI path
    client._api_key = ""
    client.api_key = ""
    client.messages = MagicMock()
    client.messages.create = AsyncMock()
    return client


def _make_ai_response(payload: dict[str, Any]) -> MagicMock:
    """Wrap a dict in the shape that anthropic.Message returns."""
    content_block = MagicMock()
    content_block.text = json.dumps(payload)
    message = MagicMock()
    message.content = [content_block]
    return message


# ===========================================================================
# CATEGORIZER TESTS
# ===========================================================================


class TestCategorizationResult:
    """Test 10 — CategorizationResult dataclass fields."""

    def test_fields_exist(self) -> None:
        from app.analytics.categorizer import CategorizationResult

        result = CategorizationResult(
            transaction_id=UUID("00000000-0000-0000-0000-000000000001"),
            category="ATM & Cash",
            sub_category="Withdrawal",
            confidence=1.0,
            method="rule",
        )
        assert result.transaction_id == UUID("00000000-0000-0000-0000-000000000001")
        assert result.category == "ATM & Cash"
        assert result.sub_category == "Withdrawal"
        assert result.confidence == 1.0
        assert result.method == "rule"


class TestCategorizerRules:
    """Tests 1-4 — rule-based matching."""

    @pytest.mark.asyncio
    async def test_atm_withdrawal_matches_rule(self, mock_anthropic_client: MagicMock) -> None:
        """Test 1 — 'ATM withdrawal' → category='ATM & Cash', method='rule'."""
        from app.analytics.categorizer import categorize_transaction

        result = await categorize_transaction(
            description="ATM withdrawal",
            amount=Decimal("500.00"),
            transaction_type="debit",
            client=mock_anthropic_client,
        )

        assert result.category == "ATM & Cash"
        assert result.sub_category == "Withdrawal"
        assert result.method == "rule"
        assert result.confidence == 1.0
        # No AI call should have been made
        mock_anthropic_client.messages.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_salary_transfer_matches_rule(self, mock_anthropic_client: MagicMock) -> None:
        """Test 2 — 'salary transfer' → category='Income', sub_category='Salary'."""
        from app.analytics.categorizer import categorize_transaction

        result = await categorize_transaction(
            description="salary transfer",
            amount=Decimal("15000.00"),
            transaction_type="credit",
            client=mock_anthropic_client,
        )

        assert result.category == "Income"
        assert result.sub_category == "Salary"
        assert result.method == "rule"
        mock_anthropic_client.messages.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_arabic_transfer_matches_rule(self, mock_anthropic_client: MagicMock) -> None:
        """Test 3 — Arabic 'تحويل' → category='Transfers', method='rule'."""
        from app.analytics.categorizer import categorize_transaction

        result = await categorize_transaction(
            description="تحويل بنكي",
            amount=Decimal("3000.00"),
            transaction_type="credit",
            client=mock_anthropic_client,
        )

        assert result.category == "Transfers"
        assert result.method == "rule"
        mock_anthropic_client.messages.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_large_credit_with_transfer_keyword_matches_rule(
        self, mock_anthropic_client: MagicMock
    ) -> None:
        """Test 4 — large credit (amount>5000, type='credit') with 'transfer' in description → 'Transfers'."""
        from app.analytics.categorizer import categorize_transaction

        result = await categorize_transaction(
            description="Incoming transfer from account",
            amount=Decimal("10000.00"),
            transaction_type="credit",
            client=mock_anthropic_client,
        )

        assert result.category == "Transfers"
        assert result.method == "rule"
        mock_anthropic_client.messages.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_large_credit_no_transfer_keyword_not_caught_by_large_credit_rule(
        self, mock_anthropic_client: MagicMock
    ) -> None:
        """Large credit without a transfer keyword does NOT trigger the large-credit catch-all."""
        from app.analytics.categorizer import categorize_transaction

        # With no API key the fallback is 'Other' via rule path
        result = await categorize_transaction(
            description="Incoming wire",
            amount=Decimal("10000.00"),
            transaction_type="credit",
            client=mock_anthropic_client,
        )

        # No transfer keyword and no API key → Other
        assert result.category == "Other"
        assert result.method == "rule"


class TestCategorizerAIPath:
    """Tests 5-7 — AI-backed categorization path."""

    @pytest.mark.asyncio
    async def test_ai_path_happy(self) -> None:
        """Test 5 — valid AI JSON response → correct category, confidence, method='ai'."""
        from app.analytics.categorizer import categorize_transaction

        client = MagicMock()
        client._api_key = "sk-test-fake-key-for-unit-tests"
        client.api_key = "sk-test-fake-key-for-unit-tests"
        client.messages = MagicMock()
        client.messages.create = AsyncMock(
            return_value=_make_ai_response(
                {"category": "Food & Dining", "sub_category": "Restaurant", "confidence": 0.92}
            )
        )

        result = await categorize_transaction(
            description="Cairo Kitchen restaurant",
            amount=Decimal("350.00"),
            transaction_type="debit",
            client=client,
        )

        assert result.method == "ai"
        assert result.category == "Food & Dining"
        assert result.sub_category == "Restaurant"
        assert abs(result.confidence - 0.92) < 0.001
        client.messages.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_ai_path_malformed_json_fallback(self) -> None:
        """Test 6 — malformed AI response → category='Other', confidence=0.3."""
        from app.analytics.categorizer import categorize_transaction

        client = MagicMock()
        client._api_key = "sk-test-fake-key-for-unit-tests"
        client.api_key = "sk-test-fake-key-for-unit-tests"
        client.messages = MagicMock()

        broken_content = MagicMock()
        broken_content.text = "this is not valid { json at all }"
        broken_message = MagicMock()
        broken_message.content = [broken_content]
        client.messages.create = AsyncMock(return_value=broken_message)

        result = await categorize_transaction(
            description="Unknown merchant 12345",
            amount=Decimal("99.00"),
            transaction_type="debit",
            client=client,
        )

        assert result.category == "Other"
        assert result.confidence == 0.3
        assert result.method == "ai"

    @pytest.mark.asyncio
    async def test_empty_api_key_skips_ai(self, mock_anthropic_client: MagicMock) -> None:
        """Test 7 — empty API key → method='rule', category='Other', no AI call."""
        from app.analytics.categorizer import categorize_transaction

        # mock_anthropic_client fixture already has an empty key
        result = await categorize_transaction(
            description="Mystery debit",
            amount=Decimal("50.00"),
            transaction_type="debit",
            client=mock_anthropic_client,
        )

        assert result.category == "Other"
        assert result.method == "rule"
        mock_anthropic_client.messages.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_ai_path_unknown_category_normalised_to_other(self) -> None:
        """AI returning an unknown category is silently normalised to 'Other'."""
        from app.analytics.categorizer import categorize_transaction

        client = MagicMock()
        client._api_key = "sk-test-key"
        client.api_key = "sk-test-key"
        client.messages = MagicMock()
        client.messages.create = AsyncMock(
            return_value=_make_ai_response(
                {"category": "Not A Real Category", "sub_category": "", "confidence": 0.9}
            )
        )

        result = await categorize_transaction(
            description="Some transaction",
            amount=Decimal("100.00"),
            transaction_type="debit",
            client=client,
        )

        assert result.category == "Other"
        assert result.confidence == 0.3  # reset by validator

    @pytest.mark.asyncio
    async def test_ai_path_markdown_fenced_json(self) -> None:
        """AI responses wrapped in markdown code fences are parsed correctly."""
        from app.analytics.categorizer import categorize_transaction

        client = MagicMock()
        client._api_key = "sk-test-key"
        client.api_key = "sk-test-key"
        client.messages = MagicMock()

        fenced_content = MagicMock()
        fenced_content.text = '```json\n{"category": "Groceries", "sub_category": "Supermarket", "confidence": 0.88}\n```'
        fenced_message = MagicMock()
        fenced_message.content = [fenced_content]
        client.messages.create = AsyncMock(return_value=fenced_message)

        result = await categorize_transaction(
            description="Carrefour supermarket",
            amount=Decimal("250.00"),
            transaction_type="debit",
            client=client,
        )

        assert result.category == "Groceries"
        assert result.method == "ai"


class TestCategorizeBatch:
    """Tests 8-9 — batch categorization."""

    @pytest.mark.asyncio
    async def test_batch_mixed_rule_and_ai(self) -> None:
        """Test 8 — batch with rule-matched and AI-path transactions returns correct methods."""
        from app.analytics.categorizer import categorize_batch

        tx_rule = make_transaction(
            description="ATM cash",
            amount="200.00",
            transaction_type="debit",
        )
        tx_ai = make_transaction(
            description="Mysterious charge",
            amount="75.00",
            transaction_type="debit",
        )

        client = MagicMock()
        client._api_key = "sk-test-key"
        client.api_key = "sk-test-key"
        client.messages = MagicMock()
        client.messages.create = AsyncMock(
            return_value=_make_ai_response(
                {"category": "Shopping", "sub_category": "Online", "confidence": 0.80}
            )
        )

        results = await categorize_batch([tx_rule, tx_ai], client)

        assert len(results) == 2
        rule_result = next(r for r in results if r.transaction_id == tx_rule.id)
        ai_result = next(r for r in results if r.transaction_id == tx_ai.id)

        assert rule_result.method == "rule"
        assert rule_result.category == "ATM & Cash"
        assert ai_result.method == "ai"
        assert ai_result.category == "Shopping"

    @pytest.mark.asyncio
    async def test_batch_empty_list_returns_empty(self, mock_anthropic_client: MagicMock) -> None:
        """Test 9 — empty transaction list → empty results, no API calls."""
        from app.analytics.categorizer import categorize_batch

        results = await categorize_batch([], mock_anthropic_client)

        assert results == []
        mock_anthropic_client.messages.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_batch_no_api_key_all_rule_method(self, mock_anthropic_client: MagicMock) -> None:
        """Batch with empty API key assigns method='rule' even for non-matching transactions."""
        from app.analytics.categorizer import categorize_batch

        txns = [
            make_transaction(description="Unknown charge X", amount="50.00"),
            make_transaction(description="Unknown charge Y", amount="60.00"),
        ]

        results = await categorize_batch(txns, mock_anthropic_client)

        assert all(r.method == "rule" for r in results)
        assert all(r.category == "Other" for r in results)
        mock_anthropic_client.messages.create.assert_not_called()


# ===========================================================================
# SPENDING BREAKDOWN TESTS
# ===========================================================================


class TestComputeSpendingBreakdown:
    """Tests 11-18 — spending breakdown computation."""

    def test_empty_transactions_returns_all_zeros(self) -> None:
        """Test 11 — empty list → SpendingBreakdown with zero totals."""
        from app.analytics.spending import compute_spending_breakdown

        breakdown = compute_spending_breakdown(
            transactions=[],
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
        )

        assert breakdown.total_debits == Decimal("0")
        assert breakdown.total_credits == Decimal("0")
        assert breakdown.net == Decimal("0")
        assert breakdown.by_category == []
        assert breakdown.currency == "EGP"

    def test_all_debits_income_is_zero(self) -> None:
        """Test 12 — all debit transactions → total_income=0, spending>0."""
        from app.analytics.spending import compute_spending_breakdown

        txns = [
            make_transaction(
                amount="500.00", transaction_type="debit", transaction_date=date(2026, 1, 10)
            ),
            make_transaction(
                amount="300.00", transaction_type="debit", transaction_date=date(2026, 1, 15)
            ),
        ]

        breakdown = compute_spending_breakdown(txns, date(2026, 1, 1), date(2026, 1, 31))

        assert breakdown.total_credits == Decimal("0")
        assert breakdown.total_debits == Decimal("800.00")

    def test_all_credits_spending_is_zero(self) -> None:
        """Test 13 — all credit transactions → total_spending=0, income>0."""
        from app.analytics.spending import compute_spending_breakdown

        txns = [
            make_transaction(
                amount="10000.00", transaction_type="credit", transaction_date=date(2026, 1, 5)
            ),
            make_transaction(
                amount="5000.00", transaction_type="credit", transaction_date=date(2026, 1, 25)
            ),
        ]

        breakdown = compute_spending_breakdown(txns, date(2026, 1, 1), date(2026, 1, 31))

        assert breakdown.total_debits == Decimal("0")
        assert breakdown.total_credits == Decimal("15000.00")
        assert breakdown.by_category == []

    def test_by_category_sorted_by_total_amount_desc(self) -> None:
        """Test 14 — by_category is sorted by total_amount descending."""
        from app.analytics.spending import compute_spending_breakdown

        txns = [
            make_transaction(
                amount="100.00",
                transaction_type="debit",
                category="Groceries",
                transaction_date=date(2026, 1, 1),
            ),
            make_transaction(
                amount="800.00",
                transaction_type="debit",
                category="Rent & Housing",
                transaction_date=date(2026, 1, 2),
            ),
            make_transaction(
                amount="250.00",
                transaction_type="debit",
                category="Food & Dining",
                transaction_date=date(2026, 1, 3),
            ),
        ]

        breakdown = compute_spending_breakdown(txns, date(2026, 1, 1), date(2026, 1, 31))

        amounts = [c.total for c in breakdown.by_category]
        assert amounts == sorted(amounts, reverse=True)
        assert breakdown.by_category[0].category == "Rent & Housing"

    def test_transactions_outside_period_excluded(self) -> None:
        """Test 15 — transactions outside [period_start, period_end] are ignored."""
        from app.analytics.spending import compute_spending_breakdown

        in_range = make_transaction(
            amount="200.00", transaction_type="debit", transaction_date=date(2026, 2, 15)
        )
        out_before = make_transaction(
            amount="999.00", transaction_type="debit", transaction_date=date(2026, 1, 31)
        )
        out_after = make_transaction(
            amount="999.00", transaction_type="debit", transaction_date=date(2026, 3, 1)
        )

        breakdown = compute_spending_breakdown(
            [in_range, out_before, out_after],
            period_start=date(2026, 2, 1),
            period_end=date(2026, 2, 28),
        )

        assert breakdown.total_debits == Decimal("200.00")

    def test_none_category_goes_to_uncategorized(self) -> None:
        """Test 16 — transaction with category=None is grouped as 'Uncategorized'."""
        from app.analytics.spending import compute_spending_breakdown

        txns = [
            make_transaction(
                amount="150.00",
                transaction_type="debit",
                category=None,
                transaction_date=date(2026, 1, 10),
            ),
        ]

        breakdown = compute_spending_breakdown(txns, date(2026, 1, 1), date(2026, 1, 31))

        assert len(breakdown.by_category) == 1
        assert breakdown.by_category[0].category == "Uncategorized"

    def test_percentages_sum_to_100(self) -> None:
        """Test 17 — sum of all category percentages is approximately 100%."""
        from app.analytics.spending import compute_spending_breakdown

        txns = [
            make_transaction(
                amount="400.00",
                transaction_type="debit",
                category="Groceries",
                transaction_date=date(2026, 1, 1),
            ),
            make_transaction(
                amount="300.00",
                transaction_type="debit",
                category="Food & Dining",
                transaction_date=date(2026, 1, 2),
            ),
            make_transaction(
                amount="300.00",
                transaction_type="debit",
                category="Transportation",
                transaction_date=date(2026, 1, 3),
            ),
        ]

        breakdown = compute_spending_breakdown(txns, date(2026, 1, 1), date(2026, 1, 31))

        total_pct = sum(c.percentage for c in breakdown.by_category)
        assert abs(total_pct - 100.0) < 0.1

    def test_net_equals_income_minus_spending(self) -> None:
        """Test 18 — net = total_income - total_spending."""
        from app.analytics.spending import compute_spending_breakdown

        txns = [
            make_transaction(
                amount="15000.00", transaction_type="credit", transaction_date=date(2026, 1, 1)
            ),
            make_transaction(
                amount="5000.00", transaction_type="debit", transaction_date=date(2026, 1, 10)
            ),
            make_transaction(
                amount="3000.00", transaction_type="debit", transaction_date=date(2026, 1, 20)
            ),
        ]

        breakdown = compute_spending_breakdown(txns, date(2026, 1, 1), date(2026, 1, 31))

        expected_net = breakdown.total_credits - breakdown.total_debits
        assert breakdown.net == expected_net
        assert breakdown.net == Decimal("7000.00")

    def test_period_boundary_dates_inclusive(self) -> None:
        """Transactions on exactly period_start and period_end are included."""
        from app.analytics.spending import compute_spending_breakdown

        txns = [
            make_transaction(
                amount="100.00", transaction_type="debit", transaction_date=date(2026, 1, 1)
            ),
            make_transaction(
                amount="200.00", transaction_type="debit", transaction_date=date(2026, 1, 31)
            ),
        ]

        breakdown = compute_spending_breakdown(txns, date(2026, 1, 1), date(2026, 1, 31))
        assert breakdown.total_debits == Decimal("300.00")

    def test_currency_inferred_from_first_transaction(self) -> None:
        """Currency is taken from the first transaction in the filtered set."""
        from app.analytics.spending import compute_spending_breakdown

        txns = [
            make_transaction(
                amount="100.00",
                transaction_type="debit",
                currency="USD",
                transaction_date=date(2026, 1, 5),
            ),
        ]

        breakdown = compute_spending_breakdown(txns, date(2026, 1, 1), date(2026, 1, 31))
        assert breakdown.currency == "USD"


# ===========================================================================
# TRENDS TESTS
# ===========================================================================


class TestComputeTrends:
    """Tests 19-24 — month-over-month trend computation."""

    def test_empty_transactions_returns_empty_report(self) -> None:
        """Test 19 — empty list → TrendReport with empty months, None change pcts."""
        from app.analytics.trends import compute_trends

        report = compute_trends([])

        assert report.months == []
        assert report.spending_change_pct is None
        assert report.income_change_pct is None
        assert report.avg_monthly_spend == Decimal("0")
        assert report.avg_monthly_income == Decimal("0")

    def test_single_month_no_change_pct(self) -> None:
        """Test 20 — single month → one snapshot, spending_change_pct=None."""
        from app.analytics.trends import compute_trends

        txns = [
            make_transaction(
                amount="1000.00", transaction_type="debit", transaction_date=date(2026, 1, 10)
            ),
            make_transaction(
                amount="500.00", transaction_type="debit", transaction_date=date(2026, 1, 20)
            ),
        ]

        report = compute_trends(txns)

        assert len(report.months) == 1
        assert report.months[0].year == 2026
        assert report.months[0].month == 1
        assert report.spending_change_pct is None
        assert report.income_change_pct is None

    def test_two_months_spending_change_pct(self) -> None:
        """Test 21 — two months → spending_change_pct computed correctly."""
        from app.analytics.trends import compute_trends

        txns = [
            # January: 1000 spending
            make_transaction(
                amount="1000.00", transaction_type="debit", transaction_date=date(2026, 1, 15)
            ),
            # February: 1500 spending → +50% change
            make_transaction(
                amount="1500.00", transaction_type="debit", transaction_date=date(2026, 2, 15)
            ),
        ]

        report = compute_trends(txns)

        # (1500 - 1000) / 1000 * 100 = 50.0
        assert report.spending_change_pct is not None
        assert abs(report.spending_change_pct - 50.0) < 0.01

    def test_lookback_months_limits_returned_months(self) -> None:
        """Test 22 — lookback_months=3 with 6 months of data → 3 months returned."""
        from app.analytics.trends import compute_trends

        # Create one transaction per month for 6 months
        txns = [
            make_transaction(
                amount="500.00",
                transaction_type="debit",
                transaction_date=date(2025, month, 15),
            )
            for month in range(7, 13)  # July through December 2025
        ]

        report = compute_trends(txns, lookback_months=3)

        assert len(report.months) == 3
        # Should be the 3 most recent months: Oct, Nov, Dec
        assert report.months[-1].month == 12
        assert report.months[-1].year == 2025

    def test_monthly_snapshot_fields(self) -> None:
        """Test 23 — MonthlySnapshot has year, month, total_spending, total_income, net, transaction_count, top_category."""
        from app.analytics.trends import MonthlySnapshot, compute_trends

        txns = [
            make_transaction(
                amount="300.00",
                transaction_type="debit",
                category="Food & Dining",
                transaction_date=date(2026, 3, 5),
            ),
            make_transaction(
                amount="700.00",
                transaction_type="debit",
                category="Rent & Housing",
                transaction_date=date(2026, 3, 20),
            ),
            make_transaction(
                amount="5000.00", transaction_type="credit", transaction_date=date(2026, 3, 1)
            ),
        ]

        report = compute_trends(txns, lookback_months=6)

        assert len(report.months) == 1
        snap = report.months[0]
        assert isinstance(snap, MonthlySnapshot)
        assert snap.year == 2026
        assert snap.month == 3
        assert snap.total_debits == Decimal("1000.00")
        assert snap.total_credits == Decimal("5000.00")
        assert snap.net == Decimal("4000.00")
        assert snap.transaction_count == 3
        # Rent & Housing (700) > Food & Dining (300)
        assert snap.top_category == "Rent & Housing"

    def test_avg_monthly_spending_is_mean(self) -> None:
        """Test 24 — avg_monthly_spending is the mean of all monthly totals in the window."""
        from app.analytics.trends import compute_trends

        txns = [
            make_transaction(
                amount="1000.00", transaction_type="debit", transaction_date=date(2026, 1, 15)
            ),
            make_transaction(
                amount="2000.00", transaction_type="debit", transaction_date=date(2026, 2, 15)
            ),
            make_transaction(
                amount="3000.00", transaction_type="debit", transaction_date=date(2026, 3, 15)
            ),
        ]

        report = compute_trends(txns, lookback_months=6)

        expected_avg = Decimal("6000.00") / Decimal("3")
        assert report.avg_monthly_spend == expected_avg

    def test_months_in_chronological_order(self) -> None:
        """Months list is oldest-first (chronological order)."""
        from app.analytics.trends import compute_trends

        txns = [
            make_transaction(
                amount="100.00", transaction_type="debit", transaction_date=date(2026, 3, 1)
            ),
            make_transaction(
                amount="100.00", transaction_type="debit", transaction_date=date(2026, 1, 1)
            ),
            make_transaction(
                amount="100.00", transaction_type="debit", transaction_date=date(2026, 2, 1)
            ),
        ]

        report = compute_trends(txns)

        months = [s.month for s in report.months]
        assert months == sorted(months)

    def test_spending_change_pct_none_when_previous_spending_zero(self) -> None:
        """spending_change_pct is None when previous month had zero spending (avoids div-by-zero)."""
        from app.analytics.trends import compute_trends

        txns = [
            # January: only income, no spending
            make_transaction(
                amount="10000.00", transaction_type="credit", transaction_date=date(2026, 1, 1)
            ),
            # February: spending present
            make_transaction(
                amount="500.00", transaction_type="debit", transaction_date=date(2026, 2, 15)
            ),
        ]

        report = compute_trends(txns)

        assert report.spending_change_pct is None


# ===========================================================================
# CREDIT REPORT TESTS
# ===========================================================================


class TestComputeCreditReport:
    """Tests 25-32 — credit report computation."""

    def test_no_accounts_no_loans_empty_report(self) -> None:
        """Test 25 — no accounts, no loans → empty lists, total_debt=0."""
        from app.analytics.credit import compute_credit_report

        report = compute_credit_report(accounts=[], loans=[])

        assert report.credit_cards == []
        assert report.loans == []
        assert report.total_debt == Decimal("0")
        assert report.total_monthly_obligations == Decimal("0")

    def test_credit_account_utilization_computed(self) -> None:
        """Test 26 — credit account with balance=10000 → utilization computed, status set."""
        from app.analytics.credit import compute_credit_report

        account = make_bank_account(account_type="credit", balance="10000.00")

        report = compute_credit_report(accounts=[account], loans=[])

        assert len(report.credit_cards) == 1
        card = report.credit_cards[0]
        assert card.credit_limit == Decimal("10000.00")
        # current_balance is 0 until pipeline data is available (see credit.py docstring)
        assert card.current_balance == Decimal("0")
        assert isinstance(card.utilization_pct, float)
        assert isinstance(card.status, str)

    def test_utilization_below_30_is_healthy(self) -> None:
        """Test 27 — utilization <30% → status='healthy'."""
        from app.analytics.credit import _utilization_status

        assert _utilization_status(0.0) == "healthy"
        assert _utilization_status(10.0) == "healthy"
        assert _utilization_status(29.99) == "healthy"

    def test_utilization_30_to_75_is_warning(self) -> None:
        """Test 28 — utilization 30-75% → status='warning'."""
        from app.analytics.credit import _utilization_status

        assert _utilization_status(30.0) == "warning"
        assert _utilization_status(50.0) == "warning"
        assert _utilization_status(74.99) == "warning"

    def test_utilization_above_75_is_critical(self) -> None:
        """Test 29 — utilization >75% → status='critical'."""
        from app.analytics.credit import _utilization_status

        assert _utilization_status(75.0) == "critical"
        assert _utilization_status(90.0) == "critical"
        assert _utilization_status(100.0) == "critical"

    def test_loan_months_remaining_computed(self) -> None:
        """Test 30 — loan with outstanding=60000, installment=2000 → months_remaining=30."""
        from app.analytics.credit import compute_credit_report

        loan = make_loan(outstanding="60000.00", installment="2000.00")

        report = compute_credit_report(accounts=[], loans=[loan])

        assert len(report.loans) == 1
        assert report.loans[0].months_remaining == 30

    def test_total_monthly_obligations_is_sum_of_installments(self) -> None:
        """Test 31 — total_monthly_obligations = sum of all loan installments."""
        from app.analytics.credit import compute_credit_report

        loans = [
            make_loan(outstanding="100000.00", installment="3000.00"),
            make_loan(outstanding="50000.00", installment="1500.00"),
        ]

        report = compute_credit_report(accounts=[], loans=loans)

        assert report.total_monthly_obligations == Decimal("4500.00")

    def test_total_debt_is_sum_of_outstanding_balances(self) -> None:
        """Test 32 — total_debt = sum of all outstanding_balance."""
        from app.analytics.credit import compute_credit_report

        loans = [
            make_loan(outstanding="60000.00", installment="2000.00"),
            make_loan(outstanding="40000.00", installment="1500.00"),
        ]

        report = compute_credit_report(accounts=[], loans=loans)

        assert report.total_debt == Decimal("100000.00")

    def test_non_credit_accounts_excluded_from_credit_cards(self) -> None:
        """Savings and current accounts are not included in credit_cards."""
        from app.analytics.credit import compute_credit_report

        savings = make_bank_account(account_type="savings", balance="50000.00")
        current = make_bank_account(account_type="current", balance="20000.00")
        credit = make_bank_account(account_type="credit", balance="15000.00")

        report = compute_credit_report(accounts=[savings, current, credit], loans=[])

        assert len(report.credit_cards) == 1
        assert report.credit_cards[0].credit_limit == Decimal("15000.00")

    def test_total_debt_includes_only_loan_outstanding_not_card_limit(self) -> None:
        """Credit card current_balance (zero until pipeline) contributes 0 to total_debt."""
        from app.analytics.credit import compute_credit_report

        credit_account = make_bank_account(account_type="credit", balance="50000.00")
        loan = make_loan(outstanding="30000.00", installment="1000.00")

        report = compute_credit_report(accounts=[credit_account], loans=[loan])

        # Card current_balance is 0 (see docstring convention), loan contributes 30000
        assert report.total_debt == Decimal("30000.00")

    def test_loan_months_remaining_is_ceiling_division(self) -> None:
        """months_remaining is ceiling(outstanding / installment), not floor."""
        from app.analytics.credit import _estimate_months_remaining

        # 61000 / 2000 = 30.5 → ceil = 31
        result = _estimate_months_remaining(Decimal("61000.00"), Decimal("2000.00"))
        assert result == 31

    def test_loan_zero_installment_returns_none(self) -> None:
        """Zero installment returns None for months_remaining."""
        from app.analytics.credit import _estimate_months_remaining

        result = _estimate_months_remaining(Decimal("60000.00"), Decimal("0"))
        assert result is None

    def test_loan_summary_fields(self) -> None:
        """LoanSummary has correct field values from compute_credit_report."""
        from app.analytics.credit import compute_credit_report

        payment_date = date(2026, 4, 1)
        loan = make_loan(
            outstanding="45000.00",
            installment="1500.00",
            interest_rate="0.1500",
            loan_type="mortgage",
            next_payment_date=payment_date,
        )

        report = compute_credit_report(accounts=[], loans=[loan])
        summary = report.loans[0]

        assert summary.loan_type == "mortgage"
        assert summary.outstanding_balance == Decimal("45000.00")
        assert summary.monthly_installment == Decimal("1500.00")
        assert summary.interest_rate == Decimal("0.1500")
        assert summary.next_payment_date == payment_date
        assert summary.months_remaining == 30  # 45000 / 1500 = 30 exactly

    def test_credit_utilization_fields(self) -> None:
        """CreditUtilization fields are populated correctly from BankAccount."""
        from app.analytics.credit import compute_credit_report

        account = make_bank_account(account_type="credit", balance="25000.00", bank_name="CIB")

        report = compute_credit_report(accounts=[account], loans=[])
        card = report.credit_cards[0]

        assert card.account_id == account.id
        assert card.bank_name == "CIB"
        assert card.account_number_masked == "****1234"
        assert card.credit_limit == Decimal("25000.00")
        assert card.utilization_pct == 0.0
        assert card.status == "healthy"
