// Non-secret public keys — safe to commit as fallback values.
const SUPABASE_URL =
  process.env.NEXT_PUBLIC_SUPABASE_URL ??
  "https://sftwyjuugkvmjpwamcoi.supabase.co";

// The anon key fallback. When inlined by Next.js/webpack, terser may wrap
// long string literals which breaks the JWT. The terserOptions below disable
// that wrapping, but as a belt-and-suspenders measure the key is also stored
// split across two env vars (both injected via the env block below) and
// re-joined in client.ts so each individual string is short enough that
// terser won't touch it.
const _ANON_P1 =
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY_P1 ??
  "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNm";
const _ANON_P2 =
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY_P2 ??
  "dHd5anV1Z2t2bWpwd2FtY29pIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzM2MDMwMjQsImV4cCI6MjA4OTE3OTAyNH0.yDJQ4s_HFmUJov-lDlAbe3wx-2uqQ2SosBOW2Dx6KuU";

const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "https://finpilot-api-lrfg.onrender.com";

/** @type {import('next').NextConfig} */
const nextConfig = {
  env: {
    NEXT_PUBLIC_SUPABASE_URL: SUPABASE_URL,
    // Full key for server components (process.env is not minified server-side).
    NEXT_PUBLIC_SUPABASE_ANON_KEY:
      process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? _ANON_P1 + _ANON_P2,
    // Split parts for client bundle — assembled in lib/supabase/client.ts.
    NEXT_PUBLIC_SUPABASE_ANON_KEY_P1: _ANON_P1,
    NEXT_PUBLIC_SUPABASE_ANON_KEY_P2: _ANON_P2,
    NEXT_PUBLIC_API_URL: API_URL,
  },
  webpack(config, { isServer }) {
    if (!isServer) {
      // Prevent terser from wrapping long string literals (e.g. JWT tokens)
      // across multiple lines, which corrupts them at runtime.
      const TerserPlugin = config.optimization?.minimizer?.find(
        (p) => p?.constructor?.name === "TerserPlugin",
      );
      if (TerserPlugin) {
        TerserPlugin.options = TerserPlugin.options ?? {};
        TerserPlugin.options.terserOptions =
          TerserPlugin.options.terserOptions ?? {};
        TerserPlugin.options.terserOptions.output =
          TerserPlugin.options.terserOptions.output ?? {};
        TerserPlugin.options.terserOptions.output.max_line_len = false;
      }
    }
    return config;
  },
  async rewrites() {
    return [
      {
        source: "/api/v1/:path*",
        destination: `${API_URL}/api/v1/:path*`,
      },
    ];
  },
};

export default nextConfig;
