# FinPilot Deployment Checklist

This checklist guides you through validating and finalizing the M1 DevOps infrastructure setup.

## Pre-Deployment Validation

### Local Testing

- [ ] Clone the repository locally
- [ ] Run `docker-compose up -d` to start all services
- [ ] Verify services are running:
  - [ ] Frontend accessible at `http://localhost:3000`
  - [ ] Backend accessible at `http://localhost:8000`
  - [ ] Health endpoint returns 200: `curl http://localhost:8000/api/v1/health`
  - [ ] PostgreSQL running on port 54322
- [ ] Run CI checks locally:
  ```bash
  # Frontend
  cd apps/web && pnpm install && pnpm lint && pnpm type-check

  # Backend
  cd apps/api && uv sync && uv run ruff check . && uv run mypy app/ && uv run pytest
  ```
- [ ] Stop services: `docker-compose down`

### GitHub Actions Validation

- [ ] Push a test branch to GitHub
- [ ] Verify GitHub Actions workflow runs automatically
- [ ] Check that all three jobs complete:
  - [ ] `lint-and-type-check-frontend` — passes
  - [ ] `test-backend` — passes with ≥80% coverage
  - [ ] `lint-backend` — passes (ruff lint, format, mypy)
- [ ] Merge to `main` and verify deploy workflows trigger:
  - [ ] `deploy-frontend.yml` runs (needs secrets configured)
  - [ ] `deploy-backend.yml` runs (informational)

## Render Deployment Setup

### Prerequisites
- [ ] Have a Render account at https://render.com
- [ ] GitHub repository is public or connected to Render

### Configuration

1. **Connect Repository**
   - [ ] Go to Render Dashboard → New → Web Service
   - [ ] Connect GitHub account and select `finpilot` repository
   - [ ] Authorize Render to access GitHub

2. **Service Configuration**
   - [ ] Select `main` branch
   - [ ] Set Name: `finpilot-api`
   - [ ] Set Root Directory: (leave blank — uses repo root)
   - [ ] Set Build Command: (use Dockerfile)
   - [ ] Set Start Command: (use Dockerfile CMD)
   - [ ] Select Plan: **Free** (auto-suspends on inactivity)

3. **Environment Variables**
   - [ ] Add `APP_ENV`: `production`
   - [ ] Add `LOG_LEVEL`: `info`
   - [ ] Add `SUPABASE_URL`: (from Supabase dashboard)
   - [ ] Add `SUPABASE_ANON_KEY`: (from Supabase dashboard)
   - [ ] Add `SUPABASE_SERVICE_ROLE_KEY`: (from Supabase dashboard, keep secure)
   - [ ] Add `ENCRYPTION_KEY`: (32-byte hex string, generate securely)
   - [ ] Add `CLAUDE_API_KEY`: (from Anthropic API dashboard)
   - [ ] Add `CORS_ORIGINS`: (Vercel frontend URL, e.g., `https://finpilot-web.vercel.app`)

4. **Deploy**
   - [ ] Click Deploy
   - [ ] Wait for build to complete (~2-3 minutes)
   - [ ] Verify health check passes: `https://finpilot-api.onrender.com/api/v1/health`
   - [ ] Service shows "Live" status

### Verification
- [ ] Open service URL in browser
- [ ] Health endpoint returns JSON: `{"status": "ok", "version": "0.1.0"}`
- [ ] Check Render logs for any startup errors
- [ ] Confirm auto-deployment is enabled (push to main triggers redeploy)

## Vercel Deployment Setup

### Prerequisites
- [ ] Have a Vercel account at https://vercel.com
- [ ] GitHub repository is connected to Vercel

### Configuration

1. **Create Project**
   - [ ] Go to Vercel Dashboard → Add New → Project
   - [ ] Import GitHub repository `finpilot`
   - [ ] Select `apps/web` as Root Directory

2. **Environment Variables**
   - [ ] Add `NEXT_PUBLIC_API_URL`: `https://finpilot-api.onrender.com` (from Render)
   - [ ] Add `NEXT_PUBLIC_SUPABASE_URL`: (from Supabase dashboard)
   - [ ] Add `NEXT_PUBLIC_SUPABASE_ANON_KEY`: (from Supabase dashboard)

3. **Deploy**
   - [ ] Click Deploy
   - [ ] Wait for build to complete (~2-3 minutes)
   - [ ] Verify frontend loads at deployment URL
   - [ ] Check that page can communicate with backend API

### Verification
- [ ] Frontend loads without errors
- [ ] Console logs show no API connection errors
- [ ] Can navigate between pages
- [ ] Confirm auto-deployment is enabled (push to main triggers redeploy)

## GitHub Secrets Configuration

### Required Secrets for CI/CD

Set these in GitHub repository Settings → Secrets and Variables → Actions:

- [ ] `VERCEL_TOKEN`: Generate at https://vercel.com/account/tokens
- [ ] `VERCEL_ORG_ID`: From Vercel dashboard (Account Settings → General)
- [ ] `VERCEL_PROJECT_ID`: From Vercel project dashboard (Settings → General)

### Verification
- [ ] Create a test commit on main branch
- [ ] Verify `deploy-frontend.yml` workflow runs and deploys to Vercel
- [ ] Check Vercel deployment succeeded in Vercel dashboard

## Monitoring & Health Checks

### Health Endpoint Monitoring

- [ ] Test health endpoint: `curl https://finpilot-api.onrender.com/api/v1/health`
- [ ] Verify response: `{"status": "ok", "version": "0.1.0"}`

### Optional: Uptime Robot

To set up automated monitoring (free tier):
- [ ] Create account at https://uptimerobot.com
- [ ] Add HTTP Monitor:
  - [ ] Name: `FinPilot Health`
  - [ ] URL: `https://finpilot-api.onrender.com/api/v1/health`
  - [ ] Interval: 5 minutes (free tier maximum)
  - [ ] Alert contact: Project owner email
- [ ] Confirm monitor shows "Up"

### Vercel & Render Dashboards

- [ ] Check Render dashboard for:
  - [ ] Service status: "Live"
  - [ ] CPU/Memory usage within limits
  - [ ] No error logs in past 24 hours
- [ ] Check Vercel dashboard for:
  - [ ] Latest deployment status: "Ready"
  - [ ] No build errors
  - [ ] Bandwidth usage < 10% of monthly limit

## Post-Deployment Testing

### Frontend Functionality
- [ ] Access Vercel deployment URL
- [ ] Verify all pages load
- [ ] Check browser console for no errors
- [ ] Test API endpoint calls (if available in UI)

### Backend API Testing
- [ ] Test health endpoint: `curl -X GET https://finpilot-api.onrender.com/api/v1/health`
- [ ] Review Render logs for startup messages and any warnings

### CI/CD Pipeline Testing
- [ ] Create a feature branch
- [ ] Make a code change
- [ ] Create a PR to `main`
- [ ] Verify GitHub Actions runs all checks
- [ ] Merge to `main`
- [ ] Verify deployment workflows run:
  - [ ] `deploy-frontend.yml` completes and Vercel updates
  - [ ] `deploy-backend.yml` notifies (Render auto-deploys in background)
- [ ] Verify both deployments appear in Vercel and Render dashboards

## Common Issues & Troubleshooting

### Render Health Check Failing
- **Issue:** Health check endpoint returns 502/503
- **Solution:**
  - Check Render logs for application startup errors
  - Verify `SUPABASE_URL` and other environment variables are set
  - Confirm `/api/v1/health` endpoint exists in FastAPI app

### Vercel Build Failing
- **Issue:** Build logs show "Cannot find module"
- **Solution:**
  - Check `pnpm-lock.yaml` is committed
  - Run `pnpm install --frozen-lockfile` locally and recommit
  - Verify `pnpm --filter web build` works locally

### Frontend Can't Connect to Backend
- **Issue:** API requests to backend fail with CORS or 404 errors
- **Solution:**
  - Verify `NEXT_PUBLIC_API_URL` is set in Vercel
  - Confirm `CORS_ORIGINS` includes Vercel deployment URL in Render
  - Check `vercel.json` rewrites are correctly configured

### Docker Compose Services Won't Start
- **Issue:** `docker-compose up` fails
- **Solution:**
  - Check Docker daemon is running
  - Run `docker-compose down -v` to remove stale volumes
  - Verify `apps/api/.env` and `apps/web/.env.local` exist (can be empty)
  - Check port conflicts: `docker ps` should be empty initially

## Monitoring Checklist (After Deployment)

### Daily (First Week)
- [ ] Check Render logs for errors
- [ ] Verify health endpoint is responsive
- [ ] Check Vercel build logs for warnings

### Weekly
- [ ] Review Render runtime logs
- [ ] Monitor Render uptime hours (should be <100 for M1)
- [ ] Check Vercel bandwidth usage
- [ ] Verify no console errors in production

### Monthly
- [ ] Check Render usage: 750 hours/month free tier
- [ ] Check Vercel bandwidth: 100 GB/month free tier
- [ ] Review and optimize if approaching limits
- [ ] Update memory notes with actual usage baselines

## Sign-Off

- [ ] All local tests pass
- [ ] GitHub Actions workflows complete successfully
- [ ] Render deployment is "Live" and health check passes
- [ ] Vercel deployment is "Ready" and frontend loads
- [ ] CI/CD pipeline works end-to-end (commit → deploy)
- [ ] Team members can clone, build, and run locally
- [ ] Monitoring dashboard(s) configured and tested

**Completion Date:** _________________
**Verified By:** _________________
