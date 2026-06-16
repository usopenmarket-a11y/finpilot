import type { Metadata } from "next";
import { Fraunces, Hanken_Grotesk, IBM_Plex_Mono } from "next/font/google";
import "./globals.css";

// Body: Hanken Grotesk — a refined humanist grotesk with genuine character
// (deliberately not Inter/Roboto). The workhorse of the "Ledger" aesthetic.
const geistSans = Hanken_Grotesk({
  variable: "--font-geist-sans",
  subsets: ["latin"],
  display: "swap",
});

// Display: Fraunces — an old-style serif with optical sizing for editorial
// gravitas on headings and page titles.
const fraunces = Fraunces({
  variable: "--font-display",
  subsets: ["latin"],
  display: "swap",
  axes: ["opsz", "SOFT", "WONK"],
});

// Numerics & code: IBM Plex Mono — editorial, characterful monospace with
// tabular figures for money.
const geistMono = IBM_Plex_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  display: "swap",
});

export const metadata: Metadata = {
  title: {
    default: "FinPilot",
    template: "%s | FinPilot",
  },
  description:
    "FinPilot — personal banking intelligence for Egyptian bank accounts. Aggregate, analyze, and act on your finances.",
  metadataBase: new URL(
    process.env.NEXT_PUBLIC_APP_URL ?? "http://localhost:3000"
  ),
  openGraph: {
    siteName: "FinPilot",
    type: "website",
    locale: "en_US",
  },
  robots: {
    index: false, // private financial app — do not index
    follow: false,
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body
        className={`${geistSans.variable} ${fraunces.variable} ${geistMono.variable} antialiased min-h-screen bg-canvas text-ink`}
      >
        {children}
      </body>
    </html>
  );
}
