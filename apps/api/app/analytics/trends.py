"""Month-over-month trend analysis.

Pure functions only — no I/O, no side effects.  All monetary values use
Decimal to avoid floating-point rounding errors.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from app.models.db import Transaction

# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class MonthlySnapshot:
    """Aggregated statistics for a single calendar month."""

    year: int
    month: int  # 1–12
    total_spending: Decimal
    total_income: Decimal
    net: Decimal
    transaction_count: int
    top_category: str | None


@dataclass
class TrendReport:
    """Trend analysis across multiple months."""

    months: list[MonthlySnapshot]  # chronological order (oldest first)
    spending_change_pct: float | None  # latest vs previous month; None if < 2 months
    income_change_pct: float | None
    avg_monthly_spending: Decimal
    avg_monthly_income: Decimal


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _pct_change(previous: Decimal, current: Decimal) -> float | None:
    """Percentage change from previous to current.

    Returns None when previous is zero to avoid division-by-zero.
    """
    if previous == Decimal("0"):
        return None
    return float((current - previous) / previous * 100)


# ---------------------------------------------------------------------------
# Pure computation
# ---------------------------------------------------------------------------


def compute_trends(
    transactions: list[Transaction],
    lookback_months: int = 6,
) -> TrendReport:
    """Compute month-over-month spending and income trends.

    Groups all provided transactions by (year, month), computes per-month
    aggregates, then returns the most recent `lookback_months` months in
    chronological order (oldest first) alongside derived trend metrics.

    The `spending_change_pct` and `income_change_pct` fields compare the
    latest month against the immediately preceding month, and are None when
    fewer than two months of data exist.

    Args:
        transactions: Flat list of Transaction objects (any date range).
        lookback_months: How many of the most-recent months to include in
            the returned snapshot list.  Defaults to 6.

    Returns:
        TrendReport with chronologically ordered monthly snapshots.
    """
    if not transactions:
        return TrendReport(
            months=[],
            spending_change_pct=None,
            income_change_pct=None,
            avg_monthly_spending=Decimal("0"),
            avg_monthly_income=Decimal("0"),
        )

    # ------------------------------------------------------------------ #
    # Bucket transactions by (year, month)
    # ------------------------------------------------------------------ #
    spending_by_month: dict[tuple[int, int], Decimal] = defaultdict(Decimal)
    income_by_month: dict[tuple[int, int], Decimal] = defaultdict(Decimal)
    count_by_month: dict[tuple[int, int], int] = defaultdict(int)
    category_tally: dict[tuple[int, int], dict[str, Decimal]] = defaultdict(
        lambda: defaultdict(Decimal)
    )

    for tx in transactions:
        key = (tx.transaction_date.year, tx.transaction_date.month)
        count_by_month[key] += 1

        if tx.transaction_type == "debit":
            spending_by_month[key] += tx.amount
            label: str = tx.category if tx.category else "Uncategorized"
            category_tally[key][label] += tx.amount
        elif tx.transaction_type == "credit":
            income_by_month[key] += tx.amount

    # ------------------------------------------------------------------ #
    # Build MonthlySnapshot objects for ALL months that have data
    # ------------------------------------------------------------------ #
    all_keys: list[tuple[int, int]] = sorted(set(spending_by_month) | set(income_by_month))

    all_snapshots: list[MonthlySnapshot] = []
    for key in all_keys:
        year, month = key
        spending = spending_by_month.get(key, Decimal("0"))
        income = income_by_month.get(key, Decimal("0"))

        # Top category by spend for this month
        tally = category_tally.get(key, {})
        top_cat: str | None = max(tally, key=lambda k: tally[k]) if tally else None

        all_snapshots.append(
            MonthlySnapshot(
                year=year,
                month=month,
                total_spending=spending,
                total_income=income,
                net=income - spending,
                transaction_count=count_by_month.get(key, 0),
                top_category=top_cat,
            )
        )

    # ------------------------------------------------------------------ #
    # Slice to the requested lookback window
    # ------------------------------------------------------------------ #
    window: list[MonthlySnapshot] = all_snapshots[-lookback_months:]

    # ------------------------------------------------------------------ #
    # Derived metrics
    # ------------------------------------------------------------------ #
    spending_change_pct: float | None = None
    income_change_pct: float | None = None

    if len(all_snapshots) >= 2:
        latest = all_snapshots[-1]
        previous = all_snapshots[-2]
        spending_change_pct = _pct_change(previous.total_spending, latest.total_spending)
        income_change_pct = _pct_change(previous.total_income, latest.total_income)

    if window:
        avg_spending = sum((s.total_spending for s in window), Decimal("0")) / Decimal(len(window))
        avg_income = sum((s.total_income for s in window), Decimal("0")) / Decimal(len(window))
    else:
        avg_spending = Decimal("0")
        avg_income = Decimal("0")

    return TrendReport(
        months=window,
        spending_change_pct=spending_change_pct,
        income_change_pct=income_change_pct,
        avg_monthly_spending=avg_spending,
        avg_monthly_income=avg_income,
    )
