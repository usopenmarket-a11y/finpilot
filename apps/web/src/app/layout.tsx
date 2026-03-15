import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
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
        className={`${geistSans.variable} ${geistMono.variable} antialiased min-h-screen bg-white dark:bg-gray-950 text-gray-900 dark:text-gray-50`}
      >
        {children}
      </body>
    </html>
  );
}
