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

export function SongRecCarousel() {
  const [songs, setSongs] = useState<Song[]>([]);
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
    setSongs(await res.json());
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

  if (retryIn !== null) {
    const ready = retryIn === 0;
    return (
      <div className="flex flex-col items-center gap-3 py-8">
        <p className="text-sm text-emerald-400">
          {ready ? "Ready to try again." : `Too many requests — try again in ${retryIn}s`}
        </p>
        <button
          disabled={!ready}
          onClick={() => {
            setRetryIn(null);
            fetchRecs();
          }}
          className={`rounded px-4 py-2 text-sm transition-colors ${
            ready
              ? "bg-emerald-500 text-white hover:bg-emerald-400"
              : "cursor-not-allowed bg-emerald-900 text-emerald-600"
          }`}
        >
          {ready ? "Try again" : `Retry in ${retryIn}s`}
        </button>
      </div>
    );
  }

  return (
    <div className="relative w-full max-w-xs">
      <Carousel>
        <CarouselContent>
          {songs.map((song) => (
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
  );
}
