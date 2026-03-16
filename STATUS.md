# FinPilot — Project Status

**Last reviewed:** 2026-03-16 (all 8 milestones complete)

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
- [x] `apps/api/app/routers/analytics.py` — 4 endpoints: `POST /api/v1/analytics/categorize`, `/spending`, `/trends`, `/credit`; all with `extra="forbid"`, no PII in logs
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
- [x] `clear_storage()` export for test isolation
- [x] `apps/api/app/main.py` — debts router registered at `/api/v1`
- [x] 52 tests in `test_debts.py` — all passing; **419 total tests passing**

---

## M6 Detailed Breakdown (100% — COMPLETE)

### Done
- [x] `apps/api/app/recommendations/monthly_plan.py` — health-scored monthly action plan; items ranked high→medium→low; confidence=0.4 when sparse (<3 months)
- [x] `apps/api/app/recommendations/forecaster.py` — 3-month cash flow forecast; per-month confidence decay (0.9→0.8→0.7); expense growth by trend direction
- [x] `apps/api/app/recommendations/debt_optimizer.py` — snowball vs avalanche simulation (cap 120 months); avalanche recommended unless all APR==0
- [x] `apps/api/app/recommendations/savings.py` — 4-pass detector: duplicate charges, recurring subscriptions (3+ months), high fees (keywords + EGP>50), irregular spikes (mean+2σ); top-10 ranked
- [x] `apps/api/app/routers/recommendations.py` — 4 endpoints:
  - `POST /api/v1/recommendations/monthly-plan`
  - `POST /api/v1/recommendations/forecast`
  - `POST /api/v1/recommendations/debt-optimizer`
  - `POST /api/v1/recommendations/savings`
- [x] Bug fix: `savings.py` `sum()` with empty generator raised `AttributeError` — fixed with `Decimal("0")` start value
- [x] `apps/api/app/main.py` — recommendations router registered
- [x] 59 tests (unit + HTTP) — all passing; **478 total tests passing**

---

## M7 Detailed Breakdown (100% — COMPLETE)

### Done
- [x] `src/lib/types.ts` — TypeScript interfaces for all domain models (Debt, Transaction, MonthlyPlan, etc.)
- [x] `src/components/ui/` — 7 hand-rolled primitives: badge, card, button, input, modal, select, empty-state
- [x] `src/components/layout/sidebar.tsx` — mobile drawer + desktop sticky, nav links, sign-out
- [x] `src/components/layout/dashboard-layout.tsx` — responsive wrapper with sidebar
- [x] `src/components/dashboard/` — account-card (KPI), spending-chart (CSS bars), recent-transactions (table), health-score (SVG gauge)
- [x] `src/components/transactions/transaction-table.tsx` — filter, sort, pagination
- [x] `src/components/debts/` — debt-list, add-debt-form, payment-modal (calls `api.post('/debts/…')`)
- [x] `src/components/recommendations/` — monthly-plan-card, savings-opportunities, forecast-chart (grouped CSS bars)
- [x] `src/hooks/use-debts.ts` + `use-transactions.ts` — fetch + loading + error + refetch pattern
- [x] Pages: `/dashboard`, `/dashboard/transactions`, `/dashboard/debts`, `/dashboard/recommendations`, `/dashboard/settings`
- [x] `src/app/dashboard/layout.tsx` — server-side auth guard, redirects unauthenticated users
- [x] Fixed pre-existing scaffold errors: Geist→Inter/JetBrains_Mono (Next.js 14), Supabase cookie type annotations
- [x] `tsc --noEmit`: **zero errors**

---

## M8 Detailed Breakdown (100% — COMPLETE)

### Done
- [x] `apps/api/.env` — all 5 secrets filled: Supabase URL/anon/service_role, ENCRYPTION_KEY, CLAUDE_API_KEY
- [x] `apps/web/.env.local` — Supabase public keys + API URL for local dev
- [x] `apps/web/next.config.mjs` — replaced `next.config.ts` (Next.js 14 requires `.js`/`.mjs`); API proxy rewrite preserved
- [x] `render.yaml` — fixed `healthCheckPath: /api/v1/health`
- [x] `vercel.json` — removed broken template syntax and conflicting `rootDirectory`
- [x] Frontend build: `pnpm build` → **11 routes compile, 0 errors**
- [x] **Render service LIVE** — `finpilot-api` (srv-d6s0bg6a2pns73dfbdl0) — verified via MCP
  - URL: `https://finpilot-api-lrfg.onrender.com`
  - Region: Oregon, Python runtime, free plan
  - Status: not_suspended, auto-deploy on push to `main`
  - All 7 env vars set (Supabase, ENCRYPTION_KEY, CLAUDE_API_KEY, CORS_ORIGINS)
- [x] **Vercel deployed LIVE** — `https://finpilot-api.vercel.app` (state: READY) — verified via MCP
  - Latest deployment: `dpl_H4yZnjrzjoWUz8fh5MTFLb79HRHm` (commit `81a6357`)
  - Framework: nextjs, `rootDirectory: apps/web` set via project settings
  - All 4 env vars set (Supabase public keys, API URL, APP URL)
- [x] **CORS_ORIGINS** updated on Render to include production Vercel URLs

---

## Current Focus

**Project complete — all 8 milestones delivered.** FinPilot is fully deployed in production.

---

## Blockers

None.

---

## Recent Changes (since last review)

| Commit | Description |
|--------|-------------|
| `81a6357` | fix(infra): remove rootDirectory from vercel.json — set via project settings |
| `aad0e2c` | docs: update STATUS.md — M8 in progress |
| `4f6c0c4` | fix(infra): M8 deploy prep — next.config.mjs, vercel.json, render.yaml health path |
| `08a08e4` | feat(web): M7 — Frontend Dashboard with all pages and components |
| `e4e2414` | feat(api): M6 — Recommendations Engine + POST /api/v1/recommendations/* endpoints |
| `8c42469` | feat(api): M5 — Debt Tracker CRUD with payment tracking and settlement flow |
| `b46fb81` | feat(analytics): M4 — analytics engine + POST /api/v1/analytics/* endpoints |
| `0b3f26a` | feat(scraper,pipeline): M3 — BDC & UB scrapers + ETL pipeline |

---

## Infrastructure State

| Service | Status | URL | Notes |
|---------|--------|-----|-------|
| Supabase DB | LIVE | — | 6 tables, RLS enabled on all, verified via MCP |
| Render (backend) | LIVE | `https://finpilot-api-lrfg.onrender.com` | srv-d6s0bg6a2pns73dfbdl0, auto-deploy on push to main |
| Vercel (frontend) | LIVE | `https://finpilot-api.vercel.app` | Latest deploy READY (dpl_H4yZnjrzjoWUz8fh5MTFLb79HRHm) |
| GitHub Actions CI | ACTIVE | — | Runs lint + tests on every PR/push |

---

## Test Suite Health

| File | Tests | Status |
|------|-------|--------|
| `test_health.py` | 8 | PASS |
| `test_models.py` | 17 | PASS |
| `test_crypto.py` | 19 | PASS |
| `test_scrapers.py` | 96 | PASS (NBE + CIB) |
| `test_scrapers_bdc_ub.py` | 143 | PASS (BDC + UB) |
| `test_pipeline.py` | 21 | PASS |
| `test_analytics.py` | 46 | PASS |
| `test_debts.py` | 52 | PASS |
| `test_recommendations.py` | 59 | PASS |
| **Total** | **478** | **478/478 passing** |
