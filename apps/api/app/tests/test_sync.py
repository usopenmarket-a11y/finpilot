"""Tests for the split-sync endpoints (loans + prepaid cards).

These endpoints return HTTP 202 immediately and spawn background tasks. The
tests patch the credential pre-flight check and the spawned background
coroutines so no real Supabase or scraper I/O occurs — we only assert the
synchronous request/response contract (202 + job_id + pending status, and the
404 path when no credentials exist).
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi import HTTPException, status
from httpx import AsyncClient

from app.routers import sync as sync_router


@pytest.fixture
def _stub_background(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the spawned background coroutines with harmless no-ops.

    The endpoint uses ``asyncio.create_task`` on these; stubbing them prevents
    any real scrape, pipeline, or durable-job DB write during the test.
    """

    async def _noop(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(sync_router, "_background_sync_loans_task", _noop)
    monkeypatch.setattr(sync_router, "_background_sync_prepaid_cards_task", _noop)
    monkeypatch.setattr(sync_router, "_create_job_in_db", _noop)
    monkeypatch.setattr(sync_router, "_keepalive_while_running", _noop)


@pytest.fixture
def _credentials_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the credential pre-flight check pass without hitting Supabase."""

    def _ok(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(sync_router, "_validate_credentials_exist", _ok)


@pytest.fixture
def _credentials_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the credential pre-flight check raise 404, as it does when none exist."""

    def _missing(*_args: object, **_kwargs: object) -> None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active credentials found for bank NBE",
        )

    monkeypatch.setattr(sync_router, "_validate_credentials_exist", _missing)


@pytest.mark.parametrize("endpoint", ["loans", "prepaid-cards"])
async def test_split_sync_returns_202_with_job_id(
    endpoint: str,
    client: AsyncClient,
    auth_headers: Callable[..., dict[str, str]],
    _credentials_present: None,
    _stub_background: None,
) -> None:
    resp = await client.post(
        f"/api/v1/accounts/sync/NBE/{endpoint}",
        headers=auth_headers(),
    )

    assert resp.status_code == status.HTTP_202_ACCEPTED
    body = resp.json()
    assert isinstance(body["job_id"], str)
    assert body["job_id"]
    assert body["status"] == "pending"


@pytest.mark.parametrize("endpoint", ["loans", "prepaid-cards"])
async def test_split_sync_404_when_no_credentials(
    endpoint: str,
    client: AsyncClient,
    auth_headers: Callable[..., dict[str, str]],
    _credentials_missing: None,
    _stub_background: None,
) -> None:
    resp = await client.post(
        f"/api/v1/accounts/sync/NBE/{endpoint}",
        headers=auth_headers(),
    )

    assert resp.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.parametrize("endpoint", ["loans", "prepaid-cards"])
async def test_split_sync_requires_auth(
    endpoint: str,
    client: AsyncClient,
    _credentials_present: None,
    _stub_background: None,
) -> None:
    resp = await client.post(f"/api/v1/accounts/sync/NBE/{endpoint}")
    assert resp.status_code in (
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,
    )
