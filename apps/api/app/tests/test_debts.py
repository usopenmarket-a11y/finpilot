"""Integration tests for the M5 Debt Tracker router.

Covers every endpoint under /api/v1/debts:
  POST   /api/v1/debts
  GET    /api/v1/debts
  GET    /api/v1/debts/{debt_id}
  PATCH  /api/v1/debts/{debt_id}
  DELETE /api/v1/debts/{debt_id}
  POST   /api/v1/debts/{debt_id}/payments

All tests run synchronously via FastAPI's TestClient — the debts router uses
in-memory storage with no async I/O, so the sync client is the right tool.

State isolation is handled by the autouse ``reset_storage`` fixture, which
calls ``clear_storage()`` exported from the router before every test.  No test
depends on ordering; each is fully independent.

Authentication
---------------
Every endpoint requires ``Depends(get_current_user_id)`` — a verified
Supabase Auth JWT in the ``Authorization: Bearer <token>`` header. The
``auth_headers`` fixture (from ``conftest.py``) mints such a token for a
given (or random) user id. Most tests use a single fixed caller via the
``user_headers`` fixture (bound to ``USER_ID``); a dedicated section near the
bottom covers cross-user isolation using a second identity
(``other_user_headers``, bound to ``OTHER_USER_ID``).

Security contract:
  - Fake counterparty data only; no real PII.
  - No network I/O; no external services.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

USER_ID = UUID("22222222-2222-2222-2222-222222222222")
OTHER_USER_ID = UUID("33333333-3333-3333-3333-333333333333")


@pytest.fixture(scope="module")
def client() -> TestClient:
    """Synchronous test client wired to the ASGI app.

    Module-scoped so the app is only instantiated once per test module.
    State isolation is achieved via the autouse ``reset_storage`` fixture.
    """
    from app.main import app

    return TestClient(app)


@pytest.fixture(autouse=True)
def reset_storage() -> None:
    """Clear in-memory debt storage before every test to guarantee isolation."""
    from app.routers.debts import clear_storage

    clear_storage()


@pytest.fixture
def user_headers(auth_headers):
    """Authorization headers for the primary test user (``USER_ID``)."""
    return auth_headers(user_id=USER_ID)


@pytest.fixture
def other_user_headers(auth_headers):
    """Authorization headers for a second, distinct test user (``OTHER_USER_ID``)."""
    return auth_headers(user_id=OTHER_USER_ID)


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------


def _lent_payload(**overrides: Any) -> dict[str, Any]:
    """Minimal valid 'lent' debt payload."""
    base: dict[str, Any] = {
        "debt_type": "lent",
        "counterparty_name": "Ahmed Hassan",
        "original_amount": 1000.0,
    }
    base.update(overrides)
    return base


def _borrowed_payload(**overrides: Any) -> dict[str, Any]:
    """Minimal valid 'borrowed' debt payload."""
    base: dict[str, Any] = {
        "debt_type": "borrowed",
        "counterparty_name": "Sara Mahmoud",
        "original_amount": 500.0,
    }
    base.update(overrides)
    return base


def _full_lent_payload(**overrides: Any) -> dict[str, Any]:
    """Fully-populated 'lent' debt payload with all optional fields."""
    base: dict[str, Any] = {
        "debt_type": "lent",
        "counterparty_name": "Mohamed Ali",
        "counterparty_phone": "+201001234567",
        "counterparty_email": "m.ali@example.com",
        "original_amount": 2500.0,
        "currency": "EGP",
        "due_date": "2026-06-30",
        "notes": "School fees loan",
    }
    base.update(overrides)
    return base


def _payment_payload(**overrides: Any) -> dict[str, Any]:
    """Minimal valid payment payload."""
    base: dict[str, Any] = {
        "amount": 100.0,
        "payment_date": "2026-03-16",
    }
    base.update(overrides)
    return base


def _create_debt(
    client: TestClient,
    headers: dict[str, str],
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a debt as the caller identified by ``headers`` and return the parsed body."""
    if payload is None:
        payload = _lent_payload()
    response = client.post("/api/v1/debts", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


# ===========================================================================
# Auth requirement (no Authorization header)
# ===========================================================================


def test_create_debt_requires_auth(client: TestClient) -> None:
    """POST without an Authorization header → 401."""
    response = client.post("/api/v1/debts", json=_lent_payload())

    assert response.status_code == 401


def test_list_debts_requires_auth(client: TestClient) -> None:
    """GET without an Authorization header → 401."""
    response = client.get("/api/v1/debts")

    assert response.status_code == 401


def test_get_debt_requires_auth(client: TestClient, user_headers: dict[str, str]) -> None:
    """GET detail without an Authorization header → 401."""
    created = _create_debt(client, user_headers)

    response = client.get(f"/api/v1/debts/{created['id']}")

    assert response.status_code == 401


def test_patch_debt_requires_auth(client: TestClient, user_headers: dict[str, str]) -> None:
    """PATCH without an Authorization header → 401."""
    created = _create_debt(client, user_headers)

    response = client.patch(f"/api/v1/debts/{created['id']}", json={"notes": "x"})

    assert response.status_code == 401


def test_delete_debt_requires_auth(client: TestClient, user_headers: dict[str, str]) -> None:
    """DELETE without an Authorization header → 401."""
    created = _create_debt(client, user_headers)

    response = client.delete(f"/api/v1/debts/{created['id']}")

    assert response.status_code == 401


def test_create_payment_requires_auth(client: TestClient, user_headers: dict[str, str]) -> None:
    """POST payment without an Authorization header → 401."""
    created = _create_debt(client, user_headers)

    response = client.post(
        f"/api/v1/debts/{created['id']}/payments",
        json=_payment_payload(),
    )

    assert response.status_code == 401


# ===========================================================================
# POST /api/v1/debts
# ===========================================================================


def test_create_debt_lent(client: TestClient, user_headers: dict[str, str]) -> None:
    """Happy path: create a 'lent' debt returns 201 with correct fields."""
    response = client.post("/api/v1/debts", json=_lent_payload(), headers=user_headers)

    assert response.status_code == 201
    data = response.json()
    assert data["debt_type"] == "lent"
    assert data["counterparty_name"] == "Ahmed Hassan"
    assert float(data["original_amount"]) == pytest.approx(1000.0)


def test_create_debt_borrowed(client: TestClient, user_headers: dict[str, str]) -> None:
    """Happy path: create a 'borrowed' debt returns 201 with debt_type='borrowed'."""
    response = client.post("/api/v1/debts", json=_borrowed_payload(), headers=user_headers)

    assert response.status_code == 201
    data = response.json()
    assert data["debt_type"] == "borrowed"
    assert data["counterparty_name"] == "Sara Mahmoud"


def test_create_debt_with_all_fields(client: TestClient, user_headers: dict[str, str]) -> None:
    """Happy path: creating a debt with all optional fields stores them correctly."""
    response = client.post("/api/v1/debts", json=_full_lent_payload(), headers=user_headers)

    assert response.status_code == 201
    data = response.json()
    assert data["counterparty_phone"] == "+201001234567"
    assert data["counterparty_email"] == "m.ali@example.com"
    assert data["due_date"] == "2026-06-30"
    assert data["notes"] == "School fees loan"
    assert data["currency"] == "EGP"


def test_create_debt_assigns_caller_user_id(
    client: TestClient, user_headers: dict[str, str]
) -> None:
    """The created debt's user_id matches the verified caller's JWT subject."""
    response = client.post("/api/v1/debts", json=_lent_payload(), headers=user_headers)

    assert response.status_code == 201
    assert response.json()["user_id"] == str(USER_ID)


def test_create_debt_invalid_type(client: TestClient, user_headers: dict[str, str]) -> None:
    """Error path: unknown debt_type value → 422 validation error."""
    response = client.post(
        "/api/v1/debts", json=_lent_payload(debt_type="gifted"), headers=user_headers
    )

    assert response.status_code == 422


def test_create_debt_zero_amount(client: TestClient, user_headers: dict[str, str]) -> None:
    """Error path: original_amount=0 violates gt=0 constraint → 422."""
    response = client.post(
        "/api/v1/debts", json=_lent_payload(original_amount=0), headers=user_headers
    )

    assert response.status_code == 422


def test_create_debt_negative_amount(client: TestClient, user_headers: dict[str, str]) -> None:
    """Error path: negative original_amount violates gt=0 constraint → 422."""
    response = client.post(
        "/api/v1/debts", json=_lent_payload(original_amount=-100.0), headers=user_headers
    )

    assert response.status_code == 422


def test_create_debt_missing_counterparty(client: TestClient, user_headers: dict[str, str]) -> None:
    """Error path: missing required counterparty_name → 422."""
    payload = {
        "debt_type": "lent",
        "original_amount": 500.0,
    }
    response = client.post("/api/v1/debts", json=payload, headers=user_headers)

    assert response.status_code == 422


def test_create_debt_extra_field_forbidden(
    client: TestClient, user_headers: dict[str, str]
) -> None:
    """Error path: extra unknown field in body → 422 (extra='forbid' on schema)."""
    response = client.post(
        "/api/v1/debts",
        json={**_lent_payload(), "surprise_field": "unexpected"},
        headers=user_headers,
    )

    assert response.status_code == 422


def test_create_debt_default_status_active(
    client: TestClient, user_headers: dict[str, str]
) -> None:
    """New debts start with status='active' by default."""
    data = _create_debt(client, user_headers)

    assert data["status"] == "active"


def test_create_debt_outstanding_equals_original(
    client: TestClient, user_headers: dict[str, str]
) -> None:
    """At creation, outstanding_balance must equal original_amount."""
    data = _create_debt(client, user_headers, _lent_payload(original_amount=750.0))

    assert float(data["outstanding_balance"]) == pytest.approx(float(data["original_amount"]))


def test_create_debt_returns_id(client: TestClient, user_headers: dict[str, str]) -> None:
    """Created debt response includes a non-empty 'id' field."""
    data = _create_debt(client, user_headers)

    assert "id" in data
    assert data["id"]


# ===========================================================================
# GET /api/v1/debts
# ===========================================================================


def test_list_debts_empty(client: TestClient, user_headers: dict[str, str]) -> None:
    """With no debts created, list endpoint returns an empty array."""
    response = client.get("/api/v1/debts", headers=user_headers)

    assert response.status_code == 200
    assert response.json() == []


def test_list_debts_returns_created(client: TestClient, user_headers: dict[str, str]) -> None:
    """Creating two debts then listing returns both."""
    _create_debt(client, user_headers, _lent_payload(counterparty_name="Person A"))
    _create_debt(client, user_headers, _borrowed_payload(counterparty_name="Person B"))

    response = client.get("/api/v1/debts", headers=user_headers)

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    names = {d["counterparty_name"] for d in data}
    assert names == {"Person A", "Person B"}


def test_list_debts_filter_by_status(client: TestClient, user_headers: dict[str, str]) -> None:
    """?status=active returns only active debts."""
    _create_debt(client, user_headers, _lent_payload())
    _create_debt(client, user_headers, _borrowed_payload())

    response = client.get("/api/v1/debts?status=active", headers=user_headers)

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert all(d["status"] == "active" for d in data)


def test_list_debts_filter_by_debt_type(client: TestClient, user_headers: dict[str, str]) -> None:
    """?debt_type=lent returns only lent debts."""
    _create_debt(client, user_headers, _lent_payload(counterparty_name="Lent Guy"))
    _create_debt(client, user_headers, _borrowed_payload(counterparty_name="Borrowed Gal"))

    response = client.get("/api/v1/debts?debt_type=lent", headers=user_headers)

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["debt_type"] == "lent"
    assert data[0]["counterparty_name"] == "Lent Guy"


def test_list_debts_filter_combined(client: TestClient, user_headers: dict[str, str]) -> None:
    """?status=active&debt_type=borrowed returns only active+borrowed debts."""
    _create_debt(client, user_headers, _lent_payload())
    _create_debt(client, user_headers, _borrowed_payload())

    response = client.get("/api/v1/debts?status=active&debt_type=borrowed", headers=user_headers)

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["debt_type"] == "borrowed"
    assert data[0]["status"] == "active"


def test_list_debts_filter_no_matches(client: TestClient, user_headers: dict[str, str]) -> None:
    """Filter that matches nothing returns an empty array (not 404)."""
    _create_debt(client, user_headers, _lent_payload())

    response = client.get("/api/v1/debts?status=settled", headers=user_headers)

    assert response.status_code == 200
    assert response.json() == []


# ===========================================================================
# GET /api/v1/debts/{debt_id}
# ===========================================================================


def test_get_debt_found(client: TestClient, user_headers: dict[str, str]) -> None:
    """Happy path: creating a debt then fetching by id returns the same debt."""
    created = _create_debt(client, user_headers)
    debt_id = created["id"]

    response = client.get(f"/api/v1/debts/{debt_id}", headers=user_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == debt_id
    assert data["counterparty_name"] == created["counterparty_name"]


def test_get_debt_not_found(client: TestClient, user_headers: dict[str, str]) -> None:
    """Error path: fetching a non-existent debt_id → 404."""
    response = client.get("/api/v1/debts/nonexistent-id-12345", headers=user_headers)

    assert response.status_code == 404


def test_get_debt_includes_payments(client: TestClient, user_headers: dict[str, str]) -> None:
    """Debt detail endpoint includes a 'payments' list; after one payment it has one entry."""
    created = _create_debt(client, user_headers, _lent_payload(original_amount=500.0))
    debt_id = created["id"]

    pay_resp = client.post(
        f"/api/v1/debts/{debt_id}/payments",
        json=_payment_payload(amount=100.0),
        headers=user_headers,
    )
    assert pay_resp.status_code == 201

    response = client.get(f"/api/v1/debts/{debt_id}", headers=user_headers)

    assert response.status_code == 200
    data = response.json()
    assert "payments" in data
    assert len(data["payments"]) == 1


# ===========================================================================
# PATCH /api/v1/debts/{debt_id}
# ===========================================================================


def test_patch_debt_notes(client: TestClient, user_headers: dict[str, str]) -> None:
    """Happy path: updating 'notes' reflects in the returned response."""
    created = _create_debt(client, user_headers)
    debt_id = created["id"]

    response = client.patch(
        f"/api/v1/debts/{debt_id}",
        json={"notes": "Updated note text"},
        headers=user_headers,
    )

    assert response.status_code == 200
    assert response.json()["notes"] == "Updated note text"


def test_patch_debt_phone(client: TestClient, user_headers: dict[str, str]) -> None:
    """Happy path: updating 'counterparty_phone' is persisted."""
    created = _create_debt(client, user_headers)
    debt_id = created["id"]

    response = client.patch(
        f"/api/v1/debts/{debt_id}",
        json={"counterparty_phone": "+20109876543"},
        headers=user_headers,
    )

    assert response.status_code == 200
    assert response.json()["counterparty_phone"] == "+20109876543"


def test_patch_debt_due_date(client: TestClient, user_headers: dict[str, str]) -> None:
    """Happy path: updating 'due_date' is persisted."""
    created = _create_debt(client, user_headers)
    debt_id = created["id"]

    response = client.patch(
        f"/api/v1/debts/{debt_id}",
        json={"due_date": "2026-12-31"},
        headers=user_headers,
    )

    assert response.status_code == 200
    assert response.json()["due_date"] == "2026-12-31"


def test_patch_debt_status(client: TestClient, user_headers: dict[str, str]) -> None:
    """Happy path: updating 'status' directly is reflected in the response."""
    created = _create_debt(client, user_headers)
    debt_id = created["id"]

    response = client.patch(
        f"/api/v1/debts/{debt_id}",
        json={"status": "partial"},
        headers=user_headers,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "partial"


def test_patch_debt_not_found(client: TestClient, user_headers: dict[str, str]) -> None:
    """Error path: patching a non-existent debt_id → 404."""
    response = client.patch(
        "/api/v1/debts/does-not-exist",
        json={"notes": "irrelevant"},
        headers=user_headers,
    )

    assert response.status_code == 404


def test_patch_debt_partial_update(client: TestClient, user_headers: dict[str, str]) -> None:
    """Partial update: only the supplied field changes; all others remain as created."""
    created = _create_debt(
        client,
        user_headers,
        _full_lent_payload(notes="Original note", counterparty_phone="+201110000001"),
    )
    debt_id = created["id"]

    response = client.patch(
        f"/api/v1/debts/{debt_id}",
        json={"notes": "Changed note"},
        headers=user_headers,
    )

    assert response.status_code == 200
    data = response.json()
    # Updated field
    assert data["notes"] == "Changed note"
    # Unchanged fields
    assert data["counterparty_phone"] == "+201110000001"
    assert data["counterparty_name"] == created["counterparty_name"]
    assert float(data["original_amount"]) == pytest.approx(float(created["original_amount"]))


# ===========================================================================
# DELETE /api/v1/debts/{debt_id}
# ===========================================================================


def test_delete_debt_returns_204(client: TestClient, user_headers: dict[str, str]) -> None:
    """Happy path: deleting an existing debt returns HTTP 204 No Content."""
    created = _create_debt(client, user_headers)
    debt_id = created["id"]

    response = client.delete(f"/api/v1/debts/{debt_id}", headers=user_headers)

    assert response.status_code == 204


def test_delete_debt_sets_settled(client: TestClient, user_headers: dict[str, str]) -> None:
    """After a soft-delete, GET on the debt shows status='settled'."""
    created = _create_debt(client, user_headers)
    debt_id = created["id"]

    client.delete(f"/api/v1/debts/{debt_id}", headers=user_headers)

    get_response = client.get(f"/api/v1/debts/{debt_id}", headers=user_headers)
    assert get_response.status_code == 200
    assert get_response.json()["status"] == "settled"


def test_delete_debt_not_found(client: TestClient, user_headers: dict[str, str]) -> None:
    """Error path: deleting a non-existent debt_id → 404."""
    response = client.delete("/api/v1/debts/ghost-id-99999", headers=user_headers)

    assert response.status_code == 404


# ===========================================================================
# POST /api/v1/debts/{debt_id}/payments
# ===========================================================================


def test_payment_reduces_balance(client: TestClient, user_headers: dict[str, str]) -> None:
    """Recording a payment reduces outstanding_balance by the payment amount."""
    created = _create_debt(client, user_headers, _lent_payload(original_amount=1000.0))
    debt_id = created["id"]
    original_balance = float(created["outstanding_balance"])

    response = client.post(
        f"/api/v1/debts/{debt_id}/payments",
        json=_payment_payload(amount=300.0),
        headers=user_headers,
    )

    assert response.status_code == 201
    data = response.json()
    assert float(data["outstanding_balance"]) == pytest.approx(original_balance - 300.0)


def test_payment_partial_sets_status_partial(
    client: TestClient, user_headers: dict[str, str]
) -> None:
    """A partial payment (leaves some balance remaining) sets status='partial'."""
    created = _create_debt(client, user_headers, _lent_payload(original_amount=1000.0))
    debt_id = created["id"]

    response = client.post(
        f"/api/v1/debts/{debt_id}/payments",
        json=_payment_payload(amount=400.0),
        headers=user_headers,
    )

    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "partial"
    assert float(data["outstanding_balance"]) == pytest.approx(600.0)


def test_payment_full_sets_status_settled(client: TestClient, user_headers: dict[str, str]) -> None:
    """A payment equal to outstanding_balance sets status='settled' and balance to 0."""
    created = _create_debt(client, user_headers, _lent_payload(original_amount=500.0))
    debt_id = created["id"]

    response = client.post(
        f"/api/v1/debts/{debt_id}/payments",
        json=_payment_payload(amount=500.0),
        headers=user_headers,
    )

    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "settled"
    assert float(data["outstanding_balance"]) == pytest.approx(0.0)


def test_payment_overpayment_returns_400(client: TestClient, user_headers: dict[str, str]) -> None:
    """Error path: payment_amount > outstanding_balance → 400 Bad Request."""
    created = _create_debt(client, user_headers, _lent_payload(original_amount=200.0))
    debt_id = created["id"]

    response = client.post(
        f"/api/v1/debts/{debt_id}/payments",
        json=_payment_payload(amount=999.0),
        headers=user_headers,
    )

    assert response.status_code == 400


def test_payment_debt_not_found(client: TestClient, user_headers: dict[str, str]) -> None:
    """Error path: recording payment on non-existent debt_id → 404."""
    response = client.post(
        "/api/v1/debts/no-such-debt/payments",
        json=_payment_payload(amount=50.0),
        headers=user_headers,
    )

    assert response.status_code == 404


def test_payment_invalid_amount_zero(client: TestClient, user_headers: dict[str, str]) -> None:
    """Error path: payment amount=0 violates gt=0 constraint → 422."""
    created = _create_debt(client, user_headers)
    debt_id = created["id"]

    response = client.post(
        f"/api/v1/debts/{debt_id}/payments",
        json=_payment_payload(amount=0),
        headers=user_headers,
    )

    assert response.status_code == 422


def test_payment_invalid_date_format(client: TestClient, user_headers: dict[str, str]) -> None:
    """Error path: malformed payment_date → 422 validation error."""
    created = _create_debt(client, user_headers)
    debt_id = created["id"]

    response = client.post(
        f"/api/v1/debts/{debt_id}/payments",
        json={"amount": 50.0, "payment_date": "not-a-date"},
        headers=user_headers,
    )

    assert response.status_code == 422


def test_payment_appears_in_debt_detail(client: TestClient, user_headers: dict[str, str]) -> None:
    """After recording a payment, it appears inside the payments list on GET detail."""
    created = _create_debt(client, user_headers, _lent_payload(original_amount=800.0))
    debt_id = created["id"]

    client.post(
        f"/api/v1/debts/{debt_id}/payments",
        json=_payment_payload(amount=200.0, notes="First installment"),
        headers=user_headers,
    )

    detail = client.get(f"/api/v1/debts/{debt_id}", headers=user_headers).json()
    payments = detail["payments"]

    assert len(payments) == 1
    assert float(payments[0]["amount"]) == pytest.approx(200.0)
    assert payments[0]["payment_date"] == "2026-03-16"


def test_payment_multiple_payments_accumulate(
    client: TestClient, user_headers: dict[str, str]
) -> None:
    """Three successive partial payments compound correctly on outstanding_balance."""
    created = _create_debt(client, user_headers, _lent_payload(original_amount=900.0))
    debt_id = created["id"]

    for amount in [100.0, 200.0, 300.0]:
        resp = client.post(
            f"/api/v1/debts/{debt_id}/payments",
            json=_payment_payload(amount=amount),
            headers=user_headers,
        )
        assert resp.status_code == 201

    detail = client.get(f"/api/v1/debts/{debt_id}", headers=user_headers).json()
    assert float(detail["outstanding_balance"]) == pytest.approx(300.0)
    assert len(detail["payments"]) == 3


def test_payment_balance_cannot_go_negative(
    client: TestClient, user_headers: dict[str, str]
) -> None:
    """A payment that exactly clears the balance results in outstanding_balance=0, not negative."""
    created = _create_debt(client, user_headers, _lent_payload(original_amount=350.0))
    debt_id = created["id"]

    response = client.post(
        f"/api/v1/debts/{debt_id}/payments",
        json=_payment_payload(amount=350.0),
        headers=user_headers,
    )

    assert response.status_code == 201
    data = response.json()
    assert float(data["outstanding_balance"]) == pytest.approx(0.0)
    assert float(data["outstanding_balance"]) >= 0.0


def test_payment_sequential_status_transitions(
    client: TestClient, user_headers: dict[str, str]
) -> None:
    """Status follows: active → partial → settled across two payments."""
    created = _create_debt(client, user_headers, _lent_payload(original_amount=1000.0))
    debt_id = created["id"]
    assert created["status"] == "active"

    # First partial payment: active → partial
    resp1 = client.post(
        f"/api/v1/debts/{debt_id}/payments",
        json=_payment_payload(amount=600.0),
        headers=user_headers,
    )
    assert resp1.status_code == 201
    assert resp1.json()["status"] == "partial"

    # Second payment clears remainder: partial → settled
    resp2 = client.post(
        f"/api/v1/debts/{debt_id}/payments",
        json=_payment_payload(amount=400.0),
        headers=user_headers,
    )
    assert resp2.status_code == 201
    assert resp2.json()["status"] == "settled"
    assert float(resp2.json()["outstanding_balance"]) == pytest.approx(0.0)


def test_payment_with_notes(client: TestClient, user_headers: dict[str, str]) -> None:
    """Payment notes are stored and returned in the payment record."""
    created = _create_debt(client, user_headers, _lent_payload(original_amount=500.0))
    debt_id = created["id"]

    resp = client.post(
        f"/api/v1/debts/{debt_id}/payments",
        json=_payment_payload(amount=100.0, notes="Monthly repayment #1"),
        headers=user_headers,
    )

    assert resp.status_code == 201

    detail = client.get(f"/api/v1/debts/{debt_id}", headers=user_headers).json()
    assert detail["payments"][0]["notes"] == "Monthly repayment #1"


# ===========================================================================
# Additional edge-case and coverage tests
# ===========================================================================


def test_create_multiple_debts_have_unique_ids(
    client: TestClient, user_headers: dict[str, str]
) -> None:
    """Each created debt receives a distinct id."""
    d1 = _create_debt(client, user_headers, _lent_payload(counterparty_name="Alice"))
    d2 = _create_debt(client, user_headers, _lent_payload(counterparty_name="Bob"))

    assert d1["id"] != d2["id"]


def test_list_debts_filter_settled_after_delete(
    client: TestClient, user_headers: dict[str, str]
) -> None:
    """After a soft-delete, ?status=settled returns the deleted debt."""
    created = _create_debt(client, user_headers)
    debt_id = created["id"]
    client.delete(f"/api/v1/debts/{debt_id}", headers=user_headers)

    response = client.get("/api/v1/debts?status=settled", headers=user_headers)

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == debt_id


def test_create_debt_currency_default_egp(client: TestClient, user_headers: dict[str, str]) -> None:
    """When currency is not supplied, it defaults to 'EGP'."""
    payload = {
        "debt_type": "lent",
        "counterparty_name": "Nour",
        "original_amount": 100.0,
    }
    data = _create_debt(client, user_headers, payload)

    assert data["currency"] == "EGP"


def test_create_debt_missing_debt_type(client: TestClient, user_headers: dict[str, str]) -> None:
    """Missing required debt_type → 422."""
    payload = {
        "counterparty_name": "Youssef",
        "original_amount": 200.0,
    }
    response = client.post("/api/v1/debts", json=payload, headers=user_headers)

    assert response.status_code == 422


def test_create_debt_missing_original_amount(
    client: TestClient, user_headers: dict[str, str]
) -> None:
    """Missing required original_amount → 422."""
    payload = {
        "debt_type": "borrowed",
        "counterparty_name": "Layla",
    }
    response = client.post("/api/v1/debts", json=payload, headers=user_headers)

    assert response.status_code == 422


def test_patch_debt_no_fields_is_no_op(client: TestClient, user_headers: dict[str, str]) -> None:
    """PATCH with an empty body (no updatable fields) returns 200 and leaves debt unchanged."""
    created = _create_debt(client, user_headers, _lent_payload(notes="Keep this"))
    debt_id = created["id"]

    response = client.patch(f"/api/v1/debts/{debt_id}", json={}, headers=user_headers)

    assert response.status_code == 200
    assert response.json()["notes"] == "Keep this"


def test_payment_negative_amount(client: TestClient, user_headers: dict[str, str]) -> None:
    """Error path: negative payment amount → 422."""
    created = _create_debt(client, user_headers)
    debt_id = created["id"]

    response = client.post(
        f"/api/v1/debts/{debt_id}/payments",
        json=_payment_payload(amount=-50.0),
        headers=user_headers,
    )

    assert response.status_code == 422


def test_list_debts_returns_200_with_content_type_json(
    client: TestClient, user_headers: dict[str, str]
) -> None:
    """List endpoint responds with Content-Type: application/json."""
    response = client.get("/api/v1/debts", headers=user_headers)

    assert response.status_code == 200
    assert "application/json" in response.headers["content-type"]


def test_get_debt_detail_has_expected_top_level_keys(
    client: TestClient, user_headers: dict[str, str]
) -> None:
    """Debt detail response includes all required top-level fields."""
    created = _create_debt(client, user_headers)
    debt_id = created["id"]

    data = client.get(f"/api/v1/debts/{debt_id}", headers=user_headers).json()

    required_keys = {
        "id",
        "debt_type",
        "counterparty_name",
        "original_amount",
        "outstanding_balance",
        "currency",
        "status",
        "payments",
    }
    assert required_keys.issubset(data.keys())


def test_overpayment_does_not_mutate_balance(
    client: TestClient, user_headers: dict[str, str]
) -> None:
    """A rejected overpayment (400) leaves the outstanding_balance unchanged."""
    created = _create_debt(client, user_headers, _lent_payload(original_amount=100.0))
    debt_id = created["id"]
    original_balance = float(created["outstanding_balance"])

    client.post(
        f"/api/v1/debts/{debt_id}/payments",
        json=_payment_payload(amount=999.0),
        headers=user_headers,
    )

    detail = client.get(f"/api/v1/debts/{debt_id}", headers=user_headers).json()
    assert float(detail["outstanding_balance"]) == pytest.approx(original_balance)


def test_payment_date_is_stored_correctly(client: TestClient, user_headers: dict[str, str]) -> None:
    """The payment_date supplied by the caller is stored verbatim on the record."""
    created = _create_debt(client, user_headers, _lent_payload(original_amount=300.0))
    debt_id = created["id"]

    client.post(
        f"/api/v1/debts/{debt_id}/payments",
        json={"amount": 50.0, "payment_date": "2026-01-15"},
        headers=user_headers,
    )

    detail = client.get(f"/api/v1/debts/{debt_id}", headers=user_headers).json()
    assert detail["payments"][0]["payment_date"] == "2026-01-15"


# ===========================================================================
# Cross-user isolation (IDOR prevention)
# ===========================================================================
#
# These tests verify that the in-memory _debts/_payments stores, which are
# shared module-level dicts across ALL callers, correctly isolate data by the
# verified user_id from the JWT. A user must never be able to view, list,
# modify, delete, or pay against another user's debt.


def test_list_debts_does_not_include_other_users_debts(
    client: TestClient, user_headers: dict[str, str], other_user_headers: dict[str, str]
) -> None:
    """User B's debt list must not include a debt created by user A."""
    _create_debt(client, user_headers, _lent_payload(counterparty_name="Owned by A"))
    _create_debt(client, other_user_headers, _lent_payload(counterparty_name="Owned by B"))

    response_a = client.get("/api/v1/debts", headers=user_headers)
    response_b = client.get("/api/v1/debts", headers=other_user_headers)

    assert response_a.status_code == 200
    assert response_b.status_code == 200

    names_a = {d["counterparty_name"] for d in response_a.json()}
    names_b = {d["counterparty_name"] for d in response_b.json()}

    assert names_a == {"Owned by A"}
    assert names_b == {"Owned by B"}


def test_get_other_users_debt_returns_404(
    client: TestClient, user_headers: dict[str, str], other_user_headers: dict[str, str]
) -> None:
    """Fetching a debt that belongs to a different user returns 404 (not 200 or 403)."""
    created = _create_debt(client, user_headers)
    debt_id = created["id"]

    response = client.get(f"/api/v1/debts/{debt_id}", headers=other_user_headers)

    assert response.status_code == 404


def test_patch_other_users_debt_returns_404(
    client: TestClient, user_headers: dict[str, str], other_user_headers: dict[str, str]
) -> None:
    """Patching a debt that belongs to a different user returns 404 and does not mutate it."""
    created = _create_debt(client, user_headers)
    debt_id = created["id"]

    response = client.patch(
        f"/api/v1/debts/{debt_id}",
        json={"notes": "hijacked"},
        headers=other_user_headers,
    )
    assert response.status_code == 404

    # Confirm the original owner's record is untouched.
    detail = client.get(f"/api/v1/debts/{debt_id}", headers=user_headers).json()
    assert detail["notes"] != "hijacked"


def test_delete_other_users_debt_returns_404(
    client: TestClient, user_headers: dict[str, str], other_user_headers: dict[str, str]
) -> None:
    """Deleting a debt that belongs to a different user returns 404 and does not soft-delete it."""
    created = _create_debt(client, user_headers)
    debt_id = created["id"]

    response = client.delete(f"/api/v1/debts/{debt_id}", headers=other_user_headers)
    assert response.status_code == 404

    # Confirm the original owner's record is still active (not settled).
    detail = client.get(f"/api/v1/debts/{debt_id}", headers=user_headers).json()
    assert detail["status"] == "active"


def test_create_payment_on_other_users_debt_returns_404(
    client: TestClient, user_headers: dict[str, str], other_user_headers: dict[str, str]
) -> None:
    """Recording a payment against another user's debt returns 404 and leaves balance unchanged."""
    created = _create_debt(client, user_headers, _lent_payload(original_amount=500.0))
    debt_id = created["id"]

    response = client.post(
        f"/api/v1/debts/{debt_id}/payments",
        json=_payment_payload(amount=100.0),
        headers=other_user_headers,
    )
    assert response.status_code == 404

    detail = client.get(f"/api/v1/debts/{debt_id}", headers=user_headers).json()
    assert float(detail["outstanding_balance"]) == pytest.approx(500.0)
    assert len(detail["payments"]) == 0
