# ADR-001: Core Database Schema — M1 Foundation Tables

**Date**: 2026-03-15
**Status**: Accepted

## Context

FinPilot needs a persistent storage layer for Egyptian retail banking data scraped
from four banks (NBE, CIB, BDC, UB).  The initial schema must cover user identity,
bank accounts, transactions, bank-originated loans, and a manual debt tracker.
It must be safe for a multi-tenant SaaS environment where each user may hold
accounts at multiple banks.

## Decision

Six tables were created in the `public` schema of a Supabase (PostgreSQL 15) project:

| Table | Purpose |
|---|---|
| `user_profiles` | Extends `auth.users` with display metadata; auto-populated via trigger |
| `bank_accounts` | One row per scraped account; masked account number only |
| `transactions` | Immutable ledger of scraped transactions; deduplication via `(account_id, external_id)` |
| `loans` | Bank-issued credit facilities linked to a `bank_accounts` row |
| `debts` | User-managed informal lending/borrowing tracker |
| `debt_payments` | Repayment events against a `debts` row |

Key schema decisions:

1. **UUID PKs with `gen_random_uuid()`** on all tables — avoids enumeration attacks
   and is safe for distributed inserts from the scraper pipeline.

2. **`user_id` denormalised onto `transactions`** — adds one column in exchange for
   simple, index-friendly RLS policies (`auth.uid() = user_id`) that avoid joins.
   The same pattern is applied to `loans` and `debts`.

3. **`NUMERIC(15, 2)` for all monetary columns** — exact decimal arithmetic; avoids
   IEEE 754 rounding errors that `FLOAT` or `REAL` would introduce for EGP amounts.

4. **`NUMERIC(6, 4)` for `interest_rate`** — supports rates up to 99.9999%, sufficient
   for Egyptian Central Bank policy rates and consumer lending products.

5. **`UNIQUE (account_id, external_id)` on `transactions`** — the pipeline layer can
   use `INSERT ... ON CONFLICT DO NOTHING` for idempotent upserts without risk of
   duplicating transactions across scraper runs.

6. **Three indexes on `transactions`** — `user_id` (RLS fast path), `account_id`
   (join to accounts), `transaction_date DESC` (timeline queries, the most common
   read pattern).

7. **`raw_data JSONB`** on `transactions` — preserves the original scraped payload for
   re-categorisation and debugging without requiring schema migrations when banks
   change their HTML structure.

8. **`handle_new_user()` trigger** — auto-creates a `user_profiles` row on every
   `auth.users` INSERT so the application layer never needs to explicitly provision
   profiles.

9. **`debt_payments` RLS via correlated subquery** — since `debt_payments` has no
   direct `user_id` column, the policy performs `SELECT user_id FROM debts WHERE
   id = debt_id`.  This is safe because the `debts` table is itself RLS-protected.

## Consequences

### Positive
- All tables are 3NF or better — no update anomalies.
- Row Level Security on every table ensures data isolation at the database layer,
  providing defence-in-depth even if application-level auth is bypassed.
- The `(account_id, external_id)` unique constraint makes the scraper pipeline
  stateless and idempotent.
- `raw_data JSONB` decouples the scraper output format from the normalised schema.

### Negative / Trade-offs
- Denormalising `user_id` onto `transactions`, `loans`, and `debts` introduces a
  minor update anomaly risk (if a user's ID ever changed, multiple tables need
  updating).  This is mitigated by the fact that Supabase Auth UUIDs are immutable.
- The correlated-subquery RLS on `debt_payments` adds a per-row lookup cost.  At
  the expected scale (hundreds of payments per user), this is negligible; revisit
  if the table grows to millions of rows.
- `NUMERIC` arithmetic is slower than `FLOAT` on the Postgres query engine.  For
  aggregate queries over large transaction sets, this may require materialized views
  in a future milestone.

## Alternatives Considered

- **Serial integer PKs**: Rejected — exposes internal row counts, not safe for
  multi-tenant public APIs.
- **Storing full account numbers encrypted in `bank_accounts`**: Rejected — FinPilot
  never needs the full number; storing only the last 4 digits eliminates the attack
  surface entirely.
- **Separate `currencies` reference table**: Rejected for M1 — EGP is the dominant
  currency; a `currency TEXT` column with ISO 4217 values is sufficient and avoids
  an unnecessary join on every query.
- **Putting `user_id` only on `bank_accounts` and traversing the FK chain for RLS**:
  Rejected — correlated-subquery RLS on a hot table like `transactions` would be a
  significant performance liability.
