# FinPilot — Project Status

**Last reviewed:** 2026-03-22

---

## Milestone Progress

| # | Milestone | Status | Progress |
|---|-----------|--------|----------|
| M1 | Foundation & Project Scaffolding | COMPLETE | 100% |
| M2 | NBE & CIB Scrapers | COMPLETE | 100% |
| M3 | BDC & UB Scrapers + Pipeline | COMPLETE | 100% |
| M4 | Analytics Engine | COMPLETE | 100% |
| M5 | Debt Tracker (CRUD) | COMPLETE | 100% |
| M6 | Recommendations Engine | COMPLETE | 100% |
| M7 | Frontend Dashboard | COMPLETE | 100% |
| M8 | Production Deploy & Monitoring | COMPLETE | 100% |
| M9 | Real Data Integration (Live Sync) | IN PROGRESS | 92% |

---

## M1 Detailed Breakdown (100% — COMPLETE)

### Done
- [x] Monorepo structure (`apps/api`, `apps/web`, `packages/shared`, `turbo.json`)
- [x] FastAPI app skeleton (`main.py`, `config.py`, CORS guard, lifespan hook)
- [x] Pydantic v2 DB models: `UserProfile`, `BankAccount`, `Transaction`, `Loan`, `Debt`, `DebtPayment`
- [x] Pydantic v2 API schemas: `SignUpRequest`, `SignInRequest`, `AuthResponse`, `DebtCreate`, `DebtPaymentCreate`, `BankAccountCreate`, `PaginatedResponse`
- [x] Supabase schema: 6 tables, all with RLS enabled (`user_profiles`, `bank_accounts`, `transactions`, `loans`, `debts`, `debt_payments`) — **verified LIVE via MCP**
- [x] Health endpoint (`GET /api/v1/health`) with full test coverage (8 tests)
- [x] Model unit tests (17 tests covering all Pydantic models)
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
- [x] `apps/api/app/routers/analytics.py` — 4 endpoints: `POST /api/v1/analytics/categorize`, `/spending`, `/trends`, `/credit`
- [x] 46 analytics unit tests (all passing)
- [x] `anthropic>=0.40.0` added to `pyproject.toml`

---

## M5 Detailed Breakdown (100% — COMPLETE)

### Done
- [x] `apps/api/app/routers/debts.py` — full CRUD with in-memory storage (swappable for Supabase)
  - `POST /api/v1/debts` — create debt (lent/borrowed); outstanding_balance = original_amount
  - `GET /api/v1/debts` — list with `?status=` and `?debt_type=` filters
  - `GET /api/v1/debts/{id}` — detail view with full payment history (`DebtDetailResponse`)
  - `PATCH /api/v1/debts/{id}` — partial update (phone, email, due_date, notes, status)
  - `DELETE /api/v1/debts/{id}` — soft-delete: status → `settled`, balance → 0
  - `POST /api/v1/debts/{id}/payments` — record payment; returns updated debt with new balance+status
- [x] Settlement logic: `active` → `partial` → `settled` based on outstanding_balance
- [x] 400 guard: payment amount cannot exceed outstanding balance
- [x] 52 tests in `test_debts.py` — all passing

---

## M6 Detailed Breakdown (100% — COMPLETE)

### Done
- [x] `apps/api/app/recommendations/monthly_plan.py` — health-scored monthly action plan
- [x] `apps/api/app/recommendations/forecaster.py` — 3-month cash flow forecast
- [x] `apps/api/app/recommendations/debt_optimizer.py` — snowball vs avalanche simulation
- [x] `apps/api/app/recommendations/savings.py` — 4-pass savings opportunity detector
- [x] `apps/api/app/routers/recommendations.py` — 4 POST endpoints
- [x] 59 tests — all passing

---

## M7 Detailed Breakdown (100% — COMPLETE)

### Done
- [x] `src/lib/types.ts` — TypeScript interfaces for all domain models
- [x] `src/components/ui/` — 7 primitives: badge, card, button, input, modal, select, empty-state
- [x] `src/components/layout/` — sidebar (mobile drawer + desktop sticky), dashboard-layout
- [x] `src/components/dashboard/` — account-card, spending-chart, recent-transactions, health-score
- [x] `src/components/transactions/transaction-table.tsx` — filter, sort, pagination
- [x] `src/components/debts/` — debt-list, add-debt-form, payment-modal
- [x] `src/components/recommendations/` — monthly-plan-card, savings-opportunities, forecast-chart
- [x] `src/hooks/use-debts.ts` + `use-transactions.ts`
- [x] Pages: `/dashboard`, `/transactions`, `/debts`, `/recommendations`, `/settings`
- [x] `tsc --noEmit`: zero errors

---

## M8 Detailed Breakdown (100% — COMPLETE)

### Done
- [x] `render.yaml` — build command installs Playwright at build time with custom `PLAYWRIGHT_BROWSERS_PATH`
- [x] `vercel.json` — clean config, rootDirectory set via Vercel project settings
- [x] **Render service LIVE** — `finpilot-api` (srv-d6s0bg6a2pns73dfbdl0)
  - URL: `https://finpilot-api-lrfg.onrender.com`
  - Region: Oregon, Python runtime, free plan, auto-deploy on push to `main`
- [x] **Vercel deployed LIVE** — `https://finpilot-api.vercel.app`
- [x] GitHub Actions CI: ruff + mypy + pytest all passing
- [x] CORS_ORIGINS configured for production Vercel URL

---

## M9 Detailed Breakdown (92% — IN PROGRESS)

### What M9 covers
Real-data integration: stored encrypted credentials → live bank sync → dashboard shows actual account data.

### Done
- [x] `apps/api/app/routers/credentials.py` — save/list/delete encrypted bank credentials in `bank_credentials` Supabase table
- [x] `apps/api/app/routers/sync.py` — async job pattern: `POST /accounts/sync/{bank}` → 202 + job_id; `GET /accounts/sync/status/{job_id}` → status/result; background asyncio task runs scrape + pipeline
- [x] `apps/api/app/routers/utils.py` — utility endpoints
- [x] `apps/web/src/components/settings/bank-accounts-section.tsx` — UI to add credentials + trigger sync
- [x] `apps/web/src/lib/api-client.ts` — `syncBank()` uses POST→poll pattern (polls every 5s, up to 5min)
- [x] Dashboard page reads real Supabase data (accounts + transactions) when available
- [x] `test_credentials.py` — credentials router tests
- [x] Playwright install at build time (not runtime) — Chromium binary confirmed present
- [x] Global scrape semaphore prevents concurrent Playwright OOM on Render free tier
- [x] Memory-reduction Chromium flags (`--disable-dev-shm-usage`, etc.) for Render free tier
- [x] NBE CC scraping: unbilled/unsettled transactions via API intercept
- [x] NBE certificate scraping: interest rate + maturity date from HTML
- [x] CC billing details (billed_amount, unbilled_amount, credit_limit) populated in pipeline
- [x] Dashboard: CC accounts show utilization bar + billed/unbilled; certificates show rate/maturity
- [x] Dashboard KPIs: Net Worth = assets − CC liabilities; Total Balance excludes CC accounts
- [x] Frontend pages: `/dashboard/credit-cards` (255 lines) + `/dashboard/certificates` (202 lines)
- [x] `shared/types/database.ts` updated with new BankAccount fields
- [x] Schema migration: 5 new nullable columns on `bank_accounts` (credit_limit, billed_amount, unbilled_amount, interest_rate, maturity_date)
- [x] CI passing (ruff + mypy clean after format fixes)

### Remaining / In Progress
- [ ] **End-to-end sync verification**: full live sync returning `transactions_scraped > 0` from production
- [ ] Dashboard showing real NBE demand-deposit + CC + certificate data after successful live sync
- [ ] NBE demand-deposit transaction table: AJAX loading from Oregon remains the last known pain point (multiple fixes deployed — status unconfirmed from latest build `e6a54fd`)

---

## Current Focus

**Verifying M9 end-to-end on production**: The last batch of commits (`e6a54fd` through `a2a6d32`) completed the CC + certificate scraping and dashboard rendering. The primary remaining task is confirming a full NBE sync succeeds end-to-end in production (demand-deposit transactions + CC + certificates all returning data). Once confirmed, M9 is done.

**Next milestone candidate (M10)**: CIB live sync verification + multi-bank dashboard aggregation, or UX polish (loading states, error toasts, sync progress indicator).

---

## Blockers

| Blocker | Impact | Resolution |
|---------|--------|------------|
| NBE demand-deposit transaction AJAX from Oregon | M9 last 8% | Multiple scraper fixes deployed. Trigger a live NBE sync from Settings to confirm. |

---

## Recent Changes (since last review 2026-03-17)

| Commit | Description |
|--------|-------------|
| `e6a54fd` | fix(api): ruff format upserter.py |
| `a2a6d32` | feat(dashboard,scraper,pipeline): CC billing details + certificate metadata; Net Worth KPI; 600-txn fetch |
| `5984e5e` | fix(scraper,tests): remove global fallback in CC/cert scrapers, update mock fixture |
| `a1d2c44` | fix(scraper): navigate to fresh dashboard before demand-deposit loop |
| `1737223` | fix(api): global scrape semaphore to prevent concurrent Playwright OOM |
| `3c3aef4` | fix(scraper): scrape CC + certificates BEFORE demand-deposit loop |
| `482e256` | fix(scraper): loggedInUser check + 120s CCA wait |
| `6169f01` | fix(scraper): memory-reduction Chromium flags for Render free tier |
| `5481e28` | feat(scraper): NBE CC unbilled/unsettled transaction scraping |
| `e5ad10c` | fix(sync): keepalive fires immediately + handles server-restart 404 gracefully |

---

## Infrastructure State

| Service | Status | URL | Notes |
|---------|--------|-----|-------|
| Supabase DB | LIVE | — | `bank_accounts` + 5 new CC/cert columns, RLS enabled |
| Render (backend) | LIVE | `https://finpilot-api-lrfg.onrender.com` | Latest: `e6a54fd` |
| Vercel (frontend) | LIVE | `https://finpilot-api.vercel.app` | Auto-deploys on push to main |
| GitHub Actions CI | PASSING | — | ruff + mypy + pytest clean |

---

## Test Suite Health

| File | Tests | Status |
|------|-------|--------|
| `test_health.py` | 8 | PASS |
| `test_models.py` | 17 | PASS |
| `test_crypto.py` | 19 | PASS |
| `test_scrapers.py` | ~111 | PASS (NBE + CIB, CC/cert mocks updated) |
| `test_scrapers_bdc_ub.py` | 143 | PASS (BDC + UB) |
| `test_pipeline.py` | 21 | PASS |
| `test_analytics.py` | 46 | PASS |
| `test_debts.py` | 52 | PASS |
| `test_recommendations.py` | 59 | PASS |
| `test_credentials.py` | ~35 | PASS |
| **Total** | **511+** | **All passing** |
