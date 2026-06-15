"""Shared FastAPI dependencies — JWT authentication and Supabase clients.

Security contract
------------------
* ``get_current_user_id`` is the SINGLE source of truth for "who is making
  this request".  It reads the ``Authorization: Bearer <jwt>`` header,
  cryptographically verifies the token's signature, and checks ``exp``
  (expiry), ``aud`` (audience), and ``iss`` (issuer) claims.  The verified
  ``sub`` claim — a UUID controlled ONLY by Supabase Auth — becomes
  ``user_id`` for every downstream query.
* Signature verification supports BOTH of Supabase's signing models:
    - New projects (and migrated projects) sign user access tokens with an
      asymmetric key (ES256/RS256) published at this project's JWKS endpoint
      (``<supabase_url>/auth/v1/.well-known/jwks.json``).
    - Older projects sign with a shared HS256 secret
      (``settings.supabase_jwt_secret``, from Project Settings -> API -> JWT
      Settings -> JWT Secret).
  ``PyJWKClient`` is tried first; if the project has no JWKS keys configured
  (legacy-only projects), verification falls back to the HS256 secret.
* This file deliberately does NOT accept a client-supplied user id from any
  header.  The previous ``x-user-id`` pattern allowed any caller to read or
  mutate any other user's data simply by supplying that user's UUID — a
  critical broken-access-control (OWASP A01) vulnerability.  Do not
  reintroduce a header-trust shortcut here.
* ``get_user_scoped_client`` returns a Supabase client authenticated as the
  calling user (via the verified JWT) so Row Level Security policies apply
  as a second layer of defence in depth on top of the explicit
  ``.eq("user_id", ...)`` filters already used throughout the routers.
* The raw JWT and its claims are NEVER logged. Only the verified ``user_id``
  (a non-secret UUID) may appear in log messages, per existing router
  conventions.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from uuid import UUID

import jwt
from fastapi import Header, HTTPException, status
from jwt import PyJWKClient
from supabase import acreate_client, create_client
from supabase._async.client import AsyncClient
from supabase._sync.client import Client

from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# JWT validation constants
# ---------------------------------------------------------------------------
# The audience for end-user session tokens is always the literal string
# "authenticated". The issuer is the project's GoTrue (Auth) endpoint.
_JWT_ALGORITHMS = ["ES256", "RS256", "HS256"]
_EXPECTED_AUDIENCE = "authenticated"


def _expected_issuer() -> str:
    """Return the expected ``iss`` claim for this Supabase project."""
    return f"{settings.supabase_url.rstrip('/')}/auth/v1"


@lru_cache(maxsize=4)
def _jwk_client(supabase_url: str) -> PyJWKClient:
    """Return a cached ``PyJWKClient`` for the given project's JWKS endpoint.

    Cached per ``supabase_url`` (rather than globally) so tests that
    monkeypatch ``settings.supabase_url`` get a fresh client instead of a
    stale one from a previous configuration. ``PyJWKClient`` caches the
    fetched keyset in-memory (default TTL) and re-fetches automatically on a
    ``kid`` it hasn't seen, so this is safe to reuse across requests without
    hammering the JWKS endpoint. A short timeout keeps an unreachable/invalid
    issuer (e.g. in tests) from stalling a request.
    """
    jwks_url = f"{supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
    return PyJWKClient(jwks_url, cache_keys=True, timeout=5)


# ---------------------------------------------------------------------------
# Authentication dependency
# ---------------------------------------------------------------------------


async def get_current_user_id(
    authorization: str | None = Header(default=None),
) -> UUID:
    """Verify the caller's Supabase Auth JWT and return their user id.

    Reads the ``Authorization`` header, expects the form
    ``Bearer <supabase_access_token>``, and validates:

    * signature — ES256/RS256 via this project's JWKS endpoint, or HS256
      via ``settings.supabase_jwt_secret`` for legacy projects
    * ``exp``    — token must not be expired
    * ``aud``    — must equal ``"authenticated"``
    * ``iss``    — must match this project's Auth endpoint

    Returns:
        The verified ``sub`` claim parsed as a ``UUID`` — the authenticated
        user's id.

    Raises:
        HTTPException 401 — missing/malformed header, expired token, invalid
            signature, or any other JWT validation failure.
        HTTPException 500 — server misconfiguration (neither JWKS nor JWT
            secret available).
    """
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header is required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header must be 'Bearer <token>'",
            headers={"WWW-Authenticate": "Bearer"},
        )

    _required_claims = ["exp", "sub", "aud", "iss"]

    signing_key: jwt.PyJWK | None = None
    jwks_error: Exception | None = None
    try:
        signing_key = _jwk_client(settings.supabase_url).get_signing_key_from_jwt(token)
    except Exception as exc:  # noqa: BLE001 - fall back to legacy secret below
        jwks_error = exc

    if signing_key is not None:
        try:
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=_JWT_ALGORITHMS,
                audience=_EXPECTED_AUDIENCE,
                issuer=_expected_issuer(),
                options={"require": _required_claims},
            )
        except jwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Access token has expired",
                headers={"WWW-Authenticate": "Bearer"},
            )
        except jwt.InvalidTokenError:
            logger.warning("Rejected invalid access token (JWKS)")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired access token",
                headers={"WWW-Authenticate": "Bearer"},
            )
    else:
        # Legacy fallback: project has no JWKS keys (or token predates JWKS
        # rollout) — verify against the shared HS256 secret instead.
        secret = settings.supabase_jwt_secret.get_secret_value()
        if not secret:
            logger.error(
                "No JWKS signing key available and SUPABASE_JWT_SECRET is not configured: %s",
                jwks_error,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Authentication is not configured",
            )

        try:
            payload = jwt.decode(
                token,
                secret,
                algorithms=["HS256"],
                audience=_EXPECTED_AUDIENCE,
                issuer=_expected_issuer(),
                options={"require": _required_claims},
            )
        except jwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Access token has expired",
                headers={"WWW-Authenticate": "Bearer"},
            )
        except jwt.InvalidTokenError:
            # Covers bad signature, bad audience/issuer, malformed token,
            # missing required claims, etc. Do not echo token contents in
            # the log.
            logger.warning("Rejected invalid access token (HS256 fallback)")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired access token",
                headers={"WWW-Authenticate": "Bearer"},
            )

    sub = payload.get("sub")
    try:
        return UUID(str(sub))
    except (ValueError, TypeError):
        logger.warning("Access token has a non-UUID 'sub' claim")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token subject",
            headers={"WWW-Authenticate": "Bearer"},
        )


def get_bearer_token(authorization: str | None = Header(default=None)) -> str:
    """Return the raw bearer token from the Authorization header.

    Used alongside ``get_current_user_id`` when a handler also needs to build
    a user-scoped (RLS-enforcing) Supabase client.  Does not re-validate the
    token — ``get_current_user_id`` is the authority on validity. Both
    dependencies run per-request, so an invalid token is rejected by
    ``get_current_user_id`` before this value would be used.
    """
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header is required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header must be 'Bearer <token>'",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token


# ---------------------------------------------------------------------------
# Supabase client factories
# ---------------------------------------------------------------------------


def get_service_role_client() -> Client:
    """Create a Supabase client using the service-role key (bypasses RLS).

    Use ONLY where the operation must legitimately span/affect rows that the
    calling user does not own (e.g. background scrape jobs that look up the
    user's own stored credentials by a server-verified ``user_id``, where no
    live request/JWT is available). All such queries MUST still filter
    explicitly by the verified ``user_id`` — service-role bypasses RLS but
    does not bypass the application's own ``.eq("user_id", ...)`` filters.
    """
    return create_client(
        settings.supabase_url,
        settings.supabase_service_role_key.get_secret_value(),
    )


async def get_async_service_role_client() -> AsyncClient:
    """Create an async Supabase client using the service-role key.

    Used by background tasks (e.g. scrape jobs) that run outside of any HTTP
    request context and therefore have no caller JWT to attach. As with
    ``get_service_role_client``, every query made with this client MUST still
    filter explicitly by a verified ``user_id`` obtained earlier in the same
    task from ``get_current_user_id``.
    """
    return await acreate_client(
        settings.supabase_url,
        settings.supabase_service_role_key.get_secret_value(),
    )


def get_user_scoped_client(access_token: str) -> Client:
    """Create a Supabase client authenticated as the calling user.

    The client is created with the anon key (no elevated privileges) and
    then has the user's verified access token attached to PostgREST requests
    via ``postgrest.auth()``. Supabase RLS policies that key off
    ``auth.uid()`` will therefore apply, giving defence-in-depth on top of the
    explicit ``.eq("user_id", ...)`` filters already used in route handlers.
    """
    client = create_client(settings.supabase_url, settings.supabase_anon_key)
    client.postgrest.auth(access_token)
    return client
