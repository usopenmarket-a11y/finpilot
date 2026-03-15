---
name: M1 Foundation Security Audit
description: Summary of all vulnerabilities found and fixed during the M1 scaffolding security audit (2026-03-15)
type: project
---

M1 security audit completed on 2026-03-15. All blockers were fixed in-place.

**Why:** M1 is the foundation; security anti-patterns set here become templates for all future code.

**How to apply:** Use this as a baseline reference when reviewing future PRs that touch these files.

## Blockers Fixed

### 1. config.py — SecretStr missing on three secret fields
- `supabase_service_role_key`, `encryption_key`, `claude_api_key` were plain `str`
- Plain `str` causes Pydantic repr, FastAPI exception handlers, and Python logging to emit raw secret values
- Fix: changed all three to `SecretStr`; callers must use `.get_secret_value()` at point of use

### 2. models/api.py — Password fields as plain `str`
- `SignUpRequest.password` and `SignInRequest.password` were `str`
- Any route handler that logs the request body or raises a validation error would leak the plaintext password
- Fix: changed both to `SecretStr`; added `ConfigDict(extra="forbid")` to both auth request models to reject unexpected fields

### 3. main.py — CORS allow_methods and allow_headers wildcards
- `allow_methods=["*"]` permitted non-standard verbs (TRACE, CONNECT, etc.)
- `allow_headers=["*"]` permitted any request header
- Fix: replaced with explicit allow-lists: methods `[GET, POST, PUT, PATCH, DELETE, OPTIONS]`, headers `[Authorization, Content-Type, X-Requested-With, Accept, Origin, X-CSRF-Token]`

### 4. main.py — No production guard against wildcard CORS origin
- No check prevented `CORS_ORIGINS=["*"]` from being set in production
- Fix: added a startup `RuntimeError` if `app_env == "production"` and cors_origins contains `*` or is empty

### 5. callback/route.ts — Open redirect via request.url origin
- `origin` was derived from `new URL(request.url)` — manipulable via `X-Forwarded-Host` in reverse-proxy deployments
- Auth code exchange errors were silently swallowed; user was redirected to /dashboard with no session
- Fix: `getSafeRedirectBase()` uses `NEXT_PUBLIC_SITE_URL` (build-time constant) as authoritative base; localhost fallback for dev; error paths redirect to /auth/login with an error query param

## Warnings (not yet blocked)

### middleware.ts — Static asset redirect loop risk
- `isPublicRoute` uses strict equality `=== '/'`; paths like `/favicon.ico` will try to redirect unauthenticated requests to /auth/login
- This only causes a UX issue (404 on static assets for unauthenticated users), not a security issue
- Deferred: acceptable for M1; should be fixed when static asset routes are confirmed

## Approved Items

- CI `ENCRYPTION_KEY` value (`0000...0000`) is a dummy test value for the local Supabase mock — not a real secret leak
- GitHub Actions uses pinned SHAs (not floating tags) for all third-party actions — supply-chain safe
- Both `.env.example` files contain only placeholder strings — no real secrets
- Login form has no min-length check on password (correct — length enforcement is a signup-only concern)
- Signup form enforces min 8 characters client-side, consistent with backend `SignUpRequest` model
