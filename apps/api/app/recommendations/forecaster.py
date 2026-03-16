"""3-month cash flow forecaster.

Projects income and expenses for the next three calendar months using
weighted averages from historical trend data and a configurable growth
factor based on the current spend direction.

All monetary values are in EGP.  Pure functions only — no I/O, no HTTP
calls, no database calls.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from pydantic import BaseModel, ConfigDict, Field

from app.recommendations.monthly_plan import TrendReport

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Number of months to forecast
FORECAST_HORIZON: int = 3

# Expense growth rates per additional forecast month
EXPENSE_GROWTH_RATE_UP: Decimal = Decimal("0.03")    # +3 % compounding
EXPENSE_GROWTH_RATE_DOWN: Decimal = Decimal("-0.02") # -2 % per month
EXPENSE_GROWTH_RATE_FLAT: Decimal = Decimal("0.00")  # no change

# Income pressure when spending is trending up (-2 % per forecast month)
INCOME_PRESSURE_RATE_UP: Decimal = Decimal("-0.02")

# Base confidence and per-month decay
BASE_CONFIDENCE: float = 0.9
CONFIDENCE_DECAY_PER_MONTH: float = 0.1

# Additional confidence reduction when history is sparse (< 3 months)
SPARSE_DATA_CONFIDENCE_PENALTY: float = 0.2
SPARSE_DATA_THRESHOLD: int = 3

# Decimal quantisation for EGP amounts (2 decimal places)
_EGP_QUANT = Decimal("0.01")

# Threshold for "improving" classification: avg net > avg_income * this factor
IMPROVING_NET_INCOME_RATIO: Decimal = Decimal("0.1")


# ---------------------------------------------------------------------------
# Output models
# ---------------------------------------------------------------------------


class ForecastPoint(BaseModel):
    """Projected cash flow for a single future calendar month."""

    model_config = ConfigDict(frozen=True)

    year: int = Field(ge=2000, le=2100, description="Forecast month year")
    month: int = Field(ge=1, le=12, description="Forecast month (1–12)")
    projected_income: Decimal = Field(
        ge=Decimal("0"),
        description="Expected EGP received in this month",
    )
    projected_expenses: Decimal = Field(
        ge=Decimal("0"),
        description="Expected EGP spent in this month",
    )
    projected_net: Decimal = Field(
        description="projected_income - projected_expenses; negative means projected deficit",
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Forecast confidence for this specific month (0–1); decreases over horizon",
    )
    confidence_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Alias of confidence — present to satisfy the standard output model contract",
    )
    generated_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="UTC timestamp when this forecast point was generated",
    )


class CashFlowForecast(BaseModel):
    """Complete 3-month cash flow forecast.

    Contains one ForecastPoint per future month plus summary statistics
    that characterise the overall projected trajectory.
    """

    model_config = ConfigDict(frozen=True)

    forecast_points: list[ForecastPoint] = Field(
        description="Exactly three forecast points, one per future calendar month",
    )
    avg_projected_monthly_net: Decimal = Field(
        description="Mean of projected_net across all forecast points (EGP); can be negative",
    )
    trend_direction: str = Field(
        description="'improving' | 'stable' | 'declining' — characterises the forecast trajectory",
    )
    confidence_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Composite model confidence for the overall forecast (0–1)",
    )
    generated_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="UTC timestamp when this forecast was generated",
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _next_month(year: int, month: int) -> tuple[int, int]:
    """Return (year, month) for the calendar month immediately following the input.

    Args:
        year: Four-digit year of the current month.
        month: Current month (1–12).

    Returns:
        Tuple of (next_year, next_month) where next_month wraps from 12 to 1.
    """
    if month == 12:
        return year + 1, 1
    return year, month + 1


def _clamp_confidence(value: float) -> float:
    """Clamp a confidence value to the valid [0.0, 1.0] range.

    Args:
        value: Raw confidence float, possibly outside [0, 1].

    Returns:
        Float clamped to [0.0, 1.0].
    """
    return max(0.0, min(1.0, value))


def _egp(value: Decimal) -> Decimal:
    """Quantise a Decimal to 2 decimal places using ROUND_HALF_UP.

    Args:
        value: Raw Decimal amount.

    Returns:
        Decimal rounded to EGP precision (2 d.p.).
    """
    return value.quantize(_EGP_QUANT, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Core generation function
# ---------------------------------------------------------------------------


def generate_forecast(
    trends: TrendReport,
    from_date: date | None = None,
) -> CashFlowForecast:
    """Generate a 3-month cash flow forecast from historical trend data.

    Uses the average monthly income and spend from the trend window as base
    values, then applies per-month growth factors driven by spend_trend_direction.
    Confidence declines with each additional month into the future and is
    further reduced when the historical lookback window is shorter than
    SPARSE_DATA_THRESHOLD months.

    Trend direction of the forecast is classified as:
      - "improving"  if avg projected net > avg_monthly_income * IMPROVING_NET_INCOME_RATIO
      - "declining"  if avg projected net < 0
      - "stable"     otherwise

    Args:
        trends: TrendReport containing historical averages and spend direction.
            Import or bridge from analytics.trends.TrendReport using the
            monthly_plan.TrendReport Pydantic model.
        from_date: Reference date used to determine which three months are
            "next".  Defaults to date.today() when None.

    Returns:
        CashFlowForecast with exactly FORECAST_HORIZON ForecastPoint entries,
        summary statistics, and a composite confidence_score.
    """
    effective_date: date = from_date if from_date is not None else date.today()

    # Determine the growth rate for expenses
    growth_rate: Decimal = {
        "up": EXPENSE_GROWTH_RATE_UP,
        "down": EXPENSE_GROWTH_RATE_DOWN,
        "flat": EXPENSE_GROWTH_RATE_FLAT,
    }[trends.spend_trend_direction]

    # Determine whether income faces pressure (only when spending is "up")
    income_monthly_adjustment: Decimal = (
        INCOME_PRESSURE_RATE_UP
        if trends.spend_trend_direction == "up"
        else Decimal("0")
    )

    # Sparse-data penalty applied uniformly across all months
    sparse_penalty: float = (
        SPARSE_DATA_CONFIDENCE_PENALTY
        if trends.lookback_months < SPARSE_DATA_THRESHOLD
        else 0.0
    )

    # Walk forward through FORECAST_HORIZON months starting from the month
    # *after* from_date
    current_year, current_month = effective_date.year, effective_date.month
    forecast_points: list[ForecastPoint] = []

    for step in range(1, FORECAST_HORIZON + 1):
        current_year, current_month = _next_month(current_year, current_month)

        # --- Income projection ---
        # Apply income_monthly_adjustment cumulatively per forecast step.
        # Formula: base * (1 + rate) ^ step
        income_factor: Decimal = (Decimal("1") + income_monthly_adjustment) ** step
        projected_income: Decimal = _egp(
            max(Decimal("0"), trends.avg_monthly_income * income_factor)
        )

        # --- Expense projection ---
        # Apply growth_rate as a compounding factor per step.
        # Formula: base * (1 + rate) ^ step
        expense_factor: Decimal = (Decimal("1") + growth_rate) ** step
        projected_expenses: Decimal = _egp(
            max(Decimal("0"), trends.avg_monthly_spend * expense_factor)
        )

        projected_net: Decimal = _egp(projected_income - projected_expenses)

        # --- Confidence ---
        # Base decays linearly by CONFIDENCE_DECAY_PER_MONTH per step,
        # then sparse penalty is applied uniformly.
        raw_confidence: float = (
            BASE_CONFIDENCE
            - (step - 1) * CONFIDENCE_DECAY_PER_MONTH
            - sparse_penalty
        )
        confidence: float = _clamp_confidence(raw_confidence)

        forecast_points.append(
            ForecastPoint(
                year=current_year,
                month=current_month,
                projected_income=projected_income,
                projected_expenses=projected_expenses,
                projected_net=projected_net,
                confidence=confidence,
                confidence_score=confidence,
            )
        )

    # ------------------------------------------------------------------ #
    # Summary statistics
    # ------------------------------------------------------------------ #
    total_net: Decimal = sum(
        (fp.projected_net for fp in forecast_points), Decimal("0")
    )
    avg_projected_monthly_net: Decimal = _egp(
        total_net / Decimal(FORECAST_HORIZON)
    )

    # Trend direction classification
    improving_threshold: Decimal = trends.avg_monthly_income * IMPROVING_NET_INCOME_RATIO
    if avg_projected_monthly_net > improving_threshold:
        trend_direction = "improving"
    elif avg_projected_monthly_net < Decimal("0"):
        trend_direction = "declining"
    else:
        trend_direction = "stable"

    # Composite confidence: average across all forecast points
    composite_confidence: float = _clamp_confidence(
        sum(fp.confidence for fp in forecast_points) / FORECAST_HORIZON
    )

    return CashFlowForecast(
        forecast_points=forecast_points,
        avg_projected_monthly_net=avg_projected_monthly_net,
        trend_direction=trend_direction,
        confidence_score=composite_confidence,
    )
