"""Credentials router — store and manage encrypted bank credentials.

Security contract
-----------------
* ``encrypted_username`` and ``encrypted_password`` arrive from the client
  already AES-256-GCM encrypted.  This endpoint NEVER decrypts them — it
  stores the ciphertext verbatim and retrieves it for the scraper layer.
* Response payloads NEVER include ``encrypted_username`` or
  ``encrypted_password``.  Only safe metadata (bank, is_active,
  last_synced_at, created_at) is returned.
* ``user_id`` comes from the ``x-user-id`` request header (UUID).  The
  header is validated to be a well-formed UUID; a missing or malformed
  header returns HTTP 400.
* The Supabase service-role key is used for all DB operations so that
  server-side mutations bypass Row Level Security where required.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict
from supabase import create_client
from supabase._sync.client import Client

from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["credentials"])


# ---------------------------------------------------------------------------
# Supabase client factory
# ---------------------------------------------------------------------------


def _get_client() -> Client:
    """Create a synchronous Supabase client using the service-role key."""
    return create_client(
        settings.supabase_url,
        settings.supabase_service_role_key.get_secret_value(),
    )


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class SaveCredentialRequest(BaseModel):
    """POST /api/v1/accounts/credentials — save or update credentials for a bank.

    ``encrypted_username`` and ``encrypted_password`` must be AES-256-GCM
    tokens produced by the frontend.  Extra fields are rejected to prevent
    parameter-pollution attacks.
    """

    model_config = ConfigDict(extra="forbid")

    bank: Literal["NBE", "CIB", "BDC", "UB"]
    encrypted_username: str
    encrypted_password: str


class CredentialInfo(BaseModel):
    """Safe credential metadata — never contains secret fields."""

    bank: str
    is_active: bool
    last_synced_at: datetime | None
    created_at: datetime


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_user_id(raw: str | None) -> UUID:
    """Validate and parse the x-user-id header value.

    Raises:
        HTTPException 400 — if the header is missing or not a valid UUID.
    """
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


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@router.post(
    "/accounts/credentials",
    response_model=CredentialInfo,
    status_code=status.HTTP_200_OK,
    summary="Save or update encrypted bank credentials",
)
async def save_credential(
    body: SaveCredentialRequest,
    x_user_id: str | None = Header(default=None, alias="x-user-id"),
) -> CredentialInfo:
    """Upsert encrypted credentials for the given bank.

    The row is identified by the (user_id, bank) unique constraint.  If a
    row already exists it is updated in place; otherwise a new row is inserted.

    The response returns only safe metadata — secret fields are never echoed.
    """
    user_id = _parse_user_id(x_user_id)

    client = _get_client()
    try:
        response = (
            client.table("bank_credentials")
            .upsert(
                {
                    "user_id": str(user_id),
                    "bank": body.bank,
                    "encrypted_username": body.encrypted_username,
                    "encrypted_password": body.encrypted_password,
                    "is_active": True,
                },
                on_conflict="user_id,bank",
            )
            .execute()
        )
    except Exception as exc:
        logger.error("Failed to save credentials for bank=%s: %s", body.bank, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save credentials",
        ) from exc

    rows = response.data
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save credentials — no row returned",
        )

    row = rows[0]
    assert isinstance(row, dict)
    logger.info("Credentials saved for bank=%s user_id=%s", body.bank, user_id)
    return CredentialInfo(
        bank=row["bank"],
        is_active=row["is_active"],
        last_synced_at=row.get("last_synced_at"),
        created_at=row["created_at"],
    )


@router.get(
    "/accounts/credentials",
    response_model=list[CredentialInfo],
    status_code=status.HTTP_200_OK,
    summary="List all saved credentials for the authenticated user",
)
async def list_credentials(
    x_user_id: str | None = Header(default=None, alias="x-user-id"),
) -> list[CredentialInfo]:
    """Return safe metadata for all stored bank credentials.

    Secret fields (``encrypted_username``, ``encrypted_password``) are
    never included in the response — only bank code, active flag, and
    timestamps are returned.
    """
    user_id = _parse_user_id(x_user_id)

    client = _get_client()
    try:
        response = (
            client.table("bank_credentials")
            .select("bank, is_active, last_synced_at, created_at")
            .eq("user_id", str(user_id))
            .execute()
        )
    except Exception as exc:
        logger.error("Failed to list credentials for user_id=%s: %s", user_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve credentials",
        ) from exc

    result: list[CredentialInfo] = []
    for row in response.data:
        assert isinstance(row, dict)
        result.append(
            CredentialInfo(
                bank=row["bank"],
                is_active=row["is_active"],
                last_synced_at=row.get("last_synced_at"),
                created_at=row["created_at"],
            )
        )
    return result


@router.delete(
    "/accounts/credentials/{bank}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove credentials for a specific bank",
)
async def delete_credential(
    bank: Literal["NBE", "CIB", "BDC", "UB"],
    x_user_id: str | None = Header(default=None, alias="x-user-id"),
) -> None:
    """Delete the stored credentials for the given bank.

    If no matching row exists the operation is silently treated as a
    success (idempotent delete).
    """
    user_id = _parse_user_id(x_user_id)

    client = _get_client()
    try:
        client.table("bank_credentials").delete().eq("user_id", str(user_id)).eq(
            "bank", bank
        ).execute()
    except Exception as exc:
        logger.error("Failed to delete credentials for bank=%s user_id=%s: %s", bank, user_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete credentials",
        ) from exc

    logger.info("Credentials deleted for bank=%s user_id=%s", bank, user_id)
