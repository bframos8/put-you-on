"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Disc3, Play } from "lucide-react";

type TopTrack = {
  id: string | number;
  title: string;
  artist_name: string;
  album_title?: string | null;
  image_url?: string | null;
  album_url?: string | null;
  duration_ms?: number | null;
  popularity?: number | null;
};

type Profile = {
  display_name?: string | null;
  email?: string | null;
  followers?: number | null;
  image_url?: string | null;
  country?: string | null;
};

const TASTE_DESCRIPTORS = [
  "melodic",
  "nocturnal",
  "warm-bodied",
  "off-kilter",
  "romantic",
  "patient",
  "polyrhythmic",
  "hi-fi",
  "nostalgic",
  "late-set",
];

const TAG_TINTS = [
  "bg-[color:var(--lime)] text-black",
  "bg-[color:var(--pink)] text-black",
  "bg-[color:var(--violet)] text-white",
  "bg-white text-black",
];

function formatDuration(ms?: number | null): string {
  if (!ms) return "—:—";
  const total = Math.round(ms / 1000);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export default function ProfilePage() {
  const router = useRouter();
  const [authed, setAuthed] = useState(false);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [tracks, setTracks] = useState<TopTrack[]>([]);
  const [loading, setLoading] = useState(true);
  const [hovered, setHovered] = useState<number | null>(null);

  useEffect(() => {
    const bypass = process.env.NEXT_PUBLIC_DEV_BYPASS_AUTH === "true";
    const base = process.env.NEXT_PUBLIC_API_URL;

    async function load() {
      try {
        if (!bypass) {
          const me = await fetch(`${base}/api/v1/auth/me`, {
            credentials: "include",
          });
          if (!me.ok) {
            router.push("/");
            return;
          }
          const p: Profile = await me.json();
          setProfile(p);
        } else {
          setProfile({ display_name: "Anonymous Listener" });
        }
        setAuthed(true);

        const res = await fetch(`${base}/api/v1/items/top_tracks/`, {
          credentials: "include",
        });
        if (res.ok) {
          const data = await res.json();
          const t: TopTrack[] = (data.tracks ?? data.items ?? data) as TopTrack[];
          if (Array.isArray(t)) setTracks(t);
        }
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [router]);

  const descriptors = useMemo(() => {
    const n = tracks.length || 5;
    const count = Math.min(5, Math.max(3, Math.floor(n / 3)));
    const shuffled = [...TASTE_DESCRIPTORS].sort(() => 0.5 - Math.random());
    return shuffled.slice(0, count);
  }, [tracks.length]);

  if (!authed && !loading) return null;

  const displayName = profile?.display_name || "Listener";
  const firstName = displayName.split(" ")[0];
  const initials = displayName
    .split(" ")
    .map((w) => w[0])
    .filter(Boolean)
    .slice(0, 2)
    .join("")
    .toUpperCase();

  return (
    <div className="relative min-h-screen pt-16 overflow-hidden">
      {/* ─── Marquee ─── */}
      <div className="border-y-2 border-white bg-[color:var(--pink)] text-black overflow-hidden">
        <div className="marquee py-2">
          <div className="marquee-track label text-[0.78rem]">
            {Array.from({ length: 12 }).map((_, i) => (
              <span key={i} className="inline-flex items-center gap-6">
                <span>◖ YOUR TASTE · ON FILE N° {(i + 1).toString().padStart(3, "0")}</span>
                <span aria-hidden>✺</span>
              </span>
            ))}
          </div>
        </div>
      </div>

      {/* ─── Identity card ─── */}
      <section className="mx-auto max-w-[1480px] px-5 md:px-10 pt-10 md:pt-14">
        <div className="grid grid-cols-12 gap-6 md:gap-10 pb-10 border-b-2 border-white">
          {/* Portrait — pasted ID card */}
          <div className="col-span-12 md:col-span-4 lg:col-span-3">
            <div className="paste paste-hover relative aspect-[4/5] overflow-hidden">
              {profile?.image_url ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={profile.image_url}
                  alt={displayName}
                  className="h-full w-full object-cover"
                />
              ) : (
                <div className="flex h-full w-full items-center justify-center bg-[color:var(--violet)] text-white">
                  <span className="tag-flat text-[clamp(5rem,18vw,14rem)] leading-none">
                    {initials || "P"}
                  </span>
                </div>
              )}
              <div className="absolute inset-x-0 bottom-0 bg-[color:var(--lime)] border-t-2 border-black px-3 py-2 flex items-center justify-between label text-black">
                <span>ON FILE</span>
                <span className="flex items-center gap-2">
                  <span className="inline-block h-[7px] w-[7px] rounded-full bg-black blink-dot" />
                  <span>VERIFIED</span>
                </span>
              </div>
            </div>
            <p className="label num mt-3 text-white/45">PORTRAIT · 001</p>
          </div>

          {/* Identity type */}
          <div className="col-span-12 md:col-span-8 lg:col-span-9 flex flex-col justify-between">
            <div>
              <div className="flex flex-wrap items-center gap-x-8 gap-y-2 label num text-white/45">
                <span>FILE N° {String(displayName.length * 41).padStart(5, "0")}</span>
                <span>COUNTRY / {profile?.country ?? "—"}</span>
                <span>EMAIL / {profile?.email ?? "—"}</span>
              </div>
              <h1
                className="mt-5 leading-[0.82] rise"
                style={{ animationDelay: "0.1s" }}
              >
                <span className="block display text-[clamp(2.6rem,9vw,7rem)] text-white">
                  What&rsquo;s good,
                </span>
                <span className="block tag-lime text-[clamp(2.8rem,11vw,8.5rem)]">
                  {firstName.toUpperCase()}.
                </span>
              </h1>
            </div>

            <div className="grid grid-cols-12 gap-6 mt-10">
              <div className="col-span-12 md:col-span-7">
                <p className="font-body text-[1.05rem] leading-relaxed text-white max-w-[60ch]">
                  Your ten most-played, plus what our machines reckon they say
                  about you. Read it as a{" "}
                  <span className="ink-lime font-semibold">listening notebook</span>
                  &nbsp;— not a diagnosis.
                </p>
              </div>
              <div className="col-span-12 md:col-span-5">
                <div className="rule-signal mb-3" />
                <div className="flex flex-col gap-2 label">
                  <div className="flex items-center justify-between">
                    <span className="text-white/45">TRACKS ON FILE</span>
                    <span className="num text-lg text-[color:var(--lime)]">
                      {tracks.length.toString().padStart(2, "0")}
                    </span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-white/45">DAILY STREAK</span>
                    <span className="num text-lg text-white">07 DAYS</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-white/45">LAST SYNC</span>
                    <span className="num text-lg text-white">just now</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ─── Taste tags ─── */}
      <section className="mx-auto max-w-[1480px] px-5 md:px-10 py-10">
        <div className="flex items-end justify-between">
          <span className="label text-[color:var(--lime)]">◖ YOUR TASTE, READ BACK</span>
          <span className="label num text-white/45">FROM YOUR TOP 10</span>
        </div>
        <div className="flex flex-wrap gap-3 mt-5">
          {descriptors.map((d, i) => (
            <span
              key={d}
              className={
                "sticker display text-xl px-4 py-2 rise " + TAG_TINTS[i % TAG_TINTS.length]
              }
              style={{ animationDelay: `${0.2 + i * 0.08}s` }}
            >
              {d}
            </span>
          ))}
        </div>
      </section>

      {/* ─── Top 10 ─── */}
      <section className="mx-auto max-w-[1480px] px-5 md:px-10 pb-20">
        <div className="flex items-end justify-between pb-4 border-b-2 border-white">
          <div>
            <span className="label text-white/50">◖ THE TOP TEN</span>
            <h2 className="display text-4xl md:text-6xl leading-[0.9] mt-3 text-white">
              Straight from{" "}
              <span className="ink-lime">your ear.</span>
            </h2>
          </div>
          <div className="hidden md:flex items-center gap-6 label num text-white/40">
            <span>TRACK</span>
            <span>LENGTH</span>
          </div>
        </div>

        {loading ? (
          <LoadingList />
        ) : tracks.length === 0 ? (
          <EmptyTracks />
        ) : (
          <ol className="mt-4">
            {tracks.slice(0, 10).map((t, i) => (
              <li
                key={t.id}
                onMouseEnter={() => setHovered(i)}
                onMouseLeave={() => setHovered(null)}
                className="relative group border-b border-white/15"
              >
                <a
                  href={t.album_url ?? undefined}
                  target={t.album_url ? "_blank" : undefined}
                  rel="noopener noreferrer"
                  className="relative z-[2] grid grid-cols-12 gap-4 items-center py-5 md:py-6"
                >
                  <span className="col-span-2 md:col-span-1 num font-body text-white/40 text-sm">
                    {(i + 1).toString().padStart(2, "0")}
                  </span>

                  <div className="col-span-10 md:col-span-7 flex items-center gap-4 min-w-0">
                    {t.image_url ? (
                      <div className="shrink-0 size-14 md:size-16 border-2 border-white/80 overflow-hidden">
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img
                          src={t.image_url}
                          alt={t.album_title ?? t.title}
                          className={
                            "h-full w-full object-cover transition-transform duration-500 " +
                            (hovered === i ? "scale-110" : "")
                          }
                        />
                      </div>
                    ) : (
                      <div className="shrink-0 size-14 md:size-16 border-2 border-white/80 flex items-center justify-center bg-[color:var(--violet)] text-white">
                        <Disc3 size={28} strokeWidth={1.5} className={hovered === i ? "reel" : ""} />
                      </div>
                    )}
                    <div className="min-w-0">
                      <p
                        className={
                          "display text-2xl md:text-3xl leading-[1.05] truncate transition-colors " +
                          (hovered === i ? "text-black" : "text-white")
                        }
                      >
                        {t.title}
                      </p>
                      <p
                        className={
                          "font-body text-[0.8rem] truncate mt-1 transition-colors " +
                          (hovered === i ? "text-black/65" : "text-white/50")
                        }
                      >
                        {t.artist_name}
                        {t.album_title ? ` · ${t.album_title}` : ""}
                      </p>
                    </div>
                  </div>

                  <div className="hidden md:flex col-span-4 items-baseline">
                    <span className="dotted-leader" />
                    <span
                      className={
                        "num label transition-colors " +
                        (hovered === i ? "text-black/70" : "text-white/45")
                      }
                    >
                      {formatDuration(t.duration_ms)}
                    </span>
                    <span
                      className={
                        "ml-4 inline-flex size-9 items-center justify-center border-2 transition-colors " +
                        (hovered === i
                          ? "bg-black text-[color:var(--lime)] border-black"
                          : "bg-transparent text-white border-white")
                      }
                    >
                      <Play size={14} className="fill-current" />
                    </span>
                  </div>
                </a>
                {/* lime sweep on hover */}
                <span
                  aria-hidden
                  className={
                    "pointer-events-none absolute left-0 top-0 h-full w-full origin-left bg-[color:var(--lime)] transition-transform duration-500 z-[1] " +
                    (hovered === i ? "scale-x-100" : "scale-x-0")
                  }
                />
              </li>
            ))}
          </ol>
        )}

        <div className="flex flex-wrap items-end justify-between gap-4 pt-6">
          <span className="label text-white/45">↳ END OF FILE</span>
          <a
            href="/dashboard"
            className="group inline-flex items-baseline gap-3"
          >
            <span className="label text-[color:var(--lime)]">NEXT UP</span>
            <span className="spray-link display text-3xl md:text-4xl text-white">
              Today&rsquo;s batch →
            </span>
          </a>
        </div>
      </section>

      {/* ─── Vanity type ─── */}
      <section className="border-t-2 border-white overflow-hidden bg-black">
        <div
          className="tag-flat leading-none text-[clamp(5rem,22vw,18rem)] whitespace-nowrap text-center py-3 text-white/10"
          aria-hidden
        >
          {firstName.toUpperCase()} ON FILE
        </div>
      </section>
    </div>
  );
}

function LoadingList() {
  return (
    <ol className="mt-4">
      {Array.from({ length: 6 }).map((_, i) => (
        <li
          key={i}
          className="grid grid-cols-12 gap-4 items-center py-6 border-b border-white/15"
        >
          <span className="col-span-1 num label text-white/35">
            {(i + 1).toString().padStart(2, "0")}
          </span>
          <div className="col-span-11 md:col-span-7 flex items-center gap-4">
            <div className="size-14 md:size-16 border-2 border-white/30 animate-pulse bg-white/5" />
            <div className="flex flex-col gap-2 w-full">
              <div className="h-5 w-1/2 bg-white/10 animate-pulse" />
              <div className="h-3 w-1/3 bg-white/10 animate-pulse" />
            </div>
          </div>
        </li>
      ))}
    </ol>
  );
}

function EmptyTracks() {
  return (
    <div className="mt-12 flex flex-col items-start gap-5">
      <span className="label text-white/50">NO TRACKS ON FILE · YET</span>
      <p className="display text-4xl md:text-5xl leading-[1] max-w-[24ch] text-white">
        Play a few songs on Spotify.{" "}
        <span className="ink-lime">Your file fills itself.</span>
      </p>
      <a
        href="/dashboard"
        className="mt-2 inline-flex items-center gap-3 border-2 border-white px-5 py-3 display text-xl text-white hover:bg-[color:var(--lime)] hover:text-black hover:border-[color:var(--lime)] transition-colors"
      >
        Head to today&rsquo;s batch →
      </a>
    </div>
  );
}
