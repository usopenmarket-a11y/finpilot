---
name: supabase-access-token-pattern
description: Standard pattern for using Supabase access tokens in client components — fetch fresh per call, never cache in long-lived state.
metadata:
  type: project
---

Never store `session.access_token` in component state and reuse it across multiple
API calls over time. Supabase access tokens are short-lived (~1 hour) and get
auto-refreshed by the Supabase client in the background, but a cached state value
does not get updated when that happens.

**Why:** This caused a production bug — `apps/web/src/components/settings/bank-accounts-section.tsx`
had a mount-only `useEffect` that called `supabase.auth.getSession()` once and stored
`access_token` in `accessToken` state. If the settings page stayed open past token
expiry/rotation, every subsequent sync/CRUD call sent the stale token and the backend
(`apps/api/app/deps.py` `get_current_user_id`) rejected it with 401 "Access token has
expired".

**How to apply:**
- `user_id` from `session.user.id` IS safe to fetch once on mount and cache — it's
  stable for the session.
- For the access token, add a small helper (e.g. `getAccessToken()` via `useCallback`)
  that calls `await supabase.auth.getSession()` and returns
  `data.session?.access_token ?? null`. Call this helper immediately before *every*
  API request (sync, CRUD, polling), not just on mount.
- This matches the pre-existing pattern in `apps/web/src/components/accounts/account-accordion.tsx`
  (`HideButton`'s `handleHide`) and `apps/web/src/components/transactions/transaction-table.tsx`
  (`handleRecategorize`) — both fetch session fresh right before the API call.
- If a fresh token comes back `null`, surface "Your session has expired. Please sign
  in again." rather than silently failing or sending an empty/stale token.
- Any new settings/CRUD component that needs auth tokens for client-side fetches
  should follow this per-call `getSession()` pattern from the start.
