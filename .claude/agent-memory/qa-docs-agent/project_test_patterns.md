---
name: FinPilot API test patterns
description: Established conventions for the pytest suite in apps/api/app/tests/ — async mode, client fixtures, teardown, and router test structure
type: project
---

The test suite lives at `apps/api/app/tests/`. pytest config is in `pyproject.toml` at `apps/api/`.

**Why:** Document patterns so future test files stay consistent and do not duplicate fixture mistakes.
**How to apply:** Follow every convention below when writing new test files for this project.

## pytest config
- `asyncio_mode = "auto"` — ALL async test functions run as asyncio automatically; do NOT add `@pytest.mark.asyncio`.
- `testpaths = ["app/tests"]`
- `fail_under = 50` (coverage threshold; aim for 80%+ on new code per project rule)

## Client fixture — two patterns coexist

### conftest.py (shared, async)
- `client` fixture at module level is `httpx.AsyncClient` with `ASGITransport`.
- Used for: routes that do real async I/O (scrapers, analytics, etc.).
- Scope: function-level (default).

### Debt router tests (sync TestClient)
- Debt router uses in-memory storage with no async I/O.
- Uses `fastapi.testclient.TestClient` in a **module-scoped** fixture defined locally in `test_debts.py`.
- Do NOT use the conftest `client` fixture for sync router tests — the two fixtures have the same name, so the local one shadows the conftest one.

## State isolation (in-memory storage routers)
- Pattern: `@pytest.fixture(autouse=True)` that imports and calls `clear_storage()` from the router before every test.
- Each router that uses in-memory storage must export `clear_storage()`.

## Import style
- Deferred local imports inside tests (`from app.routers.debts import clear_storage`) to keep the module importable even when the target router hasn't been written yet — same lazy-import philosophy as conftest.

## Helper factories
- Module-level `_payload(**overrides)` functions return `dict[str, Any]` with sensible defaults.
- `_create_debt(client, payload)` helper wraps POST + asserts 201 so tests focus on their actual assertion.
- Monetary comparisons: use `pytest.approx()` on `float(data["field"])` — response JSON floats may differ from Decimal representations.

## Test naming
- All test functions are top-level (not inside classes) for router integration tests.
- Classes are acceptable for pure unit tests (see test_analytics.py).
