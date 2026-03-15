---
name: Shared types package and Database type
description: Where the Database type lives and how to import it — critical for typed Supabase clients
type: project
---

The `Database` type (and all table row/insert/update aliases) lives in `packages/shared/src/types/database.ts` and is re-exported from `packages/shared/src/types/index.ts`.

Import path in application code: `import type { Database } from '@finpilot/shared'`

The `@finpilot/shared` workspace package is declared as a dependency in `apps/web/package.json` (added during M1).

Convenience aliases already defined and ready to use:
- `UserProfileRow`, `BankAccountRow`, `TransactionRow`, `LoanRow`, `DebtRow`, `DebtPaymentRow`
- `BankAccountInsert`, `TransactionInsert`, `LoanInsert`, `DebtInsert`, `DebtPaymentInsert`
- `BankAccountUpdate`, `TransactionUpdate`, `LoanUpdate`, `DebtUpdate`

The file is auto-generated — regenerate with Supabase MCP `generate_typescript_types` after schema changes.

**Why:** Using `Database` as the generic parameter for `createBrowserClient<Database>` and `createServerClient<Database>` gives end-to-end type safety on all Supabase queries.

**How to apply:** Any time a new Supabase query is written, use the row/insert/update aliases from `@finpilot/shared` rather than writing inline types.
