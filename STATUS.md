# FinPilot — Project Status

**Last reviewed:** 2026-03-24

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
| M9 | Real Data Integration (Live Sync) | COMPLETE | 100% |
| M10 | UX Polish & Multi-bank Expansion | NOT STARTED | 0% |

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

## M9 Detailed Breakdown (100% — COMPLETE)

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
- [x] NBE CC scraping: statement (622 txns) + unbilled/UBT (74 txns) + unsettled/UNS (3 txns) via API intercept
- [x] NBE certificate scraping: interest rate + maturity date from HTML
- [x] CC billing details (billed_amount, unbilled_amount, minimum_payment, payment_due_date) populated
- [x] Dashboard: CC accounts show billed/unbilled amounts; certificates show rate/maturity
- [x] Dashboard KPIs: Net Worth = assets − CC liabilities; Total Balance excludes CC accounts
- [x] Frontend pages: `/dashboard/credit-cards` + `/dashboard/certificates`
- [x] `shared/types/database.ts` updated with new BankAccount fields
- [x] Schema migration: 5 new nullable columns on `bank_accounts`
- [x] DB live: 642 transactions, 5 bank accounts, last_synced_at = 2026-03-23 19:52:54 UTC
- [x] UNS authdate propagation fix (`6e4468c`) — parent date fields merged into child statmentItems
- [x] Diagnostic logging downgraded to DEBUG (`e22fabd`)
- [x] CI passing (ruff + mypy clean)

---

## Current Focus

**M9 is complete.** All NBE account types scraping and storing data correctly:
- Demand deposits: transactions via AJAX intercept
- Credit card: 622 statement + 74 UBT + 3 UNS = 625+ total CC transactions
- Certificates: interest rate + maturity date

**Next milestone (M10): UX Polish & Multi-bank Expansion**
Candidates:
1. CIB live sync verification + multi-bank dashboard aggregation
2. Loading states and sync progress indicators in the UI
3. Credit limit discovery (NBE portal may not expose via API — needs investigation)
4. Transaction categorization running on live data

---

## Blockers

None. System is fully operational.

| Item | Notes |
|------|-------|
| `credit_limit=null` for NBE CC | NBE portal may not expose credit limit via any accessible API endpoint. Low priority — not blocking. |

---

## Recent Changes (since last review 2026-03-22)

| Commit | Description |
|--------|-------------|
| `e22fabd` | chore(scraper): downgrade diagnostic logging to DEBUG in NBE CC parser |
| `6e4468c` | fix(scraper): propagate parent authdate into UNS statmentItems children — **KEY FIX** |
| `5e34293` | fix(scraper): parse unsettled (UNS) transaction fields correctly |
| `4c6522c` | fix(scraper): handle epoch-ms dates in UBT response parser |
| `3f9cd47` | fix(scraper): add YYYYMMDD date format + promote date-skip log to INFO |
| `e0807b2` | fix(scraper): poll for UBT paginator re-enable before checking pagination |
| `bae4aba` | debug(scraper): log all UBT item fields + per-item skip reason |
| `04ecf8b` | fix(scraper): parse UBT field names + extra paginator wait |
| `d7815e1` | fix(scraper): wait for UBT API response before checking pagination |
| `9a32fab` | fix(scraper): broaden UBT response capture to match by body content |
| `eba3ec4` | fix(cc-ui): filter unbilled tab to current billing cycle only |
| `562ad94` | feat(scraper): paginate NBE unbilled transactions tab across all pages |

---

## Infrastructure State

| Service | Status | URL | Notes |
|---------|--------|-----|-------|
| Supabase DB | LIVE | — | 7 tables, all RLS enabled; 642 txns, 5 accounts |
| Render (backend) | LIVE | `https://finpilot-api-lrfg.onrender.com` | Latest: `e22fabd`, not_suspended |
| Vercel (frontend) | LIVE | `https://finpilot-api.vercel.app` | Latest: `dpl_YhL3sfjd` on `e22fabd` — READY |
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
