---
name: project_nbe_split_sync_flow
description: "Sync All" button now runs NBE through 3 sequential split-sync endpoints (accounts -> cards -> certificates) instead of the monolithic syncBank(); other banks unchanged.
type: project
---

`apps/web/src/components/settings/bank-accounts-section.tsx` — `handleSync` branches on `cred.bank === 'NBE'`.

**Why:** The old `syncBank()` full-job ran ONE Playwright session covering NBE login + 4 demand-deposit accounts + 1 credit card + 1 certificate, which routinely timed out / OOM'd on Render's free tier. The backend (`apps/api/app/routers/sync.py`) already exposes three split endpoints — `syncBankAccounts`, `syncBankCreditCards`, `syncBankCertificates` (all in `api-client.ts`) — each spawning its own fresh browser session with a clean memory baseline, serialized via the backend's `_SCRAPE_SEMAPHORE` (only one Playwright instance at a time anyway, so sequential is required regardless).

**Confirmed from the router (read-only):** for non-NBE banks, `start_sync_accounts_job` / `start_sync_cc_job` / `start_sync_certificates_job` ALL fall back to `scraper.scrape()` — the same full scrape. So calling all three for CIB/BDC/BDC_RETAIL/UB would triple the work for zero benefit. Only NBE (and BDC_RETAIL for the accounts-only path specifically) gets real split behavior, but per the safe-default instruction we gated the entire 3-phase flow on `cred.bank === 'NBE'` only.

**How to apply:**
- `SyncState` now has a `phase: SyncPhaseInfo | null` field (`{ index, total, label }`). `startedAt` is reset (`Date.now()`) at the START of each phase, so `elapsedSeconds[cred.id]` is a per-phase counter, not cumulative — UI reads "Syncing accounts (1/3)... 45s" then resets to "Syncing cards (2/3)... 0s..." etc.
- `NBE_SYNC_PHASES` constant (in the same file) defines the 3 phases in order: accounts, cards, certificates. Order matters — must match backend's single-browser-instance assumption.
- On phase failure: stop immediately, set `error` to `"<Phase> sync failed: <message>"` (phase label capitalized), still call `fetchCredentials()` + `fetchSyncedAccounts()` so partial progress shows in the Sync Coverage bar, then `return` (don't proceed to next phase).
- On full success: aggregate `transactions_scraped`/`transactions_saved` summed across all 3 `SyncResult`s into one `lastResult` string ("Synced N transactions (M new) across accounts, cards & certificates").
- Non-NBE banks: unchanged — single `syncBank(accessToken, cred.bank as Bank, cred.id)` call, one phase.
- If the backend ever changes which banks get real split-sync behavior (e.g. CIB gets its own `scrape_accounts()`/`scrape_credit_cards()`/`scrape_certificates()`), revisit the `cred.bank === 'NBE'` gate — check `apps/api/app/routers/sync.py` `_background_sync_*_task` functions for `if bank == "NBE":` branches before extending this to other banks.
