"use client";

import { useEffect, useState } from "react";
import { Disc3, ArrowRight } from "lucide-react";

type State = "signing_off" | "signed_off" | "error";

const SIGN_OFF_ITEMS = [
  "END OF TRANSMISSION",
  "SIDE B — SIGN OFF",
  "GOODNIGHT, LISTENER",
  "STATIC · STATIC · STATIC",
  "NO ALGORITHMS, JUST TASTE",
  "PYO / 2026",
];

export default function LogoutPage() {
  const [state, setState] = useState<State>("signing_off");

  useEffect(() => {
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
          <Disc3 size={52} className="reel" />
          <span className="label mt-6 text-[color:var(--mist)]">
            § SIGNING OFF
          </span>
          <p className="font-display text-5xl md:text-6xl leading-[0.95] mt-3">
            Cutting the{" "}
            <span className="italic font-display-soft">transmission…</span>
          </p>
          <p className="font-mono text-sm text-[color:var(--mist)] mt-4">
            Rewinding your tape. One moment.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="relative min-h-screen pt-20">
      {/* ─── Marquee ─── */}
      <div className="border-y border-[color:var(--line)] bg-[color:var(--ink)] text-[color:var(--paper)] overflow-hidden">
        <div className="marquee py-2">
          <div className="marquee-track label">
            {Array.from({ length: 4 }).flatMap((_, g) =>
              SIGN_OFF_ITEMS.map((m, i) => (
                <span key={`${g}-${i}`} className="inline-flex items-center gap-8">
                  <span>{m}</span>
                  <span aria-hidden className="text-[color:var(--acid)]">✺</span>
                </span>
              ))
            )}
          </div>
        </div>
      </div>

      {/* ─── Masthead plate ─── */}
      <section className="mx-auto max-w-[1480px] px-6 md:px-10 pt-10 md:pt-14">
        <div className="flex flex-wrap items-end justify-between gap-6 pb-6 border-b-2 border-[color:var(--ink)]">
          <div className="label num flex flex-wrap gap-x-8 gap-y-1 text-[color:var(--mist)]">
            <span>SIDE / B</span>
            <span>CUT / FINAL</span>
            <span>
              DATE /{" "}
              {new Date().toISOString().slice(0, 10).replace(/-/g, ".")}
            </span>
          </div>
          <span className="label">A FAREWELL DISPATCH</span>
        </div>

        {/* ─── Hero type ─── */}
        <div className="grid grid-cols-12 gap-4 md:gap-6 pt-10 md:pt-14 pb-6">
          <div className="col-span-12 lg:col-span-9">
            <h1 className="font-display text-[clamp(3.4rem,13vw,11rem)] leading-[0.84]">
              <span
                className="block rise"
                style={{ animationDelay: "0.05s" }}
              >
                {state === "error" ? (
                  <>
                    We&rsquo;ll try the{" "}
                    <span className="italic font-display-soft">next</span>
                  </>
                ) : (
                  <>
                    Until the <span className="italic font-display-soft">next</span>
                  </>
                )}
              </span>
              <span
                className="block rise"
                style={{ animationDelay: "0.2s" }}
              >
                dispatch,{" "}
                <span className="acid-underline">friend.</span>
              </span>
            </h1>
          </div>

          <aside
            className="col-span-12 lg:col-span-3 lg:pt-12 fade"
            style={{ animationDelay: "0.55s" }}
          >
            <div className="flex flex-col gap-5">
              <span className="label">— FROM THE EDITORS</span>
              <p className="font-display text-[1.25rem] leading-[1.25] -tracking-[0.01em]">
                {state === "error" ? (
                  <>
                    Something caught in the reels on the way out. Your session
                    may still be live — try again in a moment.
                  </>
                ) : (
                  <>
                    Your session has been{" "}
                    <span className="italic font-display-soft">cut</span>. Come
                    back when you want the next issue.
                  </>
                )}
              </p>
              <div
                className="rule rule-animate"
                style={{ animationDelay: "0.9s" }}
              />
              <p className="font-mono text-[0.78rem] leading-relaxed text-[color:var(--mist)]">
                No trackers follow you out the door. Promise.
              </p>
            </div>
          </aside>
        </div>

        {/* ─── Sign-off row ─── */}
        <div
          className="flex flex-col md:flex-row items-start md:items-center justify-between gap-8 pt-6 pb-14 border-t border-[color:var(--line)] rise"
          style={{ animationDelay: "0.75s" }}
        >
          <div className="flex items-center gap-5">
            <span className="label num text-[color:var(--mist)]">[ END ]</span>
            <a
              href="/"
              className="group relative inline-flex items-center gap-4 bg-[color:var(--ink)] px-7 py-5 text-[color:var(--paper)] transition-transform duration-300 hover:-translate-y-[3px]"
            >
              <span
                aria-hidden
                className="absolute inset-0 -z-[1] translate-x-[6px] translate-y-[6px] bg-[color:var(--acid)] transition-transform duration-300 group-hover:translate-x-[10px] group-hover:translate-y-[10px]"
              />
              <span className="label num opacity-70">[ RETURN ]</span>
              <span className="font-display text-2xl leading-none tracking-tight">
                Back to the masthead
              </span>
              <ArrowRight
                size={22}
                className="transition-transform duration-300 group-hover:translate-x-1"
              />
            </a>
          </div>
          <div className="flex items-center gap-3 label text-[color:var(--mist)]">
            <span
              aria-hidden
              className="inline-block h-[9px] w-[9px] rounded-full bg-[color:var(--acid)] blink-dot border border-[color:var(--ink)]"
            />
            <span>SIGNAL RELEASED — TAPE PARKED</span>
          </div>
        </div>
      </section>

      {/* ─── Vanity footer type ─── */}
      <section className="border-t-2 border-[color:var(--ink)] overflow-hidden">
        <div
          className="font-display leading-none text-[clamp(6rem,22vw,20rem)] tracking-[-0.06em] whitespace-nowrap text-center py-3"
          aria-hidden
        >
          goodnight{" "}
          <span className="italic font-display-soft">/ listener</span>
        </div>
      </section>
    </div>
  );
}
