---
name: M6 input model bridge pattern
description: Explains why monthly_plan.py and forecaster.py define their own Pydantic input models rather than importing analytics dataclasses directly
type: project
---

The analytics layer (`app/analytics/spending.py`, `app/analytics/trends.py`) uses Python `dataclasses`, not Pydantic models. Field names also differ from the recommendation spec:

- `SpendingBreakdown.total_spending` / `total_income` → spec calls these `total_debits` / `total_credits`
- `CategoryBreakdown.total_amount` → spec calls this `total`
- `TrendReport.avg_monthly_spending` → spec calls this `avg_monthly_spend`
- `TrendReport` has no `lookback_months`, `monthly_points`, or `spend_trend_direction` fields; callers must derive `spend_trend_direction` from `spending_change_pct`

**Why:** The recommendation modules define their own Pydantic v2 input models (`SpendingBreakdown`, `TrendReport`, etc.) to create a validated contract boundary. Callers (routers, tests) are responsible for mapping analytics dataclass output into these models.

**How to apply:** When adding new recommendation modules that consume analytics output, always define a Pydantic input model in that module (or import from `monthly_plan`). Never import analytics dataclasses directly into recommendation logic — the field-name mismatch will cause silent errors.
