# FinPilot — Project Status

**Last reviewed:** 2026-03-16 (M4 complete)

---

## Milestone Progress

| # | Milestone | Status | Progress |
|---|-----------|--------|----------|
| M1 | Foundation & Project Scaffolding | COMPLETE | 100% |
| M2 | NBE & CIB Scrapers | COMPLETE | 100% |
| M3 | BDC & UB Scrapers + Pipeline | COMPLETE | 100% |
| M4 | Analytics Engine | COMPLETE | 100% |
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
- [x] Supabase schema: 6 tables, all with RLS enabled (`user_profiles`, `bank_accounts`, `transactions`, `loans`, `debts`, `debt_payments`) — **verified LIVE**
- [x] Health endpoint (`GET /api/v1/health`) with full test coverage (8 tests)
- [x] Model unit tests (30+ tests covering all Pydantic models)
- [x] CI/CD pipeline: GitHub Actions (`ci.yml`) — frontend lint/typecheck + backend pytest + ruff/mypy
- [x] Deploy workflows: `deploy-backend.yml` (Render Git integration), `deploy-frontend.yml`
- [x] Next.js 15 frontend scaffold with Supabase auth integration
- [x] Auth pages: Login, Signup, Reset Password, OAuth callback route
- [x] Supabase client helpers: `client.ts`, `server.ts`, `middleware.ts`
- [x] Protected dashboard route (redirects unauthenticated users)
- [x] Settings config with `SecretStr` for all sensitive values
- [x] `uv` as Python package manager with `pyproject.toml`
- [x] AES-256-GCM encryption module (`app/crypto.py`) — 19 tests, 96% coverage
- [x] `cryptography>=44.0.0` in `pyproject.toml`

### Deferred (user-action required)
- [ ] Render MCP workspace not selected — cannot verify live backend service status
- [ ] Vercel project not linked locally — cannot verify live frontend deployment

---

## M2 Detailed Breakdown (100% — COMPLETE)

### Done
- [x] `apps/api/app/scrapers/base.py` — `BankScraper` ABC, `ScraperResult`, anti-detection Playwright, full exception hierarchy
- [x] `apps/api/app/scrapers/nbe.py` — NBE login, balance, transactions; SHA-256 external_id; column-resolver
- [x] `apps/api/app/scrapers/cib.py` — CIB login, balance, transactions; SPA-aware; modal dismissal
- [x] `apps/api/app/routers/scrape.py` — `POST /api/v1/scrape`; decrypts credentials; maps exceptions to HTTP codes
- [x] 96 scraper unit tests (Playwright fully mocked)
- [x] Dependencies: `playwright>=1.49.0`, `beautifulsoup4>=4.12.0`, `lxml>=5.0.0`, `pydantic[email]>=2.9.0`

---

## M3 Detailed Breakdown (100% — COMPLETE)

### Done
- [x] `apps/api/app/scrapers/bdc.py` — BDC login, balance, transactions; Arabic column headers; Arabic currency stripping
- [x] `apps/api/app/scrapers/ub.py` — UB login, balance, transactions; Dr/Cr single-amount layout; SPA-aware
- [x] `apps/api/app/routers/scrape.py` — now supports all 4 banks (NBE, CIB, BDC, UB)
- [x] `apps/api/app/pipeline/normalizer.py` — currency/type normalization, UTC timestamps
- [x] `apps/api/app/pipeline/deduplicator.py` — dedup on `(account_id, external_id)`
- [x] `apps/api/app/pipeline/upserter.py` — upsert accounts + bulk insert with ON CONFLICT DO NOTHING
- [x] `apps/api/app/pipeline/runner.py` — 6-stage ETL orchestrator → `PipelineRunResult`
- [x] 164 new tests (143 BDC/UB scraper + 21 pipeline) — **321 total passing**
- [x] `supabase>=2.0.0` in `pyproject.toml`

---

## M4 Detailed Breakdown (100% — COMPLETE)

### Done
- [x] `apps/api/app/analytics/categorizer.py` — rule-based + Claude Haiku 4.5 AI categorization; graceful degradation when API key absent; `categorize_batch` with `asyncio.Semaphore` concurrency control
- [x] `apps/api/app/analytics/spending.py` — `compute_spending_breakdown`: debit/credit split, by-category grouping, percentages, period filtering
- [x] `apps/api/app/analytics/trends.py` — `compute_trends`: monthly snapshots, MoM % change, rolling averages, lookback window
- [x] `apps/api/app/analytics/credit.py` — `compute_credit_report`: utilization % with healthy/warning/critical thresholds, loan months_remaining
- [x] `apps/api/app/routers/analytics.py` — 4 endpoints: `POST /api/v1/analytics/categorize`, `/spending`, `/trends`, `/credit`; all with `extra="forbid"`, no PII in logs
- [x] 46 analytics unit tests (all passing)
- [x] `anthropic>=0.40.0` added to `pyproject.toml`
- [x] Fixed broken import `compute_trend_report` → `compute_trends` in router

## Current Focus

**M4 is complete. Next: M5 — Debt Tracker CRUD.**

### M5 entry points
- `apps/api/app/routers/debts.py` — full CRUD for debts + payments
- Endpoints: `POST/GET/PATCH/DELETE /api/v1/debts`, `POST /api/v1/debts/{id}/payments`
- Settlement flow: auto-update debt status (active → partial → settled)
- Uses existing `Debt`, `DebtPayment` DB models and `DebtCreate`, `DebtPaymentCreate` API schemas

---

## Blockers

| Blocker | Owner | Action Required |
|---------|-------|-----------------|
| Render MCP workspace not selected | User | Select a Render workspace so the devops agent can monitor the backend service |
| Vercel project not linked | User | Run `cd apps/web && vercel link` to enable MCP frontend status checks |
| `CLAUDE_API_KEY` not set | User | Required for M4 analytics categorization (Claude Haiku 4.5) — add to `apps/api/.env` and Render env vars |

---

## Recent Changes (since last review)

| Commit | Description |
|--------|-------------|
| `0b3f26a` | M3: BDC & UB scrapers + full ETL pipeline (normalizer, deduplicator, upserter, runner) |
| `994ee89` | M2: NBE & CIB scrapers + `POST /api/v1/scrape` endpoint |
| `8eeaec6` | DevOps docs, agent configs, uv lockfile |
| `eabf68d` | M1: AES-256-GCM encryption module |
| `6bbf1c4` | M1: Foundation & project scaffolding |

---

## Infrastructure State

| Service | Status | Notes |
|---------|--------|-------|
| Supabase DB | LIVE | 6 tables, RLS enabled on all, 0 rows (fresh) |
| Render (backend) | UNKNOWN | MCP workspace not selected — user action required |
| Vercel (frontend) | UNKNOWN | Project not linked locally — user action required |
| GitHub Actions CI | CONFIGURED | Workflows exist; not yet verified against a real push |

---

## Test Suite Health

| File | Tests | Status |
|------|-------|--------|
| `test_health.py` | 8 | ✅ |
| `test_models.py` | 17 | ✅ |
| `test_crypto.py` | 19 | ✅ |
| `test_scrapers.py` | 96 | ✅ (NBE + CIB) |
| `test_scrapers_bdc_ub.py` | 143 | ✅ (BDC + UB) |
| `test_pipeline.py` | 21 | ✅ |
| `test_analytics.py` | 46 | ✅ |
| **Total** | **367** | **✅ 367/367 passing** |
