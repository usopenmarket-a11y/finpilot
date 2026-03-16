# FinPilot — Project Status

**Last reviewed:** 2026-03-16 (M7 complete)

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

## Current Focus

**M8 — Production Deploy & Monitoring**

### M8 entry points
- Deploy backend to Render (auto via git push — workflow exists)
- Deploy frontend to Vercel (need `vercel link` first)
- Set environment variables in both platforms
- Configure Sentry error tracking
- Health monitoring / uptime checks

---

## Blockers

| Blocker | Owner | Action Required |
|---------|-------|-----------------|
| Render MCP workspace not selected | User | Select a Render workspace so the devops agent can monitor the backend service |
| Vercel project not deployed | User | No Vercel project found — run `cd apps/web && vercel link` or deploy via `vercel --prod` |
| `CLAUDE_API_KEY` not set | User | Required for M4 analytics categorization (Claude Haiku 4.5) — add to `apps/api/.env` and Render env vars |

---

## Recent Changes (since last review)

| Commit | Description |
|--------|-------------|
| `08a08e4` | M7: Frontend Dashboard — 28 files, 5 pages, 0 TS errors |
| `e4e2414` | M6: Recommendations Engine — 4 modules + 4 endpoints + 59 tests (478 total) |
| `8c42469` | M5: Debt Tracker CRUD — debts router + 52 tests (419 total passing) |
| `b46fb81` | M4: Analytics engine — categorizer, spending, trends, credit + 4 API endpoints (46 new tests) |
| `0b3f26a` | M3: BDC & UB scrapers + full ETL pipeline (normalizer, deduplicator, upserter, runner) |
| `994ee89` | M2: NBE & CIB scrapers + `POST /api/v1/scrape` endpoint |

---

## Infrastructure State

| Service | Status | Notes |
|---------|--------|-------|
| Supabase DB | LIVE | 6 tables, RLS enabled on all, 0 rows (fresh) |
| Render (backend) | UNKNOWN | MCP workspace not selected — user action required |
| Vercel (frontend) | NOT DEPLOYED | No projects found in Vercel team — needs initial deploy |
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
| `test_debts.py` | 52 | ✅ |
| `test_recommendations.py` | 59 | ✅ |
| **Total** | **478** | **✅ 478/478 passing (3m 25s)** |
