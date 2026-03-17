"""Credit card utilization and loan tracking.

Pure functions only — no I/O, no side effects.  All monetary values use
Decimal to avoid floating-point rounding errors.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from app.models.db import BankAccount, Loan

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

_CAUTION_THRESHOLD = 30.0  # utilization % — below is "healthy"
_DANGER_THRESHOLD = 75.0  # utilization % — above is "critical"

# Credit health score deduction constants
_PENALTY_UTILIZATION_HIGH = 20  # any card > 80 % utilization
_PENALTY_UTILIZATION_MID = 10  # any card > 50 % utilization
_PENALTY_DTB_HIGH = 15  # debt-to-balance ratio > 0.5
_PENALTY_DTB_MID = 10  # debt-to-balance ratio > 0.3

# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class CreditUtilization:
    """Utilization snapshot for a single credit card account."""

    account_id: UUID
    bank_name: str
    account_number_masked: str
    credit_limit: Decimal
    current_balance: Decimal
    utilization_pct: float  # current_balance / credit_limit * 100
    status: str  # "healthy" | "warning" | "critical"


@dataclass
class LoanSummary:
    """High-level summary for a single loan."""

    loan_id: UUID
    loan_type: str
    outstanding_balance: Decimal
    monthly_installment: Decimal
    interest_rate: Decimal
    next_payment_date: date | None
    months_remaining: int | None  # estimated from outstanding_balance / installment


@dataclass
class CreditReport:
    """Consolidated credit overview for a user."""

    credit_cards: list[CreditUtilization]
    loans: list[LoanSummary]
    loan_summaries: list[LoanSummary]  # router-facing alias for loans
    total_debt: Decimal
    total_outstanding_debt: Decimal  # alias for total_debt
    total_balance: Decimal  # sum of non-credit account balances
    total_monthly_obligations: Decimal
    debt_to_balance_ratio: Decimal  # total_outstanding_debt / total_balance
    credit_health_score: int  # 0–100
    credit_health_label: str  # "excellent" | "good" | "fair" | "poor"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _utilization_status(pct: float) -> str:
    if pct >= _DANGER_THRESHOLD:
        return "critical"
    if pct >= _CAUTION_THRESHOLD:
        return "warning"
    return "healthy"


def _estimate_months_remaining(
    outstanding_balance: Decimal, monthly_installment: Decimal
) -> int | None:
    """Estimate months remaining as ceil(outstanding / installment).

    Returns None if the installment is zero or negative (data quality issue).
    """
    if monthly_installment <= Decimal("0"):
        return None
    # Use integer ceiling via Decimal arithmetic to stay in Decimal space
    raw = outstanding_balance / monthly_installment
    months = int(raw)
    if raw % 1 != 0:
        months += 1
    return max(months, 0)


def _compute_credit_health_score(
    credit_cards: list[CreditUtilization],
    debt_to_balance_ratio: Decimal,
) -> int:
    """Compute a 0–100 credit health score.

    Deductions applied:
    - 20 points if any credit card utilization > 80 %
    - 10 points if any credit card utilization > 50 %
    - 15 points if debt-to-balance ratio > 0.5
    - 10 points if debt-to-balance ratio > 0.3
    """
    score = 100
    for card in credit_cards:
        if card.utilization_pct > 80.0:
            score -= _PENALTY_UTILIZATION_HIGH
            break  # apply once even if multiple cards are over threshold
    for card in credit_cards:
        if card.utilization_pct > 50.0:
            score -= _PENALTY_UTILIZATION_MID
            break

    if debt_to_balance_ratio > Decimal("0.5"):
        score -= _PENALTY_DTB_HIGH
    elif debt_to_balance_ratio > Decimal("0.3"):
        score -= _PENALTY_DTB_MID

    return max(0, min(100, score))


def _credit_health_label(score: int) -> str:
    """Map a 0–100 score to a human-readable label."""
    if score >= 80:
        return "excellent"
    if score >= 60:
        return "good"
    if score >= 40:
        return "fair"
    return "poor"


# ---------------------------------------------------------------------------
# Pure computation
# ---------------------------------------------------------------------------


def compute_credit_report(
    accounts: list[BankAccount],
    loans: list[Loan],
) -> CreditReport:
    """Build a consolidated credit report from account and loan data.

    Credit cards are identified by ``account_type == "credit"``.  The account's
    ``balance`` field is interpreted as the **credit limit** (following the
    convention that the scraper stores the credit limit in ``balance`` for
    credit accounts at rest).  The current drawn balance is assumed to be zero
    until the pipeline populates richer data.

    ``total_balance`` is the sum of balances from all **non-credit** accounts
    (savings, current, etc.) passed in.  This is used to compute the
    ``debt_to_balance_ratio``.

    Args:
        accounts: All BankAccount records for the user.
        loans: All Loan records for the user.

    Returns:
        CreditReport with per-card utilization, per-loan summaries, and
        aggregate health metrics.
    """
    # ------------------------------------------------------------------ #
    # Credit card utilization
    # ------------------------------------------------------------------ #
    credit_cards: list[CreditUtilization] = []

    for account in accounts:
        if account.account_type != "credit":
            continue

        credit_limit: Decimal = account.balance
        # We treat the current drawn balance as zero until richer data is
        # available; see docstring above.
        current_balance: Decimal = Decimal("0")

        if credit_limit > Decimal("0"):
            utilization_pct = float(current_balance / credit_limit * 100)
        else:
            utilization_pct = 0.0

        credit_cards.append(
            CreditUtilization(
                account_id=account.id,
                bank_name=account.bank_name,
                account_number_masked=account.account_number_masked,
                credit_limit=credit_limit,
                current_balance=current_balance,
                utilization_pct=round(utilization_pct, 2),
                status=_utilization_status(utilization_pct),
            )
        )

    # ------------------------------------------------------------------ #
    # Loan summaries
    # ------------------------------------------------------------------ #
    loan_summaries: list[LoanSummary] = []

    for loan in loans:
        months_remaining = _estimate_months_remaining(
            loan.outstanding_balance, loan.monthly_installment
        )
        loan_summaries.append(
            LoanSummary(
                loan_id=loan.id,
                loan_type=loan.loan_type,
                outstanding_balance=loan.outstanding_balance,
                monthly_installment=loan.monthly_installment,
                interest_rate=loan.interest_rate,
                next_payment_date=loan.next_payment_date,
                months_remaining=months_remaining,
            )
        )

    # ------------------------------------------------------------------ #
    # Aggregate totals
    # ------------------------------------------------------------------ #
    total_card_debt: Decimal = sum((c.current_balance for c in credit_cards), Decimal("0"))
    total_loan_debt: Decimal = sum((ln.outstanding_balance for ln in loan_summaries), Decimal("0"))
    total_debt: Decimal = total_card_debt + total_loan_debt

    total_monthly_obligations: Decimal = sum(
        (ln.monthly_installment for ln in loan_summaries), Decimal("0")
    )

    # total_balance: sum of balances from non-credit accounts
    total_balance: Decimal = sum(
        (a.balance for a in accounts if a.account_type != "credit"),
        Decimal("0"),
    )

    # debt-to-balance ratio (guard against zero balance)
    if total_balance > Decimal("0"):
        debt_to_balance_ratio: Decimal = total_debt / total_balance
    else:
        debt_to_balance_ratio = Decimal("0")

    # Health score and label
    health_score: int = _compute_credit_health_score(credit_cards, debt_to_balance_ratio)
    health_label: str = _credit_health_label(health_score)

    return CreditReport(
        credit_cards=credit_cards,
        loans=loan_summaries,
        loan_summaries=loan_summaries,
        total_debt=total_debt,
        total_outstanding_debt=total_debt,
        total_balance=total_balance,
        total_monthly_obligations=total_monthly_obligations,
        debt_to_balance_ratio=debt_to_balance_ratio,
        credit_health_score=health_score,
        credit_health_label=health_label,
    )
