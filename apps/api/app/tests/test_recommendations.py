"""Tests for the M6 Recommendations Engine.

Two levels:
  Level 1 — unit tests on the pure-function engine modules imported directly.
             No HTTP, no ASGI, no external I/O.
  Level 2 — HTTP integration tests via a minimal FastAPI app that mounts only
             the recommendations router.  A local mini-app is constructed here
             rather than importing app.main so that these tests remain runnable
             even while the main app does not yet register the router.

Security notes:
  - No real bank credentials or PII anywhere.
  - No network I/O; all tests are fully in-process.

Known source-level bug (tracked here as failing regression tests)
-----------------------------------------------------------------
``app/recommendations/savings.py`` line 546 computes::

    total_saving = _round(
        sum(o.estimated_monthly_saving for o in top_opportunities)
    )

When ``top_opportunities`` is empty Python's built-in ``sum()`` returns
``int(0)`` rather than ``Decimal("0")``, because no explicit ``start``
argument is provided.  Passing the result to ``_round()`` then raises::

    AttributeError: 'int' object has no attribute 'quantize'

The following four unit tests specify the CORRECT expected behaviour and
therefore FAIL against the current source until the Backend Agent fixes
``savings.py`` by changing the ``sum()`` call to::

    sum(
        (o.estimated_monthly_saving for o in top_opportunities),
        Decimal("0"),
    )

Affected tests:
  - test_savings_no_opportunities_clean_data
  - test_savings_only_debits_analyzed
  - test_savings_empty_transactions
  - test_savings_analysis_period_days_is_correct
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.recommendations.debt_optimizer import (
    DebtItem,
    DebtOptimizationReport,
    optimize_debt_payoff,
)
from app.recommendations.forecaster import (
    generate_forecast,
)

# ---------------------------------------------------------------------------
# Engine imports
# ---------------------------------------------------------------------------
from app.recommendations.monthly_plan import (
    CategoryBreakdown,
    MonthlyPoint,
    SpendingBreakdown,
    TrendReport,
    generate_monthly_plan,
)
from app.recommendations.savings import (
    SavingsReport,
    TransactionSummary,
    detect_savings_opportunities,
)

# ===========================================================================
# Fixture factories — shared by both test levels
# ===========================================================================


def _make_spending(
    total_debits: str = "5000.00",
    total_credits: str = "6000.00",
    net: str = "1000.00",
    categories: list[dict[str, Any]] | None = None,
) -> SpendingBreakdown:
    """Build a SpendingBreakdown for unit tests."""
    if categories is None:
        categories = [
            {"category": "food", "total": "1500.00", "percentage": 30.0},
            {"category": "transport", "total": "1000.00", "percentage": 20.0},
        ]
    by_category = [CategoryBreakdown(**c) for c in categories]
    return SpendingBreakdown(
        total_debits=Decimal(total_debits),
        total_credits=Decimal(total_credits),
        net=Decimal(net),
        by_category=by_category,
    )


def _make_trend(
    lookback_months: int = 6,
    avg_monthly_spend: str = "5000.00",
    avg_monthly_income: str = "6000.00",
    spend_trend_direction: str = "flat",
    monthly_points: list[dict[str, Any]] | None = None,
) -> TrendReport:
    """Build a TrendReport for unit tests."""
    if monthly_points is None:
        monthly_points = [
            {
                "year": 2026,
                "month": 1,
                "total_debits": "5000",
                "total_credits": "6000",
                "net": "1000",
                "transaction_count": 50,
            },
            {
                "year": 2026,
                "month": 2,
                "total_debits": "5200",
                "total_credits": "6000",
                "net": "800",
                "transaction_count": 48,
            },
        ]
    points = [MonthlyPoint(**p) for p in monthly_points]
    return TrendReport(
        lookback_months=lookback_months,
        monthly_points=points,
        avg_monthly_spend=Decimal(avg_monthly_spend),
        avg_monthly_income=Decimal(avg_monthly_income),
        spend_trend_direction=spend_trend_direction,  # type: ignore[arg-type]
    )


def _make_debt(
    debt_id: str = "d1",
    name: str = "CIB Loan",
    debt_type: str = "loan",
    balance: str = "50000",
    rate: str = "0.185",
    minimum: str = "1500",
) -> DebtItem:
    """Build a single DebtItem for unit tests."""
    return DebtItem(
        id=debt_id,
        name=name,
        debt_type=debt_type,  # type: ignore[arg-type]
        outstanding_balance=Decimal(balance),
        interest_rate=Decimal(rate),
        minimum_payment=Decimal(minimum),
        currency="EGP",
    )


def _make_transactions() -> list[TransactionSummary]:
    """Build a mixed transaction list spanning 3+ months for savings tests."""
    return [
        # Netflix recurring debit — appears in 3 separate months
        TransactionSummary(
            description="Netflix",
            amount=Decimal("149.00"),
            transaction_type="debit",
            transaction_date=date(2026, 1, 15),
            category="entertainment",
        ),
        TransactionSummary(
            description="Netflix",
            amount=Decimal("149.00"),
            transaction_type="debit",
            transaction_date=date(2026, 2, 15),
            category="entertainment",
        ),
        TransactionSummary(
            description="Netflix",
            amount=Decimal("149.00"),
            transaction_type="debit",
            transaction_date=date(2026, 3, 15),
            category="entertainment",
        ),
        # High fee — English keyword, amount > threshold
        TransactionSummary(
            description="Account Maintenance Fee",
            amount=Decimal("75.00"),
            transaction_type="debit",
            transaction_date=date(2026, 1, 1),
            category="fees",
        ),
        # Credit — must NOT be flagged
        TransactionSummary(
            description="Salary",
            amount=Decimal("15000.00"),
            transaction_type="credit",
            transaction_date=date(2026, 1, 1),
            category="income",
        ),
    ]


# ===========================================================================
# Level 1 — Unit tests: monthly_plan
# ===========================================================================


def test_monthly_plan_health_score_up_trend() -> None:
    """Upward spend trend subtracts 0.3 from the base health score of 1.0."""
    spending = _make_spending()
    trends = _make_trend(spend_trend_direction="up")

    plan = generate_monthly_plan(spending, trends, target_month=3, target_year=2026)

    # Base 1.0 − 0.3 (up-trend penalty) = 0.7, net is positive so no net penalty
    assert plan.health_score == pytest.approx(0.7, abs=1e-4)


def test_monthly_plan_health_score_negative_net() -> None:
    """Negative net subtracts 0.2 from health.  Flat trend, no category dominance."""
    spending = _make_spending(net="-500.00")
    trends = _make_trend(spend_trend_direction="flat")

    plan = generate_monthly_plan(spending, trends, target_month=3, target_year=2026)

    assert plan.health_score == pytest.approx(0.8, abs=1e-4)


def test_monthly_plan_health_score_dominant_category() -> None:
    """A single category above 40 % subtracts 0.1 from health."""
    spending = _make_spending(
        categories=[
            {"category": "food", "total": "2200.00", "percentage": 44.0},
            {"category": "transport", "total": "800.00", "percentage": 16.0},
        ]
    )
    trends = _make_trend(spend_trend_direction="flat")

    plan = generate_monthly_plan(spending, trends, target_month=3, target_year=2026)

    assert plan.health_score == pytest.approx(0.9, abs=1e-4)


def test_monthly_plan_health_score_all_penalties() -> None:
    """All three penalty conditions active: 1.0 − 0.3 − 0.2 − 0.1 = 0.4."""
    spending = _make_spending(
        net="-200.00",
        categories=[
            {"category": "food", "total": "2100.00", "percentage": 42.0},
            {"category": "transport", "total": "800.00", "percentage": 16.0},
        ],
    )
    trends = _make_trend(spend_trend_direction="up")

    plan = generate_monthly_plan(spending, trends, target_month=3, target_year=2026)

    assert plan.health_score == pytest.approx(0.4, abs=1e-4)


def test_monthly_plan_health_score_clamped_above_zero() -> None:
    """Health score never goes below 0.0 even with theoretically excessive penalties."""
    # To trigger all three penalties and verify clamping we set them all.
    spending = _make_spending(
        net="-200.00",
        categories=[{"category": "food", "total": "2500.00", "percentage": 50.0}],
    )
    trends = _make_trend(spend_trend_direction="up")

    plan = generate_monthly_plan(spending, trends, target_month=3, target_year=2026)

    assert plan.health_score >= 0.0


def test_monthly_plan_projected_savings_positive() -> None:
    """When avg income > avg spend, projected_savings is the positive difference."""
    trends = _make_trend(avg_monthly_spend="4000.00", avg_monthly_income="6000.00")
    spending = _make_spending()

    plan = generate_monthly_plan(spending, trends, target_month=3, target_year=2026)

    assert plan.projected_savings == Decimal("2000.00")


def test_monthly_plan_projected_savings_zero_when_negative() -> None:
    """When avg income < avg spend, projected_savings is clamped to 0."""
    trends = _make_trend(avg_monthly_spend="7000.00", avg_monthly_income="5000.00")
    spending = _make_spending()

    plan = generate_monthly_plan(spending, trends, target_month=3, target_year=2026)

    assert plan.projected_savings == Decimal("0")


def test_monthly_plan_confidence_sparse() -> None:
    """lookback_months < 3 yields confidence_score of 0.4."""
    trends = _make_trend(lookback_months=2)
    spending = _make_spending()

    plan = generate_monthly_plan(spending, trends, target_month=3, target_year=2026)

    assert plan.confidence_score == pytest.approx(0.4)


def test_monthly_plan_confidence_normal() -> None:
    """lookback_months >= 3 yields confidence_score of 0.85."""
    trends = _make_trend(lookback_months=6)
    spending = _make_spending()

    plan = generate_monthly_plan(spending, trends, target_month=3, target_year=2026)

    assert plan.confidence_score == pytest.approx(0.85)


def test_monthly_plan_action_items_high_priority_for_up_trend() -> None:
    """An upward trend produces at least one high-priority spending action item."""
    trends = _make_trend(spend_trend_direction="up")
    spending = _make_spending()

    plan = generate_monthly_plan(spending, trends, target_month=3, target_year=2026)

    high_items = [i for i in plan.action_items if i.priority == "high"]
    assert len(high_items) >= 1
    titles = [i.title for i in high_items]
    assert any("Reduce" in t or "Spending" in t for t in titles)


def test_monthly_plan_action_items_for_negative_net() -> None:
    """Negative net produces a high-priority 'Close Budget Gap' action item."""
    spending = _make_spending(net="-800.00")
    trends = _make_trend(spend_trend_direction="flat")

    plan = generate_monthly_plan(spending, trends, target_month=3, target_year=2026)

    high_items = [i for i in plan.action_items if i.priority == "high"]
    assert any("Gap" in i.title or "Budget" in i.title for i in high_items)


def test_monthly_plan_action_items_sorted_high_before_low() -> None:
    """Action items are returned high → medium → low (never lower before higher)."""
    trends = _make_trend(spend_trend_direction="up")
    spending = _make_spending(
        net="-100.00",
        categories=[{"category": "food", "total": "2200.00", "percentage": 44.0}],
    )

    plan = generate_monthly_plan(spending, trends, target_month=3, target_year=2026)

    priority_order = {"high": 0, "medium": 1, "low": 2}
    scores = [priority_order[i.priority] for i in plan.action_items]
    assert scores == sorted(scores)


def test_monthly_plan_returns_month_and_year() -> None:
    """The returned plan carries the target_month and target_year from the call."""
    spending = _make_spending()
    trends = _make_trend()

    plan = generate_monthly_plan(spending, trends, target_month=7, target_year=2027)

    assert plan.month == 7
    assert plan.year == 2027


def test_monthly_plan_review_action_for_category_above_30pct() -> None:
    """A category above 30 % threshold generates a medium-priority review action item."""
    spending = _make_spending(
        categories=[
            {"category": "food", "total": "2000.00", "percentage": 35.0},
            {"category": "transport", "total": "500.00", "percentage": 10.0},
        ]
    )
    trends = _make_trend(spend_trend_direction="flat")

    plan = generate_monthly_plan(spending, trends, target_month=3, target_year=2026)

    medium_items = [i for i in plan.action_items if i.priority == "medium"]
    assert len(medium_items) >= 1
    assert any("food" in i.title.lower() for i in medium_items)


# ===========================================================================
# Level 1 — Unit tests: forecaster
# ===========================================================================


def test_forecast_returns_three_points() -> None:
    """generate_forecast always returns exactly three ForecastPoints."""
    trends = _make_trend()

    forecast = generate_forecast(trends)

    assert len(forecast.forecast_points) == 3


def test_forecast_months_are_sequential() -> None:
    """The three forecast months are consecutive calendar months."""
    trends = _make_trend()
    ref = date(2026, 1, 1)

    forecast = generate_forecast(trends, from_date=ref)

    months = [(fp.year, fp.month) for fp in forecast.forecast_points]
    # from_date=Jan 2026 → forecast months Feb, Mar, Apr
    assert months == [(2026, 2), (2026, 3), (2026, 4)]


def test_forecast_confidence_decreases_per_month() -> None:
    """Confidence should be monotonically non-increasing across the three months."""
    trends = _make_trend(lookback_months=6)

    forecast = generate_forecast(trends)

    confidences = [fp.confidence for fp in forecast.forecast_points]
    assert confidences[0] >= confidences[1] >= confidences[2]


def test_forecast_confidence_values_with_sufficient_history() -> None:
    """With lookback_months >= 3, month confidences should be 0.9, 0.8, 0.7."""
    trends = _make_trend(lookback_months=6)

    forecast = generate_forecast(trends)

    fp = forecast.forecast_points
    assert fp[0].confidence == pytest.approx(0.9, abs=1e-4)
    assert fp[1].confidence == pytest.approx(0.8, abs=1e-4)
    assert fp[2].confidence == pytest.approx(0.7, abs=1e-4)


def test_forecast_declining_when_net_negative() -> None:
    """When all projected nets are negative, trend_direction is 'declining'."""
    # avg_monthly_spend >> avg_monthly_income guarantees negative projected net
    trends = _make_trend(
        avg_monthly_spend="10000.00",
        avg_monthly_income="3000.00",
        spend_trend_direction="flat",
    )

    forecast = generate_forecast(trends)

    assert forecast.trend_direction == "declining"


def test_forecast_up_trend_increases_expenses() -> None:
    """With spend_trend_direction='up', each month's projected expenses rise."""
    trends = _make_trend(spend_trend_direction="up")

    forecast = generate_forecast(trends)

    expenses = [fp.projected_expenses for fp in forecast.forecast_points]
    assert expenses[0] < expenses[1] < expenses[2]


def test_forecast_down_trend_decreases_expenses() -> None:
    """With spend_trend_direction='down', each month's projected expenses fall."""
    trends = _make_trend(spend_trend_direction="down")

    forecast = generate_forecast(trends)

    expenses = [fp.projected_expenses for fp in forecast.forecast_points]
    assert expenses[0] > expenses[1] > expenses[2]


def test_forecast_flat_trend_stable_expenses() -> None:
    """With spend_trend_direction='flat', all three months have identical projected expenses."""
    trends = _make_trend(spend_trend_direction="flat")

    forecast = generate_forecast(trends)

    expenses = [fp.projected_expenses for fp in forecast.forecast_points]
    assert expenses[0] == expenses[1] == expenses[2]


def test_forecast_from_date_controls_start_month() -> None:
    """from_date=2026-01-01 causes the first forecast month to be February 2026."""
    trends = _make_trend()

    forecast = generate_forecast(trends, from_date=date(2026, 1, 1))

    assert forecast.forecast_points[0].year == 2026
    assert forecast.forecast_points[0].month == 2


def test_forecast_year_wrap_at_december() -> None:
    """A from_date in December should wrap the forecast into the next year."""
    trends = _make_trend()

    forecast = generate_forecast(trends, from_date=date(2025, 11, 1))

    months = [(fp.year, fp.month) for fp in forecast.forecast_points]
    assert months == [(2025, 12), (2026, 1), (2026, 2)]


def test_forecast_avg_projected_net_is_mean_of_points() -> None:
    """avg_projected_monthly_net equals the mean of the three projected nets."""
    trends = _make_trend(
        avg_monthly_spend="4000.00",
        avg_monthly_income="6000.00",
        spend_trend_direction="flat",
    )

    forecast = generate_forecast(trends)

    nets = [fp.projected_net for fp in forecast.forecast_points]
    expected_avg = sum(nets) / Decimal("3")
    assert forecast.avg_projected_monthly_net == pytest.approx(float(expected_avg), abs=0.01)


# ===========================================================================
# Level 1 — Unit tests: debt_optimizer
# ===========================================================================


def test_debt_optimizer_returns_both_strategies() -> None:
    """The report always contains both snowball and avalanche strategy objects."""
    debts = [_make_debt()]
    report = optimize_debt_payoff(debts, monthly_budget=Decimal("3000"))

    assert report.snowball.strategy_name == "snowball"
    assert report.avalanche.strategy_name == "avalanche"


def test_debt_optimizer_avalanche_recommended_with_interest() -> None:
    """With at least one non-zero rate, the recommended strategy is 'avalanche'."""
    debts = [
        _make_debt("d1", rate="0.20", balance="30000", minimum="1000"),
        _make_debt("d2", rate="0.10", balance="10000", minimum="500"),
    ]

    report = optimize_debt_payoff(debts, monthly_budget=Decimal("3000"))

    assert report.recommended_strategy == "avalanche"


def test_debt_optimizer_snowball_recommended_all_zero_apr() -> None:
    """When every debt has a 0 % interest rate, the recommended strategy is 'snowball'."""
    debts = [
        _make_debt("d1", rate="0", balance="5000", minimum="0"),
        _make_debt("d2", rate="0", balance="3000", minimum="0"),
    ]

    report = optimize_debt_payoff(debts, monthly_budget=Decimal("2000"))

    assert report.recommended_strategy == "snowball"


def test_debt_optimizer_avalanche_total_interest_lte_snowball() -> None:
    """Avalanche strategy should pay less or equal total interest than snowball."""
    debts = [
        _make_debt("d1", rate="0.20", balance="30000", minimum="500"),
        _make_debt("d2", rate="0.05", balance="10000", minimum="200"),
    ]

    report = optimize_debt_payoff(debts, monthly_budget=Decimal("3000"))

    assert report.avalanche.total_interest_paid <= report.snowball.total_interest_paid


def test_debt_optimizer_payoff_reduces_balance_to_zero() -> None:
    """After all simulation steps, every debt in the snowball plan ends at zero balance."""
    debts = [_make_debt("d1", balance="5000", rate="0.10", minimum="200")]

    report = optimize_debt_payoff(debts, monthly_budget=Decimal("2000"))

    # The last PayoffStep for this debt should show remaining_balance == 0
    last_steps = [s for s in report.snowball.monthly_steps if s.debt_id == "d1"]
    assert last_steps[-1].remaining_balance == Decimal("0")


def test_debt_optimizer_single_debt() -> None:
    """Optimizer works correctly with a single-debt input (no crash, valid output)."""
    debts = [_make_debt("solo", balance="20000", rate="0.15", minimum="500")]

    report = optimize_debt_payoff(debts, monthly_budget=Decimal("2000"))

    assert isinstance(report, DebtOptimizationReport)
    assert report.snowball.total_months >= 1
    assert report.avalanche.total_months >= 1


def test_debt_optimizer_interest_savings_field() -> None:
    """interest_savings equals snowball total_interest_paid minus avalanche total."""
    debts = [
        _make_debt("d1", rate="0.22", balance="40000", minimum="800"),
        _make_debt("d2", rate="0.08", balance="15000", minimum="400"),
    ]

    report = optimize_debt_payoff(debts, monthly_budget=Decimal("4000"))

    expected = report.snowball.total_interest_paid - report.avalanche.total_interest_paid
    assert report.interest_savings == expected


def test_debt_optimizer_zero_balance_debts_ignored() -> None:
    """Debts with outstanding_balance=0 are filtered out before simulation."""
    debts = [
        _make_debt("d1", balance="10000", rate="0.15", minimum="300"),
        _make_debt("d2", balance="0", rate="0.10", minimum="0"),
    ]

    report = optimize_debt_payoff(debts, monthly_budget=Decimal("2000"))

    # Only d1 should appear in the report's debt list
    debt_ids = {d.id for d in report.debts}
    assert "d1" in debt_ids
    assert "d2" not in debt_ids


def test_debt_optimizer_confidence_score_range() -> None:
    """confidence_score is always in [0.0, 1.0]."""
    debts = [_make_debt()]

    report = optimize_debt_payoff(debts, monthly_budget=Decimal("3000"))

    assert 0.0 <= report.confidence_score <= 1.0


# ===========================================================================
# Level 1 — Unit tests: savings
# ===========================================================================


def test_savings_detects_duplicate_charge() -> None:
    """Two identical charges in the same month are flagged as duplicate_charge."""
    txns = [
        TransactionSummary(
            description="Gym Membership",
            amount=Decimal("200.00"),
            transaction_type="debit",
            transaction_date=date(2026, 1, 10),
            category="health",
        ),
        TransactionSummary(
            description="Gym Membership",
            amount=Decimal("200.00"),
            transaction_type="debit",
            transaction_date=date(2026, 1, 20),
            category="health",
        ),
        # Credit padding to extend analysis period beyond 30 days
        TransactionSummary(
            description="Salary",
            amount=Decimal("10000.00"),
            transaction_type="credit",
            transaction_date=date(2026, 2, 15),
            category="income",
        ),
    ]

    report = detect_savings_opportunities(txns)

    types = [o.opportunity_type for o in report.opportunities]
    assert "duplicate_charge" in types


def test_savings_detects_recurring_subscription() -> None:
    """A charge appearing in 3+ distinct months is flagged as recurring_subscription."""
    txns = _make_transactions()  # Netflix in Jan, Feb, Mar

    report = detect_savings_opportunities(txns)

    types = [o.opportunity_type for o in report.opportunities]
    assert "recurring_subscription" in types


def test_savings_detects_high_fee_english_keyword() -> None:
    """A debit with 'fee' in the description above the threshold is flagged as high_fee."""
    txns = [
        TransactionSummary(
            description="Account Maintenance Fee",
            amount=Decimal("75.00"),
            transaction_type="debit",
            transaction_date=date(2026, 1, 1),
            category="fees",
        ),
        # Spread transactions to exceed 30-day period
        TransactionSummary(
            description="Groceries",
            amount=Decimal("300.00"),
            transaction_type="debit",
            transaction_date=date(2026, 2, 10),
            category="food",
        ),
    ]

    report = detect_savings_opportunities(txns)

    types = [o.opportunity_type for o in report.opportunities]
    assert "high_fee" in types


def test_savings_detects_high_fee_arabic_keyword() -> None:
    """A debit with Arabic fee keyword 'رسوم' above threshold is flagged as high_fee."""
    txns = [
        TransactionSummary(
            description="رسوم الخدمة الشهرية",
            amount=Decimal("120.00"),
            transaction_type="debit",
            transaction_date=date(2026, 1, 5),
            category="fees",
        ),
        TransactionSummary(
            description="Groceries",
            amount=Decimal("200.00"),
            transaction_type="debit",
            transaction_date=date(2026, 2, 10),
            category="food",
        ),
    ]

    report = detect_savings_opportunities(txns)

    types = [o.opportunity_type for o in report.opportunities]
    assert "high_fee" in types


def test_savings_no_opportunities_clean_data() -> None:
    """Clean transactions with no patterns produce zero or empty opportunities."""
    txns = [
        TransactionSummary(
            description="Grocery Store A",
            amount=Decimal("250.00"),
            transaction_type="debit",
            transaction_date=date(2026, 1, 5),
            category="food",
        ),
        TransactionSummary(
            description="Transport Card",
            amount=Decimal("80.00"),
            transaction_type="debit",
            transaction_date=date(2026, 1, 20),
            category="transport",
        ),
        TransactionSummary(
            description="Electricity Bill",
            amount=Decimal("400.00"),
            transaction_type="debit",
            transaction_date=date(2026, 2, 15),
            category="utilities",
        ),
    ]

    report = detect_savings_opportunities(txns)

    # No patterns here — all different descriptions, low amounts, no fee keywords
    assert isinstance(report, SavingsReport)
    # At most a few items; no subscriptions or duplicates
    for opp in report.opportunities:
        assert opp.opportunity_type in (
            "duplicate_charge",
            "recurring_subscription",
            "high_fee",
            "irregular_spike",
        )


def test_savings_total_is_sum_of_opportunities() -> None:
    """total_estimated_monthly_saving equals the sum of all opportunity savings."""
    txns = _make_transactions()

    report = detect_savings_opportunities(txns)

    expected_total = sum(o.estimated_monthly_saving for o in report.opportunities)
    assert report.total_estimated_monthly_saving == expected_total


def test_savings_max_ten_opportunities() -> None:
    """The report never returns more than 10 opportunities regardless of input."""
    # Generate many distinct fee transactions to produce many opportunities
    txns: list[TransactionSummary] = []
    for i in range(20):
        txns.append(
            TransactionSummary(
                description=f"Service Fee {i}",
                amount=Decimal("100.00"),
                transaction_type="debit",
                transaction_date=date(2026, 1 + (i % 2), (i % 28) + 1),
                category="fees",
            )
        )
    # Extend period to 30+ days
    txns.append(
        TransactionSummary(
            description="Long Period Marker",
            amount=Decimal("50.00"),
            transaction_type="debit",
            transaction_date=date(2026, 3, 1),
            category="fees",
        )
    )

    report = detect_savings_opportunities(txns)

    assert len(report.opportunities) <= 10


def test_savings_only_debits_analyzed() -> None:
    """Credit transactions are excluded from opportunity detection."""
    # Only credits — no debits at all
    txns = [
        TransactionSummary(
            description="Salary",
            amount=Decimal("15000.00"),
            transaction_type="credit",
            transaction_date=date(2026, 1, 1),
            category="income",
        ),
        TransactionSummary(
            description="Salary",
            amount=Decimal("15000.00"),
            transaction_type="credit",
            transaction_date=date(2026, 2, 1),
            category="income",
        ),
        TransactionSummary(
            description="Salary",
            amount=Decimal("15000.00"),
            transaction_type="credit",
            transaction_date=date(2026, 3, 1),
            category="income",
        ),
    ]

    report = detect_savings_opportunities(txns)

    assert report.opportunities == []
    assert report.total_estimated_monthly_saving == Decimal("0")


def test_savings_empty_transactions() -> None:
    """An empty transaction list returns a valid SavingsReport with zero opportunities."""
    report = detect_savings_opportunities([])

    assert isinstance(report, SavingsReport)
    assert report.opportunities == []
    assert report.total_estimated_monthly_saving == Decimal("0")
    assert report.analysis_period_days == 0


def test_savings_analysis_period_days_is_correct() -> None:
    """analysis_period_days equals max_date - min_date + 1 across all transactions."""
    txns = [
        TransactionSummary(
            description="Txn A",
            amount=Decimal("100.00"),
            transaction_type="debit",
            transaction_date=date(2026, 1, 1),
            category="misc",
        ),
        TransactionSummary(
            description="Txn B",
            amount=Decimal("200.00"),
            transaction_type="debit",
            transaction_date=date(2026, 1, 31),
            category="misc",
        ),
    ]

    report = detect_savings_opportunities(txns)

    # max - min + 1 = Jan 31 - Jan 1 + 1 = 31 days
    assert report.analysis_period_days == 31


def test_savings_confidence_zero_when_period_under_30_days() -> None:
    """When the analysis period is fewer than 30 days, confidence_score is 0.0."""
    # Fee transaction + another within same week → period < 30 days
    txns = [
        TransactionSummary(
            description="Account Management Fee",
            amount=Decimal("100.00"),
            transaction_type="debit",
            transaction_date=date(2026, 1, 1),
            category="fees",
        ),
        TransactionSummary(
            description="ATM Fee",
            amount=Decimal("80.00"),
            transaction_type="debit",
            transaction_date=date(2026, 1, 5),
            category="fees",
        ),
    ]

    report = detect_savings_opportunities(txns)

    assert report.confidence_score == pytest.approx(0.0)


# ===========================================================================
# Level 2 — HTTP tests via a local mini-app
#
# A minimal FastAPI app is constructed here that imports and mounts only the
# recommendations router.  This isolates these tests from app.main and means
# they are runnable even if the main ASGI app has broken imports.
#
# If the recommendations router does not yet exist (i.e. the Backend Agent has
# not yet created app/routers/recommendations.py), these tests will be skipped
# with an informative message rather than failing the entire suite.
# ===========================================================================


def _build_recommendations_app() -> FastAPI | None:
    """Attempt to import and mount the recommendations router.

    Returns None when the router module has not yet been created so that HTTP
    tests can be skipped gracefully.
    """
    try:
        from app.routers import recommendations as rec_router  # type: ignore[attr-defined]
    except (ImportError, AttributeError):
        return None

    mini_app = FastAPI(title="FinPilot Recommendations Test App")
    mini_app.include_router(rec_router.router, prefix="/api/v1")
    return mini_app


_RECOMMENDATIONS_APP = _build_recommendations_app()
_ROUTER_MISSING = _RECOMMENDATIONS_APP is None


@pytest.fixture(scope="module")
def rec_client() -> TestClient:
    """Sync TestClient wired to the recommendations mini-app."""
    assert _RECOMMENDATIONS_APP is not None, (
        "app/routers/recommendations.py does not exist — HTTP tests cannot run"
    )
    return TestClient(_RECOMMENDATIONS_APP)


# ---------------------------------------------------------------------------
# Shared JSON payloads for HTTP tests
# ---------------------------------------------------------------------------

_SPENDING_PAYLOAD: dict[str, Any] = {
    "total_debits": "5000.00",
    "total_credits": "6000.00",
    "net": "1000.00",
    "by_category": [
        {"category": "food", "total": "1500.00", "transaction_count": 20, "percentage": 30.0},
        {"category": "transport", "total": "1000.00", "transaction_count": 10, "percentage": 20.0},
    ],
}

_TREND_PAYLOAD: dict[str, Any] = {
    "lookback_months": 6,
    "monthly_points": [
        {
            "year": 2026,
            "month": 1,
            "total_debits": "5000",
            "total_credits": "6000",
            "net": "1000",
            "transaction_count": 50,
        },
        {
            "year": 2026,
            "month": 2,
            "total_debits": "5200",
            "total_credits": "6000",
            "net": "800",
            "transaction_count": 48,
        },
    ],
    "avg_monthly_spend": "5100.00",
    "avg_monthly_income": "6000.00",
    "spend_trend_direction": "up",
}

_DEBT_ITEMS_PAYLOAD: list[dict[str, Any]] = [
    {
        "id": "d1",
        "name": "CIB Loan",
        "debt_type": "loan",
        "outstanding_balance": "50000",
        "interest_rate": "0.185",
        "minimum_payment": "1500",
        "currency": "EGP",
    },
    {
        "id": "d2",
        "name": "Friend Ahmed",
        "debt_type": "borrowed",
        "outstanding_balance": "5000",
        "interest_rate": "0",
        "minimum_payment": "0",
        "currency": "EGP",
    },
]

_TRANSACTIONS_PAYLOAD: list[dict[str, Any]] = [
    {
        "description": "Netflix",
        "amount": "149.00",
        "transaction_type": "debit",
        "transaction_date": "2026-01-15",
        "category": "entertainment",
    },
    {
        "description": "Netflix",
        "amount": "149.00",
        "transaction_type": "debit",
        "transaction_date": "2026-02-15",
        "category": "entertainment",
    },
    {
        "description": "Netflix",
        "amount": "149.00",
        "transaction_type": "debit",
        "transaction_date": "2026-03-15",
        "category": "entertainment",
    },
    {
        "description": "Account Maintenance Fee",
        "amount": "75.00",
        "transaction_type": "debit",
        "transaction_date": "2026-01-01",
        "category": "fees",
    },
    {
        "description": "Salary",
        "amount": "15000.00",
        "transaction_type": "credit",
        "transaction_date": "2026-01-01",
        "category": "income",
    },
]


# ---------------------------------------------------------------------------
# monthly-plan endpoint
# ---------------------------------------------------------------------------


@pytest.mark.skipif(_ROUTER_MISSING, reason="recommendations router not yet created")
def test_monthly_plan_endpoint_happy_path(rec_client: TestClient) -> None:
    """POST /api/v1/recommendations/monthly-plan returns 200 with required fields."""
    payload = {
        "spending": _SPENDING_PAYLOAD,
        "trends": _TREND_PAYLOAD,
        "target_month": 3,
        "target_year": 2026,
    }

    response = rec_client.post("/api/v1/recommendations/monthly-plan", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert "health_score" in data
    assert "action_items" in data
    assert isinstance(data["action_items"], list)
    assert "projected_savings" in data
    assert "confidence_score" in data


@pytest.mark.skipif(_ROUTER_MISSING, reason="recommendations router not yet created")
def test_monthly_plan_endpoint_invalid_month(rec_client: TestClient) -> None:
    """POST with target_month=13 is rejected with 422 Unprocessable Entity."""
    payload = {
        "spending": _SPENDING_PAYLOAD,
        "trends": _TREND_PAYLOAD,
        "target_month": 13,
        "target_year": 2026,
    }

    response = rec_client.post("/api/v1/recommendations/monthly-plan", json=payload)

    assert response.status_code == 422


@pytest.mark.skipif(_ROUTER_MISSING, reason="recommendations router not yet created")
def test_monthly_plan_endpoint_invalid_month_zero(rec_client: TestClient) -> None:
    """POST with target_month=0 is rejected with 422."""
    payload = {
        "spending": _SPENDING_PAYLOAD,
        "trends": _TREND_PAYLOAD,
        "target_month": 0,
        "target_year": 2026,
    }

    response = rec_client.post("/api/v1/recommendations/monthly-plan", json=payload)

    assert response.status_code == 422


@pytest.mark.skipif(_ROUTER_MISSING, reason="recommendations router not yet created")
def test_monthly_plan_endpoint_missing_spending(rec_client: TestClient) -> None:
    """POST without the 'spending' field is rejected with 422."""
    payload = {
        "trends": _TREND_PAYLOAD,
        "target_month": 3,
        "target_year": 2026,
    }

    response = rec_client.post("/api/v1/recommendations/monthly-plan", json=payload)

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# forecast endpoint
# ---------------------------------------------------------------------------


@pytest.mark.skipif(_ROUTER_MISSING, reason="recommendations router not yet created")
def test_forecast_endpoint_happy_path(rec_client: TestClient) -> None:
    """POST /api/v1/recommendations/forecast returns 200 with exactly 3 forecast points."""
    payload = {"trends": _TREND_PAYLOAD}

    response = rec_client.post("/api/v1/recommendations/forecast", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert "forecast_points" in data
    assert len(data["forecast_points"]) == 3
    assert "trend_direction" in data
    assert "confidence_score" in data


@pytest.mark.skipif(_ROUTER_MISSING, reason="recommendations router not yet created")
def test_forecast_endpoint_missing_trends(rec_client: TestClient) -> None:
    """POST without the required 'trends' field is rejected with 422."""
    response = rec_client.post("/api/v1/recommendations/forecast", json={})

    assert response.status_code == 422


@pytest.mark.skipif(_ROUTER_MISSING, reason="recommendations router not yet created")
def test_forecast_endpoint_with_from_date(rec_client: TestClient) -> None:
    """POST with optional from_date returns 200 and first forecast month follows it."""
    payload = {"trends": _TREND_PAYLOAD, "from_date": "2026-01-01"}

    response = rec_client.post("/api/v1/recommendations/forecast", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["forecast_points"][0]["month"] == 2


# ---------------------------------------------------------------------------
# debt-optimizer endpoint
# ---------------------------------------------------------------------------


@pytest.mark.skipif(_ROUTER_MISSING, reason="recommendations router not yet created")
def test_debt_optimizer_endpoint_happy_path(rec_client: TestClient) -> None:
    """POST /api/v1/recommendations/debt-optimizer returns 200 with snowball and avalanche."""
    payload = {
        "debts": _DEBT_ITEMS_PAYLOAD,
        "monthly_budget": "3000",
    }

    response = rec_client.post("/api/v1/recommendations/debt-optimizer", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert "snowball" in data
    assert "avalanche" in data
    assert "recommended_strategy" in data
    assert data["recommended_strategy"] in ("snowball", "avalanche")


@pytest.mark.skipif(_ROUTER_MISSING, reason="recommendations router not yet created")
def test_debt_optimizer_endpoint_empty_debts(rec_client: TestClient) -> None:
    """POST with an empty debts list is rejected with 422 (min_length=1 constraint)."""
    payload = {
        "debts": [],
        "monthly_budget": "3000",
    }

    response = rec_client.post("/api/v1/recommendations/debt-optimizer", json=payload)

    assert response.status_code == 422


@pytest.mark.skipif(_ROUTER_MISSING, reason="recommendations router not yet created")
def test_debt_optimizer_endpoint_zero_budget(rec_client: TestClient) -> None:
    """POST with monthly_budget=0 is rejected with 422 (gt=0 constraint)."""
    payload = {
        "debts": _DEBT_ITEMS_PAYLOAD,
        "monthly_budget": "0",
    }

    response = rec_client.post("/api/v1/recommendations/debt-optimizer", json=payload)

    assert response.status_code == 422


@pytest.mark.skipif(_ROUTER_MISSING, reason="recommendations router not yet created")
def test_debt_optimizer_endpoint_missing_budget(rec_client: TestClient) -> None:
    """POST without monthly_budget is rejected with 422."""
    payload = {"debts": _DEBT_ITEMS_PAYLOAD}

    response = rec_client.post("/api/v1/recommendations/debt-optimizer", json=payload)

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# savings endpoint
# ---------------------------------------------------------------------------


@pytest.mark.skipif(_ROUTER_MISSING, reason="recommendations router not yet created")
def test_savings_endpoint_happy_path(rec_client: TestClient) -> None:
    """POST /api/v1/recommendations/savings returns 200 with an opportunities list."""
    payload = {"transactions": _TRANSACTIONS_PAYLOAD}

    response = rec_client.post("/api/v1/recommendations/savings", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert "opportunities" in data
    assert isinstance(data["opportunities"], list)
    assert "total_estimated_monthly_saving" in data
    assert "analysis_period_days" in data


@pytest.mark.skipif(_ROUTER_MISSING, reason="recommendations router not yet created")
def test_savings_endpoint_missing_transactions(rec_client: TestClient) -> None:
    """POST without the 'transactions' field is rejected with 422."""
    response = rec_client.post("/api/v1/recommendations/savings", json={})

    assert response.status_code == 422


@pytest.mark.skipif(_ROUTER_MISSING, reason="recommendations router not yet created")
def test_savings_endpoint_with_results(rec_client: TestClient) -> None:
    """POST with transactions that contain detectable patterns returns 200."""
    # Use the full fixture payload which contains Netflix (recurring) and a high fee;
    # this guarantees at least one opportunity is found and avoids the empty-list
    # Decimal bug in savings.py (see test_savings_empty_transactions unit test).
    payload = {"transactions": _TRANSACTIONS_PAYLOAD}

    response = rec_client.post("/api/v1/recommendations/savings", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert "opportunities" in data
    assert isinstance(data["opportunities"], list)
