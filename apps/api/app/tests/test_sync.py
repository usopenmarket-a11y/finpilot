"""Tests for the split-sync endpoints (loans + prepaid cards).

These endpoints return HTTP 202 immediately and spawn background tasks. The
tests patch the credential pre-flight check and the spawned background
coroutines so no real Supabase or scraper I/O occurs — we only assert the
synchronous request/response contract (202 + job_id + pending status, and the
404 path when no credentials exist).
"""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException, status
from httpx import AsyncClient

from app.routers import sync as sync_router
from app.scrapers.nbe import NBEScraper


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


@pytest.mark.parametrize(
    ("task_name", "scraper_method"),
    [
        ("_background_sync_task", "scrape"),
        ("_background_sync_accounts_task", "scrape_accounts"),
        ("_background_sync_cc_task", "scrape_credit_cards"),
        ("_background_sync_loans_task", "scrape_loans"),
        ("_background_sync_prepaid_cards_task", "scrape_prepaid_cards"),
        ("_background_sync_certificates_task", "scrape_certificates"),
    ],
)
async def test_scrape_success_with_pipeline_failure_is_reported_as_failed(
    task_name: str,
    scraper_method: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A database failure must not look like a completed bank sync."""
    updates: list[dict[str, str]] = []

    class FakeQuery:
        def select(self, *_args: object) -> FakeQuery:
            return self

        def eq(self, *_args: object) -> FakeQuery:
            return self

        def limit(self, *_args: object) -> FakeQuery:
            return self

        def update(self, payload: dict[str, str]) -> FakeQuery:
            updates.append(payload)
            return self

        def execute(self) -> SimpleNamespace:
            return SimpleNamespace(
                data=[
                    {
                        "id": str(credential_id),
                        "encrypted_username": "encrypted",
                        "encrypted_password": "encrypted",
                        "label": None,
                    }
                ]
            )

    class FakeClient:
        def table(self, name: str) -> FakeQuery:
            assert name == "bank_credentials"
            return FakeQuery()

    async def fake_async_client() -> object:
        return object()

    async def fake_scrape(_self: NBEScraper) -> object:
        return object()

    async def failing_pipeline(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("private database detail")

    monkeypatch.setattr(sync_router, "get_service_role_client", FakeClient)
    monkeypatch.setattr(sync_router, "get_async_service_role_client", fake_async_client)
    monkeypatch.setattr(sync_router, "decrypt", lambda *_args: "decrypted")
    monkeypatch.setattr(sync_router, "run_pipeline", failing_pipeline)
    monkeypatch.setattr(NBEScraper, scraper_method, fake_scrape)

    job_id = str(uuid4())
    credential_id = uuid4()
    user_id = uuid4()
    sync_router._JOBS[job_id] = {
        "status": "pending",
        "result": None,
        "error": None,
        "finished_at": None,
    }
    try:
        await getattr(sync_router, task_name)(job_id, user_id, "NBE", str(credential_id))
        job = sync_router._JOBS[job_id]
        assert job["status"] == "failed"
        assert job["result"] is None
        assert "could not be saved" in job["error"]
        assert "private database detail" not in job["error"]
        assert "private database detail" not in caplog.text
        assert job["finished_at"] is not None
        assert updates == []
    finally:
        del sync_router._JOBS[job_id]
