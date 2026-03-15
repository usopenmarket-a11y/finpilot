---
name: Free Tier Limits and Monitoring
description: Render and Vercel free tier constraints to prevent service disruption
type: project
---

## Render (Backend) Free Tier

**Limit:** 750 hours/month per service

**Action at 80% (600 hours):**
1. Check current uptime via Render MCP: `mcp__render__list_deploys`
2. Add inline comment in PR/commit noting usage
3. Flag for project lead to consider upgraded plan if trend continues

**Auto-suspend behavior:** Free tier services automatically suspend after 30 minutes of inactivity and restart on first request (cold start ~10-30 seconds). This is expected and does NOT count against the 750-hour limit.

**Baseline for M1:** During initial development with <10 requests/day, expect ~100-150 hours/month usage.

## Vercel (Frontend) Free Tier

**Limit:** 100 GB bandwidth/month

**Action at 80% (80 GB):**
1. Check bandwidth via Vercel MCP runtime logs
2. Investigate source: high image size, video assets, excessive API calls
3. Optimize before 100% threshold: compress images, implement lazy loading
4. Flag for project lead if optimization insufficient

**Baseline for M1:** During initial development with minimal traffic, expect <1 GB/month usage.

## Monitoring Approach

**Monthly Check (every 1st of month):**
- Run Render MCP to get deployment metrics
- Run Vercel MCP to check bandwidth usage
- Update this memory with actual baseline vs. expected

**Per-Deploy Check:**
- After each production deployment, verify health checks pass
- Scan logs for unusual error patterns
- Confirm no resource leaks (database connections, memory, open files)

## Future Escalation

If either service approaches limits consistently:
- **Render:** Consider upgrading to Starter ($7/month) for 1000 hours/month + dedicated instance
- **Vercel:** Consider upgrading to Pro ($20/month) for 1000 GB bandwidth/month
