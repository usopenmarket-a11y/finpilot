# FinPilot — Project Status

**Last reviewed:** 2026-03-16 (M2 complete)

---

## Milestone Progress

| # | Milestone | Status | Progress |
|---|-----------|--------|----------|
| M1 | Foundation & Project Scaffolding | COMPLETE | 100% |
| M2 | NBE & CIB Scrapers | COMPLETE | 100% |
| M3 | BDC & UB Scrapers + Pipeline | NOT STARTED | 0% |
| M4 | Analytics Engine | NOT STARTED | 0% |
| M5 | Debt Tracker (CRUD) | NOT STARTED | 0% |
| M6 | Recommendations Engine | NOT STARTED | 0% |
| M7 | Frontend Dashboard | NOT STARTED | 0% |
| M8 | Production Deploy & Monitoring | NOT STARTED | 0% |

---

## M1 Detailed Breakdown (100% — COMPLETE)

### Done
- [x] Monorepo structure (`apps/api`, `apps/web`, `packages/shared`, `turbo.json`)
- [x] FastAPI app skeleton (`main.py`, `config.py`, CORS guard, lifespan hook)
- [x] Pydantic v2 DB models: `UserProfile`, `BankAccount`, `Transaction`, `Loan`, `Debt`, `DebtPayment`
- [x] Pydantic v2 API schemas: `SignUpRequest`, `SignInRequest`, `AuthResponse`, `DebtCreate`, `DebtPaymentCreate`, `BankAccountCreate`, `PaginatedResponse`
- [x] Supabase schema: 6 tables, all with RLS enabled (`user_profiles`, `bank_accounts`, `transactions`, `loans`, `debts`, `debt_payments`)
- [x] Health endpoint (`GET /api/v1/health`) with full test coverage (8 tests)
- [x] Model unit tests (30+ tests covering all Pydantic models)
- [x] CI/CD pipeline: GitHub Actions (`ci.yml`) — frontend lint/typecheck + backend pytest + ruff/mypy
- [x] Deploy workflows: `deploy-backend.yml` (Render Git integration), `deploy-frontend.yml`
- [x] Next.js 15 frontend scaffold with Supabase auth integration
- [x] Auth pages: Login, Signup, Reset Password, OAuth callback route
- [x] Supabase client helpers: `client.ts`, `server.ts`, `middleware.ts`
- [x] Protected dashboard route (redirects unauthenticated users)
- [x] Settings config with `SecretStr` for all sensitive values (encryption key, Claude API key, service role key)
- [x] `uv` as Python package manager with `pyproject.toml`
- [x] AES-256-GCM encryption module (`app/crypto.py`) — 19 tests, 96% coverage
- [x] `cryptography>=44.0.0` added to `pyproject.toml` dependencies

### Deferred (user-action required, not blockers for M2)
- [ ] Render workspace not configured in MCP — cannot verify live backend service status
- [ ] Vercel project not linked (no `.vercel/project.json`) — cannot verify live frontend deployment

---

## M2 Detailed Breakdown (100% — COMPLETE)

### Done
- [x] `apps/api/app/scrapers/base.py` — `BankScraper` ABC, `ScraperResult` dataclass, anti-detection Playwright launch, full exception hierarchy (`ScraperLoginError`, `ScraperTimeoutError`, `ScraperParseError`, `ScraperOTPRequired`, `BankPortalUnreachableError`)
- [x] `apps/api/app/scrapers/nbe.py` — NBE (ahly-net.com) login, balance, transactions; SHA-256 external_id; column-resolver for dynamic table layouts
- [x] `apps/api/app/scrapers/cib.py` — CIB (online.cibeg.com) login, balance, transactions; SPA-aware navigation; modal dismissal
- [x] `apps/api/app/routers/scrape.py` — `POST /api/v1/scrape` endpoint; decrypts credentials, dispatches to scraper, maps exceptions to HTTP status codes
- [x] 96 scraper unit tests (all passing, Playwright fully mocked — no real browser)
- [x] Dependencies added: `playwright>=1.49.0`, `beautifulsoup4>=4.12.0`, `lxml>=5.0.0`, `pydantic[email]>=2.9.0`
- [x] Pre-existing test bug fixed: `password.get_secret_value()` assertion in `test_models.py`
- [x] All 157 backend tests passing

## Current Focus

**M2 is complete.** Moving to **M3: BDC & UB Scrapers + Pipeline**.

Next milestone entry point (M3):
- BDC scraper (`apps/api/app/scrapers/bdc.py`)
- UB scraper (`apps/api/app/scrapers/ub.py`)
- ETL pipeline (`apps/api/app/pipeline/`) — normalize, deduplicate, upsert to Supabase

---

## Blockers

| Blocker | Owner | Action Required |
|---------|-------|-----------------|
| Render MCP workspace not selected | User | Run `/review` after selecting a Render workspace, or run `mcp__render__select_workspace` |
| Vercel project not linked | User | Run `cd apps/web && vercel link` to create `.vercel/project.json` |

---

## Recent Changes

Since initial commit `6bbf1c4 feat(infra): M1 Foundation & Project Scaffolding`:

- Full monorepo scaffolded with Turbo, pnpm workspaces
- FastAPI backend with security-hardened CORS, config, and health endpoint
- Complete Pydantic v2 model layer (DB + API schemas) for all entities
- Supabase: 6-table schema deployed with RLS on all tables
- Next.js 15 frontend with Supabase auth (login, signup, password reset, OAuth callback)
- GitHub Actions CI: lint, typecheck, pytest, ruff, mypy on every push/PR
- Render + Vercel deploy workflows configured

---

## Infrastructure State

| Service | Status | Notes |
|---------|--------|-------|
| Supabase DB | LIVE | 6 tables, RLS enabled, 0 rows (fresh) |
| Render (backend) | UNKNOWN | MCP workspace not selected |
| Vercel (frontend) | UNKNOWN | Project not linked locally |
| GitHub Actions CI | CONFIGURED | Workflows exist, not verified running |
