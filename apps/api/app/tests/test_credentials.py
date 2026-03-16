"""Integration tests for the M9 credentials router.

Covers all three endpoints under /api/v1/accounts/credentials:
  POST   /api/v1/accounts/credentials
  GET    /api/v1/accounts/credentials
  DELETE /api/v1/accounts/credentials/{bank}

Supabase calls are fully intercepted via unittest.mock.patch — no real DB
connections or network I/O occur.  Each test patches
``app.routers.credentials.create_client`` with a MagicMock that returns a
controllable fake client, so the tests exercise the router logic in isolation.

Security contract verified:
  - Response payloads never contain encrypted_username or encrypted_password.
  - Missing or malformed x-user-id header always returns HTTP 400.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

VALID_USER_ID = str(uuid4())
FAKE_CREATED_AT = datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC).isoformat()


@pytest.fixture(scope="module")
def client() -> TestClient:
    """Synchronous ASGI test client — module-scoped for fast execution."""
    from app.main import app

    return TestClient(app)


def _make_supabase_mock(return_rows: list[dict[str, Any]]) -> MagicMock:
    """Build a MagicMock chain that mimics the supabase-py fluent API.

    The mock satisfies:
      client.table(...).upsert(...).execute()              → APIResponse(data=rows)
      client.table(...).select(...).eq(...).execute()      → APIResponse(data=rows)
      client.table(...).delete().eq(...).eq(...).execute() → APIResponse(data=[])
      client.table(...).update(...).eq(...).eq(...).execute()

    Strategy: create one ``chain`` MagicMock whose every named method returns
    itself so the fluent interface works regardless of call depth.  Then set
    chain.execute.return_value to a result object with a .data attribute.
    MagicMock auto-creates attributes as new MagicMocks on first access, so
    we only need to be explicit about ``execute`` and the methods that must
    return ``chain`` to continue the chain.
    """
    execute_result = MagicMock()
    execute_result.data = return_rows

    chain = MagicMock()
    chain.execute.return_value = execute_result
    chain.upsert.return_value = chain
    chain.select.return_value = chain
    chain.delete.return_value = chain
    chain.update.return_value = chain
    chain.eq.return_value = chain

    fake_client = MagicMock()
    fake_client.table.return_value = chain

    return fake_client


# ---------------------------------------------------------------------------
# POST /api/v1/accounts/credentials
# ---------------------------------------------------------------------------


def test_save_credential_returns_200(client: TestClient) -> None:
    """Happy path: valid request with x-user-id returns 200 and safe metadata."""
    fake_row = {
        "bank": "NBE",
        "is_active": True,
        "last_synced_at": None,
        "created_at": FAKE_CREATED_AT,
    }
    fake_supabase = _make_supabase_mock([fake_row])

    with patch("app.routers.credentials.create_client", return_value=fake_supabase):
        response = client.post(
            "/api/v1/accounts/credentials",
            json={
                "bank": "NBE",
                "encrypted_username": "enc_user_abc",
                "encrypted_password": "enc_pass_xyz",
            },
            headers={"x-user-id": VALID_USER_ID},
        )

    assert response.status_code == 200


def test_save_credential_response_shape(client: TestClient) -> None:
    """Response contains exactly the expected safe fields."""
    fake_row = {
        "bank": "CIB",
        "is_active": True,
        "last_synced_at": None,
        "created_at": FAKE_CREATED_AT,
    }
    fake_supabase = _make_supabase_mock([fake_row])

    with patch("app.routers.credentials.create_client", return_value=fake_supabase):
        response = client.post(
            "/api/v1/accounts/credentials",
            json={
                "bank": "CIB",
                "encrypted_username": "enc_u",
                "encrypted_password": "enc_p",
            },
            headers={"x-user-id": VALID_USER_ID},
        )

    data = response.json()
    assert set(data.keys()) == {"bank", "is_active", "last_synced_at", "created_at"}


def test_save_credential_response_never_returns_secrets(client: TestClient) -> None:
    """Security: response must NOT contain encrypted_username or encrypted_password."""
    fake_row = {
        "bank": "BDC",
        "is_active": True,
        "last_synced_at": None,
        "created_at": FAKE_CREATED_AT,
    }
    fake_supabase = _make_supabase_mock([fake_row])

    with patch("app.routers.credentials.create_client", return_value=fake_supabase):
        response = client.post(
            "/api/v1/accounts/credentials",
            json={
                "bank": "BDC",
                "encrypted_username": "super_secret",
                "encrypted_password": "also_secret",
            },
            headers={"x-user-id": VALID_USER_ID},
        )

    data = response.json()
    assert "encrypted_username" not in data
    assert "encrypted_password" not in data


def test_save_credential_missing_user_id_returns_400(client: TestClient) -> None:
    """Security: POST without x-user-id header must return 400."""
    response = client.post(
        "/api/v1/accounts/credentials",
        json={
            "bank": "NBE",
            "encrypted_username": "enc_u",
            "encrypted_password": "enc_p",
        },
    )
    assert response.status_code == 400


def test_save_credential_malformed_user_id_returns_400(client: TestClient) -> None:
    """Security: POST with non-UUID x-user-id must return 400."""
    response = client.post(
        "/api/v1/accounts/credentials",
        json={
            "bank": "NBE",
            "encrypted_username": "enc_u",
            "encrypted_password": "enc_p",
        },
        headers={"x-user-id": "not-a-uuid"},
    )
    assert response.status_code == 400


def test_save_credential_extra_fields_rejected(client: TestClient) -> None:
    """Pydantic extra=forbid: extra request fields must return 422."""
    response = client.post(
        "/api/v1/accounts/credentials",
        json={
            "bank": "NBE",
            "encrypted_username": "enc_u",
            "encrypted_password": "enc_p",
            "injected_field": "evil",
        },
        headers={"x-user-id": VALID_USER_ID},
    )
    assert response.status_code == 422


def test_save_credential_invalid_bank_returns_422(client: TestClient) -> None:
    """Validation: an unsupported bank code must return 422."""
    response = client.post(
        "/api/v1/accounts/credentials",
        json={
            "bank": "EVIL",
            "encrypted_username": "enc_u",
            "encrypted_password": "enc_p",
        },
        headers={"x-user-id": VALID_USER_ID},
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/accounts/credentials
# ---------------------------------------------------------------------------


def test_list_credentials_returns_200(client: TestClient) -> None:
    """Happy path: GET with valid x-user-id returns 200."""
    fake_supabase = _make_supabase_mock([])

    with patch("app.routers.credentials.create_client", return_value=fake_supabase):
        response = client.get(
            "/api/v1/accounts/credentials",
            headers={"x-user-id": VALID_USER_ID},
        )

    assert response.status_code == 200


def test_list_credentials_returns_list(client: TestClient) -> None:
    """Response body is a JSON array."""
    fake_supabase = _make_supabase_mock([])

    with patch("app.routers.credentials.create_client", return_value=fake_supabase):
        response = client.get(
            "/api/v1/accounts/credentials",
            headers={"x-user-id": VALID_USER_ID},
        )

    assert isinstance(response.json(), list)


def test_list_credentials_returns_stored_entries(client: TestClient) -> None:
    """Rows returned by Supabase are reflected in the response."""
    rows = [
        {
            "bank": "NBE",
            "is_active": True,
            "last_synced_at": None,
            "created_at": FAKE_CREATED_AT,
        },
        {
            "bank": "CIB",
            "is_active": False,
            "last_synced_at": FAKE_CREATED_AT,
            "created_at": FAKE_CREATED_AT,
        },
    ]
    fake_supabase = _make_supabase_mock(rows)

    with patch("app.routers.credentials.create_client", return_value=fake_supabase):
        response = client.get(
            "/api/v1/accounts/credentials",
            headers={"x-user-id": VALID_USER_ID},
        )

    data = response.json()
    assert len(data) == 2
    banks = {item["bank"] for item in data}
    assert banks == {"NBE", "CIB"}


def test_list_credentials_never_returns_secrets(client: TestClient) -> None:
    """Security: list response items must never include secret fields."""
    rows = [
        {
            "bank": "UB",
            "is_active": True,
            "last_synced_at": None,
            "created_at": FAKE_CREATED_AT,
        }
    ]
    fake_supabase = _make_supabase_mock(rows)

    with patch("app.routers.credentials.create_client", return_value=fake_supabase):
        response = client.get(
            "/api/v1/accounts/credentials",
            headers={"x-user-id": VALID_USER_ID},
        )

    for item in response.json():
        assert "encrypted_username" not in item
        assert "encrypted_password" not in item


def test_list_credentials_missing_user_id_returns_400(client: TestClient) -> None:
    """Security: GET without x-user-id header must return 400."""
    response = client.get("/api/v1/accounts/credentials")
    assert response.status_code == 400


def test_list_credentials_malformed_user_id_returns_400(client: TestClient) -> None:
    """Security: GET with non-UUID x-user-id must return 400."""
    response = client.get(
        "/api/v1/accounts/credentials",
        headers={"x-user-id": "bad-id"},
    )
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# DELETE /api/v1/accounts/credentials/{bank}
# ---------------------------------------------------------------------------


def test_delete_credential_returns_204(client: TestClient) -> None:
    """Happy path: DELETE with valid inputs returns 204 No Content."""
    fake_supabase = _make_supabase_mock([])

    with patch("app.routers.credentials.create_client", return_value=fake_supabase):
        response = client.delete(
            "/api/v1/accounts/credentials/NBE",
            headers={"x-user-id": VALID_USER_ID},
        )

    assert response.status_code == 204


def test_delete_credential_idempotent(client: TestClient) -> None:
    """Deleting a non-existent credential still returns 204 (idempotent)."""
    fake_supabase = _make_supabase_mock([])

    with patch("app.routers.credentials.create_client", return_value=fake_supabase):
        r1 = client.delete(
            "/api/v1/accounts/credentials/CIB",
            headers={"x-user-id": VALID_USER_ID},
        )
        r2 = client.delete(
            "/api/v1/accounts/credentials/CIB",
            headers={"x-user-id": VALID_USER_ID},
        )

    assert r1.status_code == 204
    assert r2.status_code == 204


def test_delete_credential_missing_user_id_returns_400(client: TestClient) -> None:
    """Security: DELETE without x-user-id header must return 400."""
    response = client.delete("/api/v1/accounts/credentials/NBE")
    assert response.status_code == 400


def test_delete_credential_malformed_user_id_returns_400(client: TestClient) -> None:
    """Security: DELETE with non-UUID x-user-id must return 400."""
    response = client.delete(
        "/api/v1/accounts/credentials/NBE",
        headers={"x-user-id": "oops"},
    )
    assert response.status_code == 400


def test_delete_credential_invalid_bank_returns_422(client: TestClient) -> None:
    """Validation: an unsupported bank code in the path must return 422."""
    response = client.delete(
        "/api/v1/accounts/credentials/FAKEBANK",
        headers={"x-user-id": VALID_USER_ID},
    )
    assert response.status_code == 422
