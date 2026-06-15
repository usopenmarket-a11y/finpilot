---
name: Continuous health score formula (monthly_plan.py)
description: The post-2026-06-15 continuous 0-1 health score blend (savings rate + trend + concentration) replacing the old flat-penalty model, plus real estimated_impact rules for action items
type: project
---

## Background

`generate_monthly_plan()` in `apps/api/app/recommendations/monthly_plan.py` used to compute
`health_score` as `1.0` minus flat penalties (-0.3 up-trend, -0.2 negative net, -0.1 dominant
category), producing only a handful of discrete values. Per
`docs/superpowers/specs/2026-06-15-real-recommendations-design.md` (Part A), this was replaced
with a continuous weighted blend on 2026-06-15. The old `HEALTH_PENALTY_*` constants were
removed entirely.

## health_score = sum of three components, clamped to [0.0, 1.0]

### 1. Savings-rate component — weight `HEALTH_WEIGHT_SAVINGS_RATE = 0.5`
- `rate = spending.net / spending.total_credits` (if `total_credits == 0`, component = 0.0,
  no divide-by-zero)
- `rate >= SAVINGS_RATE_FULL_MARKS_PCT (0.30)` -> full 0.5
- `rate == 0` -> half marks, 0.25
- `rate <= SAVINGS_RATE_ZERO_MARKS_PCT (-0.30)` -> 0.0
- Linear interpolation in [-0.30, 0] -> [0, 0.25] and [0, 0.30] -> [0.25, 0.5]
- This anchor pair (-30%/+30% symmetric around 0%) was my own design choice to make "deficit ->
  0.0" interpolable; the spec only fixed the three named anchors (deficit, 0%, >=30%)

### 2. Trend component — weight `HEALTH_WEIGHT_TREND = 0.3`
- `spend_trend_direction in ("flat", "down")` -> full 0.3
- `"up"`: compute `pct_increase = (most_recent_month.total_debits - avg(prior_months.total_debits)) / avg(prior_months.total_debits)`
  from `trends.monthly_points` (need >= 2 points; floor pct_increase at 0)
  - `pct_increase >= TREND_UP_FULL_LOSS_PCT (0.50)` -> lose full 0.3 (component = 0.0)
  - linear in between
- If `< 2` monthly_points or `prior_avg == 0`: fixed fallback loss of
  `TREND_UP_NO_HISTORY_LOSS_FRACTION (0.5)` of the weight -> component = 0.15. An "up" trend is
  never free.

### 3. Concentration component — weight `HEALTH_WEIGHT_CONCENTRATION = 0.2`
- `top_pct = max(c.percentage for c in spending.by_category)` (0.2 if `by_category` is empty)
- `top_pct <= CATEGORY_DOMINANCE_THRESHOLD_PCT (40.0)` -> full 0.2
- `top_pct >= CATEGORY_CONCENTRATION_FULL_LOSS_PCT (100.0)` -> 0.0
- Linear in between (40 -> 100 maps to 0.2 -> 0.0 loss)

### Worked examples (used in tests)
- Default spending (net=1000, total_credits=6000, categories 30%/20%), flat trend:
  savings 0.3889 + trend 0.3 + concentration 0.2 = **0.8889**
- Same but up trend with monthly_points Jan=5000, Feb=5200 (4% increase):
  savings 0.3889 + trend 0.276 + concentration 0.2 = **0.8649**
- net=-500 (deficit), total_credits=6000, flat, balanced categories:
  savings 0.1806 + trend 0.3 + concentration 0.2 = **0.6806**

## Real estimated_impact on ActionItems (A2)

- **"Close Budget Gap"** (negative net): `estimated_impact = abs(spending.net)` — unchanged
- **"Review {category} Spending"** (category % > `CATEGORY_REVIEW_THRESHOLD_PCT` = 30): `estimated_impact = _egp(cat.total * CATEGORY_REVIEW_IMPACT_FRACTION)` where `CATEGORY_REVIEW_IMPACT_FRACTION = Decimal("0.15")`
- **"Reduce Spending"** (up trend): `estimated_impact = _egp(most_recent_month.total_debits - avg(prior_months.total_debits))`, floored at `Decimal("0")` if negative or not computable (< 2 monthly_points)
- **"Build Emergency Fund"**: `estimated_impact = projected_savings` — unchanged
- **"Track Monthly Budget"**: stays `Decimal("0")` — genuinely unmeasurable

## Sort order

`items.sort(key=_action_item_sort_key)` where `_action_item_sort_key` returns
`(priority_rank, -estimated_impact)` — high -> medium -> low, then highest impact first within
each tier. Replaced the old plain `items.sort(key=_priority_key)`.

## New helpers added
`_egp()` (2dp ROUND_HALF_UP, mirrors forecaster.py's `_egp`), `_clamp()`,
`_month_over_month_increase()`, `_savings_rate_component()`, `_trend_component()`,
`_concentration_component()`. All pure functions, no I/O.

**Why:** Spec explicitly required removing the flat-penalty model because it only produced a
handful of discrete scores and felt arbitrary; continuous blend moves smoothly with user
behavior. Real impacts make the action feed rankable by EGP value (Part D of the same spec).

**How to apply:** If `CATEGORY_DOMINANCE_THRESHOLD_PCT` or `CATEGORY_REVIEW_THRESHOLD_PCT` are
ever changed, double-check the concentration component's span
(`CATEGORY_CONCENTRATION_FULL_LOSS_PCT - CATEGORY_DOMINANCE_THRESHOLD_PCT`) still makes sense.
If new action items are added, give them a real EGP impact and confirm they're not always
`Decimal("0")` — items with impact 0 always sort last within their priority tier.
