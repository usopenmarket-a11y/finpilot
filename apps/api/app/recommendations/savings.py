"""Savings opportunity detector.

Analyses a list of bank transactions and surfaces four categories of
potential savings:

1. **duplicate_charge** — same description + amount appearing 2+ times in the
   same calendar month.
2. **recurring_subscription** — a debit appearing in 3+ distinct months with
   amounts within 10 % of each other (user may wish to cancel).
3. **high_fee** — any single debit whose description contains Arabic or English
   fee keywords and whose amount exceeds the configurable HIGH_FEE_THRESHOLD.
4. **irregular_spike** — a transaction amount that exceeds the category mean by
   more than 2 standard deviations (category must have at least 3 data points).

Results are ranked by ``estimated_monthly_saving`` descending and capped at
MAX_OPPORTUNITIES.  All monetary values are in EGP (Egyptian Pounds).

This module is a pure-computation layer: no I/O, no HTTP calls, no database
access.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HIGH_FEE_THRESHOLD: Decimal = Decimal("50.00")  # EGP — flag fees above this amount
SUBSCRIPTION_AMOUNT_TOLERANCE: Decimal = Decimal("0.10")  # 10 % variance window
MIN_SUBSCRIPTION_MONTHS: int = 3  # minimum distinct months to classify as recurring
MIN_SPIKE_DATA_POINTS: int = 3  # minimum transactions per category to detect spikes
MAX_OPPORTUNITIES: int = 10  # cap on returned opportunities

HIGH_FEE_KEYWORDS: tuple[str, ...] = (
    "fee",
    "charge",
    "رسوم",
    "عمولة",
)

ROUNDING_PLACES: Decimal = Decimal("0.01")
ZERO: Decimal = Decimal("0")


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class TransactionSummary(BaseModel):
    """A lightweight transaction record used as input to the savings detector.

    Parameters
    ----------
    description:
        Raw or normalised transaction description text.
    amount:
        Transaction amount in EGP.  Always positive — direction is captured by
        ``transaction_type``.
    transaction_type:
        Money flow direction: ``"debit"`` (outgoing) or ``"credit"`` (incoming).
    transaction_date:
        Calendar date the transaction was posted.
    category:
        Optional AI-assigned spending category.  Used for spike detection.
    """

    model_config = ConfigDict(extra="forbid")

    description: str = Field(description="Transaction description text")
    amount: Decimal = Field(gt=ZERO, description="Transaction amount in EGP (positive)")
    transaction_type: Literal["debit", "credit"] = Field(
        description="Direction: debit (outgoing) | credit (incoming)"
    )
    transaction_date: date = Field(description="Date the transaction was posted")
    category: str | None = Field(default=None, description="Optional AI-assigned spending category")


# ---------------------------------------------------------------------------
# Output models
# ---------------------------------------------------------------------------


class SavingsOpportunity(BaseModel):
    """A single detected savings opportunity.

    Parameters
    ----------
    opportunity_type:
        Classification of the finding: ``"duplicate_charge"``,
        ``"recurring_subscription"``, ``"high_fee"``, or
        ``"irregular_spike"``.
    title:
        Short human-readable headline (≤ 80 chars).
    description:
        Explanation of the finding and the recommended action.
    estimated_monthly_saving:
        Estimated EGP that could be saved each month by acting on this
        opportunity.
    transactions:
        Description strings of the transactions that triggered this finding.
    confidence_score:
        Confidence in the detected pattern (0.0–1.0).  Higher when the
        pattern appears more consistently.
    generated_at:
        UTC timestamp when this opportunity was detected.
    """

    model_config = ConfigDict(frozen=True)

    opportunity_type: Literal[
        "duplicate_charge", "recurring_subscription", "high_fee", "irregular_spike"
    ] = Field(description="Category of the savings opportunity")
    title: str = Field(description="Short headline for the opportunity")
    description: str = Field(description="Explanation and recommended action")
    estimated_monthly_saving: Decimal = Field(ge=ZERO, description="Estimated monthly EGP saving")
    transactions: list[str] = Field(
        description="Description strings of transactions that triggered this finding"
    )
    confidence_score: float = Field(ge=0.0, le=1.0, description="Pattern confidence (0–1)")
    generated_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="UTC timestamp when this opportunity was detected",
    )


class SavingsReport(BaseModel):
    """Aggregated savings opportunity report.

    Parameters
    ----------
    opportunities:
        Up to MAX_OPPORTUNITIES findings ranked by estimated monthly saving.
    total_estimated_monthly_saving:
        Sum of ``estimated_monthly_saving`` across all returned opportunities.
    analysis_period_days:
        Number of calendar days spanned by the input transactions (max_date -
        min_date + 1).  Zero when no transactions are provided.
    confidence_score:
        Mean confidence across all returned opportunities, or 0.0 when the
        transaction history is too sparse (< 30 days).
    generated_at:
        UTC timestamp when this report was produced.
    """

    model_config = ConfigDict(frozen=True)

    opportunities: list[SavingsOpportunity] = Field(
        description="Ranked list of savings opportunities (up to 10)"
    )
    total_estimated_monthly_saving: Decimal = Field(
        ge=ZERO, description="Total estimated monthly EGP saving across all opportunities"
    )
    analysis_period_days: int = Field(
        ge=0, description="Number of calendar days covered by the input transactions"
    )
    confidence_score: float = Field(
        ge=0.0, le=1.0, description="Mean confidence across all opportunities (0–1)"
    )
    generated_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="UTC timestamp when this report was produced",
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _round(value: Decimal) -> Decimal:
    """Round to 2 decimal places using ROUND_HALF_UP."""
    return value.quantize(ROUNDING_PLACES, rounding=ROUND_HALF_UP)


def _analysis_period_days(transactions: list[TransactionSummary]) -> int:
    """Return the number of calendar days spanned by the transaction list.

    Parameters
    ----------
    transactions:
        Full input list (may include credits and debits).

    Returns
    -------
    int
        ``max_date - min_date + 1``, or ``0`` when the list is empty.
    """
    if not transactions:
        return 0
    dates = [t.transaction_date for t in transactions]
    return (max(dates) - min(dates)).days + 1


def _contains_fee_keyword(description: str) -> bool:
    """Return True if the description contains any fee-related keyword.

    Performs a case-insensitive substring search against HIGH_FEE_KEYWORDS.

    Parameters
    ----------
    description:
        Raw transaction description string.

    Returns
    -------
    bool
    """
    lower = description.lower()
    return any(keyword.lower() in lower for keyword in HIGH_FEE_KEYWORDS)


# ---------------------------------------------------------------------------
# Detection functions (one per opportunity type)
# ---------------------------------------------------------------------------


def _detect_duplicate_charges(
    debits: list[TransactionSummary],
) -> list[SavingsOpportunity]:
    """Detect the same charge appearing more than once in a calendar month.

    Groups debits by (description, amount, year-month).  Any group with 2+
    members is flagged as a potential duplicate.  The estimated saving is
    ``amount * (occurrences - 1)`` — i.e. refunding all but one occurrence.

    Parameters
    ----------
    debits:
        Debit transactions from the input list.

    Returns
    -------
    list[SavingsOpportunity]
        One opportunity per (description, amount, month) group that has
        duplicates.
    """
    # Key: (description, amount_str, year_month_str)
    groups: dict[tuple[str, str, str], list[TransactionSummary]] = defaultdict(list)

    for txn in debits:
        month_key = txn.transaction_date.strftime("%Y-%m")
        key = (txn.description, str(txn.amount), month_key)
        groups[key].append(txn)

    opportunities: list[SavingsOpportunity] = []

    for (description, amount_str, month_key), group in groups.items():
        count = len(group)
        if count < 2:
            continue

        amount = Decimal(amount_str)
        saving = _round(amount * (count - 1))

        # Confidence rises with number of duplicates; cap at 0.95
        confidence = round(min(0.95, 0.6 + 0.15 * (count - 1)), 4)

        opportunities.append(
            SavingsOpportunity(
                opportunity_type="duplicate_charge",
                title=f"Possible duplicate charge: {description}",
                description=(
                    f"'{description}' was charged {count} times in {month_key} "
                    f"for EGP {amount:,.2f} each.  Verify with your bank whether "
                    f"these are genuine separate transactions or billing errors.  "
                    f"Disputing the duplicates could recover EGP {saving:,.2f} "
                    f"this month."
                ),
                estimated_monthly_saving=saving,
                transactions=[t.description for t in group],
                confidence_score=confidence,
            )
        )

    return opportunities


def _detect_recurring_subscriptions(
    debits: list[TransactionSummary],
) -> list[SavingsOpportunity]:
    """Detect recurring subscription-like charges across 3+ distinct months.

    Groups debits by description.  If a description appears in at least
    MIN_SUBSCRIPTION_MONTHS distinct calendar months AND all observed amounts
    are within SUBSCRIPTION_AMOUNT_TOLERANCE (10 %) of each other, it is
    flagged as a recurring subscription.

    The estimated saving equals the average monthly charge — the full amount
    the user would save by cancelling.

    Parameters
    ----------
    debits:
        Debit transactions from the input list.

    Returns
    -------
    list[SavingsOpportunity]
    """
    # description → list of (month_key, amount) pairs
    by_description: dict[str, list[tuple[str, Decimal]]] = defaultdict(list)

    for txn in debits:
        month_key = txn.transaction_date.strftime("%Y-%m")
        by_description[txn.description].append((month_key, txn.amount))

    opportunities: list[SavingsOpportunity] = []

    for description, occurrences in by_description.items():
        distinct_months = {month for month, _ in occurrences}
        if len(distinct_months) < MIN_SUBSCRIPTION_MONTHS:
            continue

        amounts = [amt for _, amt in occurrences]
        min_amt = min(amounts)
        max_amt = max(amounts)

        # Check that all amounts fall within the tolerance band of the minimum
        if min_amt == ZERO:
            continue
        if (max_amt - min_amt) / min_amt > SUBSCRIPTION_AMOUNT_TOLERANCE:
            continue

        avg_amount = _round(sum(amounts) / len(amounts))

        # Confidence: more months = more confidence; cap at 0.90
        month_count = len(distinct_months)
        confidence = round(min(0.90, 0.55 + 0.05 * month_count), 4)

        opportunities.append(
            SavingsOpportunity(
                opportunity_type="recurring_subscription",
                title=f"Recurring subscription detected: {description}",
                description=(
                    f"'{description}' has been charged in {month_count} separate "
                    f"months at an average of EGP {avg_amount:,.2f}/month.  "
                    f"Review whether this subscription is still being actively used.  "
                    f"Cancelling would save approximately EGP {avg_amount:,.2f}/month."
                ),
                estimated_monthly_saving=avg_amount,
                transactions=[description],
                confidence_score=confidence,
            )
        )

    return opportunities


def _detect_high_fees(
    debits: list[TransactionSummary],
) -> list[SavingsOpportunity]:
    """Detect individual bank or service fees that exceed HIGH_FEE_THRESHOLD.

    Any debit whose description contains a fee-related keyword AND whose
    amount exceeds HIGH_FEE_THRESHOLD (EGP 50) is flagged.  Each qualifying
    transaction produces its own opportunity.

    Estimated saving equals the transaction amount — the user may be able to
    negotiate, switch to a lower-fee account, or change payment method.

    Parameters
    ----------
    debits:
        Debit transactions from the input list.

    Returns
    -------
    list[SavingsOpportunity]
    """
    opportunities: list[SavingsOpportunity] = []

    for txn in debits:
        if not _contains_fee_keyword(txn.description):
            continue
        if txn.amount <= HIGH_FEE_THRESHOLD:
            continue

        opportunities.append(
            SavingsOpportunity(
                opportunity_type="high_fee",
                title=f"High fee detected: {txn.description}",
                description=(
                    f"A fee of EGP {txn.amount:,.2f} was charged on "
                    f"{txn.transaction_date.isoformat()} for '{txn.description}'.  "
                    f"Consider negotiating this fee with your bank, switching to a "
                    f"lower-fee account, or identifying a fee-free alternative."
                ),
                estimated_monthly_saving=_round(txn.amount),
                transactions=[txn.description],
                confidence_score=0.85,
            )
        )

    return opportunities


def _detect_irregular_spikes(
    debits: list[TransactionSummary],
) -> list[SavingsOpportunity]:
    """Detect transactions that are statistical outliers within their category.

    For each spending category with at least MIN_SPIKE_DATA_POINTS transactions,
    compute the mean and population standard deviation.  Any transaction whose
    amount exceeds ``mean + 2 * stdev`` is flagged as an irregular spike.

    Estimated saving = transaction_amount - mean (the excess over normal spend).

    Only debits with a non-None category are eligible.

    Parameters
    ----------
    debits:
        Debit transactions from the input list.

    Returns
    -------
    list[SavingsOpportunity]
    """
    # category → list of (amount, description, date) tuples
    by_category: dict[str, list[tuple[Decimal, str, date]]] = defaultdict(list)

    for txn in debits:
        if txn.category is None:
            continue
        by_category[txn.category].append((txn.amount, txn.description, txn.transaction_date))

    opportunities: list[SavingsOpportunity] = []

    for category, items in by_category.items():
        if len(items) < MIN_SPIKE_DATA_POINTS:
            continue

        float_amounts = [float(amt) for amt, _, _ in items]

        try:
            mean_val = statistics.mean(float_amounts)
            stdev_val = statistics.pstdev(float_amounts)
        except statistics.StatisticsError:
            continue

        if stdev_val == 0:
            # All values identical — no meaningful spike detection possible
            continue

        threshold = mean_val + 2 * stdev_val

        for amount, description, txn_date in items:
            if float(amount) <= threshold:
                continue

            saving = _round(amount - Decimal(str(mean_val)))
            if saving <= ZERO:
                continue

            # Confidence scales with how far above the threshold the spike is
            z_score = (float(amount) - mean_val) / stdev_val
            confidence = round(min(0.85, 0.55 + 0.05 * z_score), 4)

            opportunities.append(
                SavingsOpportunity(
                    opportunity_type="irregular_spike",
                    title=f"Unusual {category} spend: {description}",
                    description=(
                        f"On {txn_date.isoformat()}, '{description}' was charged "
                        f"EGP {amount:,.2f} — significantly above your typical "
                        f"{category} spend of EGP {mean_val:,.2f}.  Review whether "
                        f"this was intentional; the excess over your normal spend is "
                        f"EGP {saving:,.2f}."
                    ),
                    estimated_monthly_saving=saving,
                    transactions=[description],
                    confidence_score=confidence,
                )
            )

    return opportunities


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def detect_savings_opportunities(
    transactions: list[TransactionSummary],
) -> SavingsReport:
    """Analyse transactions and return ranked savings opportunities.

    Runs four detection passes — duplicate charges, recurring subscriptions,
    high fees, and irregular spikes — then merges, deduplicates, ranks by
    estimated monthly saving, and returns up to MAX_OPPORTUNITIES findings.

    Parameters
    ----------
    transactions:
        Full list of transaction summaries to analyse.  Mix of debits and
        credits is accepted; only debits are used for opportunity detection.

    Returns
    -------
    SavingsReport
        Ranked findings with totals and metadata.  ``opportunities`` contains
        at most 10 entries sorted by ``estimated_monthly_saving`` descending.

    Notes
    -----
    - All monetary values are in EGP.
    - This function performs no I/O and has no side effects.
    - Confidence is set to 0.0 when the analysis period is shorter than 30
      days, as patterns cannot be reliably established from minimal history.
    """
    period_days = _analysis_period_days(transactions)

    debits = [t for t in transactions if t.transaction_type == "debit"]

    # Run all four detection passes
    all_opportunities: list[SavingsOpportunity] = []
    all_opportunities.extend(_detect_duplicate_charges(debits))
    all_opportunities.extend(_detect_recurring_subscriptions(debits))
    all_opportunities.extend(_detect_high_fees(debits))
    all_opportunities.extend(_detect_irregular_spikes(debits))

    # Sort descending by estimated_monthly_saving, then cap
    all_opportunities.sort(key=lambda o: o.estimated_monthly_saving, reverse=True)
    top_opportunities = all_opportunities[:MAX_OPPORTUNITIES]

    total_saving = _round(
        sum(
            (o.estimated_monthly_saving for o in top_opportunities),
            Decimal("0"),
        )
    )

    # Overall confidence: mean of individual scores, zeroed for sparse history
    if not top_opportunities:
        overall_confidence = 0.0
    elif period_days < 30:
        # Insufficient history — cannot reliably establish patterns
        overall_confidence = 0.0
    else:
        scores = [o.confidence_score for o in top_opportunities]
        overall_confidence = round(statistics.mean(scores), 4)

    return SavingsReport(
        opportunities=top_opportunities,
        total_estimated_monthly_saving=total_saving,
        analysis_period_days=period_days,
        confidence_score=overall_confidence,
    )
