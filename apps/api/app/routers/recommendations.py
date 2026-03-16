"""Recommendations router — monthly plan, cash flow forecast, debt optimizer, savings.

Security contract
-----------------
* Request bodies MUST NOT appear in any log call — amounts, descriptions, and
  account numbers are PII and potential credential-adjacent data.
* Log only event names and counts; never amounts, names, or descriptions.
* All request models carry ``ConfigDict(extra="forbid")`` to reject unknown
  fields and prevent parameter-pollution attacks.
* All monetary amounts are typed as ``Decimal``; ``float`` is forbidden for
  financial values to prevent rounding-error security bugs.

Import strategy
---------------
The recommendations sub-modules (``monthly_plan``, ``forecaster``,
``debt_optimizer``, ``savings``) are imported at module level so that a
missing module raises ``ImportError`` at application startup rather than at
first request — giving a clear, immediate failure signal during development
and CI rather than a silent 500 at runtime.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from app.recommendations.debt_optimizer import (
    DebtItem,
    DebtOptimizationReport,
    optimize_debt_payoff,
)
from app.recommendations.forecaster import (
    CashFlowForecast,
    generate_forecast,
)
from app.recommendations.monthly_plan import (
    CategoryBreakdown,
    MonthlyPlan,
    MonthlyPoint,
    SpendingBreakdown,
    TrendReport,
    generate_monthly_plan,
)
from app.recommendations.savings import (
    SavingsReport,
    TransactionSummary,
    detect_savings_opportunities,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["recommendations"])


# ---------------------------------------------------------------------------
# Wire-format input models
# ---------------------------------------------------------------------------


class CategoryBreakdownInput(BaseModel):
    """Per-category spending breakdown received from the API caller."""

    model_config = ConfigDict(extra="forbid")

    category: str
    total: Decimal
    transaction_count: int
    percentage: float


class SpendingBreakdownInput(BaseModel):
    """Full spending breakdown for the current period (wire format)."""

    model_config = ConfigDict(extra="forbid")

    total_debits: Decimal
    total_credits: Decimal
    net: Decimal
    by_category: list[CategoryBreakdownInput]


class MonthlyPointInput(BaseModel):
    """Aggregated statistics for a single calendar month (wire format)."""

    model_config = ConfigDict(extra="forbid")

    year: int
    month: int
    total_debits: Decimal
    total_credits: Decimal
    net: Decimal
    transaction_count: int


class TrendReportInput(BaseModel):
    """Multi-month trend data (wire format)."""

    model_config = ConfigDict(extra="forbid")

    lookback_months: int = Field(ge=1, le=24)
    monthly_points: list[MonthlyPointInput]
    avg_monthly_spend: Decimal
    avg_monthly_income: Decimal
    spend_trend_direction: str = Field(pattern=r"^(up|down|flat)$")


class DebtItemInput(BaseModel):
    """A single debt obligation received from the API caller (wire format)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    debt_type: str = Field(pattern=r"^(loan|lent|borrowed)$")
    outstanding_balance: Decimal = Field(ge=Decimal("0"))
    interest_rate: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    minimum_payment: Decimal = Field(ge=Decimal("0"))
    currency: str = Field(default="EGP", pattern=r"^[A-Z]{3}$")


class TransactionSummaryInput(BaseModel):
    """A lightweight transaction record received from the API caller (wire format)."""

    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=1, max_length=512)
    amount: Decimal = Field(gt=Decimal("0"))
    transaction_type: str = Field(pattern=r"^(debit|credit)$")
    transaction_date: date
    category: str | None = None


# ---------------------------------------------------------------------------
# Request body models
# ---------------------------------------------------------------------------


class MonthlyPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spending: SpendingBreakdownInput
    trends: TrendReportInput
    target_month: int = Field(ge=1, le=12)
    target_year: int = Field(ge=2000, le=2100)


class ForecastRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trends: TrendReportInput
    from_date: date | None = None


class DebtOptimizerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    debts: list[DebtItemInput] = Field(min_length=1)
    monthly_budget: Decimal = Field(gt=Decimal("0"))


class SavingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transactions: list[TransactionSummaryInput] = Field(min_length=1)


# ---------------------------------------------------------------------------
# Bridge functions — wire format → module types
# ---------------------------------------------------------------------------


def _to_spending_breakdown(inp: SpendingBreakdownInput) -> SpendingBreakdown:
    """Convert a SpendingBreakdownInput wire model to the module's SpendingBreakdown."""
    return SpendingBreakdown(
        total_debits=inp.total_debits,
        total_credits=inp.total_credits,
        net=inp.net,
        by_category=[
            CategoryBreakdown(
                category=c.category,
                total=c.total,
                percentage=c.percentage,
            )
            for c in inp.by_category
        ],
    )


def _to_trend_report(inp: TrendReportInput) -> TrendReport:
    """Convert a TrendReportInput wire model to the module's TrendReport."""
    return TrendReport(
        lookback_months=inp.lookback_months,
        monthly_points=[
            MonthlyPoint(
                year=p.year,
                month=p.month,
                total_debits=p.total_debits,
                total_credits=p.total_credits,
                net=p.net,
                transaction_count=p.transaction_count,
            )
            for p in inp.monthly_points
        ],
        avg_monthly_spend=inp.avg_monthly_spend,
        avg_monthly_income=inp.avg_monthly_income,
        spend_trend_direction=inp.spend_trend_direction,  # type: ignore[arg-type]
    )


def _to_debt_items(inp: list[DebtItemInput]) -> list[DebtItem]:
    """Convert a list of DebtItemInput wire models to the module's DebtItem list."""
    return [
        DebtItem(
            id=d.id,
            name=d.name,
            debt_type=d.debt_type,  # type: ignore[arg-type]
            outstanding_balance=d.outstanding_balance,
            interest_rate=d.interest_rate,
            minimum_payment=d.minimum_payment,
            currency=d.currency,
        )
        for d in inp
    ]


def _to_transaction_summaries(
    inp: list[TransactionSummaryInput],
) -> list[TransactionSummary]:
    """Convert a list of TransactionSummaryInput wire models to the module's TransactionSummary list."""
    return [
        TransactionSummary(
            description=t.description,
            amount=t.amount,
            transaction_type=t.transaction_type,  # type: ignore[arg-type]
            transaction_date=t.transaction_date,
            category=t.category,
        )
        for t in inp
    ]


# ---------------------------------------------------------------------------
# POST /recommendations/monthly-plan
# ---------------------------------------------------------------------------


@router.post(
    "/recommendations/monthly-plan",
    response_model=MonthlyPlan,
    status_code=status.HTTP_200_OK,
    summary="Generate a prioritised monthly action plan",
)
async def monthly_plan(body: MonthlyPlanRequest) -> MonthlyPlan:
    """Produce a prioritised list of concrete financial steps for a target month.

    Derives a health score and a set of action items from the caller-supplied
    spending breakdown and trend data.

    HTTP error mapping
    ------------------
    * 400 — Business logic error (e.g. invalid date range or constraint violation).
    * 422 — Pydantic validation failure (malformed request body).
    * 500 — Unexpected error from the monthly plan engine.
    """
    logger.info(
        "Monthly plan requested",
        extra={
            "target_month": body.target_month,
            "target_year": body.target_year,
            "category_count": len(body.spending.by_category),
            "lookback_months": body.trends.lookback_months,
        },
    )

    spending = _to_spending_breakdown(body.spending)
    trends = _to_trend_report(body.trends)

    try:
        plan = generate_monthly_plan(
            spending=spending,
            trends=trends,
            target_month=body.target_month,
            target_year=body.target_year,
        )
    except ValueError as exc:
        logger.warning("Monthly plan generation rejected: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.error(
            "Monthly plan generation failed: unexpected error",
            exc_info=exc,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Monthly plan generation error",
        ) from exc

    logger.info(
        "Monthly plan generated",
        extra={"action_item_count": len(plan.action_items)},
    )
    return plan


# ---------------------------------------------------------------------------
# POST /recommendations/forecast
# ---------------------------------------------------------------------------


@router.post(
    "/recommendations/forecast",
    response_model=CashFlowForecast,
    status_code=status.HTTP_200_OK,
    summary="Generate a 3-month cash flow forecast",
)
async def cash_flow_forecast(body: ForecastRequest) -> CashFlowForecast:
    """Project income and expenses for the next three calendar months.

    Uses weighted averages from historical trend data and a growth factor
    driven by the current spend direction.

    HTTP error mapping
    ------------------
    * 400 — Business logic error (e.g. invalid from_date).
    * 422 — Pydantic validation failure.
    * 500 — Unexpected error from the forecaster.
    """
    logger.info(
        "Cash flow forecast requested",
        extra={
            "lookback_months": body.trends.lookback_months,
            "has_from_date": body.from_date is not None,
        },
    )

    trends = _to_trend_report(body.trends)

    try:
        forecast = generate_forecast(
            trends=trends,
            from_date=body.from_date,
        )
    except ValueError as exc:
        logger.warning("Forecast generation rejected: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.error(
            "Forecast generation failed: unexpected error",
            exc_info=exc,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Forecast generation error",
        ) from exc

    logger.info(
        "Cash flow forecast generated",
        extra={"forecast_point_count": len(forecast.forecast_points)},
    )
    return forecast


# ---------------------------------------------------------------------------
# POST /recommendations/debt-optimizer
# ---------------------------------------------------------------------------


@router.post(
    "/recommendations/debt-optimizer",
    response_model=DebtOptimizationReport,
    status_code=status.HTTP_200_OK,
    summary="Compare snowball vs. avalanche debt payoff strategies",
)
async def debt_optimizer(body: DebtOptimizerRequest) -> DebtOptimizationReport:
    """Simulate both snowball and avalanche payoff strategies and recommend one.

    Returns a side-by-side report with a plain-language recommendation and
    the total interest saved by choosing the optimal strategy.

    HTTP error mapping
    ------------------
    * 400 — Business logic error (e.g. budget too low to cover minimum payments).
    * 422 — Pydantic validation failure.
    * 500 — Unexpected error from the debt optimizer.
    """
    logger.info(
        "Debt optimizer requested",
        extra={"debt_count": len(body.debts)},
    )

    debts = _to_debt_items(body.debts)

    try:
        report = optimize_debt_payoff(
            debts=debts,
            monthly_budget=body.monthly_budget,
        )
    except ValueError as exc:
        logger.warning("Debt optimizer rejected: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.error(
            "Debt optimizer failed: unexpected error",
            exc_info=exc,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Debt optimization error",
        ) from exc

    logger.info(
        "Debt optimization report generated",
        extra={"recommended_strategy": report.recommended_strategy},
    )
    return report


# ---------------------------------------------------------------------------
# POST /recommendations/savings
# ---------------------------------------------------------------------------


@router.post(
    "/recommendations/savings",
    response_model=SavingsReport,
    status_code=status.HTTP_200_OK,
    summary="Detect savings opportunities from transaction history",
)
async def savings_opportunities(body: SavingsRequest) -> SavingsReport:
    """Analyse a list of transactions and surface up to 10 ranked savings opportunities.

    Runs four detection passes: duplicate charges, recurring subscriptions,
    high bank fees, and irregular spending spikes.

    HTTP error mapping
    ------------------
    * 400 — Business logic error (e.g. invalid date range in transactions).
    * 422 — Pydantic validation failure.
    * 500 — Unexpected error from the savings detector.
    """
    logger.info(
        "Savings opportunities requested",
        extra={"transaction_count": len(body.transactions)},
    )

    transactions = _to_transaction_summaries(body.transactions)

    try:
        report = detect_savings_opportunities(transactions=transactions)
    except ValueError as exc:
        logger.warning("Savings detection rejected: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.error(
            "Savings detection failed: unexpected error",
            exc_info=exc,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Savings detection error",
        ) from exc

    logger.info(
        "Savings report generated",
        extra={"opportunity_count": len(report.opportunities)},
    )
    return report
