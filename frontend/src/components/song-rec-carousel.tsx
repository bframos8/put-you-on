"use client";
import { useEffect, useState, useCallback, useRef } from "react";
import { Disc3, ArrowLeft, ArrowRight, RefreshCw } from "lucide-react";
import {
  Carousel,
  CarouselContent,
  CarouselItem,
} from "@/components/ui/carousel";

type Song = {
  id: number;
  title: string;
  artist_name: string;
  album_title: string;
  image_url: string | null;
  external_source_id: number | null;
  album_url: string | null;
};

type RecsResponse = {
  status: string;
  query_title: string | null;
  query_artist: string | null;
  recommendations: Song[];
  locked_for_today: boolean;
  next_dispatch_at: string | null;
};

const DISPATCH_CACHE_KEY = "pyo:recs";

function readCachedDispatch(): RecsResponse | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(DISPATCH_CACHE_KEY);
    if (!raw) return null;
    const data = JSON.parse(raw) as RecsResponse;
    if (!data.next_dispatch_at) return null;
    if (new Date(data.next_dispatch_at).getTime() <= Date.now()) {
      window.localStorage.removeItem(DISPATCH_CACHE_KEY);
      return null;
    }
    return data;
  } catch {
    window.localStorage.removeItem(DISPATCH_CACHE_KEY);
    return null;
  }
}

function writeCachedDispatch(data: RecsResponse) {
  if (typeof window === "undefined") return;
  if (data.status !== "ready" || !data.locked_for_today) return;
  try {
    window.localStorage.setItem(DISPATCH_CACHE_KEY, JSON.stringify(data));
  } catch {
    // localStorage unavailable (private mode / quota) — silently skip
  }
}

function RefreshButton({
  retryIn,
  lockedForToday,
  onRefresh,
}: {
  retryIn: number | null;
  lockedForToday: boolean;
  onRefresh: () => void;
}) {
  const isRateLimited = retryIn !== null && retryIn > 0;
  const disabled = lockedForToday || isRateLimited;

  const label = lockedForToday
    ? "Tomorrow · 12:00 AM PST"
    : isRateLimited
    ? `Refresh in ${retryIn}s`
    : "Pull a new dispatch";

  return (
    <button
      disabled={disabled}
      onClick={() => !disabled && onRefresh()}
      className={
        "group inline-flex items-center gap-3 border border-[color:var(--ink)] px-5 py-3 font-display text-lg transition-colors " +
        (disabled
          ? "opacity-40 cursor-not-allowed"
          : "hover:bg-[color:var(--acid)]")
      }
    >
      <RefreshCw
        size={16}
        className="transition-transform duration-500 group-hover:rotate-180"
      />
      <span>{label}</span>
    </button>
  );
}

export function SongRecCarousel() {
  const [recs, setRecs] = useState<RecsResponse | null>(null);
  const [processing, setProcessing] = useState(false);
  const [retryIn, setRetryIn] = useState<number | null>(null);
  const [index, setIndex] = useState(0);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const fetchRecs = useCallback(async () => {
    const res = await fetch(
      `${process.env.NEXT_PUBLIC_API_URL}/api/v1/items/song_recs/`,
      { credentials: "include" }
    );

    if (res.status === 429) {
      const retryAfter = parseInt(res.headers.get("Retry-After") ?? "60", 10);
      setRetryIn(retryAfter);
      return;
    }

    if (!res.ok) return;
    setRetryIn(null);

    const data: RecsResponse = await res.json();
    if (data.status === "processing") {
      setProcessing(true);
      startPolling();
    } else {
      setProcessing(false);
      setRecs(data);
      writeCachedDispatch(data);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const startPolling = useCallback(() => {
    if (pollRef.current) return;
    pollRef.current = setInterval(async () => {
      const res = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL}/api/v1/items/status`,
        { credentials: "include" }
      );
      if (!res.ok) return;
      const data = await res.json();
      if (data.status === "ready") {
        stopPolling();
        setProcessing(false);
        fetchRecs();
      }
    }, 5000);
  }, [stopPolling, fetchRecs]);

  useEffect(() => {
    const cached = readCachedDispatch();
    if (cached) {
      setRecs(cached);
    } else {
      fetchRecs();
    }
    return () => stopPolling();
  }, [fetchRecs, stopPolling]);

  useEffect(() => {
    if (!retryIn) return;
    const id = setInterval(() => {
      setRetryIn((prev) => (prev && prev > 1 ? prev - 1 : 0));
    }, 1000);
    return () => clearInterval(id);
  }, [retryIn]);

  if (processing) {
    return (
      <div className="relative flex flex-col items-center py-16 px-4 text-center max-w-xl mx-auto">
        <Disc3 size={54} className="reel text-[color:var(--ink)]" />
        <span className="label mt-6 text-[color:var(--mist)]">
          § PRESSING YOUR DISPATCH
        </span>
        <p className="font-display text-4xl md:text-5xl leading-[0.95] mt-3">
          Cutting the{" "}
          <span className="font-display-soft">acetate…</span>
        </p>
        <p className="font-mono text-sm text-[color:var(--mist)] mt-4 max-w-sm leading-relaxed">
          First issue always takes a minute. The machines are listening back to
          your top tracks and pulling the nearest neighbors. Stay.
        </p>
      </div>
    );
  }

  if (recs && recs.recommendations.length === 0) {
    return (
      <div className="flex flex-col items-start py-10">
        <span className="label text-[color:var(--mist)]">
          § NO DISPATCH TODAY
        </span>
        <p className="font-display text-4xl md:text-5xl leading-[0.95] mt-3 max-w-[20ch]">
          You&rsquo;re{" "}
          <span className="font-display-soft">caught up.</span>
        </p>
        <p className="font-mono text-sm text-[color:var(--mist)] mt-3">
          Come back tomorrow for a fresh issue.
        </p>
        <div className="mt-6">
          <RefreshButton
            retryIn={retryIn}
            lockedForToday={recs?.locked_for_today ?? false}
            onRefresh={fetchRecs}
          />
        </div>
      </div>
    );
  }

  const tracks = recs?.recommendations ?? [];
  const total = tracks.length;

  return (
    <div className="w-full">
      {/* header strip */}
      <div className="flex flex-wrap items-end justify-between gap-4 pb-3 border-b-2 border-[color:var(--ink)]">
        <div>
          <span className="label">§ 04 — DISPATCH FOR TODAY</span>
          <h2 className="font-display text-3xl md:text-4xl leading-[0.95] mt-2 max-w-[22ch]">
            Ten songs, {" "}
            <span className="font-display-soft">
              in the key of
            </span>{" "}
            &ldquo;{recs?.query_title}&rdquo;
          </h2>
          <p className="font-mono text-[0.82rem] text-[color:var(--mist)] mt-2">
            seeded by {" "}
            <span className="text-[color:var(--ink)]">
              {recs?.query_title}
            </span>{" "}
            by {" "}
            <span className="text-[color:var(--ink)]">
              {recs?.query_artist}
            </span>
          </p>
        </div>
        <div className="flex items-center gap-4">
          <div className="label num text-[color:var(--mist)]">
            <span className="num text-[color:var(--ink)]">
              {(index + 1).toString().padStart(2, "0")}
            </span>{" "}
            / {total.toString().padStart(2, "0")}
          </div>
          <div className="flex border border-[color:var(--ink)]">
            <button
              type="button"
              onClick={() => setIndex((i) => Math.max(0, i - 1))}
              disabled={index === 0}
              className="size-10 flex items-center justify-center disabled:opacity-30 hover:bg-[color:var(--ink)] hover:text-[color:var(--paper)] transition"
              aria-label="Previous"
            >
              <ArrowLeft size={16} />
            </button>
            <button
              type="button"
              onClick={() => setIndex((i) => Math.min(total - 1, i + 1))}
              disabled={index >= total - 1}
              className="size-10 flex items-center justify-center border-l border-[color:var(--ink)] disabled:opacity-30 hover:bg-[color:var(--ink)] hover:text-[color:var(--paper)] transition"
              aria-label="Next"
            >
              <ArrowRight size={16} />
            </button>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-12 gap-6 md:gap-8 pt-6">
        {/* ─── Featured spread ─── */}
        <div className="col-span-12 lg:col-span-5">
          <div className="mx-auto w-full max-w-[360px]">
          <Carousel index={index} onIndexChange={setIndex}>
            <CarouselContent>
              {tracks.map((song, i) => (
                <CarouselItem key={song.id} className="px-1">
                  <a
                    href={song.album_url ?? undefined}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="block sleeve sleeve-hover"
                  >
                    <div className="aspect-square relative overflow-hidden bg-[color:var(--ink)]">
                      {song.image_url ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img
                          src={song.image_url}
                          alt={`${song.title} by ${song.artist_name}`}
                          className="h-full w-full object-cover"
                        />
                      ) : (
                        <div className="flex h-full w-full items-center justify-center text-[color:var(--paper)]">
                          <Disc3 size={56} />
                        </div>
                      )}
                      {/* catalog corner */}
                      <div className="absolute top-2 left-2 label num bg-[color:var(--paper)] border border-[color:var(--ink)] px-2 py-1">
                        N° {(i + 1).toString().padStart(2, "0")}
                      </div>
                      <div className="absolute top-2 right-2 label bg-[color:var(--acid)] border border-[color:var(--ink)] px-2 py-1">
                        PYO / 2026
                      </div>
                    </div>
                    {/* sleeve label plate */}
                    <div className="flex items-baseline justify-between gap-3 border-t border-[color:var(--ink)] px-3 py-2 bg-[color:var(--paper)]">
                      <div className="min-w-0">
                        <p className="font-display text-lg leading-tight truncate">
                          {song.title}
                        </p>
                        <p className="font-mono text-[0.7rem] text-[color:var(--mist)] truncate mt-0.5">
                          {song.artist_name} · {song.album_title}
                        </p>
                      </div>
                      <span className="label shrink-0">SIDE&nbsp;A</span>
                    </div>
                  </a>
                </CarouselItem>
              ))}
            </CarouselContent>
          </Carousel>
          </div>
        </div>

        {/* ─── Side contents list ─── */}
        <div className="col-span-12 lg:col-span-7">
          <div className="flex items-end justify-between pb-3 border-b-2 border-[color:var(--ink)]">
            <span className="label">§ FULL CONTENTS</span>
            <span className="label num text-[color:var(--mist)]">
              TRACKS / {total.toString().padStart(2, "0")}
            </span>
          </div>
          <ul className="max-h-[480px] overflow-y-auto no-scrollbar">
            {tracks.map((s, i) => (
              <li
                key={s.id}
                className={
                  "border-b border-dashed border-[color:var(--line)] transition-colors " +
                  (i === index ? "bg-[color:var(--acid)]/35" : "")
                }
              >
                <button
                  type="button"
                  onClick={() => setIndex(i)}
                  className="w-full flex items-baseline gap-3 py-3 text-left group"
                >
                  <span className="num label text-[color:var(--mist)] w-8 shrink-0">
                    {(i + 1).toString().padStart(2, "0")}
                  </span>
                  <span className="font-display text-[1.2rem] leading-tight truncate">
                    {s.title}
                  </span>
                  <span className="dotted-leader" />
                  <span className="font-mono text-[0.74rem] text-[color:var(--mist)] shrink-0 max-w-[40%] truncate">
                    {s.artist_name}
                  </span>
                </button>
              </li>
            ))}
          </ul>

          <div className="mt-8 flex items-center justify-between">
            <p className="label text-[color:var(--mist)]">
              ↳ the next dispatch arrives tomorrow
            </p>
            <RefreshButton
              retryIn={retryIn}
              lockedForToday={recs?.locked_for_today ?? false}
              onRefresh={fetchRecs}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
