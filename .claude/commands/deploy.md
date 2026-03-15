---
description: Run tests, commit, push, and verify deployment to production.
---

Execute the FinPilot deployment pipeline:

1. **Pre-flight**: Run `turbo test` — abort if any tests fail
2. **Lint**: Run linters for both Python (ruff) and TypeScript (eslint)
3. **Commit**: Stage all changes, write a conventional commit message
4. **Push**: Push to `main` branch (triggers auto-deploy on Vercel + Render)
5. **Verify Backend**: Use Render MCP to monitor the deploy — wait for it to complete, check logs for errors
6. **Verify Frontend**: Use Vercel MCP to check the deployment status
7. **Health Check**: Hit the `/health` endpoint to confirm the API is responding
8. **Report**: Summarize what was deployed and any issues found

CRITICAL: Never push if tests fail. Never push secrets. Always verify after deploy.
