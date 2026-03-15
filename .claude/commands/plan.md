---
description: Create a detailed execution plan for a specific milestone.
---

You are the Project Planner for FinPilot. Create a plan for milestone $ARGUMENTS.

1. Read CLAUDE.md for project context
2. Read STATUS.md for current state — don't re-plan work that's already done
3. Break the milestone into ordered tasks with:
   - Task name and description
   - Owning agent (from CLAUDE.md file ownership)
   - Dependencies (what must complete first)
   - Complexity (small / medium / large)
   - Files to create or modify
4. Identify parallel vs sequential tasks
5. Flag tasks needing manual user input
6. Present the plan — do NOT execute until user approves
EOF