---
name: project_recommendations_engine_wiring
description: Backend recommendations endpoints serialize Decimal fields as JSON strings; wiring pattern for /dashboard/recommendations real-data page
type: project
metadata:
  type: project
---

## Decimal -> JSON string (critical gotcha)

`apps/api/app/recommendations/*` Pydantic v2 models type money fields as
`Decimal`. FastAPI's default `model_dump(mode="json")` serializes `Decimal`
as a **JSON string** (e.g. `"123.45"`), NOT a number. `float` fields
(`health_score`, `confidence`, `confidence_score`, `percentage`) DO serialize
as JSON numbers.

**How to apply:** any new TS response interface for these endpoints must type
Decimal-backed fields as `string` and call `Number(...)` before arithmetic or
display. Verified empirically:
```python
class M(BaseModel):
    x: float
    y: Decimal
M(x=0.5, y=Decimal("123.45")).model_dump_json()
# -> {"x": 0.5, "y": "123.45"}
```
This affects: `MonthlyPlanResponse.projected_savings`,
`ActionItemResponse.estimated_impact`, `ForecastPointResponse.projected_*`,
`SavingsOpportunityResponse.estimated_monthly_saving`,
`DebtOptimizationReportResponse.*` (balances, rates, payments, interest),
`PayoffStepResponse.*`. See `apps/web/src/lib/api-client.ts` "Recommendations"
section for the full typed set — each Decimal field has a `/** Decimal on the
wire -> JSON string. */` comment.

## /dashboard/recommendations real-data wiring (2026-06-15)

Implemented per `docs/superpowers/specs/2026-06-15-real-recommendations-design.md`.
Page is `apps/web/src/app/dashboard/recommendations/page.tsx`, an async server
component mirroring `apps/web/src/app/dashboard/page.tsx`'s data-fetch pattern
(createClient from `@/lib/supabase/server`, parallel Supabase queries +
`supabase.auth.getSession()` for the JWT, credit-card account exclusion via
`account_type === 'credit_card'`, 6-month lookback via `dateKey`/`isInRange`
helpers).

Four backend calls (`getMonthlyPlan`, `getCashFlowForecast`,
`getSavingsReport`, `getDebtPayoffPlan` in `api-client.ts`) run via
`Promise.allSettled` — debt call is a second, separate `allSettled` because it
depends on `monthlyPlan.projected_savings` (must resolve first). Empty-txn
state (`allTransactions.length === 0`) skips all backend calls entirely
(avoids `min_length=1` 422s on `/savings` and `/debt-optimizer`). Also guards
`transactionSummaries.length === 0` after filtering (zero-amount/empty-desc
txns) by short-circuiting `/savings` with a locally-rejected promise rather
than sending a guaranteed-422 request.

**Debt section**: only send `debt_type: "borrowed"` debts with
`status in (active, partial)`, `interest_rate=0`, `minimum_payment=0`.
`monthly_budget = Math.floor(projectedSavings)`; section omitted entirely if
`debtItems.length === 0`; shows a "no surplus" message (not an error) if
`monthlyBudget <= 0`. Snowball payoff order is derived in
`debt-payoff-plan.tsx` by scanning `snowball.monthly_steps` for each debt's
first `remaining_balance <= 0` month.

**ActionFeed** (`components/recommendations/action-feed.tsx`, client
component): merges `MonthlyPlan.action_items` + `SavingsReport.opportunities`
into one list sorted by impact desc (`mergeFeedItems` export). Savings items
get a derived severity (`>=300` EGP -> high, `>=100` -> medium, else low) since
they don't carry a `priority` field. Expandable "why" via local `useState`
(no shadcn Collapsible exists in this repo — `components/ui/` is a small
hand-rolled set: `card`, `badge`, `button`, `input`, `select`, `modal`,
`empty-state` — NOT actual shadcn/ui, despite what the agent system prompt
implies. Follow these existing components, not generic shadcn patterns).

`monthly-plan-card.tsx` was trimmed to remove its action-items list (now lives
only in ActionFeed, avoiding double-render) — kept as the "Financial Health
hero" (HealthScore gauge + summary + projected savings).

`SavingsOpportunity` type in `lib/types.ts` gained an optional
`transactions?: string[]` field (backend's `SavingsOpportunity.transactions`)
for the ActionFeed's expandable "triggering transactions" list.

Verification: `pnpm --filter web type-check` and `pnpm --filter web lint`
both pass clean (the CI gates per CLAUDE.md/spec).
