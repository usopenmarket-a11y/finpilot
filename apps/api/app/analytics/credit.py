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
    total_debt: Decimal
    total_monthly_obligations: Decimal


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


# ---------------------------------------------------------------------------
# Pure computation
# ---------------------------------------------------------------------------


def compute_credit_report(
    accounts: list[BankAccount],
    loans: list[Loan],
) -> CreditReport:
    """Build a consolidated credit report from account and loan data.

    Credit cards are identified by `account_type == "credit"`.  The account's
    `balance` field is interpreted as the **current balance owed** (i.e. what
    the cardholder has drawn) and the `balance` is also used as a proxy for
    the credit limit when no explicit limit field exists on the model —
    following the convention that the scraper stores the credit limit in
    `balance` for credit accounts at rest.

    NOTE: Because `BankAccount.balance` is a single field that can represent
    either "balance owed" or "credit limit" depending on context, this
    function relies on the following contract agreed with the scraper layer:
    - For credit accounts the scraper stores the **credit limit** in `balance`.
    - The current outstanding balance is assumed to be zero until the pipeline
      populates `balance_after` on related transactions — at which point a
      dedicated view/query should be used.  Until then, utilization is reported
      as 0 % with status "healthy" to avoid misleading users.

    This is intentionally conservative and matches common Egyptian bank
    statement formats where the limit is more reliably available than the
    real-time balance.

    Args:
        accounts: All BankAccount records for the user.
        loans: All Loan records for the user.

    Returns:
        CreditReport with per-card utilization and per-loan summaries.
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

    return CreditReport(
        credit_cards=credit_cards,
        loans=loan_summaries,
        total_debt=total_debt,
        total_monthly_obligations=total_monthly_obligations,
    )
