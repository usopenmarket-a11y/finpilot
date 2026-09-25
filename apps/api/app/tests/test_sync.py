"""Tests for the split-sync endpoints (loans + prepaid cards).

These endpoints return HTTP 202 immediately and spawn background tasks. The
tests patch the credential pre-flight check and the spawned background
coroutines so no real Supabase or scraper I/O occurs — we only assert the
synchronous request/response contract (202 + job_id + pending status, and the
404 path when no credentials exist).
"""

from __future__ import annotations

import asyncio
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


_TASK_METHODS = [
    ("_background_sync_task", "scrape"),
    ("_background_sync_accounts_task", "scrape_accounts"),
    ("_background_sync_cc_task", "scrape_credit_cards"),
    ("_background_sync_loans_task", "scrape_loans"),
    ("_background_sync_prepaid_cards_task", "scrape_prepaid_cards"),
    ("_background_sync_certificates_task", "scrape_certificates"),
]


@pytest.mark.parametrize(("task_name", "scraper_method"), _TASK_METHODS)
async def test_hung_scraper_is_stopped_by_server_deadline(
    task_name: str,
    scraper_method: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stalled portal must fail the job and release the scrape slot."""
    cleanup_ran: list[bool] = []

    class FakeQuery:
        def select(self, *_args: object) -> FakeQuery:
            return self

        def eq(self, *_args: object) -> FakeQuery:
            return self

        def limit(self, *_args: object) -> FakeQuery:
            return self

        def execute(self) -> SimpleNamespace:
            return SimpleNamespace(
                data=[
                    {
                        "id": str(uuid4()),
                        "encrypted_username": "encrypted",
                        "encrypted_password": "encrypted",
                        "label": None,
                    }
                ]
            )

    class FakeClient:
        def table(self, _name: str) -> FakeQuery:
            return FakeQuery()

    async def hung_scrape(_self: NBEScraper) -> object:
        try:
            await asyncio.Event().wait()
        finally:
            cleanup_ran.append(True)  # the scraper's browser teardown must run
        return object()

    monkeypatch.setattr(sync_router, "get_service_role_client", FakeClient)
    monkeypatch.setattr(sync_router, "decrypt", lambda *_args: "decrypted")
    monkeypatch.setattr(NBEScraper, scraper_method, hung_scrape)
    monkeypatch.setattr(
        sync_router, "_PHASE_DEADLINE_S", dict.fromkeys(sync_router._PHASE_DEADLINE_S, 0.05)
    )

    job_id = str(uuid4())
    sync_router._JOBS[job_id] = {
        "status": "pending",
        "result": None,
        "error": None,
        "finished_at": None,
    }
    try:
        await asyncio.wait_for(
            getattr(sync_router, task_name)(job_id, uuid4(), "NBE", None), timeout=5
        )
        job = sync_router._JOBS[job_id]
        assert job["status"] == "failed"
        assert "timed out" in job["error"]
        assert cleanup_ran == [True]
        assert not sync_router._SCRAPE_SEMAPHORE.locked()
    finally:
        del sync_router._JOBS[job_id]


@pytest.mark.parametrize("stale_status", ["pending", "running"])
async def test_status_of_orphaned_job_reports_interruption(
    stale_status: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A durable running row with no live task (API restarted) must not poll forever."""
    persisted: list[dict[str, object]] = []

    async def fake_load(job_id: str, _user_id: object) -> sync_router.SyncJobStatusResponse:
        return sync_router.SyncJobStatusResponse(job_id=job_id, status=stale_status)

    async def fake_persist(_job_id: str, job: dict[str, object]) -> None:
        persisted.append(job)

    monkeypatch.setattr(sync_router, "_load_job_from_db", fake_load)
    monkeypatch.setattr(sync_router, "_persist_job_to_db", fake_persist)

    response = await sync_router.get_sync_status(str(uuid4()), uuid4())

    assert response.status == "failed"
    assert response.error is not None and "interrupted" in response.error
    assert len(persisted) == 1 and persisted[0]["status"] == "failed"
    assert persisted[0]["finished_at"] is not None


async def test_status_of_finished_durable_job_is_returned_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_load(job_id: str, _user_id: object) -> sync_router.SyncJobStatusResponse:
        return sync_router.SyncJobStatusResponse(
            job_id=job_id, status="failed", error="Bank portal timed out"
        )

    async def fail_persist(*_args: object) -> None:
        raise AssertionError("finished jobs must not be rewritten")

    monkeypatch.setattr(sync_router, "_load_job_from_db", fake_load)
    monkeypatch.setattr(sync_router, "_persist_job_to_db", fail_persist)

    response = await sync_router.get_sync_status(str(uuid4()), uuid4())
    assert response.status == "failed"
    assert response.error == "Bank portal timed out"
