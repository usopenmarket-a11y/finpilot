# Project status

**Repository review:** 2026-09-25. This is a source-tree snapshot, not a claim
about the live Supabase, Render, Vercel, or Kali environments.

| Area | Current repository state |
| --- | --- |
| Web | Next.js 14 / React 18 dashboard with accounts, transactions, credit cards, assets, debts, installments, loans, prepaid cards, and recommendations |
| API | FastAPI routes for health, credentials, sync, analytics, debts, installments, preferences, and recommendations |
| Bank sync | NBE, CIB, BDC Kony, and UB dispatch; CIB live sync disabled; one browser job at a time |
| Database | Existing hosted Supabase required; incremental migrations present, including the September 2026 data integrity change |
| Linux deployment | Production web/API/Caddy Compose files and existing-proxy override prepared; not deployed to the Kali host from this workspace |
| Scheduled sync | Implementation exists but is disabled in the API lifespan |
| Legacy cloud | Render/Vercel configuration remains during migration; live state not checked in this review |

## Recent source changes

- Debt and debt-payment routes now use Supabase-backed records, with balance
  integrity enforced by the September migration.
- Bank accounts can be linked to the credential that synced them, so deleting
  a credential affects only linked accounts.
- NBE credit card section replacement is atomic when the matching migration
  is installed. Missing sections retain earlier history.
- Auth callback and password reset support the explicit update-password path.
- The API can verify Supabase access tokens with JWKS keys or a legacy HS256
  secret, depending on the Supabase project.
- BDC hosted sync has proxy validation and a credential-free preflight, while
  transaction capture remains incomplete.
- The Linux stack builds both application images and routes one HTTPS domain
  through Caddy, or loopback ports through an existing proxy.

## Verified locally during the Linux preparation

Both production images built. The web image served `/auth/login`, the API image
returned `200` from `/api/v1/health`, Playwright and Patchright Chromium both
launched inside the API image, and both Compose variants parsed. Caddy accepted
its routing file. These checks do not establish a working public URL or a live
bank login.

## Before the Kali cutover

1. Clone the current repository revision on Kali and follow the deployment
   guide for its application code, migrations, and Compose files.
2. Confirm which Supabase migrations have run. Apply missing ones before the
   corresponding API/web changes; preserve the existing encryption key.
3. Set the public DNS name, inbound ports or existing proxy route, Supabase
   Auth redirect URLs, and private API environment values.
4. Start the stack using [the deployment guide](deployment/kali-linux.md),
   test login and password reset, and verify one representative bank sync
   against the bank's own values.
5. Retire legacy Render/Vercel integrations only after the new URL works and
   the old services are no longer needed.

Repository checks on 2026-09-25: the full API suite passed (618 passed,
10 skipped), with 283 warnings including NBE test mock coroutine warnings.
Ruff lint and format passed on the API application tree, mypy passed on 46
source files, and the eight web auth routing tests, web lint, and TypeScript
check passed. Both production Compose variants parsed, and all relative links
in the new guides resolved. The maintained tests are in `apps/api/app/tests`
and `apps/web/tests`.

## Sync timeout fix on 2026-09-25

Recorded `sync_jobs` rows showed two causes of "Sync job timed out". The
browser stopped polling before NBE finished (accounts limit 15 minutes while
successful runs took up to about 31 minutes; cards 8 minutes against runs of
up to 9.5 minutes). Jobs orphaned by an API restart also stayed `running`, so
the browser polled them until its limit; 27 such rows existed. The API now
enforces per-phase deadlines, releases the browser on timeout or failed
launch, and reports orphaned jobs as interrupted. The web client waits longer
than the server deadlines, and NBE "Sync all" continues past a failed phase.
See [bank-sync.md](bank-sync.md#time-limits).

The live database check on the same day confirmed that the September
migration is still not applied: `bank_accounts.credential_id` and the
`replace_credit_card_transactions` RPC are absent. Existing debt balances
equal original amount minus recorded payments for all three debts, so the
migration's balance triggers start from consistent data.

## Local bank diagnostics on 2026-09-25

The configured hosted Supabase project has four active bank credentials:
two NBE, one CIB, one BDC Kony, and none for UB. All four encrypted records
could be decrypted with the local API key. The read-only live checks used the
local API Docker image and did not save bank data:

| Bank | Read-only result |
| --- | --- |
| NBE, credential 1 | Portal timeout after the scraper's retry |
| NBE, credential 2 | Portal timeout during an account stage |
| CIB | Current scraper intentionally rejects automated live access |
| BDC Kony | Authenticated and returned one deposit account and one card; zero transactions because card transaction capture is not implemented |
| UB | No active credential to test |

An initial BDC card request stalled. The API now bounds that request and
reports a failed account/card API call as an error; a retry with the rebuilt
image returned both accounts. The configured Supabase database lacks
`bank_accounts.credential_id` (SQLSTATE `42703`), so the September migration is
still required before these application changes can persist a normal sync.
No migration was applied in this check.

The follow-up code checks passed: 59 sync/BDC tests, 107 targeted NBE tests,
10 migration integration tests against disposable PostgreSQL 17, and Ruff
lint/format checks on the edited API files. The NBE test run emitted
mock coroutine warnings; its assertions all passed. The local Supabase CLI is
not authenticated to the configured project, so migration application needs
project access or a manual SQL Editor run.
