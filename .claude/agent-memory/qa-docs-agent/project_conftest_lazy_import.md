---
name: conftest.py uses lazy app import to avoid startup failures
description: The app/tests/conftest.py defers `from app.main import app` inside the `client` fixture so broken router imports don't block pure-unit test collection
type: project
---

`app/tests/conftest.py` was updated to import `app.main` inside the `client` fixture body rather than at module level.

**Why:** `app/routers/analytics.py` has a stale `compute_trend_report` import that causes `ImportError` at module load time. With a top-level import in conftest, the entire test suite fails to collect. Moving the import inside the fixture means only tests that request `client` fail — pure unit tests (analytics, models, pipeline, crypto) run normally.

**How to apply:** Keep `from app.main import app` deferred in conftest. Once the router bug is fixed by the Backend Agent, the import can be moved back to module level if desired, but the deferred pattern is a safer long-term convention.
