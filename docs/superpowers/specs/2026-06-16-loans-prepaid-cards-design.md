# Loans & Prepaid Cards — Full Feature Design

## Context

The NBE scraper now extracts all five product types (Accounts, Certificates,
Credit Cards, Loans, Prepaid Cards) and `scrape_loans()` /
`scrape_prepaid_cards()` exist on `NBEScraper`. But Loans and Prepaid Cards
have no way into the product end-to-end from the UI:

- No backend sync endpoints (only `/accounts/sync/{bank}/{accounts,credit-cards,certificates}` exist).
- No dashboard pages or sidebar nav tabs.
- No sync buttons in Settings (the per-item split-sync covers only 3 products).

This feature closes all three gaps. Data already lands via "Sync All", so this
makes Loans and Prepaid Cards first-class, individually syncable, and viewable.

## Scope

In scope (all three layers):
1. Backend split-sync endpoints for loans + prepaid cards.
2. Two new dashboard pages (`/dashboard/loans`, `/dashboard/prepaid-cards`) with
   sidebar nav tabs.
3. Settings sync UI: replace the flat per-item buttons with a single "Sync ▾"
   dropdown covering all 5 products + Sync All.

Out of scope: non-NBE banks (their split endpoints fall back to full `scrape()`
as today); editing/CRUD of loan/prepaid records (read-only views like the
existing certificates page).

## Design-system note

No external UI/UX tooling (Figma / Claude Design) applies to this repo. "Use
UI/UX skills" is honored by following the existing FinPilot design system in
`apps/web`: Tailwind + shadcn/ui primitives (`Card`, `CardBody`, `CardHeader`,
`Badge`, `Button`), the established responsive card-row pattern from
`certificates/page.tsx` (stacks `< sm`, row `≥ sm`), dark mode, and
accessibility (ARIA, keyboard nav, focus-visible rings) consistent with the
existing `sidebar.tsx` mobile drawer and `action-feed.tsx` expander.

## Layer 1 — Backend sync endpoints (`apps/api`)

Owner: backend (any API agent) for `routers/sync.py`; architect for `models/db.py`.

- Extend `SYNC_JOB_TYPES` / `SYNC_JOB_TYPE_LITERAL` in `app/models/db.py` to add
  `"loans"` and `"prepaid_cards"`.
- Add two endpoints in `app/routers/sync.py`, mirroring the existing
  `/accounts/sync/{bank}/credit-cards` endpoint + its
  `_background_sync_credit_cards_task` exactly:
  - `POST /accounts/sync/{bank}/loans` → `_background_sync_loans_task` calling
    `scraper.scrape_loans()` for NBE, falling back to `scraper.scrape()` for
    other banks (same fallback rule the other split endpoints use).
  - `POST /accounts/sync/{bank}/prepaid-cards` → `_background_sync_prepaid_cards_task`
    calling `scraper.scrape_prepaid_cards()` for NBE, full `scrape()` otherwise.
- Each: validate credential exists, return HTTP 202 + `job_id`, run the task
  under `_SCRAPE_SEMAPHORE`, persist to `sync_jobs`, reuse the identical error
  mapping (`ScraperPasswordChangeRequired`, `ScraperLoginError` → "Invalid bank
  credentials", `ScraperTimeoutError` → "Bank portal timed out",
  `ScraperParseError`, `BankPortalUnreachableError`, generic). Pass the new
  `job_type` to `_create_job_in_db`.
- The pipeline already persists whatever `account_type` the scraper returns
  (`loan` is an existing type; `prepaid_card` was added in migration
  `20260616_add_prepaid_card_account_type`), so no pipeline change is needed.

## Layer 2 — Dashboard pages + sidebar nav (`apps/web`)

Owner: frontend.

### `/dashboard/loans/page.tsx`
Async server component mirroring `certificates/page.tsx`:
- Fetch `bank_accounts` where `is_active = true` and `account_type = 'loan'`,
  plus `bank_credentials` for credential labels (same dual `Promise.all` query).
- Header: title "Loans & Finances", subtitle, and total outstanding balance
  (sum of balances) on the right when non-empty.
- One card per loan: a `LoanRow` showing bank + masked account number,
  credential label chip, an outstanding-balance figure (right-aligned,
  `tabular-nums`), and a "Loan" badge. Negative/owed balances styled
  appropriately. Reuse the certificates row visual structure.
- Empty state card ("No loans found · synced loans will appear here") when none.

### `/dashboard/prepaid-cards/page.tsx`
Same pattern, `account_type = 'prepaid_card'`:
- Header "Prepaid Cards" + total balance.
- `PrepaidCardRow`: card icon, masked card number (`account_number_masked`),
  bank + credential label, balance right-aligned, "Prepaid" badge. Expiry shown
  if present in the masked number / available field.
- Empty state when none.

### Sidebar (`components/layout/sidebar.tsx`)
Add two `NAV_ITEMS`, flat, grouped near related items:
- `{ href: '/dashboard/loans', label: 'Loans', icon: <LoansIcon /> }` placed
  immediately after the Debts item.
- `{ href: '/dashboard/prepaid-cards', label: 'Prepaid Cards', icon: <PrepaidCardIcon /> }`
  placed immediately after the Credit Cards item.
Add two new inline SVG icon components matching the existing 20×20,
`strokeWidth={1.75}` style. The mobile drawer renders the new items
automatically (no drawer change needed).

## Layer 3 — Settings sync dropdown (`apps/web`)

Owner: frontend. File: `components/settings/bank-accounts-section.tsx`.

Replace the three flat per-item buttons (Accounts / Cards / Certificates) for
NBE credentials with one **"Sync ▾" dropdown**:
- Trigger button "Sync ▾" (shows the active phase label + spinner while a sync
  runs; disabled during any active sync for that credential).
- Menu items: Accounts · Credit Cards · Certificates · Loans · Prepaid Cards ·
  (divider) · Sync All. Selecting an item runs that single phase via
  `handleSyncItem(cred, domain)` (existing) extended to the two new domains;
  "Sync All" calls `handleSync(cred)`.
- The menu closes on select, on outside-click, and on Escape; it is keyboard
  navigable with `role="menu"` / `role="menuitem"`, `aria-expanded`, and
  focus-visible styling, consistent with the app's accessibility conventions.
  Implemented as a small local dropdown (no new dependency) using a `useState`
  open flag + a click-outside handler, matching the codebase's existing
  hand-rolled interactive components.
- Non-NBE credentials keep a single "Sync" button (unchanged).

Supporting changes:
- `lib/api-client.ts`: add `syncBankLoans(accessToken, bank, credentialId?)` and
  `syncBankPrepaidCards(...)` following the existing `syncBankCreditCards`
  pattern (POST the new endpoints, poll via `_pollSyncJob`). Use an 8-minute
  poll cap (loans/prepaid are light, single-product) — match `syncBankCreditCards`.
- Extend the `SyncDomain` type and `NBE_SYNC_PHASES` to include `'loans'` and
  `'prepaid_cards'` so "Sync All" runs all five sequentially, and
  `handleSyncItem` routes the two new domains to the new client functions.
- Update `SYNC_DOMAINS` (the coverage-bar domains) only if the coverage bar
  should reflect loans/prepaid; otherwise leave coverage as-is and note it.

## Mobile & responsiveness

- New pages reuse the certificates responsive layout: card rows stack vertically
  below `sm` and become horizontal at `sm+`; totals move below the title on
  small screens. Already mobile-proven.
- The Settings dropdown is the primary mobile win: it collapses 5 per-item
  buttons + Sync All into a single tap target, keeping the action row from
  overflowing on narrow screens.
- Verify both new pages and the dropdown at a mobile width (~375px) and desktop.

## Error handling

- Backend: per-endpoint error mapping identical to existing split endpoints; one
  product's failure is isolated to its own job.
- Frontend: each dropdown action shows its own per-credential error/result line
  (existing `syncStates` mechanism); "Sync All" stops at the first failing phase
  and surfaces which phase failed (existing behavior).

## Testing

- Backend: extend `app/tests/test_sync.py` with happy-path + credential-missing
  tests for the two new endpoints (202 + job creation, job_type recorded).
  `ruff format --check`, `ruff check`, `mypy app/`, `pytest` all green.
- Frontend: `pnpm --filter web type-check` and `pnpm --filter web lint` green.
  Manual: dev server + screenshots of `/dashboard/loans`,
  `/dashboard/prepaid-cards`, and the Settings sync dropdown at desktop and
  ~375px mobile widths.
