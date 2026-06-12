from __future__ import annotations

import time
from typing import Any
from uuid import UUID, uuid4

import jwt
import pytest
from httpx import ASGITransport, AsyncClient

# ---------------------------------------------------------------------------
# Lazy app import guard
# ---------------------------------------------------------------------------
# The FastAPI app is imported lazily inside the `client` fixture rather than
# at module level.  This keeps the conftest importable even when a router has
# a broken import (e.g. a stale function name), allowing pure-unit test
# modules (analytics, models, pipeline) to be collected and run without the
# ASGI app being fully healthy.
#
# NOTE: if `app.main` raises ImportError at fixture instantiation time, only
# the tests that actually request the `client` fixture will fail — all other
# tests continue to run.
# ---------------------------------------------------------------------------


@pytest.fixture
async def client() -> AsyncClient:
    """Async test client wired directly to the ASGI app (no network I/O)."""
    from app.main import app  # deferred so import errors surface per-test

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


# ---------------------------------------------------------------------------
# JWT auth test helpers
# ---------------------------------------------------------------------------
# Every route handler now requires a verified Supabase Auth JWT via
# ``Depends(get_current_user_id)`` (see ``app.deps``). These helpers let
# tests mint a token that ``get_current_user_id`` will accept, by:
#
#   1. Monkeypatching ``settings.supabase_jwt_secret`` and
#      ``settings.supabase_url`` to known test values (via the
#      ``supabase_jwt_test_config`` fixture, applied automatically wherever
#      ``auth_headers``/``make_access_token`` is used).
#   2. Signing a token with that same secret, with ``sub`` / ``aud`` / ``iss``
#      / ``exp`` claims matching what ``get_current_user_id`` validates.
#
# Never log or print the token value — it is a (test-only) credential.
# ---------------------------------------------------------------------------

TEST_JWT_SECRET = "test-jwt-secret-do-not-use-in-production"  # noqa: S105
TEST_SUPABASE_URL = "https://test.supabase.co"
TEST_USER_ID = UUID("11111111-1111-1111-1111-111111111111")


@pytest.fixture
def supabase_jwt_test_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Point ``app.config.settings`` at known test JWT secret/issuer values.

    Applied automatically by ``make_access_token``/``auth_headers`` so any
    test that requests those fixtures gets a working ``get_current_user_id``
    dependency without needing real Supabase credentials.
    """
    from pydantic import SecretStr

    from app.config import settings

    monkeypatch.setattr(settings, "supabase_jwt_secret", SecretStr(TEST_JWT_SECRET))
    monkeypatch.setattr(settings, "supabase_url", TEST_SUPABASE_URL)


@pytest.fixture
def make_access_token(supabase_jwt_test_config: None):
    """Return a factory that mints a valid Supabase-style HS256 access token.

    Usage::

        token = make_access_token()                  # random user id
        token = make_access_token(user_id=some_uuid) # specific user id

    The returned token satisfies every check in
    ``app.deps.get_current_user_id``: HS256 signature against
    ``TEST_JWT_SECRET``, ``aud="authenticated"``,
    ``iss="{TEST_SUPABASE_URL}/auth/v1"``, and a future ``exp``.
    """

    def _make(
        user_id: UUID | str | None = None,
        *,
        expires_in: int = 3600,
        **extra_claims: Any,
    ) -> str:
        sub = str(user_id) if user_id is not None else str(uuid4())
        now = int(time.time())
        payload: dict[str, Any] = {
            "sub": sub,
            "aud": "authenticated",
            "iss": f"{TEST_SUPABASE_URL}/auth/v1",
            "iat": now,
            "exp": now + expires_in,
            **extra_claims,
        }
        return jwt.encode(payload, TEST_JWT_SECRET, algorithm="HS256")

    return _make


@pytest.fixture
def auth_headers(make_access_token):
    """Return a factory producing ``Authorization: Bearer <jwt>`` header dicts.

    Usage::

        headers = auth_headers()                  # random user id
        headers = auth_headers(user_id=some_uuid) # specific user id
    """

    def _make(user_id: UUID | str | None = None, **kwargs: Any) -> dict[str, str]:
        token = make_access_token(user_id=user_id, **kwargs)
        return {"Authorization": f"Bearer {token}"}

    return _make
