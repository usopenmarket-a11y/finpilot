---
name: M5 Debt Tracker router contract
description: Settlement logic, schema constraints, and 404/400 edge cases for the debts router — reference for test coverage decisions
type: project
---

Router to be written at `app/routers/debts.py`. Test file written at `app/tests/test_debts.py`.

**Why:** Record the contract so future changes to the router are immediately recognisable as breaking changes against the tests.
**How to apply:** When the router is implemented by another agent, verify the implementation matches this contract before marking tests green.

## Endpoints
- `POST   /api/v1/debts`           → 201
- `GET    /api/v1/debts`           → 200, supports `?status=` and `?debt_type=` query filters
- `GET    /api/v1/debts/{debt_id}` → 200, includes `payments` list
- `PATCH  /api/v1/debts/{debt_id}` → 200, partial update
- `DELETE /api/v1/debts/{debt_id}` → 204, soft-delete sets status="settled"
- `POST   /api/v1/debts/{debt_id}/payments` → 201

## Settlement logic (payments)
- outstanding_balance -= payment_amount
- if outstanding_balance <= 0: status="settled", outstanding_balance=0
- elif outstanding_balance < original_amount: status="partial"
- else: status="active"

## Required exports from router
- `clear_storage()` — resets in-memory store; called by autouse fixture in tests

## Schema constraints
- `debt_type` must be "lent" | "borrowed" (422 otherwise)
- `original_amount` must be > 0 (422 for 0 or negative)
- `counterparty_name` is required (422 if missing)
- `DebtCreate` has `extra="forbid"` (422 on unknown fields)
- `payment.amount` must be > 0 (422 for 0 or negative)
- `payment.payment_date` must be valid "YYYY-MM-DD" (422 otherwise)
- Payment amount > outstanding_balance → 400 (not 422)

## Default values
- `status` defaults to "active" at creation
- `outstanding_balance` starts equal to `original_amount`
- `currency` defaults to "EGP"
