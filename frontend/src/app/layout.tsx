import type { Metadata } from "next";
import localFont from "next/font/local";
import "./globals.css";
import Navbar from "@/components/shadcn-studio/blocks/navbar-component-01/navbar-component-01";

/* ── BRAND FONTS ─────────────────────────────────────────────────────────
 * See frontend/.claude-frontend-V3 for the full type system + voice rules.
 *
 *  --font-body    Helvetica          the calm Swiss read (paragraphs, metadata)
 *  --font-accent  Smiley Sans (得意黑) the loud workhorse display (headlines, UI)
 *  --font-burst   behance Estrella   the rare graffiti tag / signature
 *
 * All three are self-hosted in src/assets/fonts/ and exposed as CSS variables;
 * components reference the variables, never the font names.
 * ------------------------------------------------------------------------ */

// Body — Helvetica (real, self-hosted).
const body = localFont({
  src: [
    { path: "../assets/fonts/helvetica-light-587ebe5a59211.ttf", weight: "300", style: "normal" },
    { path: "../assets/fonts/Helvetica.ttf", weight: "400", style: "normal" },
    { path: "../assets/fonts/Helvetica-Oblique.ttf", weight: "400", style: "italic" },
    { path: "../assets/fonts/Helvetica-Bold.ttf", weight: "700", style: "normal" },
    { path: "../assets/fonts/Helvetica-BoldOblique.ttf", weight: "700", style: "italic" },
  ],
  variable: "--font-body",
  display: "swap",
  fallback: ["Helvetica", "Helvetica Neue", "Arial", "sans-serif"],
});

// Accent — Smiley Sans (self-hosted).
const accent = localFont({
  src: "../assets/fonts/SmileySans-Oblique.woff2",
  variable: "--font-accent",
  display: "swap",
});

// Burst — behance Estrella, the graffiti tag face (self-hosted).
const burst = localFont({
  src: "../assets/fonts/Estrella.otf",
  variable: "--font-burst",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Put You On — songs that sound like you",
  description:
    "Log in with Spotify and get ten songs a day, picked for how close they sound to the music you already love. One small drop, not an endless feed.",
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
