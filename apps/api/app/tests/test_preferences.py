"""Integration tests for the preferences router."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

VALID_USER_ID = str(uuid4())


@pytest.fixture(scope="module")
def client() -> TestClient:
    from fastapi import FastAPI

    from app.routers.preferences import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    return TestClient(app)


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


def test_get_preferences_returns_existing_preferences(client: TestClient) -> None:
    fake_supabase = _make_supabase_mock([{"preferences": {"fawry_rate": 0.0125}}])

    with patch("app.routers.preferences.create_client", return_value=fake_supabase):
        response = client.get(
            "/api/v1/user/preferences",
            headers={"x-user-id": VALID_USER_ID},
        )

    assert response.status_code == 200
    assert response.json() == {"preferences": {"fawry_rate": 0.0125}}


def test_get_preferences_missing_profile_returns_empty_object(client: TestClient) -> None:
    fake_supabase = _make_supabase_mock([])

    with patch("app.routers.preferences.create_client", return_value=fake_supabase):
        response = client.get(
            "/api/v1/user/preferences",
            headers={"x-user-id": VALID_USER_ID},
        )

    assert response.status_code == 200
    assert response.json() == {"preferences": {}}


def test_update_preferences_merges_existing_values(client: TestClient) -> None:
    fake_supabase = _make_supabase_mock(
        [{"preferences": {"theme": "dark", "fawry_rate": 0.01}}],
        [{"preferences": {"theme": "dark", "fawry_rate": 0.015}}],
    )

    with patch("app.routers.preferences.create_client", return_value=fake_supabase):
        response = client.patch(
            "/api/v1/user/preferences",
            json={"preferences": {"fawry_rate": 0.015}},
            headers={"x-user-id": VALID_USER_ID},
        )

    assert response.status_code == 200
    assert response.json() == {"preferences": {"theme": "dark", "fawry_rate": 0.015}}


def test_preferences_missing_user_id_returns_400(client: TestClient) -> None:
    response = client.get("/api/v1/user/preferences")
    assert response.status_code == 400


def test_preferences_malformed_user_id_returns_400(client: TestClient) -> None:
    response = client.patch(
        "/api/v1/user/preferences",
        json={"preferences": {"fawry_rate": 0.01}},
        headers={"x-user-id": "bad-id"},
    )
    assert response.status_code == 400
