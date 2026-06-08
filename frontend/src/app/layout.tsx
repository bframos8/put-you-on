import type { Metadata } from "next";
import localFont from "next/font/local";
import { Hind, Permanent_Marker } from "next/font/google";
import "./globals.css";
import Navbar from "@/components/shadcn-studio/blocks/navbar-component-01/navbar-component-01";

/* ── BRAND FONTS ─────────────────────────────────────────────────────────
 * See frontend/.claude-frontend-V2 for the full type system + swap contract.
 *
 *  --font-accent  Smiley Sans (得意黑)   self-hosted, the loud workhorse display
 *  --font-body    Kohinoor Telugu        ← SUBSTITUTE: Hind (same foundry, ITF)
 *  --font-burst   behance DX Burst       ← SUBSTITUTE: Permanent Marker (tag/marker)
 *
 * To swap a substitute for the real file: drop it in src/assets/fonts/ and
 * replace the next/font/google import below with a `localFont({ ... })` call
 * exposing the SAME css variable. Nothing else needs to change.
 * ------------------------------------------------------------------------ */

// Accent — Smiley Sans (self-hosted, final).
const accent = localFont({
  src: "../assets/fonts/SmileySans-Oblique.woff2",
  variable: "--font-accent",
  display: "swap",
});

// Body — substitute for Kohinoor Telugu (warm humanist sans, same foundry).
const body = Hind({
  variable: "--font-body",
  subsets: ["latin"],
  weight: ["300", "400", "500", "600", "700"],
  display: "swap",
});

// Burst — substitute for behance DX Burst (graffiti / marker tag face).
const burst = Permanent_Marker({
  variable: "--font-burst",
  subsets: ["latin"],
  weight: "400",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Put You On — get put on to songs you haven't heard yet",
  description:
    "Put You On is a music plug. Log in with Spotify and we hand you 10 fresh songs a day — pulled straight off your own taste. No feed, no algorithm slop.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body
        className={`${accent.variable} ${body.variable} ${burst.variable} antialiased`}
      >
        <div className="grain" aria-hidden />
        <Navbar />
        <main className="relative z-[3]">{children}</main>
      </body>
    </html>
  );
}
