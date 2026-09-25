# Architecture

FinPilot has two application services and an external data service. The Linux
deployment places Caddy in front of the web and API containers. The browser
uses the same public HTTPS origin for pages and `/api/v1/*`; both application
services also connect to the existing hosted Supabase project.

| Component | Responsibility | Production entry point |
| --- | --- | --- |
| `apps/web` | Next.js 14 / React 18 dashboard and Supabase Auth session | `/` and `/dashboard/*` |
| `apps/api` | FastAPI routes, analysis, encrypted credentials, bank scrapers | `/api/v1/*` |
| Caddy | TLS and path routing | Host ports 80/443 |
| Supabase | Auth, PostgreSQL, and Row Level Security | External project URL |
| Anthropic API | Optional transaction categorization | API service only |

The production definitions are `compose.prod.yml`,
`compose.prod.existing-proxy.yml`, `apps/web/Dockerfile`, `apps/api/Dockerfile`,
and `deploy/Caddyfile`. The Compose stack starts one API instance because sync
jobs and the browser semaphore have process-local state. Job snapshots are
also written to `sync_jobs` for status recovery after a restart; a restart can
still interrupt an active scrape.

## Request and data flow

1. The browser signs in with Supabase Auth. The web app uses Supabase SSR
   cookies for server-rendered pages.
2. API calls carry the Supabase access token in `Authorization: Bearer`.
   `apps/api/app/deps.py` checks the token signature, issuer, audience, and
   expiry. It supports project JWKS keys and legacy HS256 secrets.
3. API routes derive the user ID from the verified token. They scope database
   operations to that user; user-scoped clients apply Supabase RLS, and routes
   using the service role also enforce explicit user filters.
4. Bank credentials are encrypted with AES-256-GCM before storage. The
   `ENCRYPTION_KEY` stays on the API service and must remain stable across
   deployments.
5. A sync job opens one browser, extracts bank data, normalizes it, and writes
   accounts and transactions through the pipeline. The UI polls job status.

The typed database model in `packages/shared/src/types/database.ts` currently
describes assets, bank accounts, bank credentials, debts, debt payments,
installments, loans, sync jobs, transactions, and user profiles. The SQL files
in `supabase/migrations` are **incremental**; they do not build that full
schema from an empty project. See [database.md](database.md).

## Bank support and limits

The API dispatches NBE, CIB, BDC Kony (`BDC_RETAIL`), and UB scrapers. CIB's
live scraper currently fails fast because its portal blocks automation. NBE/UB
use Playwright; BDC Kony uses Patchright Chromium. Production BDC sync requires
an Egyptian sticky proxy in the current code. Its account balance and card
detail capture are implemented, while transaction capture remains incomplete.
See [bank-sync.md](bank-sync.md) before relying on BDC transaction totals.

The scheduler implementation remains in `apps/api/app/scheduler.py`, but
`apps/api/app/main.py` does not start it. Sync is currently initiated from the
UI/API. Do not assume automatic daily sync is running on the Linux host.

## Deployment boundary

The current self-hosted deployment is documented in
[kali-linux.md](deployment/kali-linux.md). `render.yaml`, `vercel.json`, and the
old deploy notification workflow remain in the repository for the existing
cloud deployment during migration; they are not part of the Linux Compose
stack. Confirm the cutover before removing those integrations.
