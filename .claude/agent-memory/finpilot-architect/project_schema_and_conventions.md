---
name: FinPilot core schema and architectural conventions
description: Full table inventory, RLS patterns, migration sequence, Pydantic conventions, and key design decisions established in M1
type: project
---

## Database tables (all in public schema, Supabase PostgreSQL)

| Table | PK | user_id col | RLS policy style |
|---|---|---|---|
| user_profiles | id UUID (FK auth.users) | id = auth.uid() | SELECT + UPDATE separate policies |
| bank_accounts | id UUID gen_random_uuid() | user_id | FOR ALL with WITH CHECK |
| transactions | id UUID gen_random_uuid() | user_id (denormalised) | FOR ALL with WITH CHECK |
| loans | id UUID gen_random_uuid() | user_id (denormalised) | FOR ALL with WITH CHECK |
| debts | id UUID gen_random_uuid() | user_id | FOR ALL with WITH CHECK |
| debt_payments | id UUID gen_random_uuid() | none — joined via debts | correlated subquery on debts.user_id |
| bank_credentials | id UUID gen_random_uuid() | user_id | four separate policies: SELECT/INSERT/UPDATE/DELETE |
| installments | id UUID gen_random_uuid() | user_id | FOR ALL with WITH CHECK |
| assets | id UUID gen_random_uuid() | user_id | (added post-M9, see migration list) |
| sync_jobs | id UUID gen_random_uuid() (but API inserts explicit id = job_id) | user_id | SELECT-only (defence-in-depth; backend writes via service-role) |

## Migration sequence (applied M1 + M9 + post-M9; full list via list_migrations as of 2026-06-13)
1. create_user_profiles
2. create_bank_accounts
3. create_transactions
4. create_loans
5. create_debts (also creates debt_payments in same migration)
6. create_bank_credentials_table (M9)
7. expand_account_type_values — drops and recreates bank_accounts_account_type_check; migrates 'credit' rows to 'credit_card'
8. add_credit_card_and_certificate_columns (2026-03-19) — adds 5 nullable columns to bank_accounts: credit_limit NUMERIC(15,2), billed_amount NUMERIC(15,2), unbilled_amount NUMERIC(15,2), interest_rate NUMERIC(6,4), maturity_date DATE
9. add_cc_minimum_payment_due_date (2026-03-23) — adds 2 nullable columns to bank_accounts: minimum_payment NUMERIC(15,2), payment_due_date DATE
10. create_installments_table (2026-03-25) — new standalone user-owned table for BNPL/property/vehicle/other structured payment plans; includes update_installments_updated_at() trigger
11. add_credential_label_to_bank_accounts (2026-04-04)
12. create_assets_table (2026-05-25) — includes update_assets_updated_at() trigger, asset_type_enum
13. add_is_gift_to_assets (2026-05-25)
14. add_preferences_to_user_profiles (2026-05-25)
15. add_currency_code_to_assets (2026-05-26)
16. create_sync_jobs_table (2026-06-13) — durable mirror of bank-sync background job state (apps/api/app/routers/sync.py in-memory _JOBS dict). id is both PK and the job_id returned to clients (API inserts explicit id). bank/job_type/status are TEXT+CHECK (job_type: full|accounts|credit_cards|certificates; status: pending|running|complete|failed). credential_id UUID nullable, NO FK (don't block credential deletes). result JSONB, error TEXT, finished_at TIMESTAMPTZ. Index (user_id, status). Reuses existing generic set_updated_at() trigger function (same one bank_credentials uses). RLS: SELECT-only "sync_jobs_select_own" (auth.uid() = user_id) — backend writes via service-role, defence-in-depth only. NOTE: no cleanup job yet for old rows — flagged in table COMMENT for future work.

## bank_accounts.account_type allowed values
savings, current, credit_card, loan, payroll, certificate, deposit
(Note: 'credit' was replaced by 'credit_card' in migration expand_account_type_values; existing rows updated)

## Key design decisions
- Monetary amounts: NUMERIC(15,2) — never FLOAT
- Interest rates: NUMERIC(6,4) — supports up to 99.9999%
- Dedup key on transactions: UNIQUE(account_id, external_id)
- user_id denormalised onto transactions/loans/debts for fast RLS (avoids FK joins)
- raw_data JSONB on transactions preserves original scrape payload
- handle_new_user() trigger auto-provisions user_profiles on auth.users INSERT
- debt_payments RLS uses correlated subquery: SELECT user_id FROM debts WHERE id = debt_id
- bank_accounts nullable type-specific columns: credit_limit/billed_amount/unbilled_amount/minimum_payment/payment_due_date for credit_card accounts; interest_rate/maturity_date for certificate/deposit accounts. No separate tables — sparse columns are simpler given small cardinality per user.
- NBE credit card: billed_amount + unbilled_amount summed into balance; individual amounts also stored in their own columns
- NBE certificate interest_rate stored as decimal fraction (e.g. 15% → 0.1500), parsed from "Interest Rate X% | Maturing DD Mon YYYY" detail line in TRD widget HTML

## Pydantic v2 model file locations
- apps/api/app/models/db.py  — DB-mirror models (one per table)
- apps/api/app/models/api.py — Request/response wire schemas

## Pydantic conventions
- from_attributes=True on all DB-mirror models
- Decimal (not float) for all monetary fields
- Optional[T] = None for nullable DB columns
- Field(description=...) on every field
- Separate Create / Update / Response classes per entity in api.py

## TypeScript types
- Generated by Supabase MCP after every migration
- Saved to packages/shared/src/types/database.ts (re-exported via packages/shared/src/types/index.ts → "@finpilot/shared")
- Full Database type with Tables<>/TablesInsert<>/TablesUpdate<> helpers
- No separate alias file — consumers use Tables<"installments"> etc. directly

## ADRs
- ADR-001: Core database schema — M1 foundation tables (2026-03-15)
- bank_credentials: UNIQUE(user_id, bank), four operation-specific RLS policies, set_updated_at() trigger, encrypted_username/encrypted_password hold AES-256-GCM ciphertext only
- installments: standalone table (not linked to bank_accounts); category CHECK constraint on DB; computed fields (months_elapsed, months_remaining, next_payment_date, is_paid_off) in InstallmentResponse, not stored in DB

## Known minor drift (not yet fixed, low priority)
- db.py SUPPORTED_BANKS / SUPPORTED_BANKS_LITERAL = ("NBE","CIB","BDC","UB") — missing BDC_RETAIL, even though bank_accounts/bank_credentials CHECK constraints and apps/api/app/routers/sync.py's route Literal both include BDC_RETAIL (5 banks total). BankCredential model in db.py uses the narrower 4-bank literal. New sync_jobs table/SyncJobRecord correctly uses a separate SYNC_JOB_BANK_LITERAL with all 5 banks. Consider reconciling SUPPORTED_BANKS_LITERAL to 5 banks in a future cleanup (would need Orchestrator coordination since it's a shared constant).

## sync_jobs model (apps/api/app/models/db.py)
- SyncJobRecord — DB-mirror model for sync_jobs table (from_attributes=True)
- SyncJobResult — nested model for the `result` JSONB column; duplicates the shape of SyncResponse from apps/api/app/routers/sync.py (bank, account_number_masked, transactions_scraped, transactions_saved, synced_at) — duplicated rather than imported to avoid models->routers dependency
- SYNC_JOB_TYPES / SYNC_JOB_TYPE_LITERAL = full|accounts|credit_cards|certificates (maps to the 4 _background_sync_*_task variants)
- SYNC_JOB_STATUSES / SYNC_JOB_STATUS_LITERAL = pending|running|complete|failed
- SYNC_JOB_BANK_LITERAL = NBE|CIB|BDC|BDC_RETAIL|UB (5-bank, matches sync.py route literal)
- sync.py itself was NOT modified — that's a separate refactor task (router-owned file)

## Directory structure (apps/api/app/)
- scrapers/ — bank-specific Playwright scrapers
- pipeline/ — ETL, normalisation, deduplication
- analytics/ — AI categorisation, trend analysis
- recommendations/ — monthly plans, forecasting, debt optimizer
- models/ — Pydantic schemas (owned by Architect Agent)
- tests/ — pytest suite (owned by QA Agent), includes conftest.py
- middleware/ — ASGI middleware (auth guards, rate limiting)

**Why:** M1 foundation decisions that affect every other agent's work. Apply when designing any new table, writing migrations, or creating Pydantic models.
**How to apply:** Follow these patterns for all future schema work. Always check this before creating a new table to avoid convention drift.
