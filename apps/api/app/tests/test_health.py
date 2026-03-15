"""Integration tests for the /api/v1/health endpoint.

Tests run against the real ASGI app via httpx.AsyncClient — no mocking.
The health endpoint has no external dependencies, so this is a pure
ASGI integration test with zero network I/O.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_check_returns_200(client: AsyncClient) -> None:
    """Happy path: GET /api/v1/health responds with HTTP 200."""
    response = await client.get("/api/v1/health")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_health_check_status_is_ok(client: AsyncClient) -> None:
    """Happy path: response body contains status == 'ok'."""
    response = await client.get("/api/v1/health")
    data = response.json()
    assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_health_check_returns_version(client: AsyncClient) -> None:
    """Happy path: response body contains a 'version' key."""
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert "version" in data


@pytest.mark.asyncio
async def test_health_check_version_value(client: AsyncClient) -> None:
    """Response version matches the declared application version."""
    response = await client.get("/api/v1/health")
    data = response.json()
    assert data["version"] == "0.1.0"


@pytest.mark.asyncio
async def test_health_check_response_shape(client: AsyncClient) -> None:
    """Response contains exactly the expected keys — no extra fields, no missing ones."""
    response = await client.get("/api/v1/health")
    data = response.json()
    assert set(data.keys()) == {"status", "version"}


@pytest.mark.asyncio
async def test_health_check_content_type(client: AsyncClient) -> None:
    """Response Content-Type is application/json."""
    response = await client.get("/api/v1/health")
    assert "application/json" in response.headers["content-type"]


@pytest.mark.asyncio
async def test_health_check_wrong_method_returns_405(client: AsyncClient) -> None:
    """Error path: POST to the health endpoint is not allowed."""
    response = await client.post("/api/v1/health")
    assert response.status_code == 405


@pytest.mark.asyncio
async def test_health_check_missing_route_returns_404(client: AsyncClient) -> None:
    """Error path: a non-existent path returns 404."""
    response = await client.get("/api/v1/healthz")
    assert response.status_code == 404
