# FinPilot M1 DevOps Setup Summary

## Completed Tasks

### 1. GitHub Actions CI/CD Pipelines

Created three workflow files in `.github/workflows/`:

#### `.github/workflows/ci.yml`
- **Trigger:** On every push and PR to `main`
- **Jobs:**
  1. `lint-and-type-check-frontend` — ESLint + TypeScript type checking for `apps/web`
  2. `test-backend` — pytest with coverage threshold (≥80%)
  3. `lint-backend` — Ruff lint + format check + mypy type checking for `apps/api`
- **All Actions use pinned SHA versions** (not floating tags) for security
- **Caching:** pnpm and pip caches for faster builds

#### `.github/workflows/deploy-frontend.yml`
- **Trigger:** On push to `main` (only when `apps/web/**`, `packages/**`, or `pnpm-lock.yaml` change)
- **Deploys to Vercel** using `amondnet/vercel-action` with secrets:
  - `VERCEL_TOKEN`
  - `VERCEL_ORG_ID`
  - `VERCEL_PROJECT_ID`
- Production deployment via `vercel --prod` flag

#### `.github/workflows/deploy-backend.yml`
- **Trigger:** On push to `main` (only when `apps/api/**` or `render.yaml` change)
- **Informational job** — Render uses automatic Git integration for deployments
- Documents that Render watches `main` branch and auto-deploys changes

### 2. Docker Configuration

#### `docker-compose.yml` (Project Root)
- **Services:**
  - `api` — FastAPI backend with hot-reload, port 8000
  - `web` — Next.js frontend with hot-reload, port 3000
  - `supabase-local` — PostgreSQL 15 for local dev, port 54322
- **Volumes:** Live source mounts for development iteration
- **Network:** Shared `finpilot-net` bridge network for service-to-service communication

#### `apps/api/Dockerfile.dev`
- Development image with `uv sync` for dependency management
- Mounts source code for auto-reload with `--reload` flag
- Python 3.12-slim base image

#### `apps/api/Dockerfile` (Production)
- **Multi-stage build:** Reduces final image size
- Stage 1: Install dependencies with `uv sync --no-dev`
- Stage 2: Copy venv + source code, install curl for health checks
- **Health Check:** `GET /api/v1/health` every 30 seconds
- Non-root user recommended (not enforced here for MVP)
- Runs `uvicorn app.main:app --host 0.0.0.0 --port 8000`

#### `apps/web/Dockerfile.dev`
- Node.js 20-alpine with pnpm
- Mounts source + node_modules volumes for development
- Runs `pnpm dev`

#### `.dockerignore` Files
- `apps/api/.dockerignore` — Excludes Python cache, tests, coverage, `.env` files
- `apps/web/.dockerignore` — Excludes node_modules, build outputs, `.env` files

### 3. Platform Configuration

#### `render.yaml` (Project Root)
- **Service:** `finpilot-api` (web service, free plan)
- **Docker:** Multi-stage Dockerfile from `apps/api/Dockerfile`
- **Health Check:** `/api/v1/health` endpoint
- **Environment Variables:**
  - Non-secret vars: `APP_ENV=production`, `LOG_LEVEL=info`
  - Secret vars (config via Render Dashboard, not in file):
    - `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`
    - `ENCRYPTION_KEY`, `CLAUDE_API_KEY`, `CORS_ORIGINS`
- **Free Tier Note:** 750 hours/month, auto-suspends on inactivity

#### `vercel.json` (Project Root)
- **Root:** `apps/web`
- **Framework:** Next.js
- **Build Command:** `pnpm run build`
- **Output:** `.next`
- **Rewrites:** `/api/:path*` proxies to backend API URL (via env var)
- **Environment Variables:** References `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`

### 4. Agent Memory

Created persistent memory system at `.claude/agent-memory/finpilot-devops/`:
- `MEMORY.md` — Index of all memories
- `github-actions-versions.md` — Pinned SHA versions for all actions
- `render-config.md` — Render backend setup, environment variables, monitoring
- `vercel-config.md` — Vercel frontend setup, environment variables, rewrites
- `free-tier-limits.md` — Render (750 hr/mo) and Vercel (100 GB/mo) guardrails

## Health Endpoint Verification

✅ The `/api/v1/health` endpoint is already implemented:
- **File:** `apps/api/app/routers/health.py`
- **Response:** `{"status": "ok", "version": "0.1.0"}` (HTTP 200)
- **Registered:** In `apps/api/app/main.py` as a router prefix `/api/v1`
- **Used by:** Docker HEALTHCHECK, Render health probe, monitoring

## Git Ignore Status

✅ `.gitignore` already has comprehensive coverage:
- Python: `__pycache__/`, `*.py[cod]`, `.venv/`, `.mypy_cache/`, `.ruff_cache/`
- Node: `node_modules/`, `.next/`, `.turbo/`
- Environment: `.env`, `.env.local`, `.env.*.local`
- Test: `coverage/`, `.coverage`, `htmlcov/`

No updates needed.

## Next Steps for Full Deployment

1. **GitHub Secrets Setup (requires repo maintainer):**
   ```
   VERCEL_TOKEN → From Vercel account settings
   VERCEL_ORG_ID → From Vercel dashboard
   VERCEL_PROJECT_ID → From Vercel project settings
   ```

2. **Render Configuration (via Render Dashboard):**
   - Connect GitHub repository
   - Set environment variables (SUPABASE_URL, SUPABASE_ANON_KEY, etc.)
   - Enable auto-deploy on main branch

3. **Vercel Configuration (via Vercel Dashboard):**
   - Link to GitHub repository
   - Set environment variables (NEXT_PUBLIC_API_URL, NEXT_PUBLIC_SUPABASE_URL, etc.)
   - Configure deployment source as `apps/web` with build output `.next`

4. **Local Development:**
   ```bash
   # Start all services
   docker-compose up -d

   # View logs
   docker-compose logs -f

   # Stop services
   docker-compose down
   ```

## File Locations

### GitHub Actions (CI/CD)
- `/mnt/e/Work/Projects/financial_assistant/finpilot/.github/workflows/ci.yml`
- `/mnt/e/Work/Projects/financial_assistant/finpilot/.github/workflows/deploy-frontend.yml`
- `/mnt/e/Work/Projects/financial_assistant/finpilot/.github/workflows/deploy-backend.yml`

### Docker
- `/mnt/e/Work/Projects/financial_assistant/finpilot/docker-compose.yml`
- `/mnt/e/Work/Projects/financial_assistant/finpilot/apps/api/Dockerfile`
- `/mnt/e/Work/Projects/financial_assistant/finpilot/apps/api/Dockerfile.dev`
- `/mnt/e/Work/Projects/financial_assistant/finpilot/apps/web/Dockerfile.dev`
- `/mnt/e/Work/Projects/financial_assistant/finpilot/apps/api/.dockerignore`
- `/mnt/e/Work/Projects/financial_assistant/finpilot/apps/web/.dockerignore`

### Platform Configuration
- `/mnt/e/Work/Projects/financial_assistant/finpilot/render.yaml`
- `/mnt/e/Work/Projects/financial_assistant/finpilot/vercel.json`

### Agent Memory
- `/mnt/e/Work/Projects/financial_assistant/finpilot/.claude/agent-memory/finpilot-devops/MEMORY.md`
- `/mnt/e/Work/Projects/financial_assistant/finpilot/.claude/agent-memory/finpilot-devops/github-actions-versions.md`
- `/mnt/e/Work/Projects/financial_assistant/finpilot/.claude/agent-memory/finpilot-devops/render-config.md`
- `/mnt/e/Work/Projects/financial_assistant/finpilot/.claude/agent-memory/finpilot-devops/vercel-config.md`
- `/mnt/e/Work/Projects/financial_assistant/finpilot/.claude/agent-memory/finpilot-devops/free-tier-limits.md`

## Security Considerations

✅ **Implemented:**
- All GitHub Actions use pinned commit SHAs (no floating tags)
- No secrets embedded in any YAML or config files
- All sensitive values reference environment variables
- `.env` files excluded from git
- Least privilege GitHub token permissions in workflows

⚠️ **Requires Configuration (secrets management):**
- Set GitHub Secrets for VERCEL_TOKEN, VERCEL_ORG_ID, VERCEL_PROJECT_ID
- Set Render environment variables via dashboard (SUPABASE_KEY, ENCRYPTION_KEY, etc.)
- Set Vercel environment variables via dashboard

## CI/CD Pipeline Flow

1. **Developer pushes to main**
2. **GitHub Actions triggered:**
   - Frontend linting + type check (pnpm lint + type-check)
   - Backend testing (pytest with coverage report)
   - Backend linting + type check (ruff + mypy)
3. **If all checks pass:**
   - Deploy Frontend → Vercel via `deploy-frontend.yml`
   - Deploy Backend → Render (auto-triggered via Git integration)
4. **Health checks:**
   - Docker container runs HEALTHCHECK probe every 30s
   - Render monitors `/api/v1/health` endpoint
   - CI workflows log deployment status

## Monitoring & Maintenance

**Weekly:**
- Check Render logs for errors via Render MCP
- Check Vercel build logs via Vercel MCP

**Monthly:**
- Monitor Render hours used (free tier: 750 hr/month)
- Monitor Vercel bandwidth (free tier: 100 GB/month)
- Flag if either approaches 80% threshold

See `.claude/agent-memory/finpilot-devops/free-tier-limits.md` for guardrail thresholds.
