---
name: M6 recommendations modules — debt optimizer and savings detector
description: Documents the two M6 recommendation modules written to disk, their key design decisions, and threshold constants.
type: project
---

`debt_optimizer.py` and `savings.py` were written in M6 under `apps/api/app/recommendations/`.

**Why:** M6 adds the core recommendation engine. These two modules are the computation-only layer (no I/O) called by future router handlers.

**Key constants and rationale:**
- `MAX_MONTHS = 120` (debt_optimizer) — 10-year simulation ceiling; debts unlikely to be relevant beyond this window for budgeting purposes.
- `HIGH_FEE_THRESHOLD = EGP 50` (savings) — chosen to match the agent spec; flags maintenance fees and similar recurring bank charges above this amount.
- `SUBSCRIPTION_AMOUNT_TOLERANCE = 10%` (savings) — allows for minor price increases (e.g. currency fluctuation) while still classifying a charge as recurring.
- `MIN_SUBSCRIPTION_MONTHS = 3` (savings) — requires 3 distinct calendar months before classifying a charge as a subscription; avoids false positives on one-off or seasonal charges.
- `MIN_SPIKE_DATA_POINTS = 3` (savings) — minimum transactions per category needed before spike detection fires; below this, std dev is not meaningful.
- `MAX_OPPORTUNITIES = 10` (savings) — cap on returned findings; prevents overwhelming the UI with low-confidence noise.

**How to apply:** When adding new detection categories to savings.py, maintain the same pattern: pure function returning `list[SavingsOpportunity]`, composed inside `detect_savings_opportunities`. Thresholds should remain module-level constants — never hardcoded inside functions.

**Confidence scoring rules established:**
- debt_optimizer: starts at 1.0, deducted 0.2 for single-debt input, 0.3 when all rates are zero (trivial), 0.15 when majority of debts are informal.
- savings: per-opportunity confidence set by pattern strength (duplicate count, subscription month count, z-score). Overall report confidence = mean of opportunities' scores, zeroed when analysis period < 30 days.

**Recommendation logic:**
- Avalanche is always recommended unless ALL interest rates are zero, in which case snowball is recommended for account-closure momentum.
- `interest_savings` field = snowball_interest - avalanche_interest (positive means avalanche wins, which is the typical case).
