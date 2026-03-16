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

Security contract:
  - Fake counterparty data only; no real PII.
  - No network I/O; no external services.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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


def _create_debt(client: TestClient, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Create a debt and return the parsed response body."""
    if payload is None:
        payload = _lent_payload()
    response = client.post("/api/v1/debts", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


# ===========================================================================
# POST /api/v1/debts
# ===========================================================================


def test_create_debt_lent(client: TestClient) -> None:
    """Happy path: create a 'lent' debt returns 201 with correct fields."""
    response = client.post("/api/v1/debts", json=_lent_payload())

    assert response.status_code == 201
    data = response.json()
    assert data["debt_type"] == "lent"
    assert data["counterparty_name"] == "Ahmed Hassan"
    assert float(data["original_amount"]) == pytest.approx(1000.0)


def test_create_debt_borrowed(client: TestClient) -> None:
    """Happy path: create a 'borrowed' debt returns 201 with debt_type='borrowed'."""
    response = client.post("/api/v1/debts", json=_borrowed_payload())

    assert response.status_code == 201
    data = response.json()
    assert data["debt_type"] == "borrowed"
    assert data["counterparty_name"] == "Sara Mahmoud"


def test_create_debt_with_all_fields(client: TestClient) -> None:
    """Happy path: creating a debt with all optional fields stores them correctly."""
    response = client.post("/api/v1/debts", json=_full_lent_payload())

    assert response.status_code == 201
    data = response.json()
    assert data["counterparty_phone"] == "+201001234567"
    assert data["counterparty_email"] == "m.ali@example.com"
    assert data["due_date"] == "2026-06-30"
    assert data["notes"] == "School fees loan"
    assert data["currency"] == "EGP"


def test_create_debt_invalid_type(client: TestClient) -> None:
    """Error path: unknown debt_type value → 422 validation error."""
    response = client.post("/api/v1/debts", json=_lent_payload(debt_type="gifted"))

    assert response.status_code == 422


def test_create_debt_zero_amount(client: TestClient) -> None:
    """Error path: original_amount=0 violates gt=0 constraint → 422."""
    response = client.post("/api/v1/debts", json=_lent_payload(original_amount=0))

    assert response.status_code == 422


def test_create_debt_negative_amount(client: TestClient) -> None:
    """Error path: negative original_amount violates gt=0 constraint → 422."""
    response = client.post("/api/v1/debts", json=_lent_payload(original_amount=-100.0))

    assert response.status_code == 422


def test_create_debt_missing_counterparty(client: TestClient) -> None:
    """Error path: missing required counterparty_name → 422."""
    payload = {
        "debt_type": "lent",
        "original_amount": 500.0,
    }
    response = client.post("/api/v1/debts", json=payload)

    assert response.status_code == 422


def test_create_debt_extra_field_forbidden(client: TestClient) -> None:
    """Error path: extra unknown field in body → 422 (extra='forbid' on schema)."""
    response = client.post(
        "/api/v1/debts",
        json={**_lent_payload(), "surprise_field": "unexpected"},
    )

    assert response.status_code == 422


def test_create_debt_default_status_active(client: TestClient) -> None:
    """New debts start with status='active' by default."""
    data = _create_debt(client)

    assert data["status"] == "active"


def test_create_debt_outstanding_equals_original(client: TestClient) -> None:
    """At creation, outstanding_balance must equal original_amount."""
    data = _create_debt(client, _lent_payload(original_amount=750.0))

    assert float(data["outstanding_balance"]) == pytest.approx(float(data["original_amount"]))


def test_create_debt_returns_id(client: TestClient) -> None:
    """Created debt response includes a non-empty 'id' field."""
    data = _create_debt(client)

    assert "id" in data
    assert data["id"]


# ===========================================================================
# GET /api/v1/debts
# ===========================================================================


def test_list_debts_empty(client: TestClient) -> None:
    """With no debts created, list endpoint returns an empty array."""
    response = client.get("/api/v1/debts")

    assert response.status_code == 200
    assert response.json() == []


def test_list_debts_returns_created(client: TestClient) -> None:
    """Creating two debts then listing returns both."""
    _create_debt(client, _lent_payload(counterparty_name="Person A"))
    _create_debt(client, _borrowed_payload(counterparty_name="Person B"))

    response = client.get("/api/v1/debts")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    names = {d["counterparty_name"] for d in data}
    assert names == {"Person A", "Person B"}


def test_list_debts_filter_by_status(client: TestClient) -> None:
    """?status=active returns only active debts."""
    _create_debt(client, _lent_payload())
    _create_debt(client, _borrowed_payload())

    response = client.get("/api/v1/debts?status=active")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert all(d["status"] == "active" for d in data)


def test_list_debts_filter_by_debt_type(client: TestClient) -> None:
    """?debt_type=lent returns only lent debts."""
    _create_debt(client, _lent_payload(counterparty_name="Lent Guy"))
    _create_debt(client, _borrowed_payload(counterparty_name="Borrowed Gal"))

    response = client.get("/api/v1/debts?debt_type=lent")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["debt_type"] == "lent"
    assert data[0]["counterparty_name"] == "Lent Guy"


def test_list_debts_filter_combined(client: TestClient) -> None:
    """?status=active&debt_type=borrowed returns only active+borrowed debts."""
    _create_debt(client, _lent_payload())
    _create_debt(client, _borrowed_payload())

    response = client.get("/api/v1/debts?status=active&debt_type=borrowed")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["debt_type"] == "borrowed"
    assert data[0]["status"] == "active"


def test_list_debts_filter_no_matches(client: TestClient) -> None:
    """Filter that matches nothing returns an empty array (not 404)."""
    _create_debt(client, _lent_payload())

    response = client.get("/api/v1/debts?status=settled")

    assert response.status_code == 200
    assert response.json() == []


# ===========================================================================
# GET /api/v1/debts/{debt_id}
# ===========================================================================


def test_get_debt_found(client: TestClient) -> None:
    """Happy path: creating a debt then fetching by id returns the same debt."""
    created = _create_debt(client)
    debt_id = created["id"]

    response = client.get(f"/api/v1/debts/{debt_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == debt_id
    assert data["counterparty_name"] == created["counterparty_name"]


def test_get_debt_not_found(client: TestClient) -> None:
    """Error path: fetching a non-existent debt_id → 404."""
    response = client.get("/api/v1/debts/nonexistent-id-12345")

    assert response.status_code == 404


def test_get_debt_includes_payments(client: TestClient) -> None:
    """Debt detail endpoint includes a 'payments' list; after one payment it has one entry."""
    created = _create_debt(client, _lent_payload(original_amount=500.0))
    debt_id = created["id"]

    pay_resp = client.post(
        f"/api/v1/debts/{debt_id}/payments",
        json=_payment_payload(amount=100.0),
    )
    assert pay_resp.status_code == 201

    response = client.get(f"/api/v1/debts/{debt_id}")

    assert response.status_code == 200
    data = response.json()
    assert "payments" in data
    assert len(data["payments"]) == 1


# ===========================================================================
# PATCH /api/v1/debts/{debt_id}
# ===========================================================================


def test_patch_debt_notes(client: TestClient) -> None:
    """Happy path: updating 'notes' reflects in the returned response."""
    created = _create_debt(client)
    debt_id = created["id"]

    response = client.patch(
        f"/api/v1/debts/{debt_id}",
        json={"notes": "Updated note text"},
    )

    assert response.status_code == 200
    assert response.json()["notes"] == "Updated note text"


def test_patch_debt_phone(client: TestClient) -> None:
    """Happy path: updating 'counterparty_phone' is persisted."""
    created = _create_debt(client)
    debt_id = created["id"]

    response = client.patch(
        f"/api/v1/debts/{debt_id}",
        json={"counterparty_phone": "+20109876543"},
    )

    assert response.status_code == 200
    assert response.json()["counterparty_phone"] == "+20109876543"


def test_patch_debt_due_date(client: TestClient) -> None:
    """Happy path: updating 'due_date' is persisted."""
    created = _create_debt(client)
    debt_id = created["id"]

    response = client.patch(
        f"/api/v1/debts/{debt_id}",
        json={"due_date": "2026-12-31"},
    )

    assert response.status_code == 200
    assert response.json()["due_date"] == "2026-12-31"


def test_patch_debt_status(client: TestClient) -> None:
    """Happy path: updating 'status' directly is reflected in the response."""
    created = _create_debt(client)
    debt_id = created["id"]

    response = client.patch(
        f"/api/v1/debts/{debt_id}",
        json={"status": "partial"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "partial"


def test_patch_debt_not_found(client: TestClient) -> None:
    """Error path: patching a non-existent debt_id → 404."""
    response = client.patch(
        "/api/v1/debts/does-not-exist",
        json={"notes": "irrelevant"},
    )

    assert response.status_code == 404


def test_patch_debt_partial_update(client: TestClient) -> None:
    """Partial update: only the supplied field changes; all others remain as created."""
    created = _create_debt(
        client,
        _full_lent_payload(notes="Original note", counterparty_phone="+201110000001"),
    )
    debt_id = created["id"]

    response = client.patch(f"/api/v1/debts/{debt_id}", json={"notes": "Changed note"})

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


def test_delete_debt_returns_204(client: TestClient) -> None:
    """Happy path: deleting an existing debt returns HTTP 204 No Content."""
    created = _create_debt(client)
    debt_id = created["id"]

    response = client.delete(f"/api/v1/debts/{debt_id}")

    assert response.status_code == 204


def test_delete_debt_sets_settled(client: TestClient) -> None:
    """After a soft-delete, GET on the debt shows status='settled'."""
    created = _create_debt(client)
    debt_id = created["id"]

    client.delete(f"/api/v1/debts/{debt_id}")

    get_response = client.get(f"/api/v1/debts/{debt_id}")
    assert get_response.status_code == 200
    assert get_response.json()["status"] == "settled"


def test_delete_debt_not_found(client: TestClient) -> None:
    """Error path: deleting a non-existent debt_id → 404."""
    response = client.delete("/api/v1/debts/ghost-id-99999")

    assert response.status_code == 404


# ===========================================================================
# POST /api/v1/debts/{debt_id}/payments
# ===========================================================================


def test_payment_reduces_balance(client: TestClient) -> None:
    """Recording a payment reduces outstanding_balance by the payment amount."""
    created = _create_debt(client, _lent_payload(original_amount=1000.0))
    debt_id = created["id"]
    original_balance = float(created["outstanding_balance"])

    response = client.post(
        f"/api/v1/debts/{debt_id}/payments",
        json=_payment_payload(amount=300.0),
    )

    assert response.status_code == 201
    data = response.json()
    assert float(data["outstanding_balance"]) == pytest.approx(original_balance - 300.0)


def test_payment_partial_sets_status_partial(client: TestClient) -> None:
    """A partial payment (leaves some balance remaining) sets status='partial'."""
    created = _create_debt(client, _lent_payload(original_amount=1000.0))
    debt_id = created["id"]

    response = client.post(
        f"/api/v1/debts/{debt_id}/payments",
        json=_payment_payload(amount=400.0),
    )

    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "partial"
    assert float(data["outstanding_balance"]) == pytest.approx(600.0)


def test_payment_full_sets_status_settled(client: TestClient) -> None:
    """A payment equal to outstanding_balance sets status='settled' and balance to 0."""
    created = _create_debt(client, _lent_payload(original_amount=500.0))
    debt_id = created["id"]

    response = client.post(
        f"/api/v1/debts/{debt_id}/payments",
        json=_payment_payload(amount=500.0),
    )

    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "settled"
    assert float(data["outstanding_balance"]) == pytest.approx(0.0)


def test_payment_overpayment_returns_400(client: TestClient) -> None:
    """Error path: payment_amount > outstanding_balance → 400 Bad Request."""
    created = _create_debt(client, _lent_payload(original_amount=200.0))
    debt_id = created["id"]

    response = client.post(
        f"/api/v1/debts/{debt_id}/payments",
        json=_payment_payload(amount=999.0),
    )

    assert response.status_code == 400


def test_payment_debt_not_found(client: TestClient) -> None:
    """Error path: recording payment on non-existent debt_id → 404."""
    response = client.post(
        "/api/v1/debts/no-such-debt/payments",
        json=_payment_payload(amount=50.0),
    )

    assert response.status_code == 404


def test_payment_invalid_amount_zero(client: TestClient) -> None:
    """Error path: payment amount=0 violates gt=0 constraint → 422."""
    created = _create_debt(client)
    debt_id = created["id"]

    response = client.post(
        f"/api/v1/debts/{debt_id}/payments",
        json=_payment_payload(amount=0),
    )

    assert response.status_code == 422


def test_payment_invalid_date_format(client: TestClient) -> None:
    """Error path: malformed payment_date → 422 validation error."""
    created = _create_debt(client)
    debt_id = created["id"]

    response = client.post(
        f"/api/v1/debts/{debt_id}/payments",
        json={"amount": 50.0, "payment_date": "not-a-date"},
    )

    assert response.status_code == 422


def test_payment_appears_in_debt_detail(client: TestClient) -> None:
    """After recording a payment, it appears inside the payments list on GET detail."""
    created = _create_debt(client, _lent_payload(original_amount=800.0))
    debt_id = created["id"]

    client.post(
        f"/api/v1/debts/{debt_id}/payments",
        json=_payment_payload(amount=200.0, notes="First installment"),
    )

    detail = client.get(f"/api/v1/debts/{debt_id}").json()
    payments = detail["payments"]

    assert len(payments) == 1
    assert float(payments[0]["amount"]) == pytest.approx(200.0)
    assert payments[0]["payment_date"] == "2026-03-16"


def test_payment_multiple_payments_accumulate(client: TestClient) -> None:
    """Three successive partial payments compound correctly on outstanding_balance."""
    created = _create_debt(client, _lent_payload(original_amount=900.0))
    debt_id = created["id"]

    for amount in [100.0, 200.0, 300.0]:
        resp = client.post(
            f"/api/v1/debts/{debt_id}/payments",
            json=_payment_payload(amount=amount),
        )
        assert resp.status_code == 201

    detail = client.get(f"/api/v1/debts/{debt_id}").json()
    assert float(detail["outstanding_balance"]) == pytest.approx(300.0)
    assert len(detail["payments"]) == 3


def test_payment_balance_cannot_go_negative(client: TestClient) -> None:
    """A payment that exactly clears the balance results in outstanding_balance=0, not negative."""
    created = _create_debt(client, _lent_payload(original_amount=350.0))
    debt_id = created["id"]

    response = client.post(
        f"/api/v1/debts/{debt_id}/payments",
        json=_payment_payload(amount=350.0),
    )

    assert response.status_code == 201
    data = response.json()
    assert float(data["outstanding_balance"]) == pytest.approx(0.0)
    assert float(data["outstanding_balance"]) >= 0.0


def test_payment_sequential_status_transitions(client: TestClient) -> None:
    """Status follows: active → partial → settled across two payments."""
    created = _create_debt(client, _lent_payload(original_amount=1000.0))
    debt_id = created["id"]
    assert created["status"] == "active"

    # First partial payment: active → partial
    resp1 = client.post(
        f"/api/v1/debts/{debt_id}/payments",
        json=_payment_payload(amount=600.0),
    )
    assert resp1.status_code == 201
    assert resp1.json()["status"] == "partial"

    # Second payment clears remainder: partial → settled
    resp2 = client.post(
        f"/api/v1/debts/{debt_id}/payments",
        json=_payment_payload(amount=400.0),
    )
    assert resp2.status_code == 201
    assert resp2.json()["status"] == "settled"
    assert float(resp2.json()["outstanding_balance"]) == pytest.approx(0.0)


def test_payment_with_notes(client: TestClient) -> None:
    """Payment notes are stored and returned in the payment record."""
    created = _create_debt(client, _lent_payload(original_amount=500.0))
    debt_id = created["id"]

    resp = client.post(
        f"/api/v1/debts/{debt_id}/payments",
        json=_payment_payload(amount=100.0, notes="Monthly repayment #1"),
    )

    assert resp.status_code == 201

    detail = client.get(f"/api/v1/debts/{debt_id}").json()
    assert detail["payments"][0]["notes"] == "Monthly repayment #1"


# ===========================================================================
# Additional edge-case and coverage tests
# ===========================================================================


def test_create_multiple_debts_have_unique_ids(client: TestClient) -> None:
    """Each created debt receives a distinct id."""
    d1 = _create_debt(client, _lent_payload(counterparty_name="Alice"))
    d2 = _create_debt(client, _lent_payload(counterparty_name="Bob"))

    assert d1["id"] != d2["id"]


def test_list_debts_filter_settled_after_delete(client: TestClient) -> None:
    """After a soft-delete, ?status=settled returns the deleted debt."""
    created = _create_debt(client)
    debt_id = created["id"]
    client.delete(f"/api/v1/debts/{debt_id}")

    response = client.get("/api/v1/debts?status=settled")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == debt_id


def test_create_debt_currency_default_egp(client: TestClient) -> None:
    """When currency is not supplied, it defaults to 'EGP'."""
    payload = {
        "debt_type": "lent",
        "counterparty_name": "Nour",
        "original_amount": 100.0,
    }
    data = _create_debt(client, payload)

    assert data["currency"] == "EGP"


def test_create_debt_missing_debt_type(client: TestClient) -> None:
    """Missing required debt_type → 422."""
    payload = {
        "counterparty_name": "Youssef",
        "original_amount": 200.0,
    }
    response = client.post("/api/v1/debts", json=payload)

    assert response.status_code == 422


def test_create_debt_missing_original_amount(client: TestClient) -> None:
    """Missing required original_amount → 422."""
    payload = {
        "debt_type": "borrowed",
        "counterparty_name": "Layla",
    }
    response = client.post("/api/v1/debts", json=payload)

    assert response.status_code == 422


def test_patch_debt_no_fields_is_no_op(client: TestClient) -> None:
    """PATCH with an empty body (no updatable fields) returns 200 and leaves debt unchanged."""
    created = _create_debt(client, _lent_payload(notes="Keep this"))
    debt_id = created["id"]

    response = client.patch(f"/api/v1/debts/{debt_id}", json={})

    assert response.status_code == 200
    assert response.json()["notes"] == "Keep this"


def test_payment_negative_amount(client: TestClient) -> None:
    """Error path: negative payment amount → 422."""
    created = _create_debt(client)
    debt_id = created["id"]

    response = client.post(
        f"/api/v1/debts/{debt_id}/payments",
        json=_payment_payload(amount=-50.0),
    )

    assert response.status_code == 422


def test_list_debts_returns_200_with_content_type_json(client: TestClient) -> None:
    """List endpoint responds with Content-Type: application/json."""
    response = client.get("/api/v1/debts")

    assert response.status_code == 200
    assert "application/json" in response.headers["content-type"]


def test_get_debt_detail_has_expected_top_level_keys(client: TestClient) -> None:
    """Debt detail response includes all required top-level fields."""
    created = _create_debt(client)
    debt_id = created["id"]

    data = client.get(f"/api/v1/debts/{debt_id}").json()

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


def test_overpayment_does_not_mutate_balance(client: TestClient) -> None:
    """A rejected overpayment (400) leaves the outstanding_balance unchanged."""
    created = _create_debt(client, _lent_payload(original_amount=100.0))
    debt_id = created["id"]
    original_balance = float(created["outstanding_balance"])

    client.post(
        f"/api/v1/debts/{debt_id}/payments",
        json=_payment_payload(amount=999.0),
    )

    detail = client.get(f"/api/v1/debts/{debt_id}").json()
    assert float(detail["outstanding_balance"]) == pytest.approx(original_balance)


def test_payment_date_is_stored_correctly(client: TestClient) -> None:
    """The payment_date supplied by the caller is stored verbatim on the record."""
    created = _create_debt(client, _lent_payload(original_amount=300.0))
    debt_id = created["id"]

    client.post(
        f"/api/v1/debts/{debt_id}/payments",
        json={"amount": 50.0, "payment_date": "2026-01-15"},
    )

    detail = client.get(f"/api/v1/debts/{debt_id}").json()
    assert detail["payments"][0]["payment_date"] == "2026-01-15"
