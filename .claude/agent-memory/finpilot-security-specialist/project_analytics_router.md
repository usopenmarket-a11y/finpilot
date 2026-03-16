---
name: Analytics router security patterns
description: Security decisions baked into apps/api/app/routers/analytics.py — input constraints, logging rules, and forward-import strategy
type: project
---

The analytics router at `apps/api/app/routers/analytics.py` was built against the following security constraints:

**Why:** Analytics endpoints accept raw financial data (amounts, descriptions, account numbers) — logging any of that is a PII/NON-NEGOTIABLE violation. The analytics sub-modules were not yet implemented at authoring time, requiring a deliberate import strategy.

**How to apply:** Treat all four analytics endpoints as PII-sensitive. Review any future changes against the rules below.

## Input model constraints enforced

- `ConfigDict(extra="forbid")` on every request model — rejects unknown fields.
- `TransactionInput.description`: `max_length=512` to prevent oversized payloads.
- `TransactionInput.amount`: `gt=Decimal("0")` — amounts must be positive.
- `TransactionInput.transaction_type`: regex `^(debit|credit)$` — only valid values accepted.
- `AccountInput.account_number_masked`: regex `^\*+\d{4}$` — enforces the masked format; full account numbers are rejected structurally.
- `AccountInput.account_type` / `LoanInput.loan_type`: regex enums matching `db.py` constants.
- `LoanInput.interest_rate`: `ge=0, le=1` — decimal fraction only, no percentage strings.
- `SpendingRequest.currency` and `AccountInput.currency`: regex `^[A-Z]{3}$` — ISO 4217 format.
- `CategorizeRequest` / `SpendingRequest` list fields: `max_length=500` cap; `TrendsRequest`: `max_length=5000`.

## Logging rules

Only these fields are ever logged (no amounts, descriptions, or account identifiers):
- `transaction_count`, `result_count`, `lookback_months`, `account_count`, `loan_count`

## Decimal type usage

All monetary fields use `Decimal` throughout — no `float` anywhere in request or response models. This is a hard rule for financial correctness and to prevent rounding attacks.

## Forward-compatible import strategy

The four analytics functions (`categorize_batch`, `compute_spending_breakdown`, `compute_trend_report`, `compute_credit_report`) are imported at module top-level. If the analytics agent has not yet implemented a module, the application fails at startup with `ImportError` — not at first request with a silent 500. This is intentional: fail-fast is safer than fail-late for missing security-critical dependencies.

## Transaction reconstruction for categorizer

The `categorize_transactions` handler reconstructs full `Transaction` objects from `TransactionInput` using sentinel UUIDs and `date.today()` for fields the categorizer does not use. This avoids accepting — and therefore logging or persisting — full transaction metadata through the analytics API surface.

## Anthropic client instantiation

`anthropic.AsyncAnthropic` is instantiated per-request (not at module level) using `settings.claude_api_key.get_secret_value()`. Passing `None` when the key is empty relies on the categorizer's graceful degradation. The key value is never logged.

## Period validation

`/analytics/spending` explicitly validates `period_end >= period_start` and raises HTTP 400 before calling analytics logic — prevents the analytics layer from receiving nonsensical date windows.
