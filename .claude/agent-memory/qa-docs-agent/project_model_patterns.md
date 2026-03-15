---
name: Pydantic model test patterns
description: Key model fields, defaults, and validation constraints discovered in app/models/db.py and app/models/api.py
type: project
---

## DB models (app.models.db)

- All models use `ConfigDict(from_attributes=True)` for ORM compatibility.
- Monetary fields (balance, amount, principal_amount, etc.) are `Decimal` — always
  assert `isinstance(field, Decimal)` rather than comparing to float literals.
- `BankAccount`: currency defaults to `"EGP"`, `is_active` defaults to `True`,
  `last_synced_at` defaults to `None`.
- `Transaction`: `is_categorized` defaults to `False`, `currency` defaults to `"EGP"`,
  `raw_data` defaults to `{}`.  The `(account_id, external_id)` pair is the dedup key.
- `Debt`: `status` defaults to `"active"`, `currency` defaults to `"EGP"`.
- `SUPPORTED_BANKS = ("NBE", "CIB", "BDC", "UB")` and `ACCOUNT_TYPES` are module-level
  constants exported from `db.py`.

## API schemas (app.models.api)

- `SignUpRequest`: requires `email` (EmailStr) + `password` (min_length=8). `full_name` optional.
- `DebtCreate` / `DebtPaymentCreate`: `original_amount` / `amount` have `gt=0` — zero and
  negative values raise `ValidationError`.
- `PaginatedResponse`: `page >= 1`, `page_size` in [1, 100].
- `BankAccountUpdate`: all fields optional — constructing with no args is valid.

**How to apply:** When writing model tests, always test: required-field omission raises
ValidationError, numeric constraints (gt, ge, le) at and beyond boundary, and default
field values on a minimal valid construction.
