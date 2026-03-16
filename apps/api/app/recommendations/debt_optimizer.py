"""Debt payoff optimizer — snowball vs. avalanche strategy comparison.

This module is a pure-computation layer with no I/O, no HTTP calls, and no
database access.  It accepts a list of debt items and a monthly repayment
budget, then simulates both the snowball (lowest-balance-first) and avalanche
(highest-APR-first) payoff strategies, returning a side-by-side report with a
plain-language recommendation.

All monetary values are in EGP (Egyptian Pounds) and represented as Decimal to
avoid floating-point rounding errors.

Simulation cap: 120 months (10 years).  If debts are not paid off within that
window, the simulation halts and `total_months` reflects however many months
were simulated.
"""

from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_MONTHS: int = 120  # 10-year simulation ceiling
ROUNDING_PLACES: Decimal = Decimal("0.01")
ZERO: Decimal = Decimal("0")


# ---------------------------------------------------------------------------
# Input models
# ---------------------------------------------------------------------------


class DebtItem(BaseModel):
    """A single debt obligation for the optimizer to process.

    Parameters
    ----------
    id:
        Caller-assigned identifier used to cross-reference PayoffStep records.
    name:
        Human-readable label — typically a counterparty name or loan description.
    debt_type:
        Classification of the obligation.  One of: ``"loan"``, ``"lent"``,
        ``"borrowed"``.
    outstanding_balance:
        Current unpaid balance in EGP.  Must be >= 0.
    interest_rate:
        Annual interest rate expressed as a decimal fraction, e.g. ``0.185``
        for 18.5 %.  Use ``0`` for interest-free informal debts.
    minimum_payment:
        Minimum monthly payment required by the lender.  Use ``0`` for
        informal debts where no minimum is contractually defined.
    currency:
        ISO 4217 currency code.  Defaults to ``"EGP"``.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="Caller-assigned debt identifier")
    name: str = Field(description="Counterparty name or loan description")
    debt_type: Literal["loan", "lent", "borrowed"] = Field(
        description="Debt classification: loan | lent | borrowed"
    )
    outstanding_balance: Decimal = Field(ge=ZERO, description="Remaining balance in EGP (>= 0)")
    interest_rate: Decimal = Field(
        ge=ZERO,
        le=Decimal("1"),
        description="Annual interest rate as decimal fraction, e.g. 0.185 = 18.5%",
    )
    minimum_payment: Decimal = Field(
        ge=ZERO,
        description="Monthly minimum payment in EGP. Use 0 for informal debts.",
    )
    currency: str = Field(default="EGP", description="ISO 4217 currency code")

    # Convenience alias used internally during simulation
    @property
    def monthly_rate(self) -> Decimal:
        """Monthly interest rate derived from the annual rate."""
        return self.interest_rate / Decimal("12")


# ---------------------------------------------------------------------------
# Output models
# ---------------------------------------------------------------------------


class PayoffStep(BaseModel):
    """One month's payment action against a single debt.

    Parameters
    ----------
    month:
        1-based month index within the simulation.
    debt_id:
        Identifier of the debt this step applies to.
    payment:
        Total EGP amount paid toward this debt in this month (principal +
        absorbs interest already applied).
    remaining_balance:
        Outstanding balance after this month's payment.  Zero means the debt
        is fully paid.
    interest_charged:
        Interest accrued on this debt during this month before any payment was
        applied.
    """

    model_config = ConfigDict(frozen=True)

    month: int = Field(ge=1, description="1-based month index within the simulation")
    debt_id: str = Field(description="Identifier of the debt this step applies to")
    payment: Decimal = Field(description="Total EGP paid toward this debt this month")
    remaining_balance: Decimal = Field(description="Balance remaining after this payment (EGP)")
    interest_charged: Decimal = Field(
        description="Interest accrued this month before payment (EGP)"
    )


class DebtStrategy(BaseModel):
    """Complete payoff plan for a single repayment strategy.

    Parameters
    ----------
    strategy_name:
        ``"snowball"`` or ``"avalanche"``.
    total_months:
        Number of months until all debts reach zero (or MAX_MONTHS if the cap
        was hit).
    total_interest_paid:
        Sum of all interest charges across all debts over the simulation
        period, in EGP.
    total_paid:
        Total EGP disbursed (principal + interest) across the full simulation.
    monthly_steps:
        Granular month-by-month payment breakdown.  Capped at MAX_MONTHS *
        number-of-debts entries.
    confidence_score:
        Confidence in this projection.  Reduced when the debt list is sparse
        (< 2 items) or when informal (zero-rate) debts dominate.
    generated_at:
        UTC timestamp when this strategy was computed.
    """

    model_config = ConfigDict(frozen=True)

    strategy_name: Literal["snowball", "avalanche"] = Field(
        description="Name of the payoff strategy"
    )
    total_months: int = Field(ge=0, description="Months to debt-free (capped at MAX_MONTHS)")
    total_interest_paid: Decimal = Field(description="Total interest paid across all debts in EGP")
    total_paid: Decimal = Field(description="Total EGP disbursed (principal + interest)")
    monthly_steps: list[PayoffStep] = Field(
        description="Month-by-month payment breakdown (capped at 120 months)"
    )
    confidence_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence in this projection (0–1)",
    )
    generated_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="UTC timestamp when this strategy was computed",
    )


class DebtOptimizationReport(BaseModel):
    """Side-by-side comparison of snowball and avalanche payoff strategies.

    Parameters
    ----------
    debts:
        The original debt items provided by the caller.
    monthly_budget:
        Total EGP available for debt repayment each month.
    snowball:
        Full payoff plan using the snowball strategy.
    avalanche:
        Full payoff plan using the avalanche strategy.
    recommended_strategy:
        Which strategy the engine recommends: ``"snowball"`` or
        ``"avalanche"``.
    recommended_reason:
        Plain-language explanation of the recommendation.
    interest_savings:
        EGP saved in total interest by choosing avalanche over snowball.
        Negative value means snowball is cheaper (rare but possible with
        informal debts).
    confidence_score:
        Overall confidence in the report.  Inherits the lower of the two
        strategy confidence scores.
    generated_at:
        UTC timestamp when this report was produced.
    """

    model_config = ConfigDict(frozen=True)

    debts: list[DebtItem] = Field(description="Input debt items")
    monthly_budget: Decimal = Field(
        gt=ZERO, description="Total monthly EGP budget for debt repayment"
    )
    snowball: DebtStrategy = Field(description="Snowball strategy plan")
    avalanche: DebtStrategy = Field(description="Avalanche strategy plan")
    recommended_strategy: Literal["snowball", "avalanche"] = Field(
        description="Recommended strategy name"
    )
    recommended_reason: str = Field(
        description="Plain-language justification for the recommendation"
    )
    interest_savings: Decimal = Field(
        description=(
            "EGP saved in total interest by choosing avalanche over snowball "
            "(positive = avalanche wins; negative = snowball cheaper)"
        )
    )
    confidence_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Overall report confidence (0–1)",
    )
    generated_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="UTC timestamp when this report was produced",
    )


# ---------------------------------------------------------------------------
# Internal simulation helpers
# ---------------------------------------------------------------------------


def _round(value: Decimal) -> Decimal:
    """Round to 2 decimal places using banker-safe ROUND_HALF_UP."""
    return value.quantize(ROUNDING_PLACES, rounding=ROUND_HALF_UP)


def _simulate(
    debts: list[DebtItem],
    monthly_budget: Decimal,
    strategy: Literal["snowball", "avalanche"],
) -> tuple[list[PayoffStep], int, Decimal]:
    """Run a single-strategy payoff simulation.

    Parameters
    ----------
    debts:
        Debt items to simulate.  This function does NOT mutate the originals.
    monthly_budget:
        Total EGP available each month across all debts.
    strategy:
        ``"snowball"`` sorts by balance ascending; ``"avalanche"`` sorts by
        interest rate descending.

    Returns
    -------
    steps:
        Month-by-month PayoffStep records (up to MAX_MONTHS worth).
    total_months:
        Number of months the simulation ran.
    total_interest:
        Sum of all interest charges across the simulation.
    """
    # Work with mutable copies so we do not mutate caller objects
    balances: dict[str, Decimal] = {d.id: _round(d.outstanding_balance) for d in debts}
    minimums: dict[str, Decimal] = {d.id: d.minimum_payment for d in debts}
    rates: dict[str, Decimal] = {d.id: d.monthly_rate for d in debts}

    steps: list[PayoffStep] = []
    total_interest: Decimal = ZERO
    month: int = 0

    # Determine priority ordering (re-evaluated each month after a debt clears)
    def _priority_key(debt_id: str) -> tuple[Decimal, str]:
        if strategy == "snowball":
            return (balances[debt_id], debt_id)
        # avalanche: highest rate first → negate rate for ascending sort
        return (-rates[debt_id], debt_id)

    active_ids: list[str] = [d.id for d in debts if balances[d.id] > ZERO]

    while active_ids and month < MAX_MONTHS:
        month += 1

        # Step 1 — accrue monthly interest on every active debt
        interest_this_month: dict[str, Decimal] = {}
        for debt_id in active_ids:
            interest = _round(balances[debt_id] * rates[debt_id])
            balances[debt_id] = _round(balances[debt_id] + interest)
            interest_this_month[debt_id] = interest
            total_interest = _round(total_interest + interest)

        # Step 2 — pay minimums, tracking remaining budget
        remaining_budget: Decimal = monthly_budget
        min_payments_made: dict[str, Decimal] = {}

        for debt_id in active_ids:
            payment = min(minimums[debt_id], balances[debt_id])
            payment = _round(payment)
            balances[debt_id] = _round(balances[debt_id] - payment)
            remaining_budget = _round(remaining_budget - payment)
            min_payments_made[debt_id] = payment

        # Guard: if minimums alone exceeded budget (edge-case), clamp
        if remaining_budget < ZERO:
            remaining_budget = ZERO

        # Step 3 — direct extra budget to the priority debt
        priority_sorted = sorted(active_ids, key=_priority_key)
        for priority_id in priority_sorted:
            if remaining_budget <= ZERO:
                break
            extra = min(remaining_budget, balances[priority_id])
            extra = _round(extra)
            balances[priority_id] = _round(balances[priority_id] - extra)
            remaining_budget = _round(remaining_budget - extra)
            min_payments_made[priority_id] = _round(min_payments_made[priority_id] + extra)

        # Step 4 — record PayoffStep for every active debt this month
        for debt_id in active_ids:
            steps.append(
                PayoffStep(
                    month=month,
                    debt_id=debt_id,
                    payment=min_payments_made[debt_id],
                    remaining_balance=balances[debt_id],
                    interest_charged=interest_this_month[debt_id],
                )
            )

        # Step 5 — remove fully paid debts
        active_ids = [d_id for d_id in active_ids if balances[d_id] > ZERO]

    return steps, month, total_interest


def _compute_confidence(debts: list[DebtItem]) -> float:
    """Derive a confidence score for the simulation output.

    Confidence is reduced when:
    - Only one debt item is present (no trade-off to compare)
    - All debts are interest-free (strategy choice is trivial)
    - More than half of debts carry no minimum payment (informal)

    Returns
    -------
    float
        Value in [0.0, 1.0].
    """
    if not debts:
        return 0.1

    base = 1.0

    if len(debts) == 1:
        base -= 0.2

    all_zero_rate = all(d.interest_rate == ZERO for d in debts)
    if all_zero_rate:
        base -= 0.3

    informal_count = sum(1 for d in debts if d.minimum_payment == ZERO)
    if informal_count > len(debts) / 2:
        base -= 0.15

    return round(max(0.1, min(1.0, base)), 4)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def optimize_debt_payoff(
    debts: list[DebtItem],
    monthly_budget: Decimal,
) -> DebtOptimizationReport:
    """Compare snowball and avalanche debt payoff strategies for a given budget.

    Simulates both strategies month-by-month, computes total interest paid and
    months to debt-free for each, then returns a structured report with a
    recommendation.

    Parameters
    ----------
    debts:
        List of debt obligations to include in the simulation.  Items with
        ``outstanding_balance == 0`` are ignored.
    monthly_budget:
        Total EGP available each month for combined debt repayment.  Must be
        at least equal to the sum of all minimum payments to make progress;
        if it falls short, the simulation still runs but will not fully pay
        off all debts within MAX_MONTHS.

    Returns
    -------
    DebtOptimizationReport
        Side-by-side strategy comparison with recommendation and plain-language
        justification.

    Notes
    -----
    - All monetary values in the output are in EGP.
    - Simulation is capped at 120 months (10 years).
    - This function performs no I/O and has no side effects.
    """
    # Filter out already-settled debts
    active_debts = [d for d in debts if d.outstanding_balance > ZERO]

    # Run both simulations
    snow_steps, snow_months, snow_interest = _simulate(active_debts, monthly_budget, "snowball")
    aval_steps, aval_months, aval_interest = _simulate(active_debts, monthly_budget, "avalanche")

    # Compute totals for each strategy
    snow_total_paid = _round(sum(d.outstanding_balance for d in active_debts) + snow_interest)
    aval_total_paid = _round(sum(d.outstanding_balance for d in active_debts) + aval_interest)

    confidence = _compute_confidence(active_debts)

    # Determine recommendation
    all_zero_rate = all(d.interest_rate == ZERO for d in active_debts)

    if all_zero_rate:
        recommended: Literal["snowball", "avalanche"] = "snowball"
        reason = (
            "All debts are interest-free — pay smallest first to close "
            "accounts quickly and build repayment momentum."
        )
    else:
        recommended = "avalanche"
        savings_egp = _round(snow_interest - aval_interest)
        if savings_egp > ZERO:
            reason = (
                f"The avalanche strategy saves EGP {savings_egp:,.2f} in total "
                f"interest compared to snowball by targeting your highest-rate "
                f"debt first.  It is mathematically optimal whenever interest "
                f"rates differ across debts."
            )
        else:
            # Rare edge case: rates are identical, so strategies are equivalent
            reason = (
                "All debts carry the same interest rate, so both strategies "
                "produce identical results.  Avalanche is selected by default; "
                "you may switch to snowball for the psychological benefit of "
                "closing smaller accounts first."
            )

    interest_savings = _round(snow_interest - aval_interest)

    snowball_strategy = DebtStrategy(
        strategy_name="snowball",
        total_months=snow_months,
        total_interest_paid=snow_interest,
        total_paid=snow_total_paid,
        monthly_steps=snow_steps,
        confidence_score=confidence,
    )

    avalanche_strategy = DebtStrategy(
        strategy_name="avalanche",
        total_months=aval_months,
        total_interest_paid=aval_interest,
        total_paid=aval_total_paid,
        monthly_steps=aval_steps,
        confidence_score=confidence,
    )

    return DebtOptimizationReport(
        debts=active_debts,
        monthly_budget=monthly_budget,
        snowball=snowball_strategy,
        avalanche=avalanche_strategy,
        recommended_strategy=recommended,
        recommended_reason=reason,
        interest_savings=interest_savings,
        confidence_score=confidence,
    )
