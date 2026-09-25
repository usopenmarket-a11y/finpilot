"""Persistent debt tracker. Every query is scoped to the verified caller.

Payment inserts update balances atomically through the debt_payment_balance
PostgreSQL trigger shared with the web app. No application-local ledger exists.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from postgrest.exceptions import APIError
from pydantic import BaseModel, ConfigDict, Field

from app.deps import get_async_service_role_client, get_current_user_id

logger = logging.getLogger(__name__)
router = APIRouter(tags=["debts"])
_DEBT_TYPE_PATTERN = r"^(lent|borrowed)$"
_DEBT_STATUS_PATTERN = r"^(active|partial|settled)$"
_CURRENCY_PATTERN = r"^[A-Z]{3}$"


class DebtCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    debt_type: str = Field(pattern=_DEBT_TYPE_PATTERN)
    counterparty_name: str = Field(min_length=1, max_length=256)
    counterparty_phone: str | None = Field(default=None, max_length=32)
    counterparty_email: str | None = Field(default=None, max_length=256)
    original_amount: Decimal = Field(gt=Decimal("0"))
    currency: str = Field(default="EGP", pattern=_CURRENCY_PATTERN)
    due_date: date | None = None
    notes: str | None = Field(default=None, max_length=1024)


class DebtUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    counterparty_phone: str | None = Field(default=None, max_length=32)
    counterparty_email: str | None = Field(default=None, max_length=256)
    due_date: date | None = None
    notes: str | None = Field(default=None, max_length=1024)
    status: str | None = Field(default=None, pattern=_DEBT_STATUS_PATTERN)


class DebtPaymentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: Decimal = Field(gt=Decimal("0"))
    payment_date: date
    notes: str | None = Field(default=None, max_length=1024)


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class DebtResponse(BaseModel):
    id: UUID
    user_id: UUID
    debt_type: str
    counterparty_name: str
    counterparty_phone: str | None
    counterparty_email: str | None
    original_amount: Decimal
    outstanding_balance: Decimal
    currency: str
    due_date: date | None
    notes: str | None
    status: str
    created_at: datetime
    updated_at: datetime


class PaymentResponse(BaseModel):
    id: UUID
    debt_id: UUID
    amount: Decimal
    payment_date: date
    notes: str | None
    created_at: datetime


class DebtDetailResponse(DebtResponse):
    payments: list[PaymentResponse]


async def _execute(query: Any) -> list[dict]:
    try:
        response = await query.execute()
        return response.data or []
    except APIError as exc:
        if exc.code == "23514":
            raise HTTPException(
                status_code=400, detail="Payment amount exceeds outstanding balance"
            ) from exc
        if exc.code == "23503":
            raise HTTPException(status_code=404, detail="Debt not found") from exc
        logger.error("Debt database operation failed: %s", exc.code)
        raise HTTPException(
            status_code=503, detail="Debt storage is temporarily unavailable"
        ) from exc


def _validated_id(debt_id: str) -> str:
    try:
        return str(UUID(debt_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Debt not found") from exc


async def _get_debt_or_404(client: Any, debt_id: str, user_id: UUID) -> dict:
    rows = await _execute(
        client.table("debts")
        .select("*")
        .eq("id", _validated_id(debt_id))
        .eq("user_id", str(user_id))
        .limit(1)
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Debt not found")
    return rows[0]


@router.post("/debts", response_model=DebtResponse, status_code=status.HTTP_201_CREATED)
async def create_debt(
    body: DebtCreate, user_id: UUID = Depends(get_current_user_id)
) -> DebtResponse:
    client = await get_async_service_role_client()
    payload = body.model_dump(mode="json")
    payload.update(
        user_id=str(user_id), outstanding_balance=str(body.original_amount), status="active"
    )
    rows = await _execute(client.table("debts").insert(payload))
    return DebtResponse.model_validate(rows[0])


@router.get("/debts", response_model=list[DebtResponse])
async def list_debts(
    status: str | None = None,
    debt_type: str | None = None,
    user_id: UUID = Depends(get_current_user_id),
) -> list[DebtResponse]:
    if status is not None and status not in {"active", "partial", "settled"}:
        raise HTTPException(
            status_code=400, detail="Invalid status value. Must be one of: active, partial, settled"
        )
    if debt_type is not None and debt_type not in {"lent", "borrowed"}:
        raise HTTPException(
            status_code=400, detail="Invalid debt_type value. Must be one of: lent, borrowed"
        )
    client = await get_async_service_role_client()
    debts: list[DebtResponse] = []
    offset = 0
    while True:
        query = client.table("debts").select("*").eq("user_id", str(user_id)).order("id")
        if status is not None:
            query = query.eq("status", status)
        if debt_type is not None:
            query = query.eq("debt_type", debt_type)
        rows = await _execute(query.range(offset, offset + 999))
        debts.extend(DebtResponse.model_validate(row) for row in rows)
        if len(rows) < 1000:
            return debts
        offset += 1000


@router.get("/debts/{debt_id}", response_model=DebtDetailResponse)
async def get_debt(
    debt_id: str, user_id: UUID = Depends(get_current_user_id)
) -> DebtDetailResponse:
    client = await get_async_service_role_client()
    debt = await _get_debt_or_404(client, debt_id, user_id)
    payments = []
    offset = 0
    while True:
        rows = await _execute(
            client.table("debt_payments")
            .select("*")
            .eq("debt_id", debt["id"])
            .order("created_at")
            .order("id")
            .range(offset, offset + 999)
        )
        payments.extend(rows)
        if len(rows) < 1000:
            break
        offset += 1000
    return DebtDetailResponse(
        **debt, payments=[PaymentResponse.model_validate(p) for p in payments]
    )


@router.patch("/debts/{debt_id}", response_model=DebtResponse)
async def update_debt(
    debt_id: str, body: DebtUpdate, user_id: UUID = Depends(get_current_user_id)
) -> DebtResponse:
    client = await get_async_service_role_client()
    debt = await _get_debt_or_404(client, debt_id, user_id)
    updates = body.model_dump(mode="json", exclude_unset=True)
    if "status" in updates and updates["status"] is None:
        raise HTTPException(status_code=422, detail="Status cannot be null")
    updates["updated_at"] = datetime.now(UTC).isoformat()
    rows = await _execute(
        client.table("debts").update(updates).eq("id", debt["id"]).eq("user_id", str(user_id))
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Debt not found")
    return DebtResponse.model_validate(rows[0])


@router.delete("/debts/{debt_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_debt(debt_id: str, user_id: UUID = Depends(get_current_user_id)) -> None:
    """Preserve the existing API's soft-settlement contract."""
    client = await get_async_service_role_client()
    rows = await _execute(
        client.table("debts")
        .update(
            {
                "status": "settled",
                "outstanding_balance": "0",
                "updated_at": datetime.now(UTC).isoformat(),
            }
        )
        .eq("id", _validated_id(debt_id))
        .eq("user_id", str(user_id))
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Debt not found")


@router.post(
    "/debts/{debt_id}/payments", response_model=DebtResponse, status_code=status.HTTP_201_CREATED
)
async def create_payment(
    debt_id: str, body: DebtPaymentCreate, user_id: UUID = Depends(get_current_user_id)
) -> DebtResponse:
    client = await get_async_service_role_client()
    debt = await _get_debt_or_404(client, debt_id, user_id)
    # The DB trigger locks the debt and enforces overpayment validation using
    # the current balance. A separate application read/update would race.
    await _execute(
        client.table("debt_payments").insert(
            {**body.model_dump(mode="json"), "debt_id": debt["id"]}
        )
    )
    return DebtResponse.model_validate(await _get_debt_or_404(client, debt_id, user_id))
