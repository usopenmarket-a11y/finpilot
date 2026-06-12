---
name: project_jwt_auth_migration
description: Completed migration from spoofable x-user-id header to verified Supabase JWT auth across all apps/api/app/routers — dependency location, test fixture pattern, and remaining follow-ups
metadata:
  type: project
---

## What changed (completed across multiple sessions, finished 2026-06-13)

Every endpoint in `apps/api/app/routers/*.py` previously derived `user_id` from a
client-supplied `x-user-id` header validated only as "is this a well-formed UUID".
Combined with the backend using Supabase's **service-role key** everywhere
(bypassing RLS), `x-user-id` was the ONLY access control and was fully
attacker-controlled — a critical A01 Broken Access Control violation of
CLAUDE.md's "All API endpoints require JWT authentication" rule.

**Fix**: added `get_current_user_id(authorization: str | None = Header(default=None)) -> UUID`
in `apps/api/app/deps.py`. It validates a Supabase Auth JWT (HS256, signature
checked against `settings.supabase_jwt_secret`, `aud="authenticated"`,
`iss=f"{settings.supabase_url.rstrip('/')}/auth/v1"`, requires `exp/sub/aud/iss`
claims). Raises 401 for missing/malformed/expired/invalid tokens, and **fails
closed with 500** if `SUPABASE_JWT_SECRET` is unset (never falls back to
trusting the client).

All 9 routers (`installments`, `sync`, `scrape`, `analytics`, `recommendations`,
`utils`, `credentials`, `preferences`, `debts`) now use
`user_id: UUID = Depends(get_current_user_id)`. `app/deps.py` also exports
`get_service_role_client()` / `get_async_service_role_client()` /
`get_user_scoped_client()` / `get_bearer_token()`.

**Service-role client retained** (by design, with explicit `.eq("user_id", str(user_id))`
filters using the now-cryptographically-verified id): `analytics.py`,
`credentials.py`, `installments.py`, `preferences.py`, `scrape.py`, `sync.py`.
`debts.py` and `recommendations.py` don't touch Supabase (in-memory / stateless).

**`debts.py` IDOR fix**: previously ALL users shared one global in-memory debt
namespace under a hardcoded sentinel UUID
(`_SENTINEL_USER_ID = UUID("00000000-...-000000000001")`). Now every debt is
tagged with the verified `user_id` at creation, and `_get_debt_or_404(debt_id, user_id)`
returns the **same 404** whether the debt doesn't exist or belongs to another
user (prevents existence-enumeration). This "indistinguishable 404" pattern is
the standard for any future per-user resource lookup in this codebase.

**CORS**: removed `"X-User-Id"` from `_ALLOWED_CORS_HEADERS` in `apps/api/app/main.py`
(line ~47-56) now that no router reads that header. `"Authorization"` was already
present.

**Env vars**: `SUPABASE_JWT_SECRET` added as `SecretStr` in `app/config.py` and
documented in `.env.example`. Get the real value from Supabase project settings
→ API → JWT Secret (legacy HS256 secret, not the new asymmetric JWT signing keys).

## Test fixture pattern (apps/api/app/tests/conftest.py)

Reusable JWT test fixtures added to conftest, available to every test file:

- `supabase_jwt_test_config(monkeypatch)` — monkeypatches
  `settings.supabase_jwt_secret = SecretStr(TEST_JWT_SECRET)` and
  `settings.supabase_url = TEST_SUPABASE_URL`. Works even for routers mounted
  in standalone "mini-apps" (e.g. `test_recommendations.py`'s
  `_build_recommendations_app()`, `test_preferences.py`'s ad-hoc `FastAPI()`)
  because `get_current_user_id` reads `settings` lazily at request time, not
  at decoration/import time.
- `make_access_token(supabase_jwt_test_config)` — factory `_make(user_id=None, *, expires_in=3600, **extra_claims) -> str`,
  signs an HS256 token matching everything `get_current_user_id` checks.
- `auth_headers(make_access_token)` — factory `_make(user_id=None, **kwargs) -> dict[str, str]`
  returning `{"Authorization": f"Bearer {token}"}`.

**Gotcha**: tests asserting "malformed bearer token → 401" (as opposed to
"missing header → 401") must ALSO depend on `supabase_jwt_test_config` even if
they don't call `auth_headers`/`make_access_token` — otherwise
`SUPABASE_JWT_SECRET` is empty in the test env and `get_current_user_id` returns
500 (fail-closed misconfiguration) before it ever reaches the JWT-decode step
that would produce 401. Pattern: `def test_x(client, supabase_jwt_test_config: None) -> None`.

## Remaining follow-up (NOT YET DONE — frontend, read-only for this agent)

Frontend (`apps/web`, owned by finpilot-frontend-dev) still sends `x-user-id`
and needs to switch to `Authorization: Bearer <supabase_session_access_token>`
via `supabase.auth.getSession()`:
- `apps/web/src/lib/api-client.ts` (~349 lines) — `apiFetch` helper and all
  exported functions
- `apps/web/src/components/installments/installments-client.tsx` — lines
  ~424/433/454 set `'x-user-id': userId` directly, bypassing api-client.ts

## Pre-existing unrelated issue discovered during verification

`apps/api/app/tests/test_scrapers.py` (115 tests) hangs/takes >90s when run as
part of the full suite or alone — NOT caused by this migration (file untouched,
git diff confirms). Likely real `asyncio.sleep` anti-detection delays summed
across many tests, or an unmocked network call. Owned by bank-scraper agent.
All other 285 tests (`test_analytics`, `test_crypto`, `test_debts`, `test_health`,
`test_models`, `test_pipeline`, `test_preferences`, `test_recommendations`,
`test_credentials`) pass in ~3.7s total.
