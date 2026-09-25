# FinPilot contributor context

The current project documentation starts at [README.md](README.md). Keep this
file short and update the relevant guide in `docs/` when behavior changes.

## Stack and paths

- `apps/web`: Next.js 14, React 18, TypeScript, Tailwind CSS.
- `apps/api`: Python 3.12, FastAPI, Pydantic v2, Playwright and Patchright.
- `packages/shared`: generated/shared Supabase database types.
- `packages/ui`: shared React UI components.
- `supabase/migrations`: incremental SQL for the existing hosted Supabase
  project; there is no complete empty-project schema in this repo.
- `compose.prod.yml` and `deploy/Caddyfile`: Linux production stack.

The web app and API run on the Kali host under one HTTPS origin; Auth and data
remain on Supabase. See [architecture.md](docs/architecture.md) and
[kali-linux.md](docs/deployment/kali-linux.md). `render.yaml` and `vercel.json`
are legacy deployment files retained until cutover is verified.

## Local commands

```sh
pnpm install --frozen-lockfile
pnpm --filter web dev
pnpm --filter web lint
pnpm --filter web type-check
pnpm --filter web test
```

```sh
cd apps/api
uv sync --dev --locked
uv run uvicorn app.main:app --reload
uv run ruff check .
uv run ruff format --check .
uv run mypy app/
uv run pytest -v --cov=app --cov-report=term-missing
```

See [development.md](docs/development.md) for environment files and the
isolated database integration-test requirement.

## Security and data rules

- Never commit `.env` files, keys, bank credentials, access tokens, raw bank
  captures, or personal screenshots. Do not log those values.
- Keep `SUPABASE_SERVICE_ROLE_KEY` and `ENCRYPTION_KEY` on the API only. Never
  put secrets in `NEXT_PUBLIC_*` variables.
- Derive user identity from the verified Supabase JWT in `apps/api/app/deps.py`.
  Do not trust a client-supplied user ID.
- Preserve explicit user filters and Supabase RLS boundaries when changing
  database access.
- Preserve the existing encryption key when moving an installation; changing
  it makes stored bank credentials unreadable.
- Check migration history before applying SQL. Apply the September 2026
  migration before deploying its matching API/web changes.
- The daily scheduler is disabled; do not document automatic sync as active.
- BDC production sync requires an Egyptian sticky proxy and its transaction
  capture remains incomplete. See [bank-sync.md](docs/bank-sync.md).

Keep the automated tests in `apps/api/app/tests` and `apps/web/tests`. Remove
temporary browser/login probes after use; they must never contain credentials.
