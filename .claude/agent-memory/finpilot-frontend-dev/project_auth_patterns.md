---
name: Auth patterns and Supabase client setup
description: How Supabase Auth is wired into the Next.js app — client factories, middleware guard, and auth route structure
type: project
---

Supabase Auth is integrated via three client factory modules under `apps/web/src/lib/supabase/`:

- `client.ts` — browser client using `createBrowserClient` from `@supabase/ssr`. Used inside `'use client'` components.
- `server.ts` — async server client using `createServerClient` + `next/headers` cookies. Used in Server Components and Route Handlers.
- `middleware.ts` — exports `updateSession()` which refreshes the session cookie on every request. Redirects unauthenticated users to `/auth/login` and authenticated users away from `/auth/*` to `/dashboard`.

The root middleware at `apps/web/src/middleware.ts` calls `updateSession` and is matched against all routes except static assets.

Auth pages live at:
- `/auth/login` — `signInWithPassword`, redirects to `/dashboard` on success
- `/auth/signup` — `signUp` with `full_name` in metadata options, shows email confirmation screen on success
- `/auth/reset-password` — `resetPasswordForEmail` with `redirectTo` pointing to `/auth/callback`
- `/auth/callback` — Route Handler that exchanges the OAuth/magic-link `code` for a session via `exchangeCodeForSession`, then redirects to `/dashboard`

All auth page components carry `'use client'` and manage form state with `useState`. No form library is used — plain controlled inputs with local validation.

**Why:** Supabase SSR package requires the cookie-based pattern (not `createClient` from `supabase-js` directly) so that the JWT is available in Server Components and middleware for RLS to work correctly.

**How to apply:** Always import from `@/lib/supabase/client` in client components and `@/lib/supabase/server` in server components. Never call `createBrowserClient` directly in a page file.
