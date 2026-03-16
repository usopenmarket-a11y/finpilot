"""Spending breakdown analysis.

Pure functions only — no I/O, no side effects.  All monetary values use
Decimal to avoid floating-point rounding errors.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.models.db import Transaction

# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class CategoryBreakdown:
    """Spending aggregated for a single category."""

    category: str
    total_amount: Decimal
    transaction_count: int
    percentage: float  # share of total spending (0–100)


@dataclass
class SpendingBreakdown:
    """Full spending breakdown for a calendar period."""

    period_start: date
    period_end: date
    total_spending: Decimal
    total_income: Decimal
    net: Decimal
    by_category: list[CategoryBreakdown]  # sorted by total_amount desc
    currency: str


# ---------------------------------------------------------------------------
# Pure computation
# ---------------------------------------------------------------------------


def compute_spending_breakdown(
    transactions: list[Transaction],
    period_start: date,
    period_end: date,
) -> SpendingBreakdown:
    """Aggregate transactions into a spending breakdown for the given period.

    Only transactions whose `transaction_date` falls within [period_start,
    period_end] (inclusive) are considered.  Debit transactions are treated as
    spending; credit transactions contribute to income.

    Transactions without a category are grouped under "Uncategorized".  The
    returned `currency` is inferred from the first transaction in the filtered
    set; if no transactions exist it defaults to "EGP".

    Args:
        transactions: Full list of Transaction objects (may span many periods).
        period_start: First date of the period to analyse (inclusive).
        period_end: Last date of the period to analyse (inclusive).

    Returns:
        SpendingBreakdown with by_category sorted by total_amount descending.
    """
    # Filter to the requested window
    in_window: list[Transaction] = [
        tx for tx in transactions if period_start <= tx.transaction_date <= period_end
    ]

    currency: str = in_window[0].currency if in_window else "EGP"

    total_spending = Decimal("0")
    total_income = Decimal("0")
    category_totals: dict[str, Decimal] = defaultdict(Decimal)
    category_counts: dict[str, int] = defaultdict(int)

    for tx in in_window:
        if tx.transaction_type == "debit":
            total_spending += tx.amount
            label: str = tx.category if tx.category else "Uncategorized"
            category_totals[label] += tx.amount
            category_counts[label] += 1
        elif tx.transaction_type == "credit":
            total_income += tx.amount

    # Build per-category breakdown
    by_category: list[CategoryBreakdown] = []
    for cat, total in category_totals.items():
        percentage: float = float(total / total_spending * 100) if total_spending else 0.0
        by_category.append(
            CategoryBreakdown(
                category=cat,
                total_amount=total,
                transaction_count=category_counts[cat],
                percentage=round(percentage, 2),
            )
        )

    by_category.sort(key=lambda c: c.total_amount, reverse=True)

    return SpendingBreakdown(
        period_start=period_start,
        period_end=period_end,
        total_spending=total_spending,
        total_income=total_income,
        net=total_income - total_spending,
        by_category=by_category,
        currency=currency,
    )
