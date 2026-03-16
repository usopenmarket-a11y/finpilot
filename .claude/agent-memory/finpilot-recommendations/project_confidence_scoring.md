---
name: Confidence scoring heuristics
description: Confidence score values used in monthly_plan.py and forecaster.py and the rationale for each
type: project
---

## monthly_plan.py
- `plan_confidence = 0.4` when `lookback_months < 3` (sparse data)
- `plan_confidence = 0.85` otherwise
- All `ActionItem` instances inherit the same plan-level confidence

## forecaster.py
- Base confidence: 0.9 for month 1, decays by 0.1 per additional forecast month (month 2 = 0.8, month 3 = 0.7)
- Additional -0.2 penalty applied uniformly when `lookback_months < 3`
- All confidence values clamped to [0.0, 1.0]
- Composite `CashFlowForecast.confidence_score` = average of the three ForecastPoint confidence values

**Why:** System prompt mandates `confidence_score < 0.5` when data is sparse (< 3 months). The 0.4 floor for sparse plans satisfies this. The 0.1/month decay in forecasting reflects genuine uncertainty growth over a 90-day horizon.

**How to apply:** Follow the same pattern in any new recommendation module — check `lookback_months` against 3 and set a low floor; use item-level confidence for granular outputs, plan-level aggregate for summary objects.
