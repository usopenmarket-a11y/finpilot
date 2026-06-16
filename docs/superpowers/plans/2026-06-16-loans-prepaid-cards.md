# Loans & Prepaid Cards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make NBE Loans and Prepaid Cards first-class: individually syncable from Settings, viewable on their own dashboard pages, reachable from the sidebar.

**Architecture:** Backend adds two split-sync endpoints mirroring the existing credit-cards endpoint. Frontend adds two read-only server-component pages mirroring the certificates page, two sidebar nav items, and converts the Settings per-item sync buttons into a single accessible "Sync ▾" dropdown.

**Tech Stack:** FastAPI + Pydantic v2 (backend), Next.js 15 server components + Tailwind + shadcn/ui (frontend), Supabase.

**Spec:** `docs/superpowers/specs/2026-06-16-loans-prepaid-cards-design.md`

---

## File Structure

- `apps/api/app/models/db.py` (modify) — add `"loans"`, `"prepaid_cards"` to `SYNC_JOB_TYPES` / `SYNC_JOB_TYPE_LITERAL`.
- `apps/api/app/routers/sync.py` (modify) — 2 background tasks + 2 endpoints.
- `apps/api/app/tests/test_sync.py` (modify) — tests for the 2 endpoints.
- `apps/web/src/app/dashboard/loans/page.tsx` (create) — loans page.
- `apps/web/src/app/dashboard/prepaid-cards/page.tsx` (create) — prepaid cards page.
- `apps/web/src/components/layout/sidebar.tsx` (modify) — 2 nav items + 2 icons.
- `apps/web/src/lib/api-client.ts` (modify) — `syncBankLoans`, `syncBankPrepaidCards`.
- `apps/web/src/components/settings/bank-accounts-section.tsx` (modify) — dropdown + new domains.

---

## Task 1: Backend — extend sync job types

**Files:**
- Modify: `apps/api/app/models/db.py`

- [ ] **Step 1: Add the two new job types**

In `apps/api/app/models/db.py`, find:

```python
SYNC_JOB_TYPES = ("full", "accounts", "credit_cards", "certificates")
SYNC_JOB_TYPE_LITERAL = Literal["full", "accounts", "credit_cards", "certificates"]
```

Replace with:

```python
SYNC_JOB_TYPES = (
    "full",
    "accounts",
    "credit_cards",
    "certificates",
    "loans",
    "prepaid_cards",
)
SYNC_JOB_TYPE_LITERAL = Literal[
    "full", "accounts", "credit_cards", "certificates", "loans", "prepaid_cards"
]
```

Also update the field description string near it that enumerates the variants (search for `"Which background sync variant"`) to append `, loans, prepaid_cards`.

- [ ] **Step 2: Verify it compiles**

Run: `cd apps/api && uv run python -c "from app.models.db import SYNC_JOB_TYPES; print(SYNC_JOB_TYPES)"`
Expected: prints the 6-tuple including `loans` and `prepaid_cards`.

- [ ] **Step 3: Commit**

```bash
git add apps/api/app/models/db.py
git commit -m "feat(api): add loans and prepaid_cards sync job types"
```

---

## Task 2: Backend — loans + prepaid background tasks

**Files:**
- Modify: `apps/api/app/routers/sync.py`

The existing `_background_sync_cc_task(job_id, user_id, bank, credential_id)` (around line 647-825) is the exact template. Create two near-identical copies.

- [ ] **Step 1: Add `_background_sync_loans_task`**

Copy the entire `_background_sync_cc_task` function and paste it immediately after `_background_sync_cc_task` ends. In the copy, rename the function to `_background_sync_loans_task` and make ONLY these substitutions:
- The scraper call inside `if bank == "NBE":` block: change `result = await scraper.scrape_credit_cards()` → `result = await scraper.scrape_loans()`.
- All log message strings: replace `"CC-only sync initiated via stored credentials"` → `"Loans-only sync initiated via stored credentials"`, `"CC sync failed: ..."` → `"Loans sync failed: ..."`, `"CC sync completed"` → `"Loans sync completed"`, `"Pipeline failed during CC sync ..."` → `"Pipeline failed during loans sync ..."`, `"Background CC sync task failed unexpectedly"` → `"Background loans sync task failed unexpectedly"`.
- Leave EVERYTHING else identical (credential fetch, decrypt, semaphore, error mapping, pipeline call, empty-accounts handling, `last_synced_at` update, `SyncResponse`).

- [ ] **Step 2: Add `_background_sync_prepaid_cards_task`**

Repeat Step 1 with these substitutions instead:
- Function name → `_background_sync_prepaid_cards_task`.
- Scraper call → `result = await scraper.scrape_prepaid_cards()`.
- Log strings `"CC..."` → `"Prepaid-cards..."` equivalents (`"Prepaid-cards-only sync initiated via stored credentials"`, `"Prepaid cards sync failed: ..."`, `"Prepaid cards sync completed"`, `"Pipeline failed during prepaid cards sync ..."`, `"Background prepaid cards sync task failed unexpectedly"`).

- [ ] **Step 3: Verify it imports**

Run: `cd apps/api && uv run python -c "import app.routers.sync"`
Expected: no error.

- [ ] **Step 4: Commit**

```bash
git add apps/api/app/routers/sync.py
git commit -m "feat(api): add loans and prepaid-cards background sync tasks"
```

---

## Task 3: Backend — loans + prepaid endpoints

**Files:**
- Modify: `apps/api/app/routers/sync.py`

The existing `start_sync_cc_job` (around line 1239-1287) decorated with `@router.post("/accounts/sync/{bank}/credit-cards", ...)` is the template.

- [ ] **Step 1: Add the loans endpoint**

Copy the entire `start_sync_cc_job` function (including its `@router.post(...)` decorator) and paste it after the certificates endpoint. In the copy make ONLY these changes:
- Decorator path: `"/accounts/sync/{bank}/credit-cards"` → `"/accounts/sync/{bank}/loans"`.
- Decorator `summary=`: `"Start a credit-card-only sync job"` → `"Start a loans-only sync job"`.
- Function name: `start_sync_cc_job` → `start_sync_loans_job`.
- The `_create_job_in_db(...)` call's last arg: `"credit_cards"` → `"loans"`.
- The background task call: `_background_sync_cc_task(...)` → `_background_sync_loans_task(...)`.
- Docstring: replace "credit card accounts and statement transactions" / `scrape_credit_cards()` references with loans equivalents (`scraper.scrape_loans()`).

- [ ] **Step 2: Add the prepaid-cards endpoint**

Repeat Step 1 with:
- Path → `"/accounts/sync/{bank}/prepaid-cards"`.
- summary → `"Start a prepaid-cards-only sync job"`.
- Function name → `start_sync_prepaid_cards_job`.
- `_create_job_in_db` last arg → `"prepaid_cards"`.
- Task call → `_background_sync_prepaid_cards_task(...)`.
- Docstring → `scraper.scrape_prepaid_cards()`.

- [ ] **Step 3: Verify routes register**

Run: `cd apps/api && uv run python -c "from app.main import app; print([r.path for r in app.routes if 'loans' in r.path or 'prepaid' in r.path])"`
Expected: lists `/api/v1/accounts/sync/{bank}/loans` and `/api/v1/accounts/sync/{bank}/prepaid-cards`.

- [ ] **Step 4: Commit**

```bash
git add apps/api/app/routers/sync.py
git commit -m "feat(api): add loans and prepaid-cards sync endpoints"
```

---

## Task 4: Backend — endpoint tests

**Files:**
- Modify: `apps/api/app/tests/test_sync.py`

- [ ] **Step 1: Find the existing CC endpoint test**

Run: `cd apps/api && grep -n "credit-cards\|sync_cc\|start_sync_cc" app/tests/test_sync.py`
Read the existing credit-cards endpoint test(s) to learn the fixture/mock style (how it mocks `_validate_credentials_exist`, the scraper, and asserts 202 + `job_id`).

- [ ] **Step 2: Write the loans + prepaid endpoint tests**

Add two tests mirroring the CC endpoint test exactly, but POSTing to `/api/v1/accounts/sync/NBE/loans` and `/api/v1/accounts/sync/NBE/prepaid-cards` respectively. Each asserts: status 202, response JSON has a `job_id` (non-empty string) and `status == "pending"`. Use the same auth/credential mocking the CC test uses. If the CC test also asserts a 404 when no credentials exist, add the equivalent missing-credential test for at least one of the two new endpoints.

- [ ] **Step 3: Run the new tests**

Run: `cd apps/api && uv run pytest app/tests/test_sync.py -v -k "loan or prepaid"`
Expected: PASS.

- [ ] **Step 4: Full backend gate**

Run: `cd apps/api && uv run ruff format . && uv run ruff check . && uv run mypy app/ && uv run pytest app/tests/test_sync.py -q`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/tests/test_sync.py
git commit -m "test(api): cover loans and prepaid-cards sync endpoints"
```

---

## Task 5: Frontend — sidebar nav items + icons

**Files:**
- Modify: `apps/web/src/components/layout/sidebar.tsx`

- [ ] **Step 1: Add two icon components**

In `sidebar.tsx`, after the existing `AssetsIcon` function (around line 93), add:

```tsx
function LoansIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.75}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
    </svg>
  );
}

function PrepaidCardIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.75}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M3 10h18M7 15h4m-7 4h12a3 3 0 003-3V8a3 3 0 00-3-3H6a3 3 0 00-3 3v8a3 3 0 003 3z" />
    </svg>
  );
}
```

- [ ] **Step 2: Add the nav items in grouped positions**

In the `NAV_ITEMS` array, insert `Prepaid Cards` immediately after the Credit Cards item, and `Loans` immediately after the Debts item:

```tsx
const NAV_ITEMS: NavItem[] = [
  { href: '/dashboard', label: 'Dashboard', icon: <DashboardIcon /> },
  { href: '/dashboard/accounts', label: 'Accounts', icon: <AccountsIcon /> },
  { href: '/dashboard/transactions', label: 'Transactions', icon: <TransactionsIcon /> },
  { href: '/dashboard/credit-cards', label: 'Credit Cards', icon: <CreditCardIcon /> },
  { href: '/dashboard/prepaid-cards', label: 'Prepaid Cards', icon: <PrepaidCardIcon /> },
  { href: '/dashboard/certificates', label: 'Certificates & Deposits', icon: <CertificateIcon /> },
  { href: '/dashboard/assets', label: 'Assets', icon: <AssetsIcon /> },
  { href: '/dashboard/debts', label: 'Debts', icon: <DebtsIcon /> },
  { href: '/dashboard/loans', label: 'Loans', icon: <LoansIcon /> },
  { href: '/dashboard/installments', label: 'Installments', icon: <InstallmentsIcon /> },
  { href: '/dashboard/recommendations', label: 'Recommendations', icon: <RecommendationsIcon /> },
  { href: '/dashboard/settings', label: 'Settings', icon: <SettingsIcon /> },
];
```

- [ ] **Step 3: Type-check**

Run: `cd apps/web && pnpm type-check`
Expected: no errors (the two new routes won't 404 in TS — `Link href` is a string).

- [ ] **Step 4: Commit**

```bash
git add apps/web/src/components/layout/sidebar.tsx
git commit -m "feat(web): add Loans and Prepaid Cards sidebar nav items"
```

---

## Task 6: Frontend — Loans page

**Files:**
- Create: `apps/web/src/app/dashboard/loans/page.tsx`

The existing `apps/web/src/app/dashboard/certificates/page.tsx` is the template. Read it first, then create the loans page following the same structure (server component, `force-dynamic`, dual `Promise.all` query, `BANK_CODE_TO_NAME` map, total + empty state).

- [ ] **Step 1: Create the page**

Create `apps/web/src/app/dashboard/loans/page.tsx`:

```tsx
import { createClient } from '@/lib/supabase/server';
import { Card, CardBody, CardHeader } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';

export const dynamic = 'force-dynamic';
import type { Database } from '@finpilot/shared';

type BankAccountRow = Database['public']['Tables']['bank_accounts']['Row'];
type BankCredentialRow = Database['public']['Tables']['bank_credentials']['Row'];

function formatEGP(amount: number): string {
  return new Intl.NumberFormat('en-EG', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amount);
}

function formatCurrency(amount: number, currency: string): string {
  return `${currency} ${formatEGP(amount)}`;
}

const BANK_CODE_TO_NAME: Record<string, string> = {
  NBE: 'National Bank of Egypt',
  CIB: 'Commercial International Bank',
  BDC: 'Banque Du Caire (ibanking)',
  BDC_RETAIL: 'Banque Du Caire (Retail)',
  UB: 'United Bank',
};

function LoanRow({ account, credentialLabel }: { account: BankAccountRow; credentialLabel?: string }) {
  const balance = parseFloat(String(account.balance));
  const owed = balance < 0 ? Math.abs(balance) : balance;

  return (
    <div className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 overflow-hidden">
      <div className="flex flex-col justify-between gap-4 px-4 py-4 sm:flex-row sm:items-center sm:px-5">
        <div className="flex min-w-0 items-center gap-4">
          <div className="h-10 w-10 rounded-full bg-rose-100 dark:bg-rose-900/30 flex items-center justify-center flex-shrink-0">
            <svg className="h-5 w-5 text-rose-600 dark:text-rose-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.75}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-gray-900 dark:text-white">
              {account.bank_name}
            </p>
            <p className="mt-0.5 truncate text-xs text-gray-500 dark:text-gray-400">
              <span className="font-mono">{account.account_number_masked}</span>
            </p>
            {credentialLabel && (
              <span className="mt-1 inline-flex max-w-full items-center gap-1 rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-500 dark:bg-gray-800 dark:text-gray-400">
                <span className="truncate">{credentialLabel}</span>
              </span>
            )}
          </div>
        </div>
        <div className="flex w-full flex-wrap items-center justify-between gap-4 sm:w-auto sm:justify-end sm:gap-6">
          <Badge variant="danger">Loan</Badge>
          <div className="text-right">
            <p className="text-xs text-gray-500 dark:text-gray-400">Outstanding</p>
            <p className="break-words text-sm font-bold tabular-nums text-gray-900 dark:text-white">
              {formatCurrency(owed, account.currency)}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

export default async function LoansPage() {
  const supabase = await createClient();
  const { data: { user } } = await supabase.auth.getUser();
  const userId = user?.id ?? '';

  const [{ data }, { data: credData }] = await Promise.all([
    supabase
      .from('bank_accounts')
      .select('*')
      .eq('user_id', userId)
      .eq('is_active', true)
      .eq('account_type', 'loan'),
    supabase
      .from('bank_credentials')
      .select('bank, label')
      .eq('user_id', userId),
  ]);

  const accounts: BankAccountRow[] = data ?? [];

  const bankNameToLabel: Record<string, string> = {};
  for (const cred of ((credData ?? []) as Pick<BankCredentialRow, 'bank' | 'label'>[])) {
    const displayName = BANK_CODE_TO_NAME[cred.bank] ?? cred.bank;
    bankNameToLabel[displayName] = cred.label ?? cred.bank;
  }

  const totalOwed = accounts.reduce((s, a) => {
    const b = parseFloat(String(a.balance));
    return s + (b < 0 ? Math.abs(b) : b);
  }, 0);

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6 sm:space-y-8">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Loans &amp; Finances</h1>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
            Your outstanding loan and finance balances
          </p>
        </div>
        {accounts.length > 0 && (
          <div className="sm:text-right">
            <p className="text-xs text-gray-500 dark:text-gray-400">Total Outstanding</p>
            <p className="text-xl font-bold text-gray-900 dark:text-white tabular-nums">
              EGP {formatEGP(totalOwed)}
            </p>
          </div>
        )}
      </div>

      {accounts.length === 0 ? (
        <Card>
          <CardBody className="py-16 text-center">
            <svg className="mx-auto h-12 w-12 text-gray-300 dark:text-gray-600 mb-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <p className="text-base font-medium text-gray-900 dark:text-white mb-1">No loans found</p>
            <p className="text-sm text-gray-500 dark:text-gray-400">
              Synced loans and finances will appear here. Run a sync in Settings.
            </p>
          </CardBody>
        </Card>
      ) : (
        <Card>
          <CardHeader>
            <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
              <h2 className="text-base font-semibold text-gray-900 dark:text-white">All Loans</h2>
              <span className="text-sm text-gray-500 dark:text-gray-400">
                {accounts.length} loan{accounts.length !== 1 ? 's' : ''}
              </span>
            </div>
          </CardHeader>
          <CardBody className="space-y-3">
            {accounts.map((account) => (
              <LoanRow key={account.id} account={account} credentialLabel={bankNameToLabel[account.bank_name]} />
            ))}
          </CardBody>
        </Card>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Type-check + lint**

Run: `cd apps/web && pnpm type-check && pnpm lint`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add apps/web/src/app/dashboard/loans/page.tsx
git commit -m "feat(web): add Loans dashboard page"
```

---

## Task 7: Frontend — Prepaid Cards page

**Files:**
- Create: `apps/web/src/app/dashboard/prepaid-cards/page.tsx`

- [ ] **Step 1: Create the page**

Create `apps/web/src/app/dashboard/prepaid-cards/page.tsx` — same structure as Task 6, with these differences: title "Prepaid Cards", subtitle "Your prepaid card balances", query `.eq('account_type', 'prepaid_card')`, badge text "Prepaid" with `variant="info"`, the balance label "Balance" (not "Outstanding"), `totalBalance` is a plain sum (no abs), the row icon is the credit-card SVG path `M3 10h18M7 15h4m-7 4h12a3 3 0 003-3V8a3 3 0 00-3-3H6a3 3 0 00-3 3v8a3 3 0 003 3z` in `bg-indigo-100 dark:bg-indigo-900/30` / `text-indigo-600 dark:text-indigo-400`, and the empty-state copy "No prepaid cards found". Copy the full Task 6 file and apply exactly those substitutions; keep `BANK_CODE_TO_NAME`, the `Promise.all` query shape, and the responsive layout identical.

- [ ] **Step 2: Type-check + lint**

Run: `cd apps/web && pnpm type-check && pnpm lint`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add apps/web/src/app/dashboard/prepaid-cards/page.tsx
git commit -m "feat(web): add Prepaid Cards dashboard page"
```

---

## Task 8: Frontend — API client functions

**Files:**
- Modify: `apps/web/src/lib/api-client.ts`

The existing `syncBankCreditCards` (around line 316) is the template.

- [ ] **Step 1: Add `syncBankLoans` and `syncBankPrepaidCards`**

After `syncBankCreditCards`, add:

```ts
/**
 * Sync NBE loan / finance accounts only.
 * Falls back to full scrape for non-NBE banks.
 * Timeout: 8 minutes.
 */
export async function syncBankLoans(
  accessToken: string,
  bank: 'NBE' | 'CIB' | 'BDC' | 'BDC_RETAIL' | 'UB',
  credentialId?: string,
): Promise<SyncResult> {
  const qs = credentialId ? `?credential_id=${credentialId}` : '';
  const jobStart = await apiFetch<SyncJobStartResponse>(
    `/api/v1/accounts/sync/${bank}/loans${qs}`,
    { method: 'POST', accessToken }
  );
  const maxWaitMs = 8 * 60 * 1000;
  return _pollSyncJob(accessToken, jobStart.job_id, maxWaitMs);
}

/**
 * Sync NBE prepaid card accounts only.
 * Falls back to full scrape for non-NBE banks.
 * Timeout: 8 minutes.
 */
export async function syncBankPrepaidCards(
  accessToken: string,
  bank: 'NBE' | 'CIB' | 'BDC' | 'BDC_RETAIL' | 'UB',
  credentialId?: string,
): Promise<SyncResult> {
  const qs = credentialId ? `?credential_id=${credentialId}` : '';
  const jobStart = await apiFetch<SyncJobStartResponse>(
    `/api/v1/accounts/sync/${bank}/prepaid-cards${qs}`,
    { method: 'POST', accessToken }
  );
  const maxWaitMs = 8 * 60 * 1000;
  return _pollSyncJob(accessToken, jobStart.job_id, maxWaitMs);
}
```

- [ ] **Step 2: Type-check**

Run: `cd apps/web && pnpm type-check`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add apps/web/src/lib/api-client.ts
git commit -m "feat(web): add syncBankLoans and syncBankPrepaidCards clients"
```

---

## Task 9: Frontend — Settings sync dropdown

**Files:**
- Modify: `apps/web/src/components/settings/bank-accounts-section.tsx`

First read this file fully — note the `SyncDomain` type (currently `'accounts' | 'cards' | 'certificates'`), `NBE_SYNC_PHASES`, `handleSyncItem`, `handleSync`, the imports (`syncBank*` functions), and the actions block where the 3 per-item buttons + "Sync All" + Edit + Remove render.

- [ ] **Step 1: Extend the SyncDomain type and phases**

Change the `SyncDomain` type to add the two domains:

```ts
type SyncDomain = 'accounts' | 'cards' | 'certificates' | 'loans' | 'prepaid_cards';
```

Add to `NBE_SYNC_PHASES` (after the certificates entry):

```ts
  { key: 'loans', label: 'loans' },
  { key: 'prepaid_cards', label: 'prepaid cards' },
```

Note: `SYNC_DOMAINS` (the coverage-bar list) is intentionally left covering the original 3 — do NOT add loans/prepaid to it (per spec; the coverage bar stays as-is). If `SYNC_DOMAINS` and `SyncDomain` are coupled such that this causes a type error, add the two domains to `SYNC_DOMAINS` too but with the existing visual treatment.

- [ ] **Step 2: Import the new client functions**

In the import block that pulls `syncBankCreditCards`, add `syncBankLoans` and `syncBankPrepaidCards`.

- [ ] **Step 3: Route the new domains in `handleSyncItem`**

In `handleSyncItem`, the phase-key dispatch (currently calls `syncBankAccounts` / `syncBankCreditCards` / `syncBankCertificates` based on the phase key inside `runNbePhase`) must handle `'loans'` and `'prepaid_cards'`. Find the dispatch inside `runNbePhase`:

```ts
      if (phase.key === 'accounts') {
        return await syncBankAccounts(accessToken, bank, cred.id);
      } else if (phase.key === 'cards') {
        return await syncBankCreditCards(accessToken, bank, cred.id);
      }
      return await syncBankCertificates(accessToken, bank, cred.id);
```

Replace with:

```ts
      if (phase.key === 'accounts') {
        return await syncBankAccounts(accessToken, bank, cred.id);
      } else if (phase.key === 'cards') {
        return await syncBankCreditCards(accessToken, bank, cred.id);
      } else if (phase.key === 'certificates') {
        return await syncBankCertificates(accessToken, bank, cred.id);
      } else if (phase.key === 'loans') {
        return await syncBankLoans(accessToken, bank, cred.id);
      }
      return await syncBankPrepaidCards(accessToken, bank, cred.id);
```

- [ ] **Step 4: Add a reusable SyncDropdown component**

At the top of the file (after imports, before the main component or co-located above it), add a self-contained dropdown. It takes the list of options and an `onSelect(domain | 'all')` callback, plus `disabled` and `activeLabel`:

```tsx
const SYNC_MENU_ITEMS: { domain: SyncDomain; label: string }[] = [
  { domain: 'accounts', label: 'Accounts' },
  { domain: 'cards', label: 'Credit Cards' },
  { domain: 'certificates', label: 'Certificates' },
  { domain: 'loans', label: 'Loans' },
  { domain: 'prepaid_cards', label: 'Prepaid Cards' },
];

function SyncDropdown({
  disabled,
  loading,
  activeLabel,
  onSelectDomain,
  onSyncAll,
}: {
  disabled: boolean;
  loading: boolean;
  activeLabel: string | null;
  onSelectDomain: (domain: SyncDomain) => void;
  onSyncAll: () => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onDocClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false);
    }
    document.addEventListener('mousedown', onDocClick);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDocClick);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        disabled={disabled}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 px-3 py-1.5 text-sm font-medium text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500"
      >
        {loading ? (
          <>
            <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-gray-400 border-t-transparent" />
            {activeLabel ? `Syncing ${activeLabel}…` : 'Syncing…'}
          </>
        ) : (
          <>
            Sync
            <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
            </svg>
          </>
        )}
      </button>
      {open && !disabled && (
        <div
          role="menu"
          className="absolute right-0 z-20 mt-1 w-48 overflow-hidden rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 shadow-lg"
        >
          {SYNC_MENU_ITEMS.map((item) => (
            <button
              key={item.domain}
              role="menuitem"
              type="button"
              onClick={() => {
                setOpen(false);
                onSelectDomain(item.domain);
              }}
              className="block w-full px-3 py-2 text-left text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800 focus:outline-none focus-visible:bg-gray-100 dark:focus-visible:bg-gray-800"
            >
              {item.label}
            </button>
          ))}
          <div className="border-t border-gray-200 dark:border-gray-700" />
          <button
            role="menuitem"
            type="button"
            onClick={() => {
              setOpen(false);
              onSyncAll();
            }}
            className="block w-full px-3 py-2 text-left text-sm font-medium text-brand-600 dark:text-brand-400 hover:bg-gray-100 dark:hover:bg-gray-800 focus:outline-none focus-visible:bg-gray-100 dark:focus-visible:bg-gray-800"
          >
            Sync All
          </button>
        </div>
      )}
    </div>
  );
}
```

Ensure `useRef` and `useEffect` are imported from `react` at the top of the file (add to the existing `import { ... } from 'react'`).

- [ ] **Step 5: Replace the per-item buttons with the dropdown**

In the actions block, replace the entire NBE conditional (the `{cred.bank === 'NBE' && ( <> ...three buttons... </> )}` block AND the standalone `Sync All`/`Sync` button that follows it) with:

```tsx
                        {cred.bank === 'NBE' ? (
                          <SyncDropdown
                            disabled={isSyncing || isRemoving}
                            loading={isSyncing}
                            activeLabel={syncState?.phase?.label ?? null}
                            onSelectDomain={(domain) => void handleSyncItem(cred, domain)}
                            onSyncAll={() => void handleSync(cred)}
                          />
                        ) : (
                          <Button
                            size="sm"
                            variant="secondary"
                            loading={isSyncing}
                            disabled={isSyncing || isRemoving}
                            onClick={() => void handleSync(cred)}
                          >
                            Sync
                          </Button>
                        )}
```

Leave the Edit and Remove buttons that follow exactly as they are.

- [ ] **Step 6: Type-check + lint**

Run: `cd apps/web && pnpm type-check && pnpm lint`
Expected: no errors. Fix any (common: unused old button imports if the three per-item buttons were the only `Button` users in that block — `Button` is still used for non-NBE and Edit/Remove, so it stays imported).

- [ ] **Step 7: Commit**

```bash
git add apps/web/src/components/settings/bank-accounts-section.tsx
git commit -m "feat(web): replace per-item sync buttons with Sync dropdown (5 products)"
```

---

## Task 10: Full verification + manual screenshots

- [ ] **Step 1: Backend gate**

Run: `cd apps/api && uv run ruff format --check . && uv run ruff check . && uv run mypy app/ && uv run pytest -q`
Expected: all green.

- [ ] **Step 2: Frontend gate**

Run: `cd apps/web && pnpm type-check && pnpm lint`
Expected: all green.

- [ ] **Step 3: Manual screenshots (desktop + mobile)**

Start the dev server and screenshot, using the repo screenshot tool, at desktop (1280) and mobile (~375px) widths:
- `/dashboard/loans`
- `/dashboard/prepaid-cards`
- `/dashboard/settings` (open the Sync dropdown on an NBE credential)

Run: `npm run screenshot http://localhost:3000/dashboard/loans /tmp/loans.png` (repeat per page), then Read each screenshot to verify layout, dark mode, and that the dropdown opens and lists all 5 + Sync All.

- [ ] **Step 4: Final commit (if any screenshot-driven tweaks)**

```bash
git add -A apps/web
git commit -m "fix(web): polish loans/prepaid pages and sync dropdown after review"
```

---

## Self-Review Notes

- **Spec coverage:** Layer 1 (endpoints) → Tasks 1-4; Layer 2 (pages + nav) → Tasks 5-7; Layer 3 (dropdown) → Tasks 8-9; mobile/testing → Task 10. All spec sections covered.
- **Type consistency:** `SyncDomain` extended once (Task 9 Step 1) and used consistently in `NBE_SYNC_PHASES`, `handleSyncItem` dispatch, `SYNC_MENU_ITEMS`, and `SyncDropdown` props. `syncBankLoans`/`syncBankPrepaidCards` defined in Task 8, consumed in Task 9. Job types `"loans"`/`"prepaid_cards"` defined in Task 1, used in Task 3 `_create_job_in_db` calls.
- **Coverage bar:** explicitly left as the original 3 domains, with a fallback note if the type coupling forces inclusion.
