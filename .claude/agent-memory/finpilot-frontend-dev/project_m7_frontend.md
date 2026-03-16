---
name: M7 Frontend Dashboard — patterns and constraints
description: Key decisions made during M7 build: no shadcn/ui, no chart libs, CSS/SVG only, Next.js 14 App Router
type: project
---

M7 delivered the complete frontend dashboard UI from scratch in `apps/web/src/`.

**Why:** First full UI milestone — no live backend yet, all data is mock.

**Key constraints locked in during M7:**
- Next.js 14 App Router (NOT 15), React 18 (NOT 19)
- No shadcn/ui — all UI components hand-rolled in `src/components/ui/`
- No external chart packages — charts are pure CSS (bar widths as %) and SVG (stroke-dasharray gauge)
- All amounts formatted as `EGP X,XXX.XX` via `Intl.NumberFormat('en-EG')`
- Tailwind `brand-500` = `#22c55e` (green); only `brand-50`, `brand-500`, `brand-900` are defined in config
- `dark:` variant used throughout; no hardcoded hex colors in className attributes

**Component inventory:**
- `src/components/ui/` — Badge, Card/CardHeader/CardBody/CardFooter, Button, Input, Modal, Select, EmptyState
- `src/components/layout/` — Sidebar (mobile drawer + desktop sticky), DashboardLayout
- `src/components/dashboard/` — AccountCard, SpendingChart, RecentTransactions, HealthScore
- `src/components/transactions/` — TransactionTable (client component, local filter+sort+pagination)
- `src/components/debts/` — DebtList, AddDebtForm, PaymentModal
- `src/components/recommendations/` — MonthlyPlanCard, SavingsOpportunities, ForecastChart

**Auth pattern:** `src/app/dashboard/layout.tsx` is a server component that calls `createClient()` from `@/lib/supabase/server`, checks `getUser()`, and redirects to `/auth/login` if unauthenticated. Individual pages do NOT re-check auth — the layout handles it.

**How to apply:** When adding new dashboard routes, always nest them under `/dashboard/` so the layout auth guard applies automatically. Never duplicate the auth check in child pages.

**Pre-existing scaffold errors (not ours):** `@supabase/ssr`, `@finpilot/shared`, and `next/font/google` Geist types fail tsc because npm packages are not installed in the dev environment. These resolve on `npm install`.
