# FinPilot Infrastructure Reference

Complete reference for DevOps infrastructure, ownership, and architecture decisions.

## File Ownership & Boundaries

This DevOps Agent exclusively owns and maintains these paths:

```
.github/workflows/**          ← CI/CD pipelines (all workflows)
Dockerfile                    ← Production images
Dockerfile.dev               ← Development images
docker-compose.yml           ← Local dev orchestration
.dockerignore               ← Docker exclusions
render.yaml                 ← Render deployment config
vercel.json                 ← Vercel deployment config
```

**Other agents may READ these files but MUST NOT WRITE without approval.**

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                     GitHub (Source)                          │
│  • Monorepo: FinPilot (Next.js + FastAPI)                   │
│  • CI/CD: GitHub Actions workflows                          │
└────────────┬─────────────────────────────────────┬──────────┘
             │                                     │
             │ (via GitHub Actions)                │ (Git Hook)
             ▼                                     ▼
    ┌─────────────────────┐            ┌─────────────────────┐
    │  Vercel (Frontend)  │            │  Render (Backend)   │
    │  - Next.js 15       │            │  - FastAPI/Python   │
    │  - App Router       │            │  - PostgreSQL       │
    │  - 100 GB bw/mo     │            │  - 750 hr/mo        │
    │  - Free tier        │            │  - Free tier        │
    │  Port: 443          │            │  Port: 443          │
    └──────┬──────────────┘            └──────┬──────────────┘
           │                                  │
           │ (API requests)                   │ (API responses)
           └──────────────┬───────────────────┘
                          │
                    ┌─────▼─────┐
                    │ Supabase  │
                    │ PostgreSQL│
                    │ Auth      │
                    │ Row-Level │
                    │ Security  │
                    └───────────┘
```

## Technology Stack

| Component | Technology | Version | Location |
|-----------|-----------|---------|----------|
| Frontend | Next.js | 15 | `apps/web/` |
| Frontend Framework | React | 19 | `apps/web/` |
| Frontend Styling | Tailwind CSS | Latest | `apps/web/` |
| Frontend Components | shadcn/ui | Latest | `apps/web/` |
| Backend | FastAPI | ≥0.115 | `apps/api/app/` |
| Backend Language | Python | 3.12 | `pyproject.toml` |
| Database | PostgreSQL | 15 | Supabase |
| Auth | Supabase Auth | Latest | Remote |
| Package Manager (Frontend) | pnpm | 9 | `pnpm-lock.yaml` |
| Dependency Manager (Backend) | uv | Latest | `pyproject.toml` |
| Linting (Frontend) | ESLint | Latest | `apps/web/` |
| Type Checking (Frontend) | TypeScript | Strict mode | `apps/web/` |
| Linting (Backend) | Ruff | ≥0.8 | `apps/api/` |
| Type Checking (Backend) | Mypy | ≥1.13 | `apps/api/` |
| Testing (Backend) | pytest | ≥8.3 | `apps/api/` |
| Testing (Frontend) | vitest/Jest | Latest | `apps/web/` |
| Container Runtime | Docker | Latest | `docker-compose.yml` |
| Container Orchestration | Docker Compose | 3.9 | `docker-compose.yml` |

## Deployment Platforms

### Vercel (Frontend)

**Service Configuration:**
- **Project Name:** (varies, set in dashboard)
- **Root Directory:** `apps/web`
- **Framework:** Next.js
- **Build Command:** `pnpm run build`
- **Output Directory:** `.next`
- **Node Version:** 20 (configured in actions)
- **Plan:** Free (100 GB bandwidth/month)

**Environment Variables:**
- `NEXT_PUBLIC_API_URL` — Backend API base URL
- `NEXT_PUBLIC_SUPABASE_URL` — Supabase project URL
- `NEXT_PUBLIC_SUPABASE_ANON_KEY` — Supabase public key

**Deployment Flow:**
1. Push to `main` → GitHub Actions `deploy-frontend.yml` triggered
2. Runs linting, type-check, tests
3. Calls Vercel API via `amondnet/vercel-action`
4. Vercel builds Next.js and deploys to Edge Network
5. Static assets served from CDN, serverless functions available

**Health Check:**
- Frontend is statically generated — health check is page load latency
- Monitor via Vercel dashboard: Analytics → Web Vitals

### Render (Backend)

**Service Configuration:**
- **Service Name:** `finpilot-api`
- **Service Type:** Web Service (Docker)
- **Runtime:** Docker
- **Dockerfile:** `apps/api/Dockerfile`
- **Docker Context:** `apps/api/`
- **Plan:** Free (750 hours/month, auto-suspends on inactivity)
- **Region:** (configured at deploy time)
- **Health Check Path:** `/api/v1/health`
- **Health Check Interval:** 30 seconds

**Environment Variables:**
See `render.yaml` for non-secret values. Secrets configured via Render Dashboard:
- `SUPABASE_URL` — Supabase project URL
- `SUPABASE_ANON_KEY` — Supabase public key
- `SUPABASE_SERVICE_ROLE_KEY` — Supabase service role (secret)
- `ENCRYPTION_KEY` — AES-256-GCM key (32 bytes hex)
- `CLAUDE_API_KEY` — Anthropic API key
- `CORS_ORIGINS` — Comma-separated origins (include Vercel URL)

**Deployment Flow:**
1. Push to `main` → Render detects changes via Git integration
2. Reads `render.yaml` for service definition
3. Builds Docker image from `apps/api/Dockerfile`
4. Runs HEALTHCHECK probe to verify `/api/v1/health` returns 200
5. Routes traffic to successful instance
6. Spins down after 30 minutes of inactivity (free tier default)

**Health Check:**
- Endpoint: `GET /api/v1/health`
- Response: `{"status": "ok", "version": "0.1.0"}`
- Failure handling: Render auto-restarts container after 3 failed probes

## CI/CD Pipeline

### Workflow: Lint & Test (ci.yml)

**Triggers:**
- Every push to `main`
- Every PR to `main`

**Jobs (run in parallel):**

1. **lint-and-type-check-frontend**
   - Install: pnpm 9, Node 20
   - Run: `pnpm --filter web lint`
   - Run: `pnpm --filter web type-check`
   - Fails if: ESLint violations or TypeScript errors
   - Cache: pnpm dependencies

2. **test-backend**
   - Install: Python 3.12, uv
   - Run: `uv sync --dev`
   - Run: `uv run pytest -v --cov=app --cov-report=term-missing`
   - Requires: ≥80% code coverage
   - Fails if: Test fails or coverage below threshold
   - Env vars: TEST database credentials (mocked)

3. **lint-backend**
   - Install: Python 3.12, uv
   - Run: `uv run ruff check .` (lint)
   - Run: `uv run ruff format --check .` (format check)
   - Run: `uv run mypy app/` (type check)
   - Fails if: Lint errors, format issues, or type errors

**Failure Behavior:**
- All three jobs must pass
- PR is blocked if any job fails
- Commit author is notified
- Re-run on fixes to unblock

### Workflow: Deploy Frontend (deploy-frontend.yml)

**Triggers:**
- Push to `main`
- Only if paths match: `apps/web/**`, `packages/**`, or `pnpm-lock.yaml`

**Jobs:**
1. **lint-and-type-check-frontend** (from ci.yml, via reusable workflow or manual)
2. **test-frontend** (if configured)
3. **deploy** (depends on above passing)
   - Install: pnpm 9, Node 20
   - Deploy via Vercel API: `amondnet/vercel-action`
   - Uses secrets: `VERCEL_TOKEN`, `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID`
   - Production flag: `vercel-args: '--prod'`

**Success Condition:**
- Vercel build completes
- All previews are ready
- Production deployment succeeds

**Failure Behavior:**
- Vercel build logs are available for inspection
- Rollback to previous deployment (automatic)
- Author is notified of failure

### Workflow: Deploy Backend (deploy-backend.yml)

**Triggers:**
- Push to `main`
- Only if paths match: `apps/api/**` or `render.yaml`

**Jobs:**
1. **notify** (informational)
   - No automated deployment from this workflow
   - Render's Git integration handles deployment
   - This workflow documents the process

**Why Separate?**
- Render watches Git directly; no webhook trigger needed
- GitHub Actions serves as audit trail
- Allows future customization (e.g., slack notifications)

## Local Development Environment

### Docker Compose Services

**API Service:**
```yaml
api:
  image: finpilot-api:latest (built locally from Dockerfile.dev)
  ports: [8000:8000]
  volumes: [./apps/api:/app]
  environment: APP_ENV=development
  depends_on: [supabase-local]
```

**Web Service:**
```yaml
web:
  image: finpilot-web:latest (built locally from Dockerfile.dev)
  ports: [3000:3000]
  volumes: [./apps/web:/app]
  environment: NODE_ENV=development
```

**Database Service:**
```yaml
supabase-local:
  image: supabase/postgres:15.1.1.41
  ports: [54322:5432]
  volumes: [supabase-data:/var/lib/postgresql/data]
```

**Network:**
- `finpilot-net` bridge network
- All services communicate via service name (e.g., `api:8000`)

### Starting Local Stack

```bash
# Start all services
docker-compose up -d

# View logs
docker-compose logs -f

# Stop all services
docker-compose down

# Remove volumes (reset database)
docker-compose down -v
```

### Connection Strings (Local Development)

- **Frontend:** http://localhost:3000
- **Backend API:** http://localhost:8000
- **Health Check:** http://localhost:8000/api/v1/health
- **PostgreSQL:** localhost:54322 (user: postgres, password: postgres)

## Security Checklist

✅ **Implemented:**
- [ ] GitHub Actions use pinned SHA versions (no floating tags)
- [ ] No secrets in YAML or config files
- [ ] Sensitive values reference environment variables
- [ ] `.env` files excluded from Git
- [ ] Least privilege GitHub Actions permissions
- [ ] Docker runs as non-root (optional, depends on app)
- [ ] HTTPS enforced in production (Vercel/Render)
- [ ] CORS configured to limit origins
- [ ] Health endpoint available for monitoring

⚠️ **Requires Configuration:**
- [ ] Set GitHub Secrets (VERCEL_TOKEN, etc.)
- [ ] Set Render environment variables (SUPABASE_KEY, ENCRYPTION_KEY)
- [ ] Set Vercel environment variables (API_URL, SUPABASE_KEYS)
- [ ] Ensure bank credentials are AES-256-GCM encrypted (app responsibility)
- [ ] Row-level security policies configured in Supabase

## Performance Considerations

### Frontend (Vercel)

- **Build Time:** ~2-3 minutes (Next.js optimized)
- **Time to Interactive:** <2 seconds (from Edge network)
- **Caching:** Static assets cached indefinitely, ISR for dynamic pages
- **Edge Functions:** Serverless functions for API routes (if used)

### Backend (Render)

- **Cold Start:** ~10-30 seconds on free tier (after 30 min inactivity)
- **Response Time:** <100ms for health check
- **Concurrency:** Unlimited with uvicorn workers
- **Database:** Supabase PostgreSQL with optimized queries

### Build Optimization

- **Frontend Caching:** pnpm lockfile ensures reproducible installs
- **Backend Caching:** uv and multi-stage Docker reduces rebuild time
- **CI Caching:** GitHub Actions cache layers for pip and pnpm

## Monitoring & Alerting

### Dashboard Access

| Platform | URL | Purpose |
|----------|-----|---------|
| Vercel | https://vercel.com/dashboard | Frontend deployments, analytics |
| Render | https://dashboard.render.com | Backend service, logs, metrics |
| Supabase | https://supabase.com/dashboard | Database, auth, logs |
| GitHub Actions | https://github.com/owner/finpilot/actions | CI/CD workflows |

### Key Metrics to Monitor

**Backend (Render):**
- Health check response time
- CPU usage (should be <50% at rest)
- Memory usage (should be <200MB)
- Request latency (p50, p95)
- Error rate (should be <1%)
- Monthly uptime hours (750 max on free tier)

**Frontend (Vercel):**
- Build success rate
- Page load performance (Core Web Vitals)
- Bandwidth usage (100 GB/month limit)
- Error rate (should be <1%)

**Shared:**
- API response times (end-to-end)
- Database query performance
- Error logs and patterns

## Cost Tracking

### Current Configuration (Free Tier)

| Service | Limit | Current Usage | Alert Threshold |
|---------|-------|----------------|-----------------|
| Render API | 750 hr/month | ~100-150 hr/month* | 600 hr (80%) |
| Vercel | 100 GB/month | <1 GB/month* | 80 GB (80%) |

*Estimates for M1 (low traffic, daily development deploys)

### Escalation Path

If approaching limits:
1. **Render:** Consider Starter plan ($7/month) for 1000 hr/month
2. **Vercel:** Consider Pro plan ($20/month) for 1000 GB/month

## Common Operations

### Redeploy Latest Commit

**Frontend (Vercel):**
1. Go to https://vercel.com/dashboard
2. Select `finpilot` project
3. Find latest deployment
4. Click "Redeploy" on deployment row

**Backend (Render):**
1. Go to https://dashboard.render.com
2. Select `finpilot-api` service
3. Click "Redeploy" (top right)
4. Confirm restart

### View Logs

**Frontend (Vercel):**
```bash
vercel logs --follow
```

**Backend (Render):**
```
Via MCP: mcp__render__list_logs with resource=finpilot-api-id
```

### Update Environment Variables

**Frontend (Vercel):**
1. Project Settings → Environment Variables
2. Edit or add variable
3. Automatic redeploy on save

**Backend (Render):**
1. Service Settings → Environment
2. Edit or add variable
3. Manual redeploy required

### Rollback to Previous Deployment

**Frontend (Vercel):**
1. Deployments tab
2. Find previous successful deployment
3. Click "Promote to Production"

**Backend (Render):**
1. Logs → Deploys tab
2. Find previous successful deploy
3. Click "Redeploy" on past deployment

## Related Documentation

- `DEVOPS_SETUP_SUMMARY.md` — Files created and configuration applied
- `DEPLOYMENT_CHECKLIST.md` — Step-by-step validation before going live
- `.claude/agent-memory/finpilot-devops/` — Persistent knowledge base for future reference

## Contact & Questions

For infrastructure questions or changes:
1. Check memory system: `.claude/agent-memory/finpilot-devops/`
2. Review relevant documentation files
3. Request changes through Orchestrator if files outside DevOps boundary need updates
