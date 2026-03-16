---
name: M9 Real Data Wiring — patterns and contracts
description: M9 connected frontend to real Supabase data and added bank credential management with server-side encryption
type: project
---

M9 replaced all mock data on the dashboard and added a live bank credential management UI.

**Why:** Backend now has working credential storage and scrape-to-pipeline endpoints — time to wire the frontend to real data.

**Key patterns established in M9:**

### Server-side encryption flow
- Frontend NEVER holds the AES-256-GCM key
- Before calling `POST /api/v1/accounts/credentials`, the frontend calls `POST /api/v1/utils/encrypt` twice (username, then password) to get opaque tokens
- Only the tokens travel from browser to backend; plaintext credentials are ephemeral in the browser's call stack only
- `apps/api/app/routers/utils.py` — the encrypt helper endpoint (never logs the value)
- `apps/api/app/routers/sync.py` — reads stored credentials from Supabase, runs scraper+pipeline, returns result

### Credential management UI
- `apps/web/src/components/settings/bank-accounts-section.tsx` — self-contained client component
- Pattern: fetch userId from Supabase Auth, then call API with `x-user-id` header
- Sync state is tracked per-bank key in a `Record<string, SyncState>` map
- "Sync Now" calls `POST /api/v1/accounts/sync/{bank}` — no credentials travel from browser (backend reads them from DB)
- Remove button calls `DELETE /api/v1/accounts/credentials/{bank}` and does an optimistic list update

### Typed API client
- `apps/web/src/lib/api-client.ts` — all backend calls go through this typed client
- `apiFetch<T>` helper handles `x-user-id` header injection, JSON parse, 204 No Content, and error extraction from `{detail: string}` response bodies
- Exported functions: `encryptValue`, `listCredentials`, `saveCredential`, `deleteCredential`, `syncBank`

### Dashboard real data (server component)
- `apps/web/src/app/dashboard/page.tsx` is now a full async Server Component
- Uses `createClient()` from `@/lib/supabase/server` — RLS enforces user isolation automatically
- Fetches `bank_accounts` and last 50 `transactions` in parallel via `Promise.all`
- KPIs: totalBalance = sum of bank_account.balance; monthlyIncome/Expenses filtered by current month start ISO string
- Health score = `50 + savings_rate_pts (0–30) + tx_volume_pts (0–20)` — returns 50 when no data
- Spending categories: debit transactions in current month, grouped by `category`, top 6, with fallback color `#6b7280`
- Empty-state copy: "Connect a bank account in Settings to see your real data"

**How to apply:** When adding more real-data features, follow the same server-component pattern for read paths and the `api-client.ts` typed helper for write/mutate paths. Never fetch data in a client component unless it requires user interaction.
