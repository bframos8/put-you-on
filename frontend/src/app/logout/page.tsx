"use client";

import { useEffect, useState } from "react";
import { Disc3, ArrowRight } from "lucide-react";

type State = "signing_off" | "signed_off" | "error";

const SIGN_OFF_ITEMS = [
  "CATCH YOU LATER",
  "TAPE PARKED",
  "GOODNIGHT, LISTENER",
  "COME BACK TOMORROW",
  "NO ALGORITHM SLOP",
  "PYO / 2026",
];

export default function LogoutPage() {
  const [state, setState] = useState<State>("signing_off");

  useEffect(() => {
    try {
      window.localStorage.removeItem("pyo:recs");
    } catch {
      // ignore
    }
    const controller = new AbortController();
    fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/v1/auth/logout`, {
      method: "POST",
      credentials: "include",
      signal: controller.signal,
    })
      .then((res) => {
        setState(res.ok ? "signed_off" : "error");
      })
      .catch((err) => {
        if (err?.name === "AbortError") return;
        setState("error");
      });
    return () => controller.abort();
  }, []);

  if (state === "signing_off") {
    return (
      <div className="relative min-h-screen pt-20 flex items-center justify-center px-6">
        <div className="flex flex-col items-start text-left max-w-2xl w-full">
          <Disc3 size={52} strokeWidth={1.5} className="reel text-[color:var(--lime)]" />
          <span className="label mt-6 text-white/50">◖ BOUNCING…</span>
          <p className="tag text-5xl md:text-6xl mt-4">PEACE.</p>
          <p className="font-body text-[0.95rem] text-white/60 mt-4">
            Clearing your session. One sec.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="relative min-h-screen pt-16 overflow-hidden">
      {/* ─── Marquee ─── */}
      <div className="border-y-2 border-white bg-[color:var(--violet)] text-white overflow-hidden">
        <div className="marquee py-2">
          <div className="marquee-track label text-[0.78rem]">
            {Array.from({ length: 4 }).flatMap((_, g) =>
              SIGN_OFF_ITEMS.map((m, i) => (
                <span key={`${g}-${i}`} className="inline-flex items-center gap-6">
                  <span>{m}</span>
                  <span aria-hidden className="text-[color:var(--lime)]">✺</span>
                </span>
              ))
            )}
          </div>
        </div>
      </div>

      {/* ─── Hero ─── */}
      <section className="mx-auto max-w-[1480px] px-5 md:px-10 pt-10 md:pt-14">
        <div className="flex flex-wrap items-end justify-between gap-6 pb-6 border-b-2 border-white">
          <div className="label num flex flex-wrap gap-x-8 gap-y-1 text-white/45">
            <span>STATUS / SIGNED OUT</span>
            <span>
              DATE / {new Date().toISOString().slice(0, 10).replace(/-/g, ".")}
            </span>
          </div>
          <span className="label text-white">A FAREWELL</span>
        </div>

        <div className="grid grid-cols-12 gap-4 md:gap-6 pt-10 md:pt-14 pb-6">
          <div className="col-span-12 lg:col-span-9">
            <h1 className="leading-[0.84]">
              <span
                className="block tag text-[clamp(3rem,12vw,10rem)] stamp"
                style={{ animationDelay: "0.05s" }}
              >
                {state === "error" ? "ALMOST." : "CATCH YOU"}
              </span>
              <span
                className="block display text-[clamp(3rem,12vw,10rem)] text-[color:var(--lime)] stamp"
                style={{ animationDelay: "0.2s" }}
              >
                {state === "error" ? "try again." : "tomorrow."}
              </span>
            </h1>
          </div>

          <aside
            className="col-span-12 lg:col-span-3 lg:pt-12 fade"
            style={{ animationDelay: "0.55s" }}
          >
            <div className="flex flex-col gap-5">
              <span className="label text-white/50">— FROM YOUR PLUG</span>
              <p className="font-body text-[1.05rem] leading-relaxed text-white">
                {state === "error" ? (
                  <>
                    Something caught on the way out. Your session may still be
                    live — try again in a moment.
                  </>
                ) : (
                  <>
                    Your session is{" "}
                    <span className="ink-lime font-semibold">cleared</span>. Come
                    back when you want the next batch.
                  </>
                )}
              </p>
              <div className="rule-signal rule-animate" style={{ animationDelay: "0.9s" }} />
              <p className="font-body text-[0.88rem] leading-relaxed text-white/55">
                No trackers follow you out the door. Promise.
              </p>
            </div>
          </aside>
        </div>

        {/* ─── Return row ─── */}
        <div
          className="flex flex-col md:flex-row items-start md:items-center justify-between gap-8 pt-6 pb-14 border-t-2 border-white rise"
          style={{ animationDelay: "0.75s" }}
        >
          <a
            href="/"
            className="group relative inline-flex items-center gap-3 bg-[color:var(--lime)] px-7 py-4 text-black transition-transform duration-300 hover:-translate-x-[3px] hover:-translate-y-[3px]"
          >
            <span
              aria-hidden
              className="absolute inset-0 -z-[1] translate-x-[7px] translate-y-[7px] bg-[color:var(--violet)] transition-transform duration-300 group-hover:translate-x-[11px] group-hover:translate-y-[11px]"
            />
            <span className="label text-black/55">[ HOME ]</span>
            <span className="display text-2xl leading-none">Back to the wall</span>
            <ArrowRight size={22} strokeWidth={2.5} className="transition-transform duration-300 group-hover:translate-x-1" />
          </a>
          <div className="flex items-center gap-3 label text-white/55">
            <span aria-hidden className="inline-block h-[10px] w-[10px] rounded-full bg-[color:var(--lime)] blink-dot" />
            <span>SESSION RELEASED</span>
          </div>
        </div>
      </section>

      {/* ─── Vanity footer ─── */}
      <section className="border-t-2 border-white overflow-hidden bg-black">
        <div
          className="tag-flat leading-none text-[clamp(5rem,22vw,18rem)] whitespace-nowrap text-center py-3 text-white/10"
          aria-hidden
        >
          GOODNIGHT
        </div>
      </section>
    </div>
  );
}
