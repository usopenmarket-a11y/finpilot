"""User preference router.

Preferences are stored on ``public.user_profiles.preferences`` as JSONB. The
frontend uses this endpoint instead of writing directly through the browser
Supabase client so preference saves are not blocked by profile-table RLS
upsert semantics.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from supabase import create_client
from supabase._sync.client import Client

from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["preferences"])


class PreferencesResponse(BaseModel):
    """User preference payload."""

    preferences: dict[str, Any] = Field(default_factory=dict)


class UpdatePreferencesRequest(BaseModel):
    """PATCH /user/preferences request body."""

    model_config = ConfigDict(extra="forbid")

    preferences: dict[str, Any]


def _get_client() -> Client:
    """Create a synchronous Supabase client using the service-role key."""
    return create_client(
        settings.supabase_url,
        settings.supabase_service_role_key.get_secret_value(),
    )


def _parse_user_id(raw: str | None) -> UUID:
    """Validate and parse the x-user-id header value."""
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


def _read_preferences(client: Client, user_id: UUID) -> dict[str, Any]:
    response = (
        client.table("user_profiles")
        .select("preferences")
        .eq("id", str(user_id))
        .limit(1)
        .execute()
    )
    if not response.data:
        return {}

    first = response.data[0]
    if not isinstance(first, dict):
        return {}

    preferences = first.get("preferences")
    return preferences if isinstance(preferences, dict) else {}


@router.get(
    "/user/preferences",
    response_model=PreferencesResponse,
    status_code=status.HTTP_200_OK,
    summary="Read user preferences",
)
async def get_preferences(
    x_user_id: str | None = Header(default=None, alias="x-user-id"),
) -> PreferencesResponse:
    user_id = _parse_user_id(x_user_id)
    client = _get_client()

    try:
        return PreferencesResponse(preferences=_read_preferences(client, user_id))
    except Exception as exc:
        logger.error("Failed to load preferences for user_id=%s: %s", user_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to load preferences",
        ) from exc


@router.patch(
    "/user/preferences",
    response_model=PreferencesResponse,
    status_code=status.HTTP_200_OK,
    summary="Update user preferences",
)
async def update_preferences(
    body: UpdatePreferencesRequest,
    x_user_id: str | None = Header(default=None, alias="x-user-id"),
) -> PreferencesResponse:
    user_id = _parse_user_id(x_user_id)
    client = _get_client()

    try:
        current = _read_preferences(client, user_id)
        next_preferences = {**current, **body.preferences}
        response = (
            client.table("user_profiles")
            .upsert(
                {
                    "id": str(user_id),
                    "preferences": next_preferences,
                    "updated_at": datetime.now(UTC).isoformat(),
                },
                on_conflict="id",
            )
            .execute()
        )
    except Exception as exc:
        logger.error("Failed to save preferences for user_id=%s: %s", user_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save preferences",
        ) from exc

    if response.data:
        first = response.data[0]
        if isinstance(first, dict) and isinstance(first.get("preferences"), dict):
            return PreferencesResponse(preferences=first["preferences"])

    return PreferencesResponse(preferences=next_preferences)
