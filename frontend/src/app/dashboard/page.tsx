"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { SongRecCarousel } from "@/components/song-rec-carousel";
import { LogOut } from "lucide-react";

const TAPE_ITEMS = [
  "TODAY'S BATCH",
  "FRESH PRESS",
  "10 A DAY",
  "STRAIGHT OFF YOUR TASTE",
  "MADE WITH EMBEDDINGS",
  "NO ALGORITHM SLOP",
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
          <span className="label text-white/50">◖ TUNING IN…</span>
          <p className="tag text-4xl md:text-5xl">DIGGING…</p>
        </div>
      </div>
    );
  }

  return (
    <div className="relative min-h-screen pt-16 overflow-hidden">
      {/* ─── Tape marquee ─── */}
      <div className="border-y-2 border-white bg-[color:var(--lime)] text-black overflow-hidden">
        <div className="marquee py-2">
          <div className="marquee-track label text-[0.78rem]">
            {Array.from({ length: 6 }).flatMap((_, g) =>
              TAPE_ITEMS.map((m, i) => (
                <span key={`${g}-${i}`} className="inline-flex items-center gap-6">
                  <span>{m}</span>
                  <span aria-hidden>✺</span>
                </span>
              ))
            )}
          </div>
        </div>
      </div>

      {/* ─── Date plate ─── */}
      <section className="mx-auto max-w-[1480px] px-5 md:px-10 pt-10 md:pt-14">
        <div className="flex flex-wrap items-end justify-between gap-4 pb-6 border-b-2 border-white">
          <div>
            <span className="label text-[color:var(--lime)]">◖ TODAY&rsquo;S BATCH</span>
            <h1
              className="mt-3 leading-[0.84] rise"
              style={{ animationDelay: "0.05s" }}
            >
              <span className="block tag text-[clamp(2.6rem,9vw,7rem)]">
                FRESH PRESS,
              </span>
              <span className="block display text-[clamp(2.6rem,9vw,7rem)] text-white">
                just for you.
              </span>
            </h1>
          </div>
          <div className="text-right flex flex-col items-end gap-1">
            <span className="label num text-white">
              {new Date().toISOString().slice(0, 10).replace(/-/g, ".")}
            </span>
            <span className="font-body text-[0.85rem] text-white/55">{date}</span>
          </div>
        </div>
      </section>

      {/* ─── Recommendations ─── */}
      <section
        className="mx-auto max-w-[1480px] px-5 md:px-10 pt-10 pb-20 rise"
        style={{ animationDelay: "0.2s" }}
      >
        <SongRecCarousel />
      </section>

      {/* ─── Footer / logout row ─── */}
      <section className="border-t-2 border-white bg-[color:var(--violet)]">
        <div className="mx-auto max-w-[1480px] px-5 md:px-10 py-12 grid grid-cols-12 gap-6 items-center">
          <div className="col-span-12 md:col-span-7">
            <span className="label text-white/60">◖ THE PLUG</span>
            <p className="display text-2xl md:text-3xl leading-[1.1] mt-2 max-w-[40ch] text-white">
              Picked by nearest-neighbor vectors and a little{" "}
              <span className="text-[color:var(--lime)]">good taste.</span>
            </p>
          </div>
          <div className="col-span-12 md:col-span-5 flex md:justify-end items-center gap-4">
            <a href="/profile" className="label text-white spray-link">
              ↩ YOUR TOP TEN
            </a>
            <button
              onClick={() => router.push("/logout")}
              className="inline-flex items-center gap-2 border-2 border-white px-4 py-2 label text-white hover:bg-white hover:text-black transition-colors"
            >
              <LogOut size={14} strokeWidth={2.5} />
              <span>BOUNCE</span>
            </button>
          </div>
        </div>
      </section>

      {/* ─── Vanity footer ─── */}
      <section className="border-t-2 border-white overflow-hidden bg-black">
        <div
          className="tag-flat leading-none text-[clamp(4rem,20vw,16rem)] whitespace-nowrap text-center py-3 text-white/10"
          aria-hidden
        >
          THAT&rsquo;S THE BATCH
        </div>
      </section>
    </div>
  );
}
