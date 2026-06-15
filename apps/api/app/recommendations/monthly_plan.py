"""Monthly action plan generator.

Produces a prioritised list of concrete financial steps a user can take in a
given month, derived from their current spending breakdown and multi-month
trend data.  All monetary values are in EGP.

Pure functions only — no I/O, no HTTP calls, no database calls.
"""

from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Constants — all EGP thresholds live here so callers can override in tests
# ---------------------------------------------------------------------------

# Category share of total_debits above which a review action is generated
CATEGORY_REVIEW_THRESHOLD_PCT: float = 30.0

# Category share above which health_score is penalised (single category dominance)
CATEGORY_DOMINANCE_THRESHOLD_PCT: float = 40.0

# --- Continuous health score: component weights (must sum to 1.0) ---------

# Savings-rate component: net / total_credits
HEALTH_WEIGHT_SAVINGS_RATE: float = 0.5

# Trend component: scaled by month-over-month spend change magnitude
HEALTH_WEIGHT_TREND: float = 0.3

# Concentration component: scaled by how dominant the top category is
HEALTH_WEIGHT_CONCENTRATION: float = 0.2

# --- Savings-rate component anchors ----------------------------------------

# A savings rate >= this value earns full marks for the savings-rate component
SAVINGS_RATE_FULL_MARKS_PCT: float = 0.30

# A savings rate <= this value (a deficit of the same magnitude) earns zero
# marks for the savings-rate component; linear in between
SAVINGS_RATE_ZERO_MARKS_PCT: float = -0.30

# --- Trend component anchors ------------------------------------------------

# A month-over-month spend increase >= this percentage causes the trend
# component to lose its full weight; linear in between 0% and this value
TREND_UP_FULL_LOSS_PCT: float = 0.50

# Fraction of the trend weight lost on an "up" trend when the magnitude of
# the increase cannot be computed from monthly_points (too few points)
TREND_UP_NO_HISTORY_LOSS_FRACTION: float = 0.5

# --- Concentration component anchors ----------------------------------------

# Top-category share at which the concentration component loses its full
# weight; CATEGORY_DOMINANCE_THRESHOLD_PCT is the point at which it starts
# losing weight (linear in between)
CATEGORY_CONCENTRATION_FULL_LOSS_PCT: float = 100.0

# --- Action item impact -----------------------------------------------------

# Fraction of a dominant category's actual total used as the estimated EGP
# impact of reviewing/reducing spending in that category
CATEGORY_REVIEW_IMPACT_FRACTION: Decimal = Decimal("0.15")

# Decimal quantisation for EGP amounts (2 d.p.)
_EGP_QUANT: Decimal = Decimal("0.01")

# ---------------------------------------------------------------------------
# Input models
# ---------------------------------------------------------------------------


class CategoryBreakdown(BaseModel):
    """Spending aggregated for a single category within a period.

    Fields mirror the analytics layer's CategoryBreakdown dataclass but are
    expressed as a Pydantic v2 model so that callers can validate input at
    the recommendation boundary.
    """

    model_config = ConfigDict(frozen=True)

    category: str = Field(description="Spending category label, e.g. 'Food & Dining'")
    total: Decimal = Field(
        ge=Decimal("0"),
        description="Total EGP spent in this category during the period",
    )
    percentage: float = Field(
        ge=0.0,
        le=100.0,
        description="Share of total_debits (0–100)",
    )


class SpendingBreakdown(BaseModel):
    """Full spending breakdown for the current period.

    Callers bridge from analytics.spending.SpendingBreakdown by mapping
    total_spending -> total_debits, total_income -> total_credits, and
    CategoryBreakdown.total_amount -> CategoryBreakdown.total.
    """

    model_config = ConfigDict(frozen=True)

    total_debits: Decimal = Field(
        ge=Decimal("0"),
        description="Total EGP spent (debit transactions) in the period",
    )
    total_credits: Decimal = Field(
        ge=Decimal("0"),
        description="Total EGP received (credit transactions) in the period",
    )
    net: Decimal = Field(
        description="total_credits - total_debits; negative means overspending",
    )
    by_category: list[CategoryBreakdown] = Field(
        default_factory=list,
        description="Per-category breakdown; order is caller's choice",
    )


class MonthlyPoint(BaseModel):
    """Aggregated statistics for a single calendar month within the trend window."""

    model_config = ConfigDict(frozen=True)

    year: int = Field(ge=2000, le=2100, description="Calendar year")
    month: int = Field(ge=1, le=12, description="Calendar month (1–12)")
    total_debits: Decimal = Field(ge=Decimal("0"), description="Total EGP spent")
    total_credits: Decimal = Field(ge=Decimal("0"), description="Total EGP received")
    net: Decimal = Field(description="total_credits - total_debits")
    transaction_count: int = Field(ge=0, description="Number of transactions in this month")


class TrendReport(BaseModel):
    """Multi-month trend data used as input to recommendation generators.

    Callers bridge from analytics.trends.TrendReport by mapping
    avg_monthly_spending -> avg_monthly_spend, avg_monthly_income unchanged,
    and computing spend_trend_direction from spending_change_pct.
    """

    model_config = ConfigDict(frozen=True)

    lookback_months: int = Field(
        ge=1,
        description="Number of months included in monthly_points",
    )
    monthly_points: list[MonthlyPoint] = Field(
        default_factory=list,
        description="Chronologically ordered monthly snapshots (oldest first)",
    )
    avg_monthly_spend: Decimal = Field(
        ge=Decimal("0"),
        description="Average EGP spent per month across the lookback window",
    )
    avg_monthly_income: Decimal = Field(
        ge=Decimal("0"),
        description="Average EGP received per month across the lookback window",
    )
    spend_trend_direction: Literal["up", "down", "flat"] = Field(
        description="Direction of spending trend derived from month-over-month change",
    )


# ---------------------------------------------------------------------------
# Output models
# ---------------------------------------------------------------------------


class ActionItem(BaseModel):
    """A single concrete step the user should take this month.

    Items are ranked by ROI (estimated_impact / effort implied by priority
    level) before being assembled into the plan list.
    """

    model_config = ConfigDict(frozen=True)

    priority: Literal["high", "medium", "low"] = Field(
        description="Execution priority — high items should be addressed first",
    )
    category: Literal["spending", "savings", "debt", "income"] = Field(
        description="Broad financial category this action addresses",
    )
    title: str = Field(
        min_length=1,
        description="Short action title shown as a headline in the UI",
    )
    description: str = Field(
        min_length=1,
        description="Expanded guidance explaining what the user should do and why",
    )
    estimated_impact: Decimal = Field(
        ge=Decimal("0"),
        description="Estimated EGP saved or gained if this action is completed; 0 if unmeasurable",
    )
    confidence_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Model confidence in this recommendation (0–1)",
    )
    generated_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="UTC timestamp when this item was generated",
    )


class MonthlyPlan(BaseModel):
    """Complete monthly action plan for a user.

    Contains a prioritised list of action items, a projected savings figure,
    and a health score summarising the user's current financial position.
    """

    model_config = ConfigDict(frozen=True)

    month: int = Field(ge=1, le=12, description="Target month (1–12)")
    year: int = Field(ge=2000, le=2100, description="Target year")
    summary: str = Field(
        min_length=1,
        description="One-to-two sentence plain-language overview of the user's financial position",
    )
    action_items: list[ActionItem] = Field(
        description="Prioritised list of concrete actions, sorted high -> medium -> low",
    )
    projected_savings: Decimal = Field(
        ge=Decimal("0"),
        description="Expected EGP surplus next month based on trend averages; 0 if negative",
    )
    health_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Composite financial health score (0–1); higher is better",
    )
    confidence_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Overall model confidence in this plan (0–1); reduced when data is sparse",
    )
    generated_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="UTC timestamp when this plan was generated",
    )


# ---------------------------------------------------------------------------
# Priority sort key — high=0, medium=1, low=2 for stable ordering
# ---------------------------------------------------------------------------

_PRIORITY_ORDER: dict[str, int] = {"high": 0, "medium": 1, "low": 2}


def _priority_key(item: ActionItem) -> int:
    """Return numeric sort key for an ActionItem by priority level.

    Args:
        item: ActionItem whose priority field is inspected.

    Returns:
        Integer sort key (0=high, 1=medium, 2=low).
    """
    return _PRIORITY_ORDER.get(item.priority, 99)


def _action_item_sort_key(item: ActionItem) -> tuple[int, Decimal]:
    """Return a (priority, -impact) sort key for ranking action items.

    Items are ordered high -> medium -> low priority, and within the same
    priority tier the item with the highest estimated_impact sorts first.

    Args:
        item: ActionItem whose priority and estimated_impact are inspected.

    Returns:
        Tuple of (priority rank, negated estimated_impact) suitable for
        ascending sort.
    """
    return (_priority_key(item), -item.estimated_impact)


# ---------------------------------------------------------------------------
# Helpers — EGP rounding and health-score component calculations
# ---------------------------------------------------------------------------


def _egp(value: Decimal) -> Decimal:
    """Quantise a Decimal to 2 decimal places using ROUND_HALF_UP.

    Args:
        value: Raw Decimal amount.

    Returns:
        Decimal rounded to EGP precision (2 d.p.).
    """
    return value.quantize(_EGP_QUANT, rounding=ROUND_HALF_UP)


def _clamp(value: float, low: float, high: float) -> float:
    """Clamp a float to the inclusive range [low, high].

    Args:
        value: Raw float value.
        low: Minimum allowed value.
        high: Maximum allowed value.

    Returns:
        Float clamped to [low, high].
    """
    return max(low, min(high, value))


def _month_over_month_increase(trends: TrendReport) -> Decimal | None:
    """Compute the EGP increase of the most recent month's spend vs prior average.

    Compares the most recent month's ``total_debits`` against the average
    ``total_debits`` of all prior months in ``monthly_points``.

    Args:
        trends: Multi-month trend report with chronologically ordered
            monthly_points (oldest first).

    Returns:
        ``most_recent_total_debits - average_of_prior_months`` as a Decimal
        (may be negative or zero), or ``None`` if fewer than two monthly
        points are available to compute the comparison.
    """
    points = trends.monthly_points
    if len(points) < 2:
        return None

    most_recent = points[-1].total_debits
    prior_points = points[:-1]
    prior_avg = sum((p.total_debits for p in prior_points), Decimal("0")) / Decimal(
        len(prior_points)
    )
    return most_recent - prior_avg


def _savings_rate_component(spending: SpendingBreakdown) -> float:
    """Compute the savings-rate contribution to the continuous health score.

    The savings rate is ``spending.net / spending.total_credits``. A rate of
    ``SAVINGS_RATE_FULL_MARKS_PCT`` or higher earns the full
    ``HEALTH_WEIGHT_SAVINGS_RATE``; a rate of 0% earns half that weight; a
    deficit of ``SAVINGS_RATE_ZERO_MARKS_PCT`` or worse earns zero. The score
    is linearly interpolated between these anchors.

    Args:
        spending: Current-period spending breakdown.

    Returns:
        Float contribution in [0.0, HEALTH_WEIGHT_SAVINGS_RATE]. Returns 0.0
        when total_credits is zero (avoids division by zero).
    """
    if spending.total_credits == Decimal("0"):
        return 0.0

    rate = float(spending.net / spending.total_credits)
    half_marks = HEALTH_WEIGHT_SAVINGS_RATE / 2.0

    if rate >= SAVINGS_RATE_FULL_MARKS_PCT:
        return HEALTH_WEIGHT_SAVINGS_RATE

    if rate >= 0.0:
        # Interpolate between 0% (half marks) and FULL_MARKS_PCT (full marks)
        fraction = rate / SAVINGS_RATE_FULL_MARKS_PCT
        return half_marks + fraction * half_marks

    if rate <= SAVINGS_RATE_ZERO_MARKS_PCT:
        return 0.0

    # Interpolate between ZERO_MARKS_PCT (zero) and 0% (half marks)
    fraction = (rate - SAVINGS_RATE_ZERO_MARKS_PCT) / (0.0 - SAVINGS_RATE_ZERO_MARKS_PCT)
    return fraction * half_marks


def _trend_component(trends: TrendReport) -> float:
    """Compute the trend contribution to the continuous health score.

    Flat or downward trends earn the full ``HEALTH_WEIGHT_TREND``. Upward
    trends lose weight proportional to the magnitude of the month-over-month
    spend increase: 0% increase loses nothing, an increase of
    ``TREND_UP_FULL_LOSS_PCT`` or more loses the full weight, linear in
    between. If the magnitude cannot be derived from monthly_points (fewer
    than two points), a fixed ``TREND_UP_NO_HISTORY_LOSS_FRACTION`` of the
    weight is deducted so an "up" trend is never free.

    Args:
        trends: Multi-month trend report including spend_trend_direction and
            monthly_points.

    Returns:
        Float contribution in [0.0, HEALTH_WEIGHT_TREND].
    """
    if trends.spend_trend_direction in ("flat", "down"):
        return HEALTH_WEIGHT_TREND

    # spend_trend_direction == "up"
    points = trends.monthly_points
    if len(points) < 2:
        return HEALTH_WEIGHT_TREND * (1.0 - TREND_UP_NO_HISTORY_LOSS_FRACTION)

    most_recent = points[-1].total_debits
    prior_points = points[:-1]
    prior_avg = sum((p.total_debits for p in prior_points), Decimal("0")) / Decimal(
        len(prior_points)
    )

    if prior_avg == Decimal("0"):
        return HEALTH_WEIGHT_TREND * (1.0 - TREND_UP_NO_HISTORY_LOSS_FRACTION)

    pct_increase = float((most_recent - prior_avg) / prior_avg)
    pct_increase = max(0.0, pct_increase)

    loss_fraction = _clamp(pct_increase / TREND_UP_FULL_LOSS_PCT, 0.0, 1.0)
    return HEALTH_WEIGHT_TREND * (1.0 - loss_fraction)


def _concentration_component(spending: SpendingBreakdown) -> float:
    """Compute the category-concentration contribution to the health score.

    Earns the full ``HEALTH_WEIGHT_CONCENTRATION`` when no category exceeds
    ``CATEGORY_DOMINANCE_THRESHOLD_PCT`` of total spending. Otherwise loses
    weight proportional to how far the top category's share is past that
    threshold, where the threshold loses nothing and
    ``CATEGORY_CONCENTRATION_FULL_LOSS_PCT`` loses the full weight (clamped).

    Args:
        spending: Current-period spending breakdown including by_category.

    Returns:
        Float contribution in [0.0, HEALTH_WEIGHT_CONCENTRATION].
    """
    if not spending.by_category:
        return HEALTH_WEIGHT_CONCENTRATION

    top_pct = max(c.percentage for c in spending.by_category)

    if top_pct <= CATEGORY_DOMINANCE_THRESHOLD_PCT:
        return HEALTH_WEIGHT_CONCENTRATION

    span = CATEGORY_CONCENTRATION_FULL_LOSS_PCT - CATEGORY_DOMINANCE_THRESHOLD_PCT
    loss_fraction = _clamp((top_pct - CATEGORY_DOMINANCE_THRESHOLD_PCT) / span, 0.0, 1.0)
    return HEALTH_WEIGHT_CONCENTRATION * (1.0 - loss_fraction)


# ---------------------------------------------------------------------------
# Core generation function
# ---------------------------------------------------------------------------


def generate_monthly_plan(
    spending: SpendingBreakdown,
    trends: TrendReport,
    target_month: int,
    target_year: int,
) -> MonthlyPlan:
    """Generate a prioritised monthly action plan from spending and trend data.

    Computes a continuous health_score as a weighted blend of three
    components — savings rate, spend trend, and category concentration —
    then assembles a list of concrete ActionItems based on the same signals,
    each carrying a realistic estimated EGP impact. Items are sorted
    high -> medium -> low priority, and ranked by estimated_impact (desc)
    within each priority tier.

    The overall confidence_score is set to 0.4 when lookback_months < 3
    (sparse data) and 0.85 otherwise.  Individual action items inherit the
    same confidence.

    Args:
        spending: Current-period spending breakdown including category shares.
        trends: Multi-month trend report with direction and averages.
        target_month: Month (1–12) the plan is being generated for.
        target_year: Four-digit year the plan is being generated for.

    Returns:
        MonthlyPlan with ranked action_items, projected_savings, health_score,
        and confidence_score all expressed in EGP.
    """
    # ------------------------------------------------------------------ #
    # Confidence — reduced when we have fewer than 3 months of history
    # ------------------------------------------------------------------ #
    plan_confidence: float = 0.4 if trends.lookback_months < 3 else 0.85

    # ------------------------------------------------------------------ #
    # Health score — continuous blend of three weighted components
    # ------------------------------------------------------------------ #
    health = (
        _savings_rate_component(spending)
        + _trend_component(trends)
        + _concentration_component(spending)
    )
    health = _clamp(health, 0.0, 1.0)

    # ------------------------------------------------------------------ #
    # Projected savings
    # ------------------------------------------------------------------ #
    raw_savings: Decimal = trends.avg_monthly_income - trends.avg_monthly_spend
    projected_savings: Decimal = raw_savings if raw_savings > Decimal("0") else Decimal("0")

    # ------------------------------------------------------------------ #
    # Month-over-month spend increase — used for the "Reduce Spending"
    # action item's estimated_impact (floored at 0; None if not computable)
    # ------------------------------------------------------------------ #
    mom_increase = _month_over_month_increase(trends)
    if mom_increase is not None and mom_increase > Decimal("0"):
        reduce_spending_impact: Decimal = _egp(mom_increase)
    else:
        reduce_spending_impact = Decimal("0")

    # ------------------------------------------------------------------ #
    # Action items
    # ------------------------------------------------------------------ #
    items: list[ActionItem] = []

    # High priority: spending is trending upward
    if trends.spend_trend_direction == "up":
        if reduce_spending_impact > Decimal("0"):
            reduce_spending_description = (
                "Your spending has been increasing month-over-month, up by "
                f"EGP {reduce_spending_impact:,.2f} compared to your prior average. "
                "Review your largest expense categories and identify at least one "
                "area where you can cut back this month to reverse the trend."
            )
        else:
            reduce_spending_description = (
                "Your spending has been increasing month-over-month. "
                "Review your largest expense categories and identify at least one "
                "area where you can cut back this month to reverse the trend."
            )
        items.append(
            ActionItem(
                priority="high",
                category="spending",
                title="Reduce Spending",
                description=reduce_spending_description,
                estimated_impact=reduce_spending_impact,
                confidence_score=plan_confidence,
            )
        )

    # High priority: currently spending more than earning
    if spending.net < Decimal("0"):
        gap: Decimal = abs(spending.net)
        items.append(
            ActionItem(
                priority="high",
                category="spending",
                title="Close Budget Gap",
                description=(
                    f"You spent EGP {gap:,.2f} more than you earned this period. "
                    "Identify discretionary expenses to reduce so that outflows no "
                    "longer exceed inflows."
                ),
                estimated_impact=gap,
                confidence_score=plan_confidence,
            )
        )

    # Medium priority: categories consuming more than 30 % of spending
    review_categories: list[CategoryBreakdown] = [
        c for c in spending.by_category if c.percentage > CATEGORY_REVIEW_THRESHOLD_PCT
    ]
    for cat in review_categories:
        category_review_impact = _egp(cat.total * CATEGORY_REVIEW_IMPACT_FRACTION)
        items.append(
            ActionItem(
                priority="medium",
                category="spending",
                title=f"Review {cat.category} Spending",
                description=(
                    f"{cat.category} accounts for {cat.percentage:.1f}% of your total "
                    f"spending (EGP {cat.total:,.2f}). Consider whether this level of "
                    "expenditure aligns with your financial goals and look for ways to "
                    f"reduce it — even a {CATEGORY_REVIEW_IMPACT_FRACTION:.0%} cut would "
                    f"save approximately EGP {category_review_impact:,.2f} this month."
                ),
                estimated_impact=category_review_impact,
                confidence_score=plan_confidence,
            )
        )

    # Low priority: there is a positive savings margin — encourage building a buffer
    if projected_savings > Decimal("0"):
        items.append(
            ActionItem(
                priority="low",
                category="savings",
                title="Build Emergency Fund",
                description=(
                    f"You have a projected monthly surplus of EGP {projected_savings:,.2f}. "
                    "Direct at least a portion of this into a dedicated emergency fund "
                    "until you have three to six months of expenses saved."
                ),
                estimated_impact=projected_savings,
                confidence_score=plan_confidence,
            )
        )

    # Low priority: always-present tracking nudge
    items.append(
        ActionItem(
            priority="low",
            category="spending",
            title="Track Monthly Budget",
            description=(
                "Review your transactions at the end of each week to stay aware of "
                "where your money is going and catch any unexpected charges early."
            ),
            estimated_impact=Decimal("0"),
            confidence_score=plan_confidence,
        )
    )

    # Sort: high -> medium -> low, then by estimated_impact desc within tier
    items.sort(key=_action_item_sort_key)

    # ------------------------------------------------------------------ #
    # Summary sentence
    # ------------------------------------------------------------------ #
    trend_phrase: str = {
        "up": "Your spending is trending upward",
        "down": "Your spending is trending downward",
        "flat": "Your spending has been stable",
    }[trends.spend_trend_direction]

    if spending.net >= Decimal("0"):
        balance_phrase = (
            f"and you ended the period with a positive balance of EGP {spending.net:,.2f}"
        )
    else:
        balance_phrase = f"and you ended the period with a deficit of EGP {abs(spending.net):,.2f}"

    summary: str = f"{trend_phrase} {balance_phrase}."

    return MonthlyPlan(
        month=target_month,
        year=target_year,
        summary=summary,
        action_items=items,
        projected_savings=projected_savings,
        health_score=round(health, 4),
        confidence_score=plan_confidence,
    )
