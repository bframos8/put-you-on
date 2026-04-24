"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { SongRecCarousel } from "@/components/song-rec-carousel";
import { LogOut } from "lucide-react";

const TAPE_ITEMS = [
  "SIDE A",
  "TRACK LISTING",
  "FRESH PRESS",
  "PYO 0412",
  "MADE WITH EMBEDDINGS",
  "NO ALGORITHMS, JUST TASTE",
];

export default function Dashboard() {
  const router = useRouter();
  const [authed, setAuthed] = useState(false);
  const [date, setDate] = useState("");

  useEffect(() => {
    const d = new Date();
    const opts: Intl.DateTimeFormatOptions = {
      weekday: "long",
      month: "long",
      day: "numeric",
      year: "numeric",
    };
    setDate(d.toLocaleDateString("en-US", opts));

    if (process.env.NEXT_PUBLIC_DEV_BYPASS_AUTH === "true") {
      setAuthed(true);
      return;
    }
    fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/v1/auth/me`, {
      credentials: "include",
    })
      .then((res) => {
        if (!res.ok) {
          router.push("/");
          throw new Error("Not authenticated");
        }
        return res.json();
      })
      .then(() => setAuthed(true))
      .catch(() => {});
  }, [router]);

  if (!authed) {
    return (
      <div className="relative min-h-screen pt-20 flex items-center justify-center">
        <div className="flex flex-col items-center gap-4 text-center">
          <span className="label text-[color:var(--mist)]">TUNING IN…</span>
          <p className="font-display text-4xl md:text-5xl leading-[1]">
            Warming the{" "}
            <span className="italic font-display-soft">tape heads.</span>
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="relative min-h-screen pt-20">
      {/* ─── Tape marquee ─── */}
      <div className="border-y border-[color:var(--line)] bg-[color:var(--ink)] text-[color:var(--paper)] overflow-hidden">
        <div className="marquee py-2">
          <div className="marquee-track label">
            {Array.from({ length: 6 }).flatMap((_, g) =>
              TAPE_ITEMS.map((m, i) => (
                <span key={`${g}-${i}`} className="inline-flex items-center gap-8">
                  <span>{m}</span>
                  <span aria-hidden className="text-[color:var(--acid)]">✺</span>
                </span>
              ))
            )}
          </div>
        </div>
      </div>

      {/* ─── Editorial date plate ─── */}
      <section className="mx-auto max-w-[1480px] px-6 md:px-10 pt-10 md:pt-14">
        <div className="flex flex-wrap items-end justify-between gap-4 pb-6 border-b-2 border-[color:var(--ink)]">
          <div>
            <span className="label">§ TODAY&rsquo;S DISPATCH</span>
            <h1
              className="font-display text-[clamp(3rem,10vw,8rem)] leading-[0.86] mt-3 rise"
              style={{ animationDelay: "0.05s" }}
            >
              <span className="block">The{" "}
                <span className="italic font-display-soft">queue</span>,
              </span>
              <span className="block">freshly pressed.</span>
            </h1>
          </div>
          <div className="text-right flex flex-col items-end gap-1">
            <span className="label">ISSUE · {new Date().toISOString().slice(0,10).replace(/-/g,".")}</span>
            <span className="font-mono text-[0.82rem] text-[color:var(--mist)]">
              {date}
            </span>
          </div>
        </div>
      </section>

      {/* ─── Recommendations ─── */}
      <section
        className="mx-auto max-w-[1480px] px-6 md:px-10 pt-10 pb-20 rise"
        style={{ animationDelay: "0.2s" }}
      >
        <SongRecCarousel />
      </section>

      {/* ─── Colophon / logout row ─── */}
      <section className="border-t-2 border-[color:var(--ink)]">
        <div className="mx-auto max-w-[1480px] px-6 md:px-10 py-10 grid grid-cols-12 gap-6 items-center">
          <div className="col-span-12 md:col-span-7">
            <span className="label text-[color:var(--mist)]">
              COLOPHON · SET IN FRAUNCES &amp; IBM PLEX MONO
            </span>
            <p className="font-display text-2xl md:text-3xl leading-[1.1] mt-2 max-w-[40ch]">
              Curated by nearest-neighbor vectors and{" "}
              <span className="italic font-display-soft">
                editorial instinct.
              </span>
            </p>
          </div>
          <div className="col-span-12 md:col-span-5 flex md:justify-end items-center gap-4">
            <a
              href="/profile"
              className="label hover-rule"
            >
              ↩ YOUR TOP TEN
            </a>
            <button
              onClick={() => router.push("/logout")}
              className="inline-flex items-center gap-2 border border-[color:var(--ink)] px-4 py-2 label hover:bg-[color:var(--ink)] hover:text-[color:var(--paper)] transition-colors"
            >
              <LogOut size={14} />
              <span>SIGN OFF</span>
            </button>
          </div>
        </div>
      </section>

      {/* ─── Vanity footer ─── */}
      <section className="border-t border-[color:var(--line)] overflow-hidden">
        <div
          className="font-display leading-none text-[clamp(5rem,20vw,18rem)] tracking-[-0.06em] whitespace-nowrap text-center py-3"
          aria-hidden
        >
          END <span className="italic font-display-soft">of side A</span>
        </div>
      </section>
    </div>
  );
}
