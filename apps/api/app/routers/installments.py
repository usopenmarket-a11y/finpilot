"""Installments router — CRUD for monthly obligation tracker.

Tracks recurring monthly financial obligations such as BNPL (Valu, etc.),
home/property purchase plans, vehicle loans, and other fixed monthly payments.

Security contract
-----------------
* All endpoints require ``x-user-id`` header (validated UUID).
* All DB queries filter by user_id to prevent cross-user data access
  (defence-in-depth alongside Supabase Row Level Security).
* No PII in log messages — names and amounts are NOT logged.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, date, datetime
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, status
from supabase import create_client

from app.config import settings
from app.models.api import InstallmentCreate, InstallmentResponse, InstallmentUpdate

logger = logging.getLogger(__name__)

router = APIRouter(tags=["installments"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_user_id(raw: str | None) -> UUID:
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="x-user-id header is required",
        )
    try:
        return UUID(raw)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="x-user-id header must be a valid UUID",
        )


def _compute_fields(start_date: date, total_months: int, billing_day: int | None) -> dict:
    """Compute derived fields for InstallmentResponse."""
    today = datetime.now(UTC).date()

    # months elapsed since start_date
    months_elapsed = (today.year - start_date.year) * 12 + (today.month - start_date.month)
    # Don't count current month if we haven't reached the billing day yet
    if billing_day is not None and today.day < billing_day:
        months_elapsed = max(0, months_elapsed - 1)
    months_elapsed = max(0, months_elapsed)

    months_remaining = max(0, total_months - months_elapsed)
    is_paid_off = months_elapsed >= total_months

    next_payment_date: date | None = None
    if not is_paid_off:
        # Next billing_day occurrence on or after today
        day = billing_day if billing_day is not None else start_date.day
        # Try this month first, fall back to next month
        try:
            candidate = today.replace(day=day)
        except ValueError:
            # Day doesn't exist in this month (e.g. day=31 in April)
            if today.month == 12:
                candidate = today.replace(year=today.year + 1, month=1, day=1)
            else:
                candidate = today.replace(month=today.month + 1, day=1)
        if candidate < today:
            if today.month == 12:
                try:
                    candidate = candidate.replace(year=today.year + 1, month=1)
                except ValueError:
                    candidate = date(today.year + 1, 1, 1)
            else:
                try:
                    candidate = candidate.replace(month=today.month + 1)
                except ValueError:
                    candidate = date(today.year, today.month + 1, 1)
        next_payment_date = candidate

    return {
        "months_elapsed": months_elapsed,
        "months_remaining": months_remaining,
        "next_payment_date": next_payment_date,
        "is_paid_off": is_paid_off,
    }


def _row_to_response(row: dict) -> InstallmentResponse:
    computed = _compute_fields(
        start_date=date.fromisoformat(row["start_date"]),
        total_months=row["total_months"],
        billing_day=row.get("billing_day"),
    )
    return InstallmentResponse(**row, **computed)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get(
    "/installments",
    response_model=list[InstallmentResponse],
    summary="List all installment plans",
)
async def list_installments(
    x_user_id: str | None = Header(default=None, alias="x-user-id"),
    include_inactive: bool = False,
) -> list[InstallmentResponse]:
    """Return all instalment plans for the authenticated user."""
    user_id = _parse_user_id(x_user_id)

    def _fetch() -> list[dict]:
        client = create_client(
            settings.supabase_url,
            settings.supabase_service_role_key.get_secret_value(),
        )
        q = (
            client.table("installments")
            .select("*")
            .eq("user_id", str(user_id))
            .order("start_date", desc=True)
        )
        if not include_inactive:
            q = q.eq("is_active", True)
        return q.execute().data or []

    rows = await asyncio.to_thread(_fetch)
    return [_row_to_response(r) for r in rows]


@router.post(
    "/installments",
    response_model=InstallmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an installment plan",
)
async def create_installment(
    body: InstallmentCreate,
    x_user_id: str | None = Header(default=None, alias="x-user-id"),
) -> InstallmentResponse:
    user_id = _parse_user_id(x_user_id)

    def _insert() -> dict:
        client = create_client(
            settings.supabase_url,
            settings.supabase_service_role_key.get_secret_value(),
        )
        payload = {
            "user_id": str(user_id),
            "name": body.name,
            "category": body.category,
            "total_amount": str(body.total_amount),
            "down_payment": str(body.down_payment),
            "monthly_amount": str(body.monthly_amount),
            "billing_day": body.billing_day,
            "start_date": body.start_date.isoformat(),
            "total_months": body.total_months,
            "notes": body.notes,
        }
        resp = client.table("installments").insert(payload).execute()
        return resp.data[0]

    try:
        row = await asyncio.to_thread(_insert)
    except Exception as exc:
        logger.error("Failed to create installment: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create installment plan",
        ) from exc

    return _row_to_response(row)


@router.get(
    "/installments/{installment_id}",
    response_model=InstallmentResponse,
    summary="Get a single installment plan",
)
async def get_installment(
    installment_id: str,
    x_user_id: str | None = Header(default=None, alias="x-user-id"),
) -> InstallmentResponse:
    user_id = _parse_user_id(x_user_id)

    def _fetch_one() -> dict | None:
        client = create_client(
            settings.supabase_url,
            settings.supabase_service_role_key.get_secret_value(),
        )
        resp = (
            client.table("installments")
            .select("*")
            .eq("id", installment_id)
            .eq("user_id", str(user_id))
            .limit(1)
            .execute()
        )
        return resp.data[0] if resp.data else None

    row = await asyncio.to_thread(_fetch_one)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Installment not found")
    return _row_to_response(row)


@router.patch(
    "/installments/{installment_id}",
    response_model=InstallmentResponse,
    summary="Update an installment plan",
)
async def update_installment(
    installment_id: str,
    body: InstallmentUpdate,
    x_user_id: str | None = Header(default=None, alias="x-user-id"),
) -> InstallmentResponse:
    user_id = _parse_user_id(x_user_id)

    updates = body.model_dump(exclude_none=True)
    # Convert Decimal/date to JSON-serialisable types
    for key in ("total_amount", "down_payment", "monthly_amount"):
        if key in updates:
            updates[key] = str(updates[key])
    if "start_date" in updates:
        updates["start_date"] = updates["start_date"].isoformat()

    if not updates:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No fields to update",
        )

    def _update() -> dict | None:
        client = create_client(
            settings.supabase_url,
            settings.supabase_service_role_key.get_secret_value(),
        )
        resp = (
            client.table("installments")
            .update(updates)
            .eq("id", installment_id)
            .eq("user_id", str(user_id))
            .execute()
        )
        return resp.data[0] if resp.data else None

    try:
        row = await asyncio.to_thread(_update)
    except Exception as exc:
        logger.error("Failed to update installment %s: %s", installment_id, type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update installment plan",
        ) from exc

    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Installment not found")
    return _row_to_response(row)


@router.delete(
    "/installments/{installment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an installment plan",
)
async def delete_installment(
    installment_id: str,
    x_user_id: str | None = Header(default=None, alias="x-user-id"),
) -> None:
    user_id = _parse_user_id(x_user_id)

    def _delete() -> bool:
        client = create_client(
            settings.supabase_url,
            settings.supabase_service_role_key.get_secret_value(),
        )
        resp = (
            client.table("installments")
            .delete()
            .eq("id", installment_id)
            .eq("user_id", str(user_id))
            .execute()
        )
        return bool(resp.data)

    found = await asyncio.to_thread(_delete)
    if not found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Installment not found")
