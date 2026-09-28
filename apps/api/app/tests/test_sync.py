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
from app.scrapers.base import ScraperLoginError, ScraperResult
from app.scrapers.nbe import NBEPhaseOutcome, NBEScraper


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
        ("_background_sync_task", "scrape_all_products"),
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

    async def fake_scrape(_self: NBEScraper, *args: object) -> object:
        section = SimpleNamespace(accounts=[object()], transactions=[])
        if args:  # scrape_all_products(on_phase): hand one section to the saver
            await args[0](NBEPhaseOutcome(phase="accounts", result=section))  # type: ignore[operator]
            return []
        return section

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
    ("_background_sync_task", "scrape_all_products"),
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

    async def hung_scrape(_self: NBEScraper, *_args: object) -> object:
        try:
            await asyncio.Event().wait()
        finally:
            cleanup_ran.append(True)  # the scraper's browser teardown must run
        return object()

    async def fake_async_client() -> object:
        return object()

    monkeypatch.setattr(sync_router, "get_service_role_client", FakeClient)
    monkeypatch.setattr(sync_router, "get_async_service_role_client", fake_async_client)
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


# ---------------------------------------------------------------------------
# NBE one-session "Sync all"
# ---------------------------------------------------------------------------


def _patch_nbe_all(
    monkeypatch: pytest.MonkeyPatch,
    outcomes: list[NBEPhaseOutcome] | Exception,
    saved: list[str],
) -> list[dict[str, str]]:
    """Stub scrape_all_products, the pipeline and credential timestamp update."""
    updates: list[dict[str, str]] = []

    class FakeQuery:
        def update(self, payload: dict[str, str]) -> FakeQuery:
            updates.append(payload)
            return self

        def eq(self, *_args: object) -> FakeQuery:
            return self

        def execute(self) -> SimpleNamespace:
            return SimpleNamespace(data=[])

    class FakeClient:
        def table(self, _name: str) -> FakeQuery:
            return FakeQuery()

    async def fake_all(_self: NBEScraper, on_phase: Callable[..., object]) -> object:
        if isinstance(outcomes, Exception):
            raise outcomes
        for outcome in outcomes:
            await on_phase(outcome)  # type: ignore[misc]
        return outcomes

    async def fake_pipeline(result: ScraperResult, **_kwargs: object) -> SimpleNamespace:
        saved.append(str(result.accounts[0]))
        return SimpleNamespace(transactions_new=len(result.transactions))

    async def fake_async_client() -> object:
        return object()

    monkeypatch.setattr(NBEScraper, "scrape_all_products", fake_all)
    monkeypatch.setattr(sync_router, "run_pipeline", fake_pipeline)
    monkeypatch.setattr(sync_router, "get_async_service_role_client", fake_async_client)
    monkeypatch.setattr(sync_router, "get_service_role_client", FakeClient)
    return updates


def _section(name: str, txns: int = 0) -> ScraperResult:
    # Plain placeholders: the pipeline is stubbed, only counts are read.
    return ScraperResult(accounts=[name], transactions=[object()] * txns)  # type: ignore[list-item]


async def _run_nbe_all(job_id: str) -> dict[str, object]:
    sync_router._JOBS[job_id] = {"status": "running", "result": None, "error": None}
    scraper = NBEScraper(username="u", password="p")
    await sync_router._sync_nbe_all_products(job_id, uuid4(), scraper, uuid4(), "NBE-Test")
    return sync_router._JOBS.pop(job_id)


async def test_nbe_sync_all_saves_each_section_and_reports_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saved: list[str] = []
    updates = _patch_nbe_all(
        monkeypatch,
        [
            NBEPhaseOutcome("credit_cards", _section("card", 3)),
            NBEPhaseOutcome("accounts", _section("savings", 2)),
            NBEPhaseOutcome("certificates", error="timed out"),
            NBEPhaseOutcome("loans", _section("loan")),
            NBEPhaseOutcome("prepaid_cards", ScraperResult(accounts=[], transactions=[])),
        ],
        saved,
    )
    job = await _run_nbe_all(str(uuid4()))

    assert job["status"] == "complete"
    assert saved == ["card", "savings", "loan"]  # empty section saves nothing
    result = job["result"]
    assert isinstance(result, sync_router.SyncResponse)
    assert result.transactions_scraped == 5
    by_phase = {p.phase: p for p in result.phases or []}
    assert by_phase["certificates"].status == "failed"
    assert by_phase["certificates"].error == "timed out"
    assert by_phase["prepaid_cards"].status == "complete"
    assert len(updates) == 1  # credential last_synced_at advanced once
    assert job["progress"] is None


async def test_nbe_sync_all_fails_when_no_section_is_saved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    updates = _patch_nbe_all(
        monkeypatch,
        [NBEPhaseOutcome(p, error="timed out") for p in sync_router.NBE_SYNC_PHASES],
        [],
    )
    job = await _run_nbe_all(str(uuid4()))
    assert job["status"] == "failed"
    assert "No NBE section synced" in str(job["error"])
    assert updates == []


async def test_nbe_sync_all_login_rejection_fails_job(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_nbe_all(monkeypatch, ScraperLoginError("bad", bank_code="NBE"), [])
    job = await _run_nbe_all(str(uuid4()))
    assert job["status"] == "failed"
    assert job["error"] == "Invalid bank credentials"


async def test_nbe_sync_all_keeps_saved_sections_when_deadline_hits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saved: list[str] = []
    _patch_nbe_all(monkeypatch, [], saved)

    async def slow_all(_self: NBEScraper, on_phase: Callable[..., object]) -> None:
        await on_phase(NBEPhaseOutcome("credit_cards", _section("card", 1)))  # type: ignore[misc]
        await asyncio.Event().wait()

    monkeypatch.setattr(NBEScraper, "scrape_all_products", slow_all)
    monkeypatch.setattr(
        sync_router, "_PHASE_DEADLINE_S", dict.fromkeys(sync_router._PHASE_DEADLINE_S, 0.05)
    )
    job = await _run_nbe_all(str(uuid4()))

    assert job["status"] == "complete"
    assert saved == ["card"]
    phases = {p.phase: p for p in job["result"].phases}  # type: ignore[union-attr]
    assert phases["credit_cards"].status == "complete"
    assert phases["accounts"].status == "failed"
    assert phases["accounts"].error == "Bank portal timed out"
    assert not sync_router._SCRAPE_SEMAPHORE.locked()
