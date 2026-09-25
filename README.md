# FinPilot

FinPilot is a personal finance dashboard for Egyptian bank accounts. The web app
shows accounts, transactions, credit cards, loans, prepaid cards, installments,
debts, and recommendations. A FastAPI service handles bank sync and analysis.

## Deployment

The supported self-hosted setup runs the web app and API in Docker on a Linux
host. Caddy serves both under one HTTPS domain. An override is included for a
host that already has a reverse proxy. FinPilot still uses an existing hosted
Supabase project for authentication and data; this repository does not contain
a complete base schema for a new Supabase installation.

Start with [the Kali Linux deployment guide](docs/deployment/kali-linux.md).
The production stack is in `compose.prod.yml`; the existing-proxy override is
in `compose.prod.existing-proxy.yml`.

## Development

Use Node.js 20+, pnpm 9, Python 3.12, and `uv`. Copy the example environment
files before starting either service. The full commands and test instructions
are in [development.md](docs/development.md).

## Documentation

| Guide | Purpose |
| --- | --- |
| [Architecture](docs/architecture.md) | Services, data flow, and security boundaries |
| [Development](docs/development.md) | Local setup and checks |
| [Kali Linux deployment](docs/deployment/kali-linux.md) | Public URL, environment, containers, and updates |
| [Database](docs/database.md) | Existing Supabase project and incremental migrations |
| [Bank sync](docs/bank-sync.md) | Sync behavior, BDC proxy, and diagnostics |
| [Project status](docs/status.md) | Verified repository state and open work |

## Repository layout

| Path | Contents |
| --- | --- |
| `apps/web` | Next.js 14 web app |
| `apps/api` | FastAPI service and bank scrapers |
| `packages/shared` | Shared TypeScript database types |
| `packages/ui` | Shared UI components |
| `supabase/migrations` | Incremental SQL migrations |
| `deploy` | Caddy configuration |
| `docs` | Current project documentation |

Never commit `.env` files, service-role keys, bank credentials, or browser
captures. The `Banks` and `Screenshots` folders are ignored local material and
are not needed to build or deploy the app.
