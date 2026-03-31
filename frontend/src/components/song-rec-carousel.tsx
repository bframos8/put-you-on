"use client";
import { useEffect, useState, useCallback } from "react";
import {
  Carousel,
  CarouselContent,
  CarouselNavigation,
  CarouselIndicator,
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
  query_title: string;
  query_artist: string;
  recommendations: Song[];
};

function RefreshButton({
  retryIn,
  onRefresh,
}: {
  retryIn: number | null;
  onRefresh: () => void;
}) {
  const isRateLimited = retryIn !== null && retryIn > 0;
  const ready = retryIn === 0;

  return (
    <button
      disabled={isRateLimited}
      onClick={() => !isRateLimited && onRefresh()}
      className={`mt-6 rounded px-5 py-2 text-sm font-medium transition-colors ${
        isRateLimited
          ? "cursor-not-allowed bg-black text-zinc-600"
          : "bg-emerald-500 text-white hover:bg-emerald-400"
      }`}
    >
      {isRateLimited
        ? `Refresh in ${retryIn}s`
        : ready
        ? "Try again"
        : "Refresh"}
    </button>
  );
}

export function SongRecCarousel() {
  const [recs, setRecs] = useState<RecsResponse | null>(null);
  const [retryIn, setRetryIn] = useState<number | null>(null);

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
    setRecs(await res.json());
  }, []);

  useEffect(() => {
    fetchRecs();
  }, [fetchRecs]);

  // countdown timer
  useEffect(() => {
    if (!retryIn) return;
    const id = setInterval(() => {
      setRetryIn((prev) => (prev && prev > 1 ? prev - 1 : 0));
    }, 1000);
    return () => clearInterval(id);
  }, [retryIn]);

  if (recs && recs.recommendations.length === 0) {
    return (
      <div className="flex flex-col items-center">
        <p className="text-sm text-emerald-400 py-8">
          No new recommendations for now. Come back tomorrow.
        </p>
        <RefreshButton retryIn={retryIn} onRefresh={fetchRecs} />
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center w-full max-w-xs">
      <p className="mb-1 text-lg font-bold text-white">10 Recommendations</p>
      <p className="mb-4 text-sm text-emerald-400">
        based off of {recs?.query_title} by {recs?.query_artist}
      </p>
      <div className="relative w-full">
        <Carousel>
          <CarouselContent>
            {(recs?.recommendations ?? []).map((song) => (
              <CarouselItem key={song.id} className="p-4">
                <a href={song.album_url ?? undefined} target="_blank" rel="noopener noreferrer">
                  <div className="flex aspect-square items-center justify-center">
                    <img
                      src={song.image_url ?? undefined}
                      alt={`${song.title} by ${song.artist_name}`}
                      className="h-full w-full object-cover"
                    />
                  </div>
                  <div className="mt-2 text-center text-white">
                    <p className="font-semibold">{song.title}</p>
                    <p className="text-sm text-emerald-400">{song.artist_name}</p>
                  </div>
                </a>
              </CarouselItem>
            ))}
          </CarouselContent>
          <CarouselNavigation alwaysShow />
          <CarouselIndicator />
        </Carousel>
      </div>
      <RefreshButton retryIn={retryIn} onRefresh={fetchRecs} />
    </div>
  );
}
