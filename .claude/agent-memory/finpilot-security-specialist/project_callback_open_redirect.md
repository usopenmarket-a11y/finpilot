---
name: Auth Callback Open Redirect Mitigation
description: Pattern for safe redirect URL construction in the Supabase auth callback route
type: project
---

`apps/web/src/app/auth/callback/route.ts` uses `NEXT_PUBLIC_SITE_URL` as the authoritative redirect base.

**Why:** `new URL(request.url).origin` can be manipulated via `X-Forwarded-Host` headers in reverse-proxy deployments (Vercel, Render). An attacker who can set this header on a request flowing through the proxy could redirect an authenticated user to a hostile domain after the OAuth code exchange.

**How to apply:** Any route that constructs a redirect URL from request data must use `NEXT_PUBLIC_SITE_URL` as the base, not `request.url` or `request.headers.host`.

## Pattern

```typescript
const safeBase = process.env.NEXT_PUBLIC_SITE_URL?.replace(/\/$/, '') ?? ''
// localhost fallback for development only
return NextResponse.redirect(`${safeBase}/dashboard`)
```

## Required env var

`NEXT_PUBLIC_SITE_URL` must be set in production Vercel deployments to the canonical app URL (e.g. `https://finpilot.vercel.app`). It is documented in `apps/web/.env.example`.

## Error handling added

The original callback silently swallowed `exchangeCodeForSession` errors and redirected to `/dashboard` regardless. The fixed version redirects to `/auth/login?error=auth_failed` on exchange failure and `/auth/login?error=missing_code` when the `code` parameter is absent.
