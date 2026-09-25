import { createServerClient } from '@supabase/ssr'
import { NextResponse, type NextRequest } from 'next/server'
import type { Database } from '@finpilot/shared'

type CookieToSet = { name: string; value: string; options?: Record<string, unknown> }

// Reassemble the anon key from split env vars (see next.config.mjs for why it
// is split). Falls back to literal halves so middleware works on Vercel even
// when the project-level env vars are not explicitly set.
const _supabaseUrl =
  process.env.NEXT_PUBLIC_SUPABASE_URL ??
  'https://sftwyjuugkvmjpwamcoi.supabase.co'

const _anonKey =
  (process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY_P1 ??
    'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNm') +
  (process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY_P2 ??
    'dHd5anV1Z2t2bWpwd2FtY29pIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzM2MDMwMjQsImV4cCI6MjA4OTE3OTAyNH0.yDJQ4s_HFmUJov-lDlAbe3wx-2uqQ2SosBOW2Dx6KuU')

export async function updateSession(request: NextRequest) {
  let supabaseResponse = NextResponse.next({ request })

  const supabase = createServerClient<Database>(
    _supabaseUrl,
    _anonKey,
    {
      cookies: {
        getAll() {
          return request.cookies.getAll()
        },
        setAll(cookiesToSet: CookieToSet[]) {
          cookiesToSet.forEach(({ name, value }: CookieToSet) =>
            request.cookies.set(name, value)
          )
          supabaseResponse = NextResponse.next({ request })
          cookiesToSet.forEach(({ name, value, options }: CookieToSet) =>
            supabaseResponse.cookies.set(name, value, options)
          )
        },
      },
    }
  )

  const {
    data: { user },
  } = await supabase.auth.getUser()

  const isAuthRoute = request.nextUrl.pathname.startsWith('/auth')
  const isRecoveryOrCallback = ['/auth/callback', '/auth/update-password'].includes(request.nextUrl.pathname)
  const isPublicRoute = request.nextUrl.pathname === '/'
  const redirectWithCookies = (url: URL) => {
    const response = NextResponse.redirect(url)
    supabaseResponse.cookies.getAll().forEach(cookie => response.cookies.set(cookie))
    return response
  }

  if (!user && !isAuthRoute && !isPublicRoute) {
    const url = request.nextUrl.clone()
    url.pathname = '/auth/login'
    return redirectWithCookies(url)
  }

  if (user && isAuthRoute && !isRecoveryOrCallback) {
    const url = request.nextUrl.clone()
    url.pathname = '/dashboard'
    return redirectWithCookies(url)
  }

  return supabaseResponse
}
