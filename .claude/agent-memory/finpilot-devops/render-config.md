---
name: Render Deployment Configuration
description: Render backend service setup, free tier limits, and deployment pipeline
type: reference
---

## Service Configuration

**Service Name:** `finpilot-api`
**Type:** Web service (Docker-based)
**Framework:** Python 3.12 (FastAPI)
**Plan:** Free tier (750 hours/month, auto-suspends on inactivity)
**Build Trigger:** Automatic on git push to `main` (set via Render dashboard)

## Health Check

- **Endpoint:** `/api/v1/health`
- **Method:** GET
- **Response:** `{"status": "ok", "version": "0.1.0"}` (HTTP 200)
- **Used by:** Docker health checks, Uptime Robot monitoring

## Environment Variables (Secrets)

The following secrets must be configured via Render Dashboard (NOT in `render.yaml`):

| Variable | Description | Source |
|----------|-------------|--------|
| `SUPABASE_URL` | Supabase project API URL | Supabase dashboard |
| `SUPABASE_ANON_KEY` | Supabase anon key (public) | Supabase dashboard |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase service role key (secret) | Supabase dashboard (keep secure) |
| `ENCRYPTION_KEY` | AES-256-GCM key (32 bytes hex) | Generate and store securely |
| `CLAUDE_API_KEY` | Anthropic API key for categorization | Anthropic API dashboard |
| `CORS_ORIGINS` | Comma-separated list of allowed origins | Set to Vercel frontend URL |

## Deployment Pipeline

1. **Push to main** → GitHub detects push
2. **GitHub Actions** → Runs linting, testing, build checks (`.github/workflows/ci.yml`)
3. **Render Git Hook** → Automatically deploys if CI passes
4. **Build Phase** → Runs `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
5. **Health Check** → Render probes `/api/v1/health` every 30 seconds

**Note:** Do NOT use Render's manual deploy button in normal workflow — deployments happen automatically from Git.

## Free Tier Guardrails

- **750 hours/month** per service → Monitor via Render MCP dashboard logs
- **Auto-suspend on inactivity** → Default behavior, no configuration needed
- **At 80% usage (600 hours):** Flag in logs and notify via comment

## Monitoring

Use Render MCP to:
1. Check service uptime hours
2. Read runtime logs (check for errors in startup, API failures)
3. Verify environment variables are set (never retrieve actual values)
