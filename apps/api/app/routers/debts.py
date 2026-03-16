"""Debts router — manual borrowing/lending tracker CRUD.

Security contract
-----------------
* No PII in log messages — counterparty names, phone numbers, emails, and
  monetary amounts MUST NOT appear in any log call.
* Log only event names, opaque IDs, and aggregate counts.
* All request models carry ``ConfigDict(extra="forbid")`` to reject unknown
  fields and prevent parameter-pollution attacks.
* All monetary amounts in responses are typed as ``Decimal``; ``float`` is
  forbidden for financial values to prevent rounding-error bugs.

Storage strategy
----------------
This router uses module-level in-memory dicts for testability without a live
Supabase connection.  The ``clear_storage()`` function is exported for test
teardown.  A production implementation would replace the dict operations with
async Supabase client calls.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

router = APIRouter(tags=["debts"])


# ---------------------------------------------------------------------------
# In-memory storage (swap for real DB calls in production)
# ---------------------------------------------------------------------------

_debts: dict[str, dict] = {}
_payments: dict[str, list[dict]] = defaultdict(list)


def clear_storage() -> None:
    """Reset all in-memory state.  Call from test teardown fixtures."""
    _debts.clear()
    _payments.clear()


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

_DEBT_TYPE_PATTERN = r"^(lent|borrowed)$"
_DEBT_STATUS_PATTERN = r"^(active|partial|settled)$"
_DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"
_CURRENCY_PATTERN = r"^[A-Z]{3}$"


class DebtCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    debt_type: str = Field(pattern=_DEBT_TYPE_PATTERN)
    counterparty_name: str = Field(min_length=1, max_length=256)
    counterparty_phone: Optional[str] = Field(default=None, max_length=32)
    counterparty_email: Optional[str] = Field(default=None, max_length=256)
    original_amount: Decimal = Field(gt=Decimal("0"))
    currency: str = Field(default="EGP", pattern=_CURRENCY_PATTERN)
    due_date: Optional[str] = Field(default=None, pattern=_DATE_PATTERN)
    notes: Optional[str] = Field(default=None, max_length=1024)


class DebtUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    counterparty_phone: Optional[str] = Field(default=None, max_length=32)
    counterparty_email: Optional[str] = Field(default=None, max_length=256)
    due_date: Optional[str] = Field(default=None, pattern=_DATE_PATTERN)
    notes: Optional[str] = Field(default=None, max_length=1024)
    status: Optional[str] = Field(default=None, pattern=_DEBT_STATUS_PATTERN)


class DebtPaymentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: Decimal = Field(gt=Decimal("0"))
    payment_date: str = Field(pattern=_DATE_PATTERN)
    notes: Optional[str] = Field(default=None, max_length=1024)


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class DebtResponse(BaseModel):
    id: UUID
    user_id: UUID
    debt_type: str
    counterparty_name: str
    counterparty_phone: Optional[str]
    counterparty_email: Optional[str]
    original_amount: Decimal
    outstanding_balance: Decimal
    currency: str
    due_date: Optional[date]
    notes: Optional[str]
    status: str
    created_at: datetime
    updated_at: datetime


class PaymentResponse(BaseModel):
    id: UUID
    debt_id: UUID
    amount: Decimal
    payment_date: date
    notes: Optional[str]
    created_at: datetime


class DebtDetailResponse(DebtResponse):
    payments: list[PaymentResponse]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# Sentinel user_id used in place of a real JWT-extracted identity.  In
# production this would come from the request's JWT claim.
_SENTINEL_USER_ID = UUID("00000000-0000-0000-0000-000000000001")


def _is_valid_uuid(value: str) -> bool:
    try:
        UUID(value)
        return True
    except (ValueError, AttributeError):
        return False


def _get_debt_or_404(debt_id: str) -> dict:
    debt = _debts.get(debt_id)
    if debt is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Debt not found",
        )
    return debt


def _dict_to_debt_response(d: dict) -> DebtResponse:
    return DebtResponse(
        id=d["id"],
        user_id=d["user_id"],
        debt_type=d["debt_type"],
        counterparty_name=d["counterparty_name"],
        counterparty_phone=d["counterparty_phone"],
        counterparty_email=d["counterparty_email"],
        original_amount=d["original_amount"],
        outstanding_balance=d["outstanding_balance"],
        currency=d["currency"],
        due_date=d["due_date"],
        notes=d["notes"],
        status=d["status"],
        created_at=d["created_at"],
        updated_at=d["updated_at"],
    )


def _dict_to_payment_response(p: dict) -> PaymentResponse:
    return PaymentResponse(
        id=p["id"],
        debt_id=p["debt_id"],
        amount=p["amount"],
        payment_date=p["payment_date"],
        notes=p["notes"],
        created_at=p["created_at"],
    )


def _update_debt_status(debt: dict) -> None:
    """Recompute status in-place after a payment is recorded."""
    balance: Decimal = debt["outstanding_balance"]
    original: Decimal = debt["original_amount"]

    if balance <= Decimal("0"):
        debt["outstanding_balance"] = Decimal("0")
        debt["status"] = "settled"
    elif balance < original:
        debt["status"] = "partial"
    else:
        debt["status"] = "active"


# ---------------------------------------------------------------------------
# POST /api/v1/debts — create a new debt
# ---------------------------------------------------------------------------


@router.post(
    "/debts",
    response_model=DebtResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new debt record (lent or borrowed)",
)
async def create_debt(body: DebtCreate) -> DebtResponse:
    """Record a new manual debt entry.

    HTTP error mapping
    ------------------
    * 422 — Pydantic validation failure (malformed request body).
    """
    debt_id = uuid4()
    now = datetime.now(tz=timezone.utc)

    due_date_parsed: Optional[date] = (
        date.fromisoformat(body.due_date) if body.due_date else None
    )

    debt: dict = {
        "id": debt_id,
        "user_id": _SENTINEL_USER_ID,
        "debt_type": body.debt_type,
        "counterparty_name": body.counterparty_name,
        "counterparty_phone": body.counterparty_phone,
        "counterparty_email": body.counterparty_email,
        "original_amount": body.original_amount,
        "outstanding_balance": body.original_amount,
        "currency": body.currency,
        "due_date": due_date_parsed,
        "notes": body.notes,
        "status": "active",
        "created_at": now,
        "updated_at": now,
    }

    _debts[str(debt_id)] = debt

    logger.info("Debt created", extra={"debt_id": str(debt_id)})

    return _dict_to_debt_response(debt)


# ---------------------------------------------------------------------------
# GET /api/v1/debts — list debts with optional filters
# ---------------------------------------------------------------------------


@router.get(
    "/debts",
    response_model=list[DebtResponse],
    status_code=status.HTTP_200_OK,
    summary="List all debt records, optionally filtered by status or type",
)
async def list_debts(
    status: Optional[str] = None,
    debt_type: Optional[str] = None,
) -> list[DebtResponse]:
    """Return all stored debts for the current user.

    Query parameters
    ----------------
    * ``status``    — filter by debt status: ``active`` | ``partial`` | ``settled``
    * ``debt_type`` — filter by direction: ``lent`` | ``borrowed``

    HTTP error mapping
    ------------------
    * 400 — invalid ``status`` or ``debt_type`` query parameter value.
    * 422 — Pydantic validation failure.
    """
    import re

    if status is not None and not re.fullmatch(_DEBT_STATUS_PATTERN[1:-1], status):
        raise HTTPException(
            status_code=400,
            detail="Invalid status value. Must be one of: active, partial, settled",
        )
    if debt_type is not None and not re.fullmatch(_DEBT_TYPE_PATTERN[1:-1], debt_type):
        raise HTTPException(
            status_code=400,
            detail="Invalid debt_type value. Must be one of: lent, borrowed",
        )

    debts = list(_debts.values())

    if status is not None:
        debts = [d for d in debts if d["status"] == status]
    if debt_type is not None:
        debts = [d for d in debts if d["debt_type"] == debt_type]

    logger.info("Debts listed", extra={"result_count": len(debts)})

    return [_dict_to_debt_response(d) for d in debts]


# ---------------------------------------------------------------------------
# GET /api/v1/debts/{debt_id} — get a single debt with payment history
# ---------------------------------------------------------------------------


@router.get(
    "/debts/{debt_id}",
    response_model=DebtDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve a single debt record with its full payment history",
)
async def get_debt(debt_id: str) -> DebtDetailResponse:
    """Fetch one debt by ID, including all associated payment records.

    HTTP error mapping
    ------------------
    * 404 — debt not found.
    """
    debt = _get_debt_or_404(debt_id)
    payments = _payments.get(debt_id, [])

    logger.info("Debt retrieved", extra={"debt_id": debt_id})

    return DebtDetailResponse(
        **{k: v for k, v in _dict_to_debt_response(debt).model_dump().items()},
        payments=[_dict_to_payment_response(p) for p in payments],
    )





# ---------------------------------------------------------------------------
# PATCH /api/v1/debts/{debt_id} — update mutable fields
# ---------------------------------------------------------------------------


@router.patch(
    "/debts/{debt_id}",
    response_model=DebtResponse,
    status_code=status.HTTP_200_OK,
    summary="Update mutable fields on an existing debt record",
)
async def update_debt(debt_id: str, body: DebtUpdate) -> DebtResponse:
    """Apply a partial update to a debt record.

    Only the fields present in the request body are modified; omitted fields
    are left unchanged.

    HTTP error mapping
    ------------------
    * 404 — debt not found.
    * 422 — Pydantic validation failure.
    """
    debt = _get_debt_or_404(debt_id)

    update_fields = body.model_dump(exclude_unset=True)

    if "due_date" in update_fields:
        raw = update_fields.pop("due_date")
        update_fields["due_date"] = date.fromisoformat(raw) if raw else None

    debt.update(update_fields)
    debt["updated_at"] = datetime.now(tz=timezone.utc)

    logger.info("Debt updated", extra={"debt_id": debt_id})

    return _dict_to_debt_response(debt)


# ---------------------------------------------------------------------------
# DELETE /api/v1/debts/{debt_id} — soft-delete (mark as settled)
# ---------------------------------------------------------------------------


@router.delete(
    "/debts/{debt_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete a debt by marking it as settled",
)
async def delete_debt(debt_id: str) -> None:
    """Mark a debt as ``settled`` without removing the record.

    This is a soft-delete: the row is retained for audit purposes but the
    status transitions to ``settled`` and the outstanding balance is zeroed.

    HTTP error mapping
    ------------------
    * 404 — debt not found.
    """
    debt = _get_debt_or_404(debt_id)

    debt["status"] = "settled"
    debt["outstanding_balance"] = Decimal("0")
    debt["updated_at"] = datetime.now(tz=timezone.utc)

    logger.info("Debt soft-deleted (settled)", extra={"debt_id": debt_id})


# ---------------------------------------------------------------------------
# POST /api/v1/debts/{debt_id}/payments — record a payment
# ---------------------------------------------------------------------------


@router.post(
    "/debts/{debt_id}/payments",
    response_model=DebtResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record a payment against a debt and recompute its status",
)
async def create_payment(debt_id: str, body: DebtPaymentCreate) -> DebtResponse:
    """Record a partial or full payment against a debt.

    Returns the updated debt record so the caller can immediately inspect the
    new ``outstanding_balance`` and ``status``.

    Settlement logic
    ----------------
    After the payment amount is subtracted from ``outstanding_balance``:

    * If ``outstanding_balance <= 0``: status → ``settled``, balance clamped to 0.
    * Elif ``outstanding_balance < original_amount``: status → ``partial``.
    * Else: status remains ``active``.

    HTTP error mapping
    ------------------
    * 400 — payment amount exceeds the current outstanding balance.
    * 404 — debt not found.
    * 422 — Pydantic validation failure.
    """
    debt = _get_debt_or_404(debt_id)

    if body.amount > debt["outstanding_balance"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Payment amount exceeds outstanding balance",
        )

    payment_id = uuid4()
    now = datetime.now(tz=timezone.utc)
    payment_date_parsed = date.fromisoformat(body.payment_date)

    payment: dict = {
        "id": payment_id,
        "debt_id": UUID(debt_id) if _is_valid_uuid(debt_id) else uuid4(),
        "amount": body.amount,
        "payment_date": payment_date_parsed,
        "notes": body.notes,
        "created_at": now,
    }

    # Apply the payment to the debt's outstanding balance.
    debt["outstanding_balance"] = debt["outstanding_balance"] - body.amount
    _update_debt_status(debt)
    debt["updated_at"] = now

    _payments[debt_id].append(payment)

    logger.info(
        "Payment recorded",
        extra={"debt_id": debt_id, "payment_id": str(payment_id)},
    )

    return _dict_to_debt_response(debt)
