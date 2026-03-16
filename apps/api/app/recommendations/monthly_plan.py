"""Monthly action plan generator.

Produces a prioritised list of concrete financial steps a user can take in a
given month, derived from their current spending breakdown and multi-month
trend data.  All monetary values are in EGP.

Pure functions only — no I/O, no HTTP calls, no database calls.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Constants — all EGP thresholds live here so callers can override in tests
# ---------------------------------------------------------------------------

# Category share of total_debits above which a review action is generated
CATEGORY_REVIEW_THRESHOLD_PCT: float = 30.0

# Category share above which health_score is penalised (single category dominance)
CATEGORY_DOMINANCE_THRESHOLD_PCT: float = 40.0

HEALTH_PENALTY_TREND_UP: float = 0.3
HEALTH_PENALTY_NEGATIVE_NET: float = 0.2
HEALTH_PENALTY_CATEGORY_DOMINANCE: float = 0.1

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

    Computes a health_score by applying deductions for negative signals
    (upward spend trend, negative net balance, single-category dominance),
    then assembles a list of concrete ActionItems based on the same signals.
    Items are sorted high -> medium -> low priority.

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
    # Health score
    # ------------------------------------------------------------------ #
    health: float = 1.0

    if trends.spend_trend_direction == "up":
        health -= HEALTH_PENALTY_TREND_UP

    if spending.net < Decimal("0"):
        health -= HEALTH_PENALTY_NEGATIVE_NET

    dominant_categories: list[CategoryBreakdown] = [
        c for c in spending.by_category if c.percentage > CATEGORY_DOMINANCE_THRESHOLD_PCT
    ]
    if dominant_categories:
        health -= HEALTH_PENALTY_CATEGORY_DOMINANCE

    health = max(0.0, min(1.0, health))

    # ------------------------------------------------------------------ #
    # Projected savings
    # ------------------------------------------------------------------ #
    raw_savings: Decimal = trends.avg_monthly_income - trends.avg_monthly_spend
    projected_savings: Decimal = raw_savings if raw_savings > Decimal("0") else Decimal("0")

    # ------------------------------------------------------------------ #
    # Action items
    # ------------------------------------------------------------------ #
    items: list[ActionItem] = []

    # High priority: spending is trending upward
    if trends.spend_trend_direction == "up":
        items.append(
            ActionItem(
                priority="high",
                category="spending",
                title="Reduce Spending",
                description=(
                    "Your spending has been increasing month-over-month. "
                    "Review your largest expense categories and identify at least one "
                    "area where you can cut back this month to reverse the trend."
                ),
                estimated_impact=Decimal("0"),
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
        items.append(
            ActionItem(
                priority="medium",
                category="spending",
                title=f"Review {cat.category} Spending",
                description=(
                    f"{cat.category} accounts for {cat.percentage:.1f}% of your total "
                    f"spending (EGP {cat.total:,.2f}). Consider whether this level of "
                    "expenditure aligns with your financial goals and look for ways to "
                    "reduce it."
                ),
                estimated_impact=Decimal("0"),
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

    # Sort: high -> medium -> low (stable within same priority)
    items.sort(key=_priority_key)

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
