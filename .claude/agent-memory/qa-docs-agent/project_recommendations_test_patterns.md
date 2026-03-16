---
name: M6 Recommendations Engine test patterns and known bugs
description: Router wire-format gap (transaction_count), savings.py empty-sum bug, mini-app pattern for isolated router testing, and recommendation module contracts
type: project
---

## Recommendation module locations

- `app/recommendations/monthly_plan.py` — `generate_monthly_plan(spending, trends, target_month, target_year)`
- `app/recommendations/forecaster.py` — `generate_forecast(trends, from_date=None)`
- `app/recommendations/debt_optimizer.py` — `optimize_debt_payoff(debts, monthly_budget)`
- `app/recommendations/savings.py` — `detect_savings_opportunities(transactions)`
- `app/routers/recommendations.py` — exists; NOT yet wired into `app/main.py`

## Router wire-format gap

`app/routers/recommendations.py` defines `CategoryBreakdownInput` with a **required `transaction_count: int`** field. The monthly_plan domain model (`CategoryBreakdown`) does NOT have this field — the router strips it during bridging. Any HTTP test payload for the monthly-plan endpoint must include `transaction_count` in each category object or it will get a 422.

## Known source bug: savings.py empty-opportunity sum

`savings.py` line 546:
```python
total_saving = _round(
    sum(o.estimated_monthly_saving for o in top_opportunities)
)
```
When `top_opportunities` is empty, `sum(generator)` returns `int(0)`, causing `AttributeError: 'int' object has no attribute 'quantize'` inside `_round()`.

Fix (Backend Agent): add the Decimal start value:
```python
sum((o.estimated_monthly_saving for o in top_opportunities), Decimal("0"))
```

Affected call paths: empty transaction list, credit-only input, or any input that produces zero detectable opportunities.

Four unit tests in `test_recommendations.py` intentionally fail as regression tests for this bug:
- `test_savings_no_opportunities_clean_data`
- `test_savings_only_debits_analyzed`
- `test_savings_empty_transactions`
- `test_savings_analysis_period_days_is_correct`

## Mini-app pattern for isolated router testing

Because `app/main.py` does not yet import the recommendations router, HTTP tests build their own mini-app:
```python
mini_app = FastAPI(title="FinPilot Recommendations Test App")
mini_app.include_router(rec_router.router, prefix="/api/v1")
```
All HTTP tests are guarded with `@pytest.mark.skipif(_ROUTER_MISSING, ...)` so they skip gracefully if the router module is deleted or renamed.

## Module contracts confirmed by tests

### monthly_plan
- Base health = 1.0; subtract 0.3 (up-trend), 0.2 (negative net), 0.1 (any category > 40%)
- Clamp to [0.0, 1.0]
- projected_savings = max(avg_income − avg_spend, 0)
- confidence = 0.4 if lookback < 3, else 0.85
- Action items sorted high → medium → low (stable within tier)

### forecaster
- Always exactly 3 ForecastPoints
- Confidence: 0.9, 0.8, 0.7 per month (with sufficient history)
- "up" trend: expenses grow each month; "down": shrink; "flat": identical
- `from_date` sets the reference; first forecast month is `from_date` + 1 month
- December wrap: from_date=Nov 2025 → months Dec 2025, Jan 2026, Feb 2026

### debt_optimizer
- With any non-zero rate: recommended_strategy = "avalanche"
- All zero rates: recommended_strategy = "snowball"
- avalanche.total_interest_paid <= snowball.total_interest_paid (always)
- interest_savings = snowball.total_interest_paid − avalanche.total_interest_paid
- Debts with outstanding_balance = 0 are silently filtered before simulation

### savings
- HIGH_FEE_THRESHOLD = 50.00 EGP; keywords: "fee", "charge", "رسوم", "عمولة"
- Recurring subscription: description in 3+ distinct months within 10% amount tolerance
- Duplicate charge: same (description, amount, year-month) ≥ 2 times
- Only debits are analyzed; credits are silently ignored
- overall confidence = 0.0 when analysis_period_days < 30
- analysis_period_days = max_date − min_date + 1 (0 for empty list)

**Why:** To prevent repeated investigation of the same test failures on future runs.
**How to apply:** Before writing any new recommendations tests, check this entry for known contract edge cases and the savings bug status.
