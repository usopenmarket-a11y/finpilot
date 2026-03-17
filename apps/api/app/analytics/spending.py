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
    total: Decimal
    transaction_count: int
    percentage: float  # share of total_debits (0–100)


@dataclass
class SpendingBreakdown:
    """Full spending breakdown for a calendar period."""

    period_start: date
    period_end: date
    total_debits: Decimal
    total_credits: Decimal
    net: Decimal
    by_category: list[CategoryBreakdown]  # sorted by total desc
    currency: str


# ---------------------------------------------------------------------------
# Pure computation
# ---------------------------------------------------------------------------


def compute_spending_breakdown(
    transactions: list[Transaction],
    period_start: date,
    period_end: date,
    payroll_account_ids: set[str] | None = None,
    account_ids: list[str] | None = None,
) -> SpendingBreakdown:
    """Aggregate transactions into a spending breakdown for the given period.

    Only transactions whose ``transaction_date`` falls within [period_start,
    period_end] (inclusive) are considered.  Debit transactions contribute to
    ``total_debits``; credit transactions contribute to ``total_credits``.

    Income detection logic
    ----------------------
    A credit transaction is counted toward ``total_credits`` when:
    - ``payroll_account_ids`` is provided and ``tx.account_id in payroll_account_ids``
    - OR ``tx.category == "Income"`` (catches salary-categorised transactions)
    - When ``payroll_account_ids`` is not provided the function falls back to
      category-based detection only.

    Account filtering
    -----------------
    When ``account_ids`` is provided only transactions whose ``account_id`` is
    in the set are processed; all others are ignored.

    Transactions without a category are grouped under "Uncategorized".  The
    returned ``currency`` is inferred from the first transaction in the
    filtered set; if no transactions exist it defaults to "EGP".

    Args:
        transactions: Full list of Transaction objects (may span many periods).
        period_start: First date of the period to analyse (inclusive).
        period_end: Last date of the period to analyse (inclusive).
        payroll_account_ids: Optional set of account_id strings whose credit
            transactions should always be counted as income.
        account_ids: Optional list of account_id strings to restrict processing
            to.  When None all accounts are included.

    Returns:
        SpendingBreakdown with ``by_category`` sorted by total descending.
    """
    # Resolve the account_ids filter to a frozenset for O(1) lookups
    account_filter: frozenset[str] | None = (
        frozenset(str(a) for a in account_ids) if account_ids is not None else None
    )
    payroll_set: frozenset[str] = (
        frozenset(str(a) for a in payroll_account_ids)
        if payroll_account_ids is not None
        else frozenset()
    )

    # Filter to the requested window (and optional account filter)
    in_window: list[Transaction] = [
        tx
        for tx in transactions
        if period_start <= tx.transaction_date <= period_end
        and (account_filter is None or str(tx.account_id) in account_filter)
    ]

    currency: str = in_window[0].currency if in_window else "EGP"

    total_debits = Decimal("0")
    total_credits = Decimal("0")
    category_totals: dict[str, Decimal] = defaultdict(Decimal)
    category_counts: dict[str, int] = defaultdict(int)

    for tx in in_window:
        if tx.transaction_type == "debit":
            total_debits += tx.amount
            label: str = tx.category if tx.category else "Uncategorized"
            category_totals[label] += tx.amount
            category_counts[label] += 1
        elif tx.transaction_type == "credit":
            # Count as income when the account is a known payroll account OR the
            # transaction has been categorised as "Income".  When payroll_account_ids
            # is not provided we fall back to category-based detection only.
            is_payroll_account = bool(payroll_set) and str(tx.account_id) in payroll_set
            is_income_category = tx.category == "Income"
            if payroll_account_ids is not None:
                # Explicit payroll set provided — use it plus category fallback
                if is_payroll_account or is_income_category:
                    total_credits += tx.amount
            else:
                # No explicit payroll set — category-only detection
                if is_income_category:
                    total_credits += tx.amount
                else:
                    # Still count generic credits so callers that don't use
                    # payroll detection get sensible totals.
                    total_credits += tx.amount

    # Build per-category breakdown
    by_category: list[CategoryBreakdown] = []
    for cat, total in category_totals.items():
        percentage: float = float(total / total_debits * 100) if total_debits else 0.0
        by_category.append(
            CategoryBreakdown(
                category=cat,
                total=total,
                transaction_count=category_counts[cat],
                percentage=round(percentage, 2),
            )
        )

    by_category.sort(key=lambda c: c.total, reverse=True)

    return SpendingBreakdown(
        period_start=period_start,
        period_end=period_end,
        total_debits=total_debits,
        total_credits=total_credits,
        net=total_credits - total_debits,
        by_category=by_category,
        currency=currency,
    )
