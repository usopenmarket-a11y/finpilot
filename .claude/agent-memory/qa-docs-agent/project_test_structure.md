---
name: M1 test scaffolding structure
description: Established test file layout, conftest fixture, and pyproject.toml config for the API test suite
type: project
---

Tests live at `apps/api/app/tests/` (not `apps/api/tests/`).

The `conftest.py` at that path provides a single `client` fixture using
`httpx.AsyncClient` with `ASGITransport(app=app)` and `base_url="http://test"`.
It already exists and matches the required pattern — do not recreate it.

`pyproject.toml` (`apps/api/pyproject.toml`) has `testpaths = ["app/tests"]` (corrected
from the original `["tests"]`).  `asyncio_mode = "auto"` is set, so `@pytest.mark.asyncio`
decorators on individual tests are redundant but harmless.

Coverage config block added:
- `[tool.coverage.run]` source = `["app"]`, omit tests and migrations
- `[tool.coverage.report]` show_missing = true, fail_under = 50

**Why:** The original `testpaths = ["tests"]` would have caused pytest to not find
any tests when run from `apps/api/`.

**How to apply:** When adding new test files, always place them under `apps/api/app/tests/`
and mirror the source path (e.g. `apps/api/app/scrapers/nbe.py` →
`apps/api/app/tests/test_nbe.py`).
