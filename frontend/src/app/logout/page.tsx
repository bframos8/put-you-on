"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Disc3, ArrowRight } from "lucide-react";

type State = "signing_off" | "signed_off" | "error";

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
          <Disc3 size={48} strokeWidth={1.5} className="reel text-[color:var(--pink)]" />
          <span className="label mt-6 text-white/45">Signing you out</span>
          <p className="display text-5xl md:text-6xl mt-4 text-white">One sec</p>
          <p className="font-body text-[0.95rem] text-white/55 mt-4">
            Clearing your session.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="relative min-h-screen pt-16 overflow-hidden">
      <section className="mx-auto max-w-[1320px] px-5 md:px-10 pt-20 md:pt-28">
        <div className="flex flex-wrap items-end justify-between gap-6 pb-8 border-b border-white/15">
          <div className="label num flex flex-wrap gap-x-8 gap-y-1 text-white/40">
            <span>Status / signed out</span>
            <span>
              Date / {new Date().toISOString().slice(0, 10).replace(/-/g, ".")}
            </span>
          </div>
        </div>

        <div className="grid grid-cols-12 gap-6 md:gap-10 pt-16 md:pt-24 pb-10">
          <div className="col-span-12 lg:col-span-8">
            <h1 className="leading-[0.9]">
              <span
                className="block display text-[clamp(2.8rem,10vw,8rem)] text-white rise"
                style={{ animationDelay: "0.05s" }}
              >
                {state === "error" ? "Almost." : "See you"}
              </span>
              <span
                className="block tag tag-pink text-[clamp(3rem,12vw,9rem)] rise"
                style={{ animationDelay: "0.18s" }}
              >
                {state === "error" ? "try again." : "tomorrow."}
              </span>
            </h1>
          </div>

          <aside
            className="col-span-12 lg:col-span-4 lg:pt-10 fade"
            style={{ animationDelay: "0.5s" }}
          >
            <div className="flex flex-col gap-5">
              <p className="font-body text-[1.05rem] leading-relaxed text-white/70">
                {state === "error" ? (
                  <>
                    Something caught on the way out. Your session may still be
                    live, so try again in a moment.
                  </>
                ) : (
                  <>
                    Your session is{" "}
                    <span className="ink-pink font-semibold">cleared</span>. Come
                    back when you want the next drop.
                  </>
                )}
              </p>
              <div className="border-t-2 border-[color:var(--blue)]" />
              <p className="font-body text-[0.88rem] leading-relaxed text-white/45">
                No trackers follow you out the door.
              </p>
            </div>
          </aside>
        </div>

        <div
          className="flex flex-col md:flex-row items-start md:items-center justify-between gap-8 pt-8 pb-16 border-t border-white/15 rise"
          style={{ animationDelay: "0.6s" }}
        >
          <Link
            href="/"
            className="group inline-flex items-center gap-3 bg-[color:var(--pink)] px-7 py-4 text-black transition-transform duration-300 hover:-translate-y-[3px]"
          >
            <span className="label text-black/55">Home</span>
            <span className="display text-2xl leading-none">Back home</span>
            <ArrowRight size={22} strokeWidth={2.5} className="transition-transform duration-300 group-hover:translate-x-1" />
          </Link>
          <div className="flex items-center gap-3 label text-white/45">
            <span aria-hidden className="inline-block h-1.5 w-1.5 rounded-full bg-[color:var(--pink)] blink-dot" />
            <span>Session released</span>
          </div>
        </div>
      </section>
    </div>
  );
}
