"use client";
import { useEffect, useState, useCallback, useRef, useMemo } from "react";
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
    ? "Back tomorrow · 12 AM PST"
    : isRateLimited
    ? `One sec · ${retryIn}s`
    : "Pull a fresh drop";

  return (
    <button
      disabled={disabled}
      onClick={() => !disabled && onRefresh()}
      className={
        "group inline-flex items-center gap-3 border border-white/40 px-5 py-3 display text-lg text-white transition-colors " +
        (disabled
          ? "opacity-40 cursor-not-allowed"
          : "hover:bg-[color:var(--pink)] hover:text-black hover:border-[color:var(--pink)]")
      }
    >
      <RefreshCw
        size={16}
        strokeWidth={2.5}
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

  const date = useMemo(
    () =>
      new Date().toLocaleDateString("en-US", {
        weekday: "long",
        month: "long",
        day: "numeric",
      }),
    []
  );

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  // Holds the latest fetchRecs so startPolling can call it without depending on
  // it directly — that back-reference is what created the declaration cycle.
  const fetchRecsRef = useRef<() => void>(() => {});

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
        fetchRecsRef.current();
      }
    }, 5000);
  }, [stopPolling]);

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
  }, [startPolling]);

  useEffect(() => {
    fetchRecsRef.current = fetchRecs;
  }, [fetchRecs]);

  useEffect(() => {
    // localStorage is client-only, so the cached drop can only be read post-mount.
    const cached = readCachedDispatch();
    if (cached) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- hydrating from a client-only cache on mount is intentional, not a cascading render
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
        <Disc3 size={54} strokeWidth={1.5} className="reel text-[color:var(--pink)]" />
        <span className="label mt-6 text-white/45">Building your drop</span>
        <p className="display text-4xl md:text-5xl mt-4 text-white">
          Listening close
        </p>
        <p className="font-body text-[0.95rem] text-white/55 mt-4 max-w-sm leading-relaxed">
          The first one takes a minute. We&rsquo;re going back through your top
          tracks to find the songs that sit closest to how they sound. Hang
          tight.
        </p>
      </div>
    );
  }

  if (recs && recs.recommendations.length === 0) {
    return (
      <div className="flex flex-col items-start py-10">
        <span className="label text-white/45">Nothing new today</span>
        <p className="display text-4xl md:text-5xl leading-[0.95] mt-3 max-w-[20ch] text-white">
          You&rsquo;re <span className="ink-pink">all caught up.</span>
        </p>
        <p className="font-body text-[0.95rem] text-white/55 mt-3">
          Come back tomorrow for a fresh drop.
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
      {/* header strip — combines the daily framing, the date, and the seed track */}
      <div className="flex flex-wrap items-end justify-between gap-4 pb-4 border-b border-white/15">
        <div>
          <span className="label text-[color:var(--pink)]" suppressHydrationWarning>
            Today{date ? ` · ${date}` : ""}
          </span>
          <h2 className="mt-3 leading-tight">
            <span className="display text-3xl md:text-4xl text-white">
              Ten songs, matched to{" "}
            </span>
            <span className="tag tag-pink text-4xl md:text-5xl">
              your sound.
            </span>
          </h2>
          <p className="font-body text-[0.9rem] text-white/50 mt-3">
            Built around{" "}
            <span className="text-white font-semibold">{recs?.query_title}</span>{" "}
            by{" "}
            <span className="text-white font-semibold">{recs?.query_artist}</span>
          </p>
        </div>
        <div className="flex items-center gap-4">
          <div className="label num text-white/40">
            <span className="num text-[color:var(--pink)]">
              {(index + 1).toString().padStart(2, "0")}
            </span>{" "}
            / {total.toString().padStart(2, "0")}
          </div>
          <div className="flex border border-white/40">
            <button
              type="button"
              onClick={() => setIndex((i) => Math.max(0, i - 1))}
              disabled={index === 0}
              className="size-10 flex items-center justify-center text-white disabled:opacity-30 hover:bg-[color:var(--pink)] hover:text-black transition"
              aria-label="Previous"
            >
              <ArrowLeft size={16} strokeWidth={2.5} />
            </button>
            <button
              type="button"
              onClick={() => setIndex((i) => Math.min(total - 1, i + 1))}
              disabled={index >= total - 1}
              className="size-10 flex items-center justify-center text-white border-l border-white/40 disabled:opacity-30 hover:bg-[color:var(--pink)] hover:text-black transition"
              aria-label="Next"
            >
              <ArrowRight size={16} strokeWidth={2.5} />
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
                    className="block paste lift"
                  >
                    <div className="aspect-square relative overflow-hidden bg-black">
                      {song.image_url ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img
                          src={song.image_url}
                          alt={`${song.title} by ${song.artist_name}`}
                          className="h-full w-full object-cover"
                        />
                      ) : (
                        <div className="flex h-full w-full items-center justify-center text-[color:var(--pink)]">
                          <Disc3 size={56} strokeWidth={1.5} />
                        </div>
                      )}
                      {/* catalog corner */}
                      <div className="absolute top-2 left-2 label num bg-[color:var(--violet)] text-black px-2 py-1">
                        N° {(i + 1).toString().padStart(2, "0")}
                      </div>
                    </div>
                    {/* label plate */}
                    <div className="flex items-baseline justify-between gap-3 border-t border-black/10 px-3 py-3 bg-white">
                      <div className="min-w-0">
                        <p className="display text-lg leading-tight truncate text-black">
                          {song.title}
                        </p>
                        <p className="font-body text-[0.78rem] text-black/55 truncate mt-1">
                          {song.artist_name} · {song.album_title}
                        </p>
                      </div>
                      <span className="label shrink-0 text-black/55">Play ↗</span>
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
          <div className="flex items-end justify-between pb-4 border-b border-white/15">
            <span className="label text-white">The full set</span>
            <span className="label num text-white/40">
              {total.toString().padStart(2, "0")} tracks
            </span>
          </div>
          <ul className="max-h-[480px] overflow-y-auto no-scrollbar">
            {tracks.map((s, i) => (
              <li
                key={s.id}
                className={
                  "border-b border-white/10 transition-colors " +
                  (i === index ? "bg-[color:var(--pink)] text-black" : "")
                }
              >
                <button
                  type="button"
                  onClick={() => setIndex(i)}
                  className="w-full flex items-baseline gap-3 py-3.5 px-2 text-left group"
                >
                  <span
                    className={
                      "num label w-8 shrink-0 " +
                      (i === index ? "text-black/60" : "text-white/40")
                    }
                  >
                    {(i + 1).toString().padStart(2, "0")}
                  </span>
                  <span
                    className={
                      "display text-[1.2rem] leading-tight truncate transition-colors " +
                      (i === index
                        ? "text-black"
                        : "text-white group-hover:text-[color:var(--pink)]")
                    }
                  >
                    {s.title}
                  </span>
                  <span className="dotted-leader" />
                  <span
                    className={
                      "font-body text-[0.78rem] shrink-0 max-w-[40%] truncate " +
                      (i === index ? "text-black/65" : "text-white/45")
                    }
                  >
                    {s.artist_name}
                  </span>
                </button>
              </li>
            ))}
          </ul>

          <div className="mt-8 flex flex-wrap items-center justify-between gap-4">
            <p className="label text-white/40">Next drop lands tomorrow</p>
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
