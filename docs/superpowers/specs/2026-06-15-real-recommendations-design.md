# Intelligent Recommendations Dashboard — Design

## Context

`apps/web/src/app/dashboard/recommendations/page.tsx` currently renders entirely
hardcoded mock data (`MOCK_PLAN`, `MOCK_OPPORTUNITIES`, `MOCK_FORECAST`) — the same
fiction for every user. The backend recommendations engine
(`apps/api/app/recommendations/*` + `apps/api/app/routers/recommendations.py`) is
fully implemented with four engines, three of which have endpoints the frontend
never calls and one (debt optimizer) that is shown nowhere:

- `POST /api/v1/recommendations/monthly-plan` → `MonthlyPlan`
- `POST /api/v1/recommendations/forecast` → `CashFlowForecast`
- `POST /api/v1/recommendations/savings` → `SavingsReport`
- `POST /api/v1/recommendations/debt-optimizer` → `DebtOptimizerReport` (currently unused)

This change wires the page to real synced data, surfaces all four engines, and
upgrades the two weakest parts of the engine (health score + action-item impact)
to produce genuinely intelligent, personalised advice. Strictly rule-based — no
ML, no LLM narrative, no new data sources beyond the user's existing
transactions and debts.

## Scope

In scope:
- **Backend engine upgrade** (`apps/api/app/recommendations/monthly_plan.py`):
  continuous health score + real per-item `estimated_impact`.
- **Wire all four endpoints** to real Supabase data.
- **New Debt Payoff Plan section** surfacing the debt engine.
- **Redesigned layout**: a prioritised insight feed instead of three static cards.

Out of scope: ML/LLM, trading features, new data sources (bill calendar,
category budgets), and any change to the savings or forecaster engine logic
(they are already good — only consumed, not modified).

## Part A — Backend engine upgrade (`monthly_plan.py`)

Owner: `finpilot-recommendations` agent.

### A1. Continuous health score (replaces flat three-step penalty)

Current logic is `1.0` minus flat penalties (−0.3 trend-up, −0.2 negative-net,
−0.1 category-dominance), so the score only takes a handful of discrete values.
Replace with a smooth 0–1 blend of three components:

- **Savings-rate component (0–0.5 weight)**: `net / total_credits` mapped so
  that a ≥30% savings rate scores full marks, 0% scores half, and a deficit
  scores 0. Linear in between.
- **Trend component (0–0.3 weight)**: scaled by the *magnitude* of the
  month-over-month spend change, not a flat step. Flat/down trends score full;
  an upward trend loses weight proportional to how steep it is (clamped).
- **Concentration component (0–0.2 weight)**: full marks when no category
  exceeds 40% of spend; loses weight proportional to how far the top category
  is past 40% (clamped at 100%).

Result is a continuous score that moves with behaviour. Keep the field
`0.0–1.0` (frontend multiplies by 100). Existing tests that assert exact
penalty values will be updated by the recommendations agent.

### A2. Real `estimated_impact` on action items

Today most action items carry `estimated_impact=0` and generic copy. Give each
a realistic EGP figure tied to the user's actual numbers:

- "Close Budget Gap" → already uses the real deficit (keep).
- "Review {category} Spending" → impact = a conservative fraction (e.g. 15%) of
  that category's *actual* EGP total, instead of 0.
- "Reduce Spending" (trend-up) → impact = the EGP amount of the month-over-month
  increase that would be reversed by returning to the prior-month average.
- "Build Emergency Fund" → already uses projected surplus (keep).

Items are then ranked by `estimated_impact` desc within each priority tier so
the highest-value advice surfaces first.

## Part B — Frontend data fetching (async server component)

Owner: `finpilot-frontend-dev` agent. Mirror `apps/web/src/app/dashboard/page.tsx`.

1. **Fetch from Supabase (server-side)**: `bank_accounts` (active),
   `transactions` (ordered by `transaction_date` desc, limit 5000), `debts`
   (active/partial), and the session JWT via `supabase.auth.getSession()`.
2. **Empty state**: if `transactions.length === 0`, render a "Connect a bank
   account in Settings" card and skip all backend calls (avoids `min_length=1`
   422s).
3. **Build wire-format inputs in TypeScript** (no `/analytics/*` round-trips):
   - `SpendingBreakdownInput` (current calendar month, non-card txns):
     `total_debits`, `total_credits`, `net`, and `by_category` (debit txns
     grouped by `category` → `"Uncategorized"`, each with `total`,
     `transaction_count`, `percentage` of `total_debits`).
   - `TrendReportInput` (6-month lookback, non-card txns): one `MonthlyPoint`
     per of the last 6 calendar months; `avg_monthly_spend`/`avg_monthly_income`
     averages; `spend_trend_direction` from most-recent-month debits vs. prior
     average (>5% → up, <−5% → down, else flat); `lookback_months: 6`.
   - `TransactionSummaryInput[]` (all txns): `description`, `amount`,
     `transaction_type`, `transaction_date`, `category` — for savings.
   - `DebtItemInput[]` (active/partial borrowed debts, see Part C).
4. **Call all four endpoints in parallel** via `Promise.allSettled` with the
   user's JWT. Each is independent; one failure shows a per-section fallback,
   never blanks the page.
5. **Map responses to frontend types** (`@/lib/types`): `health_score` ×100
   (rounded); `forecast_points` and `opportunities` pass through; `action_items`
   pass through.

## Part C — Debt Payoff Plan (surfacing the unused engine)

The `debts` table holds informal lent/borrowed records with **no `interest_rate`
and no `minimum_payment`**. The optimizer requires both, so all real debts map to
`interest_rate=0`, `minimum_payment=0`. With every APR at 0, snowball and
avalanche collapse to the *same* ordering — a side-by-side comparison would be
meaningless. Therefore:

- Send only **`debt_type: "borrowed"`** debts (money the user owes) that are
  `active` or `partial`, mapped with `interest_rate=0`, `minimum_payment=0`,
  `outstanding_balance` from the row.
- `monthly_budget`: derived from the user's real projected monthly surplus
  (the forecaster's / plan's `projected_savings`), floored at a small positive
  value so the endpoint's `gt=0` constraint holds. If surplus is 0, skip the
  section with a note ("No surplus available to model a payoff plan").
- Render the engine's **snowball** result only (smallest-balance-first — the one
  meaningful strategy without APRs) as a "Debt Payoff Plan" card: total
  borrowed, months-to-debt-free at the modelled budget, and payoff order.
- If the user has no borrowed debts, omit the section entirely.

## Part D — Redesigned layout (prioritised insight feed)

Replace the three-static-card grid with a ranked, action-first layout:

1. **Financial Health hero** — real continuous score (0–100) + plain-language
   summary + real projected savings, full-width at top.
2. **Prioritised Action Feed** — merge `MonthlyPlan.action_items` and
   `SavingsReport.opportunities` into one list ranked by EGP impact
   (`estimated_impact` / `estimated_monthly_saving`). Each row: severity colour,
   EGP/mo value badge, title, and an expandable "why" (description + triggering
   transactions for savings items). This is the "what do I do first" view that
   is missing today.
3. **Debt Payoff Plan** (Part C) — when borrowed debts exist.
4. **3-Month Forecast** — existing `ForecastChart` on real numbers.

A new `ActionFeed` component renders the merged/ranked list. Existing
`MonthlyPlanCard`, `SavingsOpportunities`, and `ForecastChart` are reused where
they still fit; `SavingsOpportunities`' content is folded into the feed.

## New API client functions (`apps/web/src/lib/api-client.ts`)

Following the existing `apiFetch<T>` pattern (each takes `accessToken` + typed
body, returns typed response):

- `getMonthlyPlan(accessToken, body)`
- `getCashFlowForecast(accessToken, body)`
- `getSavingsReport(accessToken, body)`
- `getDebtPayoffPlan(accessToken, body)`

Request/response TS interfaces mirror the backend Pydantic wire models.

## Error handling

- Per-section `Promise.allSettled` — one slow/failed endpoint doesn't blank the page.
- Zero-transaction empty state avoids 422s from `min_length=1` endpoints.
- `UnauthorizedError` from `apiFetch` bubbles to a section-level fallback, not a crash.

## Testing

- Backend: `finpilot-recommendations` updates/extends `monthly_plan` tests for
  the new continuous health score and non-zero impacts; `pytest` must pass.
- Frontend: `npx tsc --noEmit` in `apps/web`; manual dev-server + screenshot of
  the page with real synced data and of the empty state.
