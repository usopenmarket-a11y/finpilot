import { type NextRequest } from 'next/server'
import { updateSession } from '@/lib/supabase/middleware'

export async function middleware(request: NextRequest) {
  return await updateSession(request)
}

// /api/v1/* is rewritten to the FastAPI service, which verifies the Supabase
// JWT itself. Running the session middleware there would redirect cookie-less
// server-side API calls to /auth/login and add a Supabase round trip per call.
export const config = {
  matcher: [
    '/((?!api/v1/|_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)',
  ],
}
