import type { Metadata } from "next";
import { Fraunces, IBM_Plex_Mono } from "next/font/google";
import "./globals.css";
import Navbar from "@/components/shadcn-studio/blocks/navbar-component-01/navbar-component-01";

const fraunces = Fraunces({
  variable: "--font-fraunces",
  subsets: ["latin"],
  display: "swap",
  axes: ["opsz", "SOFT", "WONK"],
});

const plexMono = IBM_Plex_Mono({
  variable: "--font-plex-mono",
  subsets: ["latin"],
  weight: ["300", "400", "500", "600"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "Put You On — a dispatch of sounds, sent your way",
  description:
    "Put You On is a music discovery dispatch. Log in with Spotify and we'll hand you songs you haven't heard yet — curated off your own listening.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body
        className={`${fraunces.variable} ${plexMono.variable} antialiased vignette`}
      >
        <div className="grain" aria-hidden />
        <Navbar />
        <main className="relative z-[3]">{children}</main>
      </body>
    </html>
  );
}
