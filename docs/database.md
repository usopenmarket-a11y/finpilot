# Database and migrations

FinPilot currently depends on an existing hosted Supabase project for Auth and
PostgreSQL. The repository has incremental files in `supabase/migrations`, but
does **not** include the complete initial schema, Auth setup, or every RLS
policy needed to create a new project from zero. The TypeScript type snapshot
is `packages/shared/src/types/database.ts`.

## Migration order

Apply only the migrations that your existing project has not already applied,
in filename order:

| File | Change |
| --- | --- |
| `20260318_expand_account_type.sql` | More bank account types |
| `20260319_add_credit_card_and_certificate_columns.sql` | Credit card and certificate fields |
| `20260526_add_user_profile_preferences.sql` | User preferences |
| `20260616_add_loans_prepaid_sync_job_types.sql` | Sync job types for loans and prepaid cards |
| `20260616_add_prepaid_card_account_type.sql` | Prepaid account type |
| `20260907_fix_data_integrity.sql` | Debt balance triggers, credential ownership, credit card replacement RPC |

The September migration is paired with the newer API and web code in this
working tree. Apply it to the target Supabase project **before** deploying
those application changes. Its debt payment triggers serialize updates and
reject invalid balances. It links bank accounts to the credential that synced
them, deactivates only linked accounts when that credential is deleted, and
adds a service-role-only transaction replacement RPC. Empty scraper sections
retain existing card history because an empty result may be a failed fetch.

Legacy accounts with ambiguous credential labels remain unlinked until their
next successful sync. Debt records previously stored only in an API process's
memory cannot be recovered from that old process after it exits.

The presence of a SQL file in the repository does **not** prove it has run in
the hosted database. Check the project's migration history and schema before
deploying. Back up the target database first, apply the missing migration
through your normal Supabase migration workflow, then regenerate/check shared
types. Never run a migration against production merely to make a local test
pass.

## Integration tests

CI starts a disposable PostgreSQL 17 database called `finpilot_test` and sets
`FINPILOT_TEST_DATABASE_URL`. The integration fixture bootstraps a small legacy
schema, applies the actual September migration, and tests rollback,
concurrency, and access rules. For local runs, use an isolated disposable
database with that name. Do not point the variable at application data.
