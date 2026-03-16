---
name: M4 Analytics Engine — implementation summary
description: What was built in the M4 analytics milestone, key design decisions, and conventions to maintain going forward
type: project
---

M4 Analytics Engine was implemented under `apps/api/app/analytics/` with four
modules: categorizer, spending, trends, credit.

**Why:** M4 is the analytics milestone for FinPilot; the engine feeds the
recommendations layer and the dashboard API routes.

**How to apply:** When extending any analytics module, follow the conventions
below — they were established during M4 and must remain consistent.

## Key design decisions

### categorizer.py
- Rule engine runs FIRST (no I/O).  AI is only reached when no rule matches.
- API key guard: reads `client._api_key` (private attr on AsyncAnthropic).
  If empty, returns `category="Other", method="rule"` — never raises.
- Model: `claude-haiku-4-5-20251001`
- `categorize_transaction` uses a sentinel UUID
  `00000000-0000-0000-0000-000000000000` because it takes raw field values,
  not a Transaction object.  Call `categorize_batch` when you have Transaction
  instances.
- `categorize_batch` uses `asyncio.Semaphore(concurrency)` — rule-based
  results bypass the semaphore.
- JSON fence stripping: model sometimes wraps JSON in ```json ... ``` blocks;
  `_parse_ai_response` handles this.

### spending.py
- Debits → spending; credits → income.  No mixing.
- Missing category → grouped under "Uncategorized" (not "Other").
- `currency` inferred from first transaction in window; defaults to "EGP".

### trends.py
- All months with data are computed; only the latest `lookback_months` are
  returned in `TrendReport.months`.
- `spending_change_pct` / `income_change_pct` are derived from ALL historical
  months (not just the window), so a 2-month comparison is always the two
  most-recent months overall.
- `_pct_change` returns None (not 0.0) when previous value is zero.

### credit.py
- Credit limit is read from `BankAccount.balance` for `account_type="credit"`.
  Current drawn balance is set to zero (conservative) until the pipeline
  provides per-transaction balance data.
- Thresholds: healthy < 30 %, warning 30–75 %, critical ≥ 75 %.
- `months_remaining` = ceil(outstanding / installment); None when installment ≤ 0.

## CATEGORIES list (canonical, never add to this)
Food & Dining, Shopping, Transportation, Utilities, Healthcare, Education,
Entertainment, Travel, Groceries, Rent & Housing, Transfers, ATM & Cash,
Government & Fees, Insurance, Investment, Other

## Dependency added
`anthropic>=0.40.0` added to `[project].dependencies` in pyproject.toml.
