# Real Recommendations Dashboard — Design

## Context

`apps/web/src/app/dashboard/recommendations/page.tsx` currently renders entirely
hardcoded mock data (`MOCK_PLAN`, `MOCK_OPPORTUNITIES`, `MOCK_FORECAST`). The
backend recommendations engine (`apps/api/app/recommendations/*` +
`apps/api/app/routers/recommendations.py`) is fully implemented with three
relevant endpoints:

- `POST /api/v1/recommendations/monthly-plan` → `MonthlyPlan`
- `POST /api/v1/recommendations/forecast` → `CashFlowForecast`
- `POST /api/v1/recommendations/savings` → `SavingsReport`

This change wires the page to real data from the user's synced transactions.

## Scope

- In scope: Monthly Plan card, Savings Opportunities, 3-Month Forecast — the
  three sections that already exist on the page.
- Out of scope: Debt payoff optimizer (`/recommendations/debt-optimizer`) — no
  new "Debt Strategy" section in this pass.

## Architecture

Convert the page to an **async server component**, mirroring the pattern in
`apps/web/src/app/dashboard/page.tsx`:

1. **Fetch from Supabase (server-side)**:
   - `bank_accounts` (active, for the current user) — used to identify
     credit-card account IDs so card spend can be excluded from "cash flow"
     the same way `dashboard/page.tsx` does.
   - `transactions` (current user, ordered by `transaction_date` desc, limit
     5000) — source data for all three backend calls.
   - Supabase session (`supabase.auth.getSession()`) for the JWT access token
     required by `apiFetch`.

2. **Empty state**: if `transactions.length === 0`, render a "Connect a bank
   account in Settings to get personalised recommendations" card and skip all
   backend calls. No 422s from the `min_length=1` constraints on the
   recommendations endpoints.

3. **Build wire-format inputs directly in TypeScript** (no intermediate calls
   to `/analytics/spending` or `/analytics/trends` — avoids extra Render
   round-trips on the free tier; reuses the dashboard's existing aggregation
   approach):

   - **`SpendingBreakdownInput`** (current calendar month, non-card
     transactions):
     - `total_debits`, `total_credits`, `net`
     - `by_category`: group debit transactions by `category` (fallback
       `"Uncategorized"`), each with `total`, `transaction_count`, and
       `percentage` (share of `total_debits`)

   - **`TrendReportInput`** (6-month lookback, non-card transactions):
     - `monthly_points`: one entry per of the last 6 calendar months —
       `year`, `month`, `total_debits`, `total_credits`, `net`,
       `transaction_count`
     - `avg_monthly_spend` / `avg_monthly_income`: averages of
       `total_debits` / `total_credits` across the 6 points
     - `spend_trend_direction`: compare the most recent month's
       `total_debits` against the average of the prior months; "up" if
       >5% higher, "down" if >5% lower, else "flat"
     - `lookback_months`: 6

   - **`TransactionSummaryInput[]`** (all fetched transactions, both card and
     non-card): `description`, `amount`, `transaction_type`,
     `transaction_date`, `category` — for `/recommendations/savings`.

4. **Call the three endpoints in parallel** via `Promise.allSettled` (server
   side, using the user's JWT):
   - `monthly-plan` body: `{ spending, trends, target_month, target_year }`
     (target = current month/year)
   - `forecast` body: `{ trends }` (no `from_date` — defaults to today)
   - `savings` body: `{ transactions }`

   Each call is independent; a failure in one (e.g. cold-start timeout) must
   not break the other two sections. Each section shows its real data on
   success or a small "Unable to load — try refreshing" message on failure.

5. **Map responses to existing frontend types** (`@/lib/types`):
   - `MonthlyPlan.health_score` is `0.0–1.0` in the backend but
     `MonthlyPlanCard`/`HealthScore` expect `0–100` — multiply by 100
     (rounded) when constructing the prop.
   - `CashFlowForecast.forecast_points` → `ForecastPoint[]` — shapes already
     match `@/lib/types.ForecastPoint`, pass through directly.
   - `SavingsReport.opportunities` → `SavingsOpportunity[]` — shapes already
     match `@/lib/types.SavingsOpportunity`, pass through directly.
   - `MonthlyPlan.action_items` → `ActionItem[]` — backend `category` is a
     narrower literal (`"spending"|"savings"|"debt"|"income"`) than the
     frontend's `string`; compatible as-is.

## New API client functions

Add to `apps/web/src/lib/api-client.ts`, following the existing `apiFetch<T>`
pattern (each takes `accessToken` + typed request body, returns typed
response):

- `getMonthlyPlan(accessToken, body): Promise<MonthlyPlanResponse>`
- `getCashFlowForecast(accessToken, body): Promise<CashFlowForecastResponse>`
- `getSavingsReport(accessToken, body): Promise<SavingsReportResponse>`

Request/response TS interfaces mirror the backend Pydantic wire models
(`SpendingBreakdownInput`, `TrendReportInput`, `TransactionSummaryInput`,
`MonthlyPlan`, `CashFlowForecast`, `SavingsReport`) as described above.

## Error handling

- Per-section `Promise.allSettled` — one slow/failed endpoint doesn't blank
  the whole page.
- Zero-transaction empty state avoids calling endpoints that reject empty
  lists (422).
- Network/auth errors (`UnauthorizedError` from `apiFetch`) bubble to a
  section-level fallback message, not a page crash.

## Testing

- `npx tsc --noEmit` in `apps/web` to confirm types compile.
- Manual verification via dev server + browser screenshot of the
  recommendations page with real synced data (and ideally a check of the
  empty state by temporarily considering a zero-transaction user, if
  feasible).
