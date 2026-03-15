---
name: Health endpoint contract
description: Verified shape and routing of the /api/v1/health endpoint
type: project
---

Endpoint: `GET /api/v1/health`
Router file: `apps/api/app/routers/health.py`
Mounted at: `app.include_router(health.router, prefix="/api/v1")` in `main.py`

Response model: `HealthResponse(status: str, version: str)`
Current response: `{"status": "ok", "version": "0.1.0"}`

The router has `tags=["health"]` and no authentication requirement.
`POST /api/v1/health` returns 405 (Method Not Allowed) — FastAPI default.

**How to apply:** Any future health-check tests should target `/api/v1/health` and assert
both `status == "ok"` and `version == "0.1.0"`.  If the version bumps, update
`test_health_check_version_value` in `test_health.py`.
