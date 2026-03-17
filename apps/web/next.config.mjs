/** @type {import('next').NextConfig} */
const nextConfig = {
  // Provide fallback values for public env vars so the build works even
  // when NEXT_PUBLIC_* vars are not set in the Vercel project settings.
  // These are non-secret public keys — safe to commit.
  env: {
    NEXT_PUBLIC_SUPABASE_URL:
      process.env.NEXT_PUBLIC_SUPABASE_URL ??
      "https://sftwyjuugkvmjpwamcoi.supabase.co",
    NEXT_PUBLIC_SUPABASE_ANON_KEY:
      process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ??
      "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNmdHd5anV1Z2t2bWpwd2FtY29pIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzM2MDMwMjQsImV4cCI6MjA4OTE3OTAyNH0.yDJQ4s_HFmUJov-lDlAbe3wx-2uqQ2SosBOW2Dx6KuU",
    NEXT_PUBLIC_API_URL:
      process.env.NEXT_PUBLIC_API_URL ??
      "https://finpilot-api-lrfg.onrender.com",
  },
  async rewrites() {
    return [
      {
        source: "/api/v1/:path*",
        destination: `${process.env.NEXT_PUBLIC_API_URL ?? "https://finpilot-api-lrfg.onrender.com"}/api/v1/:path*`,
      },
    ];
  },
};

export default nextConfig;
