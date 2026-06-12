"""Integration tests for the preferences router.

Every endpoint requires a verified Supabase Auth JWT via
``Depends(get_current_user_id)`` (see ``app.deps``). Missing/malformed/
expired tokens return HTTP 401. ``user_id`` is the JWT ``sub`` claim and is
never client-supplied.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client() -> TestClient:
    from fastapi import FastAPI

    from app.routers.preferences import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    return TestClient(app)


@pytest.fixture
def user_headers(auth_headers):
    """Authorization header for a single authenticated test user."""
    return auth_headers()


def _make_supabase_mock(
    return_rows: list[dict[str, Any]],
    second_return_rows: list[dict[str, Any]] | None = None,
) -> MagicMock:
    execute_result = MagicMock()
    execute_result.data = return_rows
    second_execute_result = MagicMock()
    second_execute_result.data = second_return_rows

    chain = MagicMock()
    if second_return_rows is None:
        chain.execute.return_value = execute_result
    else:
        chain.execute.side_effect = [execute_result, second_execute_result]
    chain.select.return_value = chain
    chain.upsert.return_value = chain
    chain.eq.return_value = chain
    chain.limit.return_value = chain

    fake_client = MagicMock()
    fake_client.table.return_value = chain
    return fake_client


def test_get_preferences_returns_existing_preferences(
    client: TestClient, user_headers: dict[str, str]
) -> None:
    fake_supabase = _make_supabase_mock([{"preferences": {"fawry_rate": 0.0125}}])

    with patch("app.routers.preferences.get_service_role_client", return_value=fake_supabase):
        response = client.get(
            "/api/v1/user/preferences",
            headers=user_headers,
        )

    assert response.status_code == 200
    assert response.json() == {"preferences": {"fawry_rate": 0.0125}}


def test_get_preferences_missing_profile_returns_empty_object(
    client: TestClient, user_headers: dict[str, str]
) -> None:
    fake_supabase = _make_supabase_mock([])

    with patch("app.routers.preferences.get_service_role_client", return_value=fake_supabase):
        response = client.get(
            "/api/v1/user/preferences",
            headers=user_headers,
        )

    assert response.status_code == 200
    assert response.json() == {"preferences": {}}


def test_update_preferences_merges_existing_values(
    client: TestClient, user_headers: dict[str, str]
) -> None:
    fake_supabase = _make_supabase_mock(
        [{"preferences": {"theme": "dark", "fawry_rate": 0.01}}],
        [{"preferences": {"theme": "dark", "fawry_rate": 0.015}}],
    )

    with patch("app.routers.preferences.get_service_role_client", return_value=fake_supabase):
        response = client.patch(
            "/api/v1/user/preferences",
            json={"preferences": {"fawry_rate": 0.015}},
            headers=user_headers,
        )

    assert response.status_code == 200
    assert response.json() == {"preferences": {"theme": "dark", "fawry_rate": 0.015}}


def test_get_preferences_requires_auth(client: TestClient) -> None:
    """Security: GET without an Authorization header must return 401."""
    response = client.get("/api/v1/user/preferences")
    assert response.status_code == 401


def test_update_preferences_requires_auth(client: TestClient) -> None:
    """Security: PATCH without an Authorization header must return 401."""
    response = client.patch(
        "/api/v1/user/preferences",
        json={"preferences": {"fawry_rate": 0.01}},
    )
    assert response.status_code == 401


def test_update_preferences_invalid_bearer_token_returns_401(
    client: TestClient, supabase_jwt_test_config: None
) -> None:
    """Security: PATCH with a malformed/invalid bearer token must return 401."""
    response = client.patch(
        "/api/v1/user/preferences",
        json={"preferences": {"fawry_rate": 0.01}},
        headers={"Authorization": "Bearer bad-id"},
    )
    assert response.status_code == 401


def test_update_preferences_extra_fields_rejected(
    client: TestClient, user_headers: dict[str, str]
) -> None:
    """Pydantic extra=forbid: extra request fields must return 422."""
    response = client.patch(
        "/api/v1/user/preferences",
        json={"preferences": {"fawry_rate": 0.01}, "injected_field": "evil"},
        headers=user_headers,
    )
    assert response.status_code == 422
