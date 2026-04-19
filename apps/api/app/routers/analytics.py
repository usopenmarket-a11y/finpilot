"""Analytics router — categorization, spending, trends, and credit analysis.

Security contract
-----------------
* Request bodies MUST NOT appear in any log call — amounts, descriptions, and
  account numbers are PII and potential credential-adjacent data.
* Log only event names, counts, and opaque identifiers (e.g. number of
  transactions processed).
* All request models carry ``ConfigDict(extra="forbid")`` to reject unknown
  fields and prevent parameter-pollution attacks.
* ``settings`` is imported from ``app.config`` — never re-instantiated here.
* All monetary amounts are typed as ``Decimal``; ``float`` is forbidden for
  financial values to prevent rounding-error security bugs.

Import strategy
---------------
The analytics sub-modules (``categorizer``, ``spending``, ``trends``,
``credit``) are being built in parallel by the analytics agent.  They are
imported at module level so that a missing module raises ``ImportError`` at
application startup rather than at first request — this gives a clear,
immediate failure signal during development and CI rather than a silent 500
at runtime.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from uuid import UUID

import anthropic
from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from app.analytics.categorizer import categorize_batch
from app.analytics.credit import compute_credit_report
from app.analytics.spending import compute_spending_breakdown
from app.analytics.trends import compute_trends
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["analytics"])


# ---------------------------------------------------------------------------
# Shared input model
# ---------------------------------------------------------------------------


class TransactionInput(BaseModel):
    """Minimal transaction representation accepted by all analytics endpoints."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    description: str = Field(min_length=1, max_length=512)
    amount: Decimal = Field(gt=Decimal("0"))
    transaction_type: str = Field(pattern=r"^(debit|credit)$")
    account_id: UUID | None = None
    transaction_date: date | None = None
    category: str | None = None
    currency: str | None = None


# ---------------------------------------------------------------------------
# /categorize
# ---------------------------------------------------------------------------


class CategorizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transactions: list[TransactionInput] = Field(min_length=1, max_length=500)


class CategorizationResultResponse(BaseModel):
    transaction_id: UUID
    category: str
    sub_category: str
    confidence: float
    method: str


@router.post(
    "/analytics/categorize",
    response_model=list[CategorizationResultResponse],
    status_code=status.HTTP_200_OK,
    summary="AI-categorize a batch of transactions",
)
async def categorize_transactions(
    body: CategorizeRequest,
) -> list[CategorizationResultResponse]:
    """Run AI categorization on a batch of transactions.

    The Claude API key is read from ``settings``; if it is empty the
    categorizer degrades gracefully to rule-based fallback — callers do not
    need to guard for that case.

    HTTP error mapping
    ------------------
    * 422 — Pydantic validation failure (malformed request body).
    * 500 — Unexpected error from the categorizer.
    """
    client = anthropic.AsyncAnthropic(
        api_key=settings.claude_api_key.get_secret_value() or None,
    )

    # Build Transaction-like objects expected by the categorizer.  We pass only
    # the fields the categorizer actually reads: id, description, amount,
    # transaction_type.  Extra fields default to safe values.
    from datetime import datetime
    from uuid import uuid4

    from app.models.db import Transaction  # local import avoids circular risk

    _sentinel_account_id = uuid4()
    _sentinel_user_id = uuid4()
    _now = datetime.now()
    _today = date.today()

    transactions_for_categorizer: list[Transaction] = [
        Transaction(
            id=t.id,
            user_id=_sentinel_user_id,
            account_id=t.account_id if t.account_id is not None else _sentinel_account_id,
            external_id=str(t.id),
            amount=t.amount,
            currency=t.currency if t.currency is not None else "EGP",
            transaction_type=t.transaction_type,
            description=t.description,
            category=t.category,
            transaction_date=t.transaction_date if t.transaction_date is not None else _today,
            is_categorized=False,
            raw_data={},
            created_at=_now,
            updated_at=_now,
        )
        for t in body.transactions
    ]

    logger.info(
        "Categorization requested",
        extra={"transaction_count": len(body.transactions)},
    )

    try:
        results = await categorize_batch(transactions_for_categorizer, client)
    except Exception as exc:
        logger.error(
            "Categorization failed: unexpected error",
            exc_info=exc,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Categorization error",
        ) from exc

    logger.info(
        "Categorization completed",
        extra={"result_count": len(results)},
    )

    return [
        CategorizationResultResponse(
            transaction_id=r.transaction_id,
            category=r.category,
            sub_category=r.sub_category,
            confidence=r.confidence,
            method=r.method,
        )
        for r in results
    ]


# ---------------------------------------------------------------------------
# /analytics/recategorize — bulk re-categorize all transactions for a user
# ---------------------------------------------------------------------------


class RecategorizeResponse(BaseModel):
    processed: int
    updated: int


@router.post(
    "/analytics/recategorize",
    response_model=RecategorizeResponse,
    status_code=status.HTTP_200_OK,
    summary="Re-categorize all transactions for a user using updated rules + AI",
)
async def recategorize_all(
    x_user_id: str | None = Header(default=None, alias="x-user-id"),
) -> RecategorizeResponse:
    """Re-run categorization on every transaction for the given user.

    Reads all transactions from Supabase, runs them through the rule engine
    (and AI fallback), then bulk-updates the category/sub_category fields.
    Safe to run repeatedly — idempotent.
    """
    import uuid as _uuid_mod
    from datetime import datetime
    from uuid import UUID as _UUID

    from supabase import acreate_client

    from app.analytics.categorizer import categorize_batch
    from app.models.db import Transaction

    if not x_user_id:
        raise HTTPException(status_code=400, detail="x-user-id header is required")
    try:
        user_uuid = _UUID(x_user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid x-user-id header")

    supabase = await acreate_client(
        settings.supabase_url,
        settings.supabase_service_role_key.get_secret_value(),
    )

    # Fetch all transactions for the user
    response = (
        await supabase.table("transactions").select("*").eq("user_id", str(user_uuid)).execute()
    )
    rows = response.data or []

    if not rows:
        return RecategorizeResponse(processed=0, updated=0)

    _now = datetime.now()

    transactions: list[Transaction] = []
    for row in rows:
        try:
            transactions.append(
                Transaction(
                    id=_UUID(row["id"]),
                    user_id=user_uuid,
                    account_id=_UUID(row["account_id"]),
                    external_id=row.get("external_id", row["id"]),
                    amount=Decimal(str(row["amount"])),
                    currency=row.get("currency", "EGP"),
                    transaction_type=row["transaction_type"],
                    description=row["description"],
                    category=row.get("category"),
                    transaction_date=date.fromisoformat(row["transaction_date"]),
                    is_categorized=bool(row.get("is_categorized", False)),
                    raw_data=row.get("raw_data") or {},
                    created_at=_now,
                    updated_at=_now,
                )
            )
        except Exception:
            continue

    ai_client = anthropic.AsyncAnthropic(
        api_key=settings.claude_api_key.get_secret_value() or None,
    )

    logger.info("Bulk recategorize started: user_id=%s txn_count=%d", user_uuid, len(transactions))

    results = await categorize_batch(transactions, ai_client)

    updated = 0
    for txn, result in zip(transactions, results, strict=False):
        if result.category == "Other" and result.confidence < 0.5:
            continue
        det_id = str(
            _uuid_mod.uuid5(_uuid_mod.NAMESPACE_OID, f"{txn.account_id}:{txn.external_id}")
        )
        try:
            await (
                supabase.table("transactions")
                .update(
                    {
                        "category": result.category,
                        "sub_category": result.sub_category,
                        "is_categorized": True,
                    }
                )
                .eq("id", det_id)
                .execute()
            )
            updated += 1
        except Exception:
            logger.exception("Failed to update category for txn %s", det_id)

    logger.info("Bulk recategorize done: updated=%d/%d", updated, len(transactions))
    return RecategorizeResponse(processed=len(transactions), updated=updated)


# ---------------------------------------------------------------------------
# /spending
# ---------------------------------------------------------------------------


class SpendingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transactions: list[TransactionInput] = Field(min_length=1, max_length=500)
    period_start: date
    period_end: date
    currency: str = Field(default="EGP", pattern=r"^[A-Z]{3}$")
    payroll_account_ids: list[UUID] | None = None


class CategoryBreakdownResponse(BaseModel):
    category: str
    total: Decimal
    transaction_count: int
    percentage: float


class SpendingBreakdownResponse(BaseModel):
    period_start: date
    period_end: date
    currency: str
    total_debits: Decimal
    total_credits: Decimal
    net: Decimal
    by_category: list[CategoryBreakdownResponse]


@router.post(
    "/analytics/spending",
    response_model=SpendingBreakdownResponse,
    status_code=status.HTTP_200_OK,
    summary="Compute spending breakdown for a set of transactions",
)
async def spending_breakdown(body: SpendingRequest) -> SpendingBreakdownResponse:
    """Aggregate debit/credit totals and per-category spending for a period.

    HTTP error mapping
    ------------------
    * 400 — ``period_end`` is before ``period_start``.
    * 422 — Pydantic validation failure.
    * 500 — Unexpected error from the spending module.
    """
    if body.period_end < body.period_start:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="period_end must be on or after period_start",
        )

    logger.info(
        "Spending breakdown requested",
        extra={"transaction_count": len(body.transactions)},
    )

    from datetime import datetime
    from uuid import uuid4

    from app.models.db import Transaction

    _sentinel_user_id = uuid4()
    _now = datetime.now()

    transactions_for_spending: list[Transaction] = [
        Transaction(
            id=t.id,
            user_id=_sentinel_user_id,
            account_id=t.account_id if t.account_id is not None else uuid4(),
            external_id=str(t.id),
            amount=t.amount,
            currency=t.currency if t.currency is not None else body.currency,
            transaction_type=t.transaction_type,
            description=t.description,
            category=t.category,
            transaction_date=t.transaction_date
            if t.transaction_date is not None
            else body.period_start,
            is_categorized=t.category is not None,
            raw_data={},
            created_at=_now,
            updated_at=_now,
        )
        for t in body.transactions
    ]

    payroll_set: set[str] | None = (
        {str(aid) for aid in body.payroll_account_ids}
        if body.payroll_account_ids is not None
        else None
    )

    try:
        result = compute_spending_breakdown(
            transactions_for_spending,
            body.period_start,
            body.period_end,
            payroll_account_ids=payroll_set,
        )
    except Exception as exc:
        logger.error(
            "Spending breakdown failed: unexpected error",
            exc_info=exc,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Spending breakdown error",
        ) from exc

    return SpendingBreakdownResponse(
        period_start=result.period_start,
        period_end=result.period_end,
        currency=body.currency,
        total_debits=result.total_debits,
        total_credits=result.total_credits,
        net=result.net,
        by_category=[
            CategoryBreakdownResponse(
                category=c.category,
                total=c.total,
                transaction_count=c.transaction_count,
                percentage=c.percentage,
            )
            for c in result.by_category
        ],
    )


# ---------------------------------------------------------------------------
# /trends
# ---------------------------------------------------------------------------


class TrendsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transactions: list[TransactionInput] = Field(min_length=1, max_length=5000)
    lookback_months: int = Field(default=6, ge=1, le=24)
    payroll_account_ids: list[UUID] | None = None


class MonthlyTrendPointResponse(BaseModel):
    year: int
    month: int
    total_debits: Decimal
    total_credits: Decimal
    net: Decimal
    transaction_count: int


class TrendReportResponse(BaseModel):
    lookback_months: int
    monthly_points: list[MonthlyTrendPointResponse]
    avg_monthly_spend: Decimal
    avg_monthly_income: Decimal
    spend_trend_direction: str  # "up" | "down" | "flat"


@router.post(
    "/analytics/trends",
    response_model=TrendReportResponse,
    status_code=status.HTTP_200_OK,
    summary="Compute monthly spending and income trends",
)
async def trend_report(body: TrendsRequest) -> TrendReportResponse:
    """Produce a month-by-month trend analysis over the requested lookback window.

    HTTP error mapping
    ------------------
    * 422 — Pydantic validation failure.
    * 500 — Unexpected error from the trends module.
    """
    logger.info(
        "Trend analysis requested",
        extra={
            "transaction_count": len(body.transactions),
            "lookback_months": body.lookback_months,
        },
    )

    from datetime import datetime
    from uuid import uuid4

    from app.models.db import Transaction

    _sentinel_user_id = uuid4()
    _now = datetime.now()
    _today = date.today()

    transactions_for_trends: list[Transaction] = [
        Transaction(
            id=t.id,
            user_id=_sentinel_user_id,
            account_id=t.account_id if t.account_id is not None else uuid4(),
            external_id=str(t.id),
            amount=t.amount,
            currency=t.currency if t.currency is not None else "EGP",
            transaction_type=t.transaction_type,
            description=t.description,
            category=t.category,
            transaction_date=t.transaction_date if t.transaction_date is not None else _today,
            is_categorized=t.category is not None,
            raw_data={},
            created_at=_now,
            updated_at=_now,
        )
        for t in body.transactions
    ]

    payroll_set: set[str] | None = (
        {str(aid) for aid in body.payroll_account_ids}
        if body.payroll_account_ids is not None
        else None
    )

    try:
        result = compute_trends(
            transactions_for_trends,
            body.lookback_months,
            payroll_account_ids=payroll_set,
        )
    except Exception as exc:
        logger.error(
            "Trend analysis failed: unexpected error",
            exc_info=exc,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Trend analysis error",
        ) from exc

    return TrendReportResponse(
        lookback_months=result.lookback_months,
        monthly_points=[
            MonthlyTrendPointResponse(
                year=p.year,
                month=p.month,
                total_debits=p.total_debits,
                total_credits=p.total_credits,
                net=p.net,
                transaction_count=p.transaction_count,
            )
            for p in result.monthly_points
        ],
        avg_monthly_spend=result.avg_monthly_spend,
        avg_monthly_income=result.avg_monthly_income,
        spend_trend_direction=result.spend_trend_direction,
    )


# ---------------------------------------------------------------------------
# /credit
# ---------------------------------------------------------------------------


class AccountInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    bank_name: str = Field(min_length=1, max_length=64)
    account_number_masked: str = Field(
        min_length=4,
        max_length=32,
        pattern=r"^\*+\d{4}$",
        description="Masked account number — must be in the form ****NNNN",
    )
    account_type: str = Field(pattern=r"^(savings|current|credit|loan)$")
    balance: Decimal
    currency: str = Field(default="EGP", pattern=r"^[A-Z]{3}$")


class LoanInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    loan_type: str = Field(pattern=r"^(personal|mortgage|auto|overdraft)$")
    outstanding_balance: Decimal = Field(ge=Decimal("0"))
    monthly_installment: Decimal = Field(gt=Decimal("0"))
    interest_rate: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    next_payment_date: date | None = None


class CreditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accounts: list[AccountInput] = Field(min_length=1, max_length=20)
    loans: list[LoanInput] = Field(default_factory=list, max_length=20)


class LoanSummaryResponse(BaseModel):
    loan_id: UUID
    loan_type: str
    outstanding_balance: Decimal
    monthly_installment: Decimal
    interest_rate: Decimal
    next_payment_date: date | None


class CreditReportResponse(BaseModel):
    total_balance: Decimal
    total_outstanding_debt: Decimal
    total_monthly_obligations: Decimal
    debt_to_balance_ratio: float
    loan_summaries: list[LoanSummaryResponse]
    credit_health_score: float  # 0.0 – 1.0 (normalised from 0–100 int for API compat)
    credit_health_label: str  # "excellent" | "good" | "fair" | "poor"


@router.post(
    "/analytics/credit",
    response_model=CreditReportResponse,
    status_code=status.HTTP_200_OK,
    summary="Compute credit utilization and debt health report",
)
async def credit_report(body: CreditRequest) -> CreditReportResponse:
    """Aggregate account balances and loan obligations into a credit health snapshot.

    HTTP error mapping
    ------------------
    * 422 — Pydantic validation failure.
    * 500 — Unexpected error from the credit module.
    """
    logger.info(
        "Credit report requested",
        extra={
            "account_count": len(body.accounts),
            "loan_count": len(body.loans),
        },
    )

    from datetime import datetime
    from uuid import uuid4

    from app.models.db import BankAccount, Loan

    _sentinel_user_id = uuid4()
    _now = datetime.now()

    accounts_for_credit: list[BankAccount] = [
        BankAccount(
            id=a.id,
            user_id=_sentinel_user_id,
            bank_name=a.bank_name,
            account_number_masked=a.account_number_masked,
            account_type=a.account_type,
            balance=a.balance,
            currency=a.currency,
            created_at=_now,
            updated_at=_now,
        )
        for a in body.accounts
    ]

    loans_for_credit: list[Loan] = [
        Loan(
            id=ln.id,
            user_id=_sentinel_user_id,
            account_id=uuid4(),
            loan_type=ln.loan_type,
            principal_amount=ln.outstanding_balance,
            outstanding_balance=ln.outstanding_balance,
            interest_rate=ln.interest_rate,
            monthly_installment=ln.monthly_installment,
            next_payment_date=ln.next_payment_date,
            created_at=_now,
            updated_at=_now,
        )
        for ln in body.loans
    ]

    try:
        result = compute_credit_report(accounts_for_credit, loans_for_credit)
    except Exception as exc:
        logger.error(
            "Credit report failed: unexpected error",
            exc_info=exc,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Credit report error",
        ) from exc

    return CreditReportResponse(
        total_balance=result.total_balance,
        total_outstanding_debt=result.total_outstanding_debt,
        total_monthly_obligations=result.total_monthly_obligations,
        debt_to_balance_ratio=float(result.debt_to_balance_ratio),
        loan_summaries=[
            LoanSummaryResponse(
                loan_id=loan.loan_id,
                loan_type=loan.loan_type,
                outstanding_balance=loan.outstanding_balance,
                monthly_installment=loan.monthly_installment,
                interest_rate=loan.interest_rate,
                next_payment_date=loan.next_payment_date,
            )
            for loan in result.loan_summaries
        ],
        # Normalise 0–100 int score to 0.0–1.0 float for API consumers
        credit_health_score=result.credit_health_score / 100.0,
        credit_health_label=result.credit_health_label,
    )
