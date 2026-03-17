import { createServerClient } from '@supabase/ssr'
import { cookies } from 'next/headers'
import type { Database } from '@finpilot/shared'

type CookieToSet = { name: string; value: string; options?: Record<string, unknown> }

// Reassemble the anon key from split env vars (see next.config.mjs for why).
const _supabaseUrl =
  process.env.NEXT_PUBLIC_SUPABASE_URL ??
  'https://sftwyjuugkvmjpwamcoi.supabase.co'

const _anonKey =
  (process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY_P1 ??
    'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNm') +
  (process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY_P2 ??
    'dHd5anV1Z2t2bWpwd2FtY29pIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzM2MDMwMjQsImV4cCI6MjA4OTE3OTAyNH0.yDJQ4s_HFmUJov-lDlAbe3wx-2uqQ2SosBOW2Dx6KuU')

export async function createClient() {
  const cookieStore = await cookies()

  return createServerClient<Database>(
    _supabaseUrl,
    _anonKey,
    {
      cookies: {
        getAll() {
          return cookieStore.getAll()
        },
        setAll(cookiesToSet: CookieToSet[]) {
          try {
            cookiesToSet.forEach(({ name, value, options }: CookieToSet) =>
              cookieStore.set(name, value, options)
            )
          } catch {
            // Server component — cookies set by middleware
          }
        },
      },
    }
  )
}
