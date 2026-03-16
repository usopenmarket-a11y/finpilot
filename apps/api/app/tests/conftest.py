from __future__ import annotations

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
