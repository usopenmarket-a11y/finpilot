---
description: Evaluate current project state and update STATUS.md with findings.
---

You are the Project Evaluator for FinPilot.

## Step 1: Read current state
- Read CLAUDE.md for milestone definitions and standards
- Read STATUS.md for previous review state
- Use Supabase MCP: list_tables to check database schema
- Use Render MCP: check backend service status
- Use Vercel MCP: check frontend deployment status
- Run: git log --oneline -20 for recent commits
- Run: find apps/api -name "*.py" | head -40
- Run: find apps/web/src -name "*.tsx" -o -name "*.ts" | head -40
- Check test results if tests exist

## Step 2: Grade each milestone
For each milestone M1-M8, determine:
- NOT STARTED (0%)
- IN PROGRESS (10-90%, estimate percentage)
- COMPLETE (100%, all deliverables done and tested)
- BLOCKED (explain why)

Check specific deliverables:
- M1: Does schema exist? Auth working? CI/CD pipeline? Encryption module?
- M2: NBE scraper exists? CIB scraper? Tests with mocks?
- M3: BDC/UB scrapers? Unified pipeline? Dedup? Cron jobs?
- M4: Categorization engine? Trend analysis? Credit card tracking?
- M5: Debt CRUD? Payment tracking? Settlement flow?
- M6: Monthly plans? Forecasting? Debt optimizer?
- M7: Dashboard? Charts? Transaction explorer? Responsive?
- M8: Production deploy? SSL? Monitoring? Docs?

## Step 3: Update STATUS.md
Write the updated STATUS.md with:
- Updated milestone table with current status and percentages
- "Current Focus" section with what to work on next
- "Blockers" section with anything needing manual intervention
- "Recent Changes" section summarizing what changed since last review
- "Last reviewed" timestamp updated to today

## Step 4: Report to user
After updating the file, give a brief verbal summary:
- What's done
- What's next
- Any action needed from the user

IMPORTANT: Always update STATUS.md — this is the project's living record that all agents reference.
EOF