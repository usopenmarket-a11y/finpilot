"""Utils router — server-side helpers for the frontend.

Security contract
-----------------
* ``POST /utils/encrypt`` accepts a plaintext value and returns an opaque
  AES-256-GCM token.  It MUST only be called over HTTPS.
* The plaintext value is NEVER logged.  Only the fact that encryption was
  requested is logged (no content, no user identity).
* This endpoint exists solely to let the frontend prepare credential tokens
  without ever having access to the raw encryption key.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from app.config import settings
from app.crypto import encrypt

logger = logging.getLogger(__name__)

router = APIRouter(tags=["utils"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class EncryptRequest(BaseModel):
    """POST /utils/encrypt — encrypt a plaintext value server-side."""

    model_config = ConfigDict(extra="forbid")

    value: str


class EncryptResponse(BaseModel):
    """Encrypted token ready to store as a credential token."""

    token: str


# ---------------------------------------------------------------------------
# Route handler
# ---------------------------------------------------------------------------


@router.post(
    "/utils/encrypt",
    response_model=EncryptResponse,
    summary="Encrypt a plaintext value using the server-side AES-256-GCM key",
)
async def encrypt_value(body: EncryptRequest) -> EncryptResponse:
    """Encrypt *value* using the server-side encryption key.

    Used by the frontend to prepare credential tokens before calling
    ``POST /accounts/credentials``.  The plaintext value is never logged.

    Returns:
        ``{"token": "<encrypted_token>"}``
    """
    # Intentionally do NOT log body.value.
    logger.debug("encrypt_value called")
    token = encrypt(body.value, settings.encryption_key)
    return EncryptResponse(token=token)
