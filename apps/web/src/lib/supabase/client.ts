import { createBrowserClient } from '@supabase/ssr'
import type { Database } from '@finpilot/shared'

// Reassemble the anon key from two short halves injected via next.config.mjs
// env block. This prevents the minifier from wrapping the long JWT string
// literal across lines, which corrupts the token at runtime.
const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL!
const anonKey =
  (process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY_P1 ?? '') +
  (process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY_P2 ?? '')

export function createClient() {
  return createBrowserClient<Database>(supabaseUrl, anonKey)
}
