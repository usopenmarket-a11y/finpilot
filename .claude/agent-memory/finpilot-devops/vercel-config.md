---
name: Vercel Frontend Deployment Configuration
description: Vercel deployment setup for Next.js 15 frontend with environment variables
type: reference
---

## Project Configuration

**Root Directory:** `apps/web`
**Framework:** Next.js 15 (App Router)
**Build Command:** `pnpm run build`
**Output Directory:** `.next`

## Environment Variables

All environment variables must be configured via **Vercel Dashboard** (not in `vercel.json`).

| Variable | Scope | Description |
|----------|-------|-------------|
| `NEXT_PUBLIC_API_URL` | Public (frontend) | Backend API URL (e.g., `https://finpilot-api.onrender.com`) |
| `NEXT_PUBLIC_SUPABASE_URL` | Public | Supabase project URL |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Public | Supabase anon key |

**Public variables** are prefixed with `NEXT_PUBLIC_` and embedded in the client bundle. Only non-sensitive URLs and keys should use this prefix.

## Deployment Pipeline

1. **Push to main** (only `apps/web/**` changes) → GitHub detects via path filter
2. **GitHub Actions** (`deploy-frontend.yml`) → Lints, type-checks, runs tests
3. **Vercel Deploy** → Uses `amondnet/vercel-action` with stored secrets:
   - `VERCEL_TOKEN` (GitHub secret)
   - `VERCEL_ORG_ID` (GitHub secret)
   - `VERCEL_PROJECT_ID` (GitHub secret)
4. **Build Output** → Next.js generates `.next/` static and serverless functions
5. **CDN Distribution** → Deployed to Vercel Edge Network

## API Rewrites

The `vercel.json` includes a rewrite rule:
```json
"rewrites": [
  {
    "source": "/api/:path*",
    "destination": "${{ secrets.API_URL }}/api/:path*"
  }
]
```

This proxies `/api/*` requests from frontend to backend without exposing the backend URL to the client.

## Free Tier Guardrails

- **100 GB bandwidth/month** (as of 2026)
- **At 80 GB (80% usage):** Flag in Vercel MCP logs and notify via comment
- Monitor via `mcp__vercel__get_runtime_logs` for unexpected bandwidth spikes

## Monitoring

Use Vercel MCP to:
1. Check build logs for deployment errors
2. Verify environment variables are set (never retrieve actual values)
3. Monitor runtime logs for client-side errors
