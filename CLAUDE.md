# FinPilot — Personal Banking Intelligence System

## Project Overview

FinPilot scrapes, analyzes, and provides financial recommendations from Egyptian bank accounts (NBE, CIB, BDC, UB). It includes a manual borrowing/lending tracker.

## Tech Stack

- **Frontend**: Next.js 15 + React 19 + Tailwind CSS + shadcn/ui → `/apps/web`
- **Backend**: Python FastAPI (async) + Pydantic v2 → `/apps/api`
- **Scraping**: Playwright (headless Chromium) + BeautifulSoup4 fallback
- **Database**: Supabase (PostgreSQL) with Row Level Security
- **Auth**: Supabase Auth (email/password + magic link)
- **AI**: Claude API (Haiku 4.5 for transaction categorization)
- **Hosting**: Vercel (frontend) + Render (backend) — both free tier
- **CI/CD**: GitHub Actions

## Monorepo Structure

```
finpilot/
├── CLAUDE.md                 # THIS FILE — project constitution
├── .claude/
│   ├── agents/               # Subagent definitions (auto-invoked)
│   └── commands/             # Slash commands
├── .mcp.json                 # MCP server connections (Supabase, Render, Vercel)
├── .github/workflows/        # CI/CD pipelines
├── apps/
│   ├── web/                  # Next.js frontend (Vercel)
│   │   ├── src/
│   │   │   ├── app/          # App router pages
│   │   │   ├── components/   # React components
│   │   │   ├── hooks/        # Custom hooks
│   │   │   └── lib/          # Utilities, API clients
│   │   ├── public/
│   │   └── package.json
│   └── api/                  # FastAPI backend (Render)
│       ├── main.py           # App entry point
│       ├── scrapers/         # Bank-specific scraper modules
│       │   ├── nbe.py
│       │   ├── cib.py
│       │   ├── bdc.py
│       │   └── ub.py
│       ├── pipeline/         # ETL, normalization, deduplication
│       ├── analytics/        # Categorization, trend analysis, credit tracking
│       ├── recommendations/  # Monthly plans, forecasting, debt optimizer
│       ├── models/           # Pydantic schemas, DB models
│       ├── routers/          # API route handlers
│       ├── tests/            # pytest test suite
│       └── requirements.txt
├── packages/
│   └── shared/               # Shared types, constants, utilities
├── turbo.json
└── package.json
```

## File Ownership Rules

These rules prevent agents from stepping on each other's files:

| Path | Owner Agent | Others May |
|------|-------------|------------|
| `apps/web/**` | Frontend Agent | Read only |
| `apps/api/scrapers/**` | Scraper Agent | Read only |
| `apps/api/pipeline/**` | Data Pipeline Agent | Read only |
| `apps/api/analytics/**` | Analytics Agent | Read only |
| `apps/api/recommendations/**` | Recommendations Agent | Read only |
| `apps/api/routers/**` | Backend (any API agent) | Read only |
| `apps/api/models/**` | Architect Agent | Read only |
| `apps/api/tests/**` | QA Agent | Read only |
| `.github/workflows/**` | DevOps Agent | Read only |
| `CLAUDE.md` | Orchestrator only | Read only |

If an agent needs to modify files it doesn't own, it must request the change through the Orchestrator, which delegates to the owning agent.

## Sub-Agent Routing Rules

### Parallel dispatch (ALL conditions must be met):
- 3+ unrelated tasks across different file ownership areas
- No shared state between tasks
- Clear file boundaries with no overlap

### Sequential dispatch (ANY condition triggers):
- Tasks have dependencies (B needs output from A)
- Shared files or state (merge conflict risk)
- Database schema changes (must be coordinated)

### Background dispatch:
- Research or analysis tasks (not file modifications)
- Running test suites
- Scraper testing with mocked responses

## MCP Tools — When to Use

### Supabase MCP
- Use for: schema changes, migrations, SQL queries, type generation, log inspection
- Always use `apply_migration` for schema changes (never raw SQL for DDL)
- Generate TypeScript types after every schema change
- Prompt: "Use Supabase MCP to..." when you want database operations

### Render MCP
- Use for: checking service status, reading logs, managing env vars
- Deploys happen automatically via Git push — do NOT try to trigger deploys manually
- Prompt: "Use Render MCP to..." when you need backend service info

### Vercel MCP
- Use for: reading deployment logs, checking build errors, searching Vercel docs
- Read-only — cannot modify deployments
- Prompt: "Use Vercel MCP to..." when you need frontend deployment info

## Coding Standards

### Python (Backend)
- Python 3.11+, type hints everywhere
- Pydantic v2 for all data models
- Async by default (use `async def` for all route handlers)
- pytest for testing, minimum 80% coverage for new code
- Naming: `snake_case` for files, functions, variables
- Imports: stdlib → third-party → local (isort order)

### TypeScript (Frontend)
- TypeScript strict mode, no `any` types
- React functional components with hooks only
- shadcn/ui for all UI components
- Tailwind CSS for styling (no CSS modules, no styled-components)
- Naming: `PascalCase` for components, `camelCase` for functions/variables
- File naming: `kebab-case.tsx` for components

### Git
- Branch from `main`, PR back to `main`
- Commit messages: `type(scope): description` (conventional commits)
  - Types: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`, `ci`
  - Scope: `web`, `api`, `scraper`, `analytics`, `pipeline`, `infra`
- One logical change per commit
- Always run tests before committing

## Security Rules (NON-NEGOTIABLE)

1. **Never** store bank credentials in plaintext — always AES-256-GCM encrypted
2. **Never** log sensitive data (passwords, tokens, account numbers)
3. **Never** commit `.env` files or secrets to Git
4. **Always** use Supabase Row Level Security on all tables
5. **Always** validate and sanitize all user input
6. **Always** use parameterized queries (never string concatenation for SQL)
7. Bank credentials exist only in memory during scraper execution
8. All API endpoints require JWT authentication

## Current Milestone

**M1: Foundation & Project Scaffolding** — See project guide for full milestone details.

## How to Run Locally

```bash
# Frontend
cd apps/web && npm install && npm run dev

# Backend
cd apps/api && pip install -r requirements.txt && uvicorn main:app --reload

# Both via Turbo
turbo dev
```

## Testing

```bash
# Backend tests
cd apps/api && pytest -v --cov=. --cov-report=term-missing

# Frontend tests
cd apps/web && npm test

# All tests via Turbo
turbo test
```
