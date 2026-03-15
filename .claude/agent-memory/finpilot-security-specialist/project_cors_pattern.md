---
name: CORS Hardening Pattern
description: Approved CORS configuration for FastAPI main.py including production guard and explicit allow-lists
type: project
---

CORS in `apps/api/app/main.py` is hardened with explicit method/header allow-lists and a startup guard.

**Why:** Wildcard `allow_methods` and `allow_headers` permit unnecessary attack surface (TRACE, CONNECT, arbitrary headers). A wildcard `allow_origins` combined with `allow_credentials=True` is a critical misconfiguration that could allow cross-origin credential theft.

**How to apply:** Any PR that modifies `main.py` CORS config must be checked against these constraints.

## Approved allow-lists (as of M1)

```python
_ALLOWED_CORS_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
_ALLOWED_CORS_HEADERS = [
    "Authorization",
    "Content-Type",
    "X-Requested-With",
    "Accept",
    "Origin",
    "X-CSRF-Token",
]
```

## Production guard

A `RuntimeError` is raised at module import time if `app_env == "production"` and `cors_origins` contains `"*"` or is empty. This prevents a misconfigured deploy from silently serving broken CORS headers.

## Docs endpoint suppression

`/docs` and `/redoc` are disabled in production (`docs_url=None`, `redoc_url=None`) to prevent leaking the internal API schema to unauthenticated users.
