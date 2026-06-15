# FinPilot Frontend Agent Memory Index

| File | Type | Description |
|------|------|-------------|
| [project_auth_patterns.md](./project_auth_patterns.md) | project | Supabase Auth wiring — client factories, middleware guard, auth route structure |
| [project_shared_types.md](./project_shared_types.md) | project | `@finpilot/shared` Database type — import path, aliases, regeneration instructions |
| [project_m7_frontend.md](./project_m7_frontend.md) | project | M7 build constraints: no shadcn/ui, no chart libs, Next.js 14, component inventory, auth guard pattern |
| [project_m9_real_data.md](./project_m9_real_data.md) | project | M9 patterns: server-side encrypt flow, credential management UI, typed api-client, dashboard real Supabase data |
| [project_m10_dashboard_accounts.md](./project_m10_dashboard_accounts.md) | project | M10 patterns: account schema facts, CSS chart pattern, tab split, payroll income, account filter on transactions |
| [supabase_access_token_pattern.md](./supabase_access_token_pattern.md) | project | Always fetch `access_token` fresh via `getSession()` per API call — never cache in long-lived state (caused "Access token has expired" bug) |
| [project_nbe_split_sync_flow.md](./project_nbe_split_sync_flow.md) | project | "Sync All" for NBE runs 3 sequential split-sync phases (accounts/cards/certs); other banks use single full syncBank() |
