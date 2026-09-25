# Development

The development workflow runs the web app and API directly. Use Node.js 20+,
pnpm 9.15, Python 3.12, and `uv`. An existing Supabase project is required;
the repository's SQL migrations do not create a complete new project.

## Configure

From the repository root:

```sh
corepack enable
corepack prepare pnpm@9.15.0 --activate
pnpm install --frozen-lockfile
cp apps/web/.env.local.example apps/web/.env.local
cp apps/api/.env.example apps/api/.env
```

Fill in the Supabase URL and anon key in both files. Put the Supabase service
role key and the existing `ENCRYPTION_KEY` only in `apps/api/.env`. A legacy
HS256 Supabase project also needs `SUPABASE_JWT_SECRET`; projects using JWKS
signing keys are verified through their JWKS endpoint. Keep the service role
key, encryption key, and bank proxy credentials out of `NEXT_PUBLIC_*` values.
For local password reset, allow the localhost callback URL in Supabase Auth.

## Run

In separate terminals:

```sh
pnpm --filter web dev
```

```sh
cd apps/api
uv sync --dev --locked
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

The web app runs at `http://localhost:3000`; the API health check is
`http://localhost:8000/api/v1/health`. Bank scraping needs browser binaries:

```sh
cd apps/api
uv run playwright install chromium
uv run patchright install chromium
```

The production Dockerfile installs the browsers and their Linux packages
automatically. `docker-compose.yml` from the original prototype is retired.
To run the containers on this machine without a domain, use the
[local-only Compose override](deployment/kali-linux.md#local-only-run).

## Checks

```sh
pnpm --filter web lint
pnpm --filter web type-check
pnpm --filter web test
```

```sh
cd apps/api
uv run ruff check .
uv run ruff format --check .
uv run mypy app/
uv run pytest -v --cov=app --cov-report=term-missing
```

CI also runs database integration tests against a disposable PostgreSQL 17
database named `finpilot_test`. Locally, set `FINPILOT_TEST_DATABASE_URL` only
to an isolated test database before running those tests. Never point it at an
application or production database. See [database.md](database.md).

The files under `apps/api/app/tests` and `apps/web/tests` are the maintained
automated suites. Browser login probes containing personal credentials and
older portal investigation scripts are not part of the test suite.
