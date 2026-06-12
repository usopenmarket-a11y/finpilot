"""User preference router.

Preferences are stored on ``public.user_profiles.preferences`` as JSONB. The
frontend uses this endpoint instead of writing directly through the browser
Supabase client so preference saves are not blocked by profile-table RLS
upsert semantics.

``user_id`` is the verified ``sub`` claim from the caller's Supabase Auth JWT
(see ``app.deps.get_current_user_id``) — it is cryptographically authenticated
and cannot be supplied or spoofed by the client.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from supabase._sync.client import Client

from app.deps import get_current_user_id, get_service_role_client

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
    return get_service_role_client()


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
    user_id: UUID = Depends(get_current_user_id),
) -> PreferencesResponse:
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
    user_id: UUID = Depends(get_current_user_id),
) -> PreferencesResponse:
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
