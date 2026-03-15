---
description: Check the health and status of the entire FinPilot system.
---

Run a full system health check for FinPilot:

1. **Code**: Run `turbo test` and report pass/fail counts
2. **Database**: Use Supabase MCP to `list_tables` and check table row counts
3. **Backend**: Use Render MCP to check service status and recent logs for errors
4. **Frontend**: Use Vercel MCP to check latest deployment status
5. **Git**: Show current branch, uncommitted changes, and last 5 commits
6. **Dependencies**: Check for outdated packages with security vulnerabilities

Provide a concise summary with a health score (healthy / warning / critical) for each component.
