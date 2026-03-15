import { NextResponse } from 'next/server'
import { createClient } from '@/lib/supabase/server'

// ---------------------------------------------------------------------------
// Open-redirect guard
// ---------------------------------------------------------------------------
// The callback receives a `code` query parameter from Supabase and must
// redirect the user after exchanging it for a session.  Naively redirecting
// to `origin` derived from the inbound request.url is dangerous: in a
// reverse-proxy environment (Render, Vercel) the host portion can be
// influenced by attacker-controlled headers (X-Forwarded-Host), allowing an
// attacker to redirect authenticated users to a hostile domain.
//
// Mitigation: use the NEXT_PUBLIC_SITE_URL environment variable as the
// authoritative redirect base.  This value is set at build/deploy time and
// cannot be overridden at runtime by request headers.  Fallback to the
// request origin only in local development where NEXT_PUBLIC_SITE_URL is
// intentionally absent.
// ---------------------------------------------------------------------------

function getSafeRedirectBase(requestOrigin: string): string {
  const siteUrl = process.env.NEXT_PUBLIC_SITE_URL

  if (siteUrl) {
    // Strip any trailing slash so we always produce clean paths.
    return siteUrl.replace(/\/$/, '')
  }

  // Development fallback: trust the request origin only if it resolves to
  // localhost or a loopback address.
  try {
    const parsed = new URL(requestOrigin)
    const hostname = parsed.hostname
    if (hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '::1') {
      return requestOrigin.replace(/\/$/, '')
    }
  } catch {
    // Malformed origin — fall through to the safe error path.
  }

  // Cannot determine a safe base: redirect to a relative error path.  The
  // browser will resolve this against whatever origin the page was served
  // from, which is always correct.
  return ''
}

export async function GET(request: Request) {
  const { searchParams, origin } = new URL(request.url)
  const code = searchParams.get('code')

  const safeBase = getSafeRedirectBase(origin)

  if (!code) {
    // No auth code present — redirect to login with an error indicator so
    // the UI can display a meaningful message rather than a blank screen.
    return NextResponse.redirect(`${safeBase}/auth/login?error=missing_code`)
  }

  const supabase = await createClient()
  const { error } = await supabase.auth.exchangeCodeForSession(code)

  if (error) {
    // Exchange failed (expired code, already-used code, etc.).  Do NOT
    // redirect to /dashboard — the user has no valid session.
    return NextResponse.redirect(`${safeBase}/auth/login?error=auth_failed`)
  }

  return NextResponse.redirect(`${safeBase}/dashboard`)
}
