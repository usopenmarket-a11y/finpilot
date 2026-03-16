---
name: Analytics test patterns and fixture conventions
description: Fixture factories and mock patterns established in test_analytics.py for the M4 Analytics Engine
type: project
---

`app/tests/test_analytics.py` established the following reusable patterns:

## Fixture factories (module-level functions, not pytest fixtures)
- `make_transaction(amount, transaction_type, description, category, transaction_date, currency)` — builds a minimal valid `Transaction`
- `make_bank_account(account_type, balance, bank_name)` — builds a minimal valid `BankAccount`
- `make_loan(outstanding, installment, interest_rate, loan_type, next_payment_date)` — builds a minimal valid `Loan`

## Anthropic client mock pattern
```python
client = MagicMock()
client._api_key = "sk-test-fake-key-for-unit-tests"  # must set BOTH attributes
client.api_key  = "sk-test-fake-key-for-unit-tests"
client.messages = MagicMock()
client.messages.create = AsyncMock(return_value=_make_ai_response({...}))
```
- `_make_ai_response(payload: dict)` wraps a dict in the shape `anthropic.Message.content[0].text` returns
- The `mock_anthropic_client` pytest fixture has EMPTY `_api_key` — for testing the no-key path
- Tests that need an active AI path create their own client with a fake key

## Key behavioural contracts confirmed by tests
- Rule engine fires before AI; if any rule matches, `method="rule"`, no API call
- Empty `_api_key` or `api_key` → `method="rule"`, `category="Other"`, no API call
- Large credit threshold is STRICT `>5000` (not `>=5000`)
- `months_remaining` uses ceiling division, returns `None` for zero installment
- `by_category` sorted descending by `total_amount`
- Percentages are rounded to 2dp; sum within 0.1% of 100
- `compute_trends` change_pct is `None` when previous month spending/income is zero (not divide-by-zero)
- Credit account `current_balance` is always `Decimal("0")` until pipeline populates `balance_after`
