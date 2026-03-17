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
    total_debits: Decimal
    total_credits: Decimal
    net: Decimal
    transaction_count: int
    top_category: str | None


@dataclass
class TrendReport:
    """Trend analysis across multiple months."""

    months: list[MonthlySnapshot]  # chronological order (oldest first)
    monthly_points: list[MonthlySnapshot]  # alias for months — router-facing name
    spending_change_pct: float | None  # latest vs previous month; None if < 2 months
    income_change_pct: float | None
    avg_monthly_spend: Decimal
    avg_monthly_income: Decimal
    lookback_months: int  # number of months in the window
    spend_trend_direction: str  # "up" | "down" | "flat"


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
    payroll_account_ids: set[str] | None = None,
    account_ids: list[str] | None = None,
) -> TrendReport:
    """Compute month-over-month spending and income trends.

    Groups all provided transactions by (year, month), computes per-month
    aggregates, then returns the most recent ``lookback_months`` months in
    chronological order (oldest first) alongside derived trend metrics.

    The ``spending_change_pct`` and ``income_change_pct`` fields compare the
    latest month against the immediately preceding month, and are None when
    fewer than two months of data exist.

    ``spend_trend_direction`` is derived from ``spending_change_pct``:
    - "up"   if spending increased month-over-month (pct > 0)
    - "down" if spending decreased (pct < 0)
    - "flat" when there is no prior month or spending was unchanged

    Income detection follows the same logic as spending.py:
    - Credit transactions from accounts in ``payroll_account_ids`` always count
      as income.
    - Credit transactions categorised as ``"Income"`` always count.
    - When ``payroll_account_ids`` is None all credit transactions count.

    Account filtering
    -----------------
    When ``account_ids`` is provided only transactions whose ``account_id`` is
    in the set are processed.

    Args:
        transactions: Flat list of Transaction objects (any date range).
        lookback_months: How many of the most-recent months to include in
            the returned snapshot list.  Defaults to 6.
        payroll_account_ids: Optional set of account_id strings treated as
            payroll/income sources.
        account_ids: Optional list of account_id strings to restrict
            processing to.  When None all accounts are included.

    Returns:
        TrendReport with chronologically ordered monthly snapshots.
    """
    # Resolve filters
    account_filter: frozenset[str] | None = (
        frozenset(str(a) for a in account_ids) if account_ids is not None else None
    )
    payroll_set: frozenset[str] = (
        frozenset(str(a) for a in payroll_account_ids)
        if payroll_account_ids is not None
        else frozenset()
    )

    # Apply account filter
    filtered: list[Transaction] = (
        [tx for tx in transactions if str(tx.account_id) in account_filter]
        if account_filter is not None
        else transactions
    )

    if not filtered:
        return TrendReport(
            months=[],
            monthly_points=[],
            spending_change_pct=None,
            income_change_pct=None,
            avg_monthly_spend=Decimal("0"),
            avg_monthly_income=Decimal("0"),
            lookback_months=0,
            spend_trend_direction="flat",
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

    for tx in filtered:
        key = (tx.transaction_date.year, tx.transaction_date.month)
        count_by_month[key] += 1

        if tx.transaction_type == "debit":
            spending_by_month[key] += tx.amount
            label: str = tx.category if tx.category else "Uncategorized"
            category_tally[key][label] += tx.amount
        elif tx.transaction_type == "credit":
            is_payroll_account = bool(payroll_set) and str(tx.account_id) in payroll_set
            is_income_category = tx.category == "Income"
            if payroll_account_ids is not None:
                if is_payroll_account or is_income_category:
                    income_by_month[key] += tx.amount
            else:
                # No explicit payroll set — all credits count
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
                total_debits=spending,
                total_credits=income,
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
        spending_change_pct = _pct_change(previous.total_debits, latest.total_debits)
        income_change_pct = _pct_change(previous.total_credits, latest.total_credits)

    # spend_trend_direction: "up" if spending increased MoM, "down" if decreased, "flat" otherwise
    if spending_change_pct is not None and spending_change_pct > 0:
        spend_trend_direction = "up"
    elif spending_change_pct is not None and spending_change_pct < 0:
        spend_trend_direction = "down"
    else:
        spend_trend_direction = "flat"

    if window:
        avg_spending = sum((s.total_debits for s in window), Decimal("0")) / Decimal(len(window))
        avg_income = sum((s.total_credits for s in window), Decimal("0")) / Decimal(len(window))
    else:
        avg_spending = Decimal("0")
        avg_income = Decimal("0")

    return TrendReport(
        months=window,
        monthly_points=window,
        spending_change_pct=spending_change_pct,
        income_change_pct=income_change_pct,
        avg_monthly_spend=avg_spending,
        avg_monthly_income=avg_income,
        lookback_months=len(window),
        spend_trend_direction=spend_trend_direction,
    )
