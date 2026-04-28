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
    <div className="relative min-h-screen pt-20">
      {/* ─── Section label / masthead ─── */}
      <div className="border-y border-[color:var(--line)] bg-[color:var(--paper)]">
        <div className="marquee py-2">
          <div className="marquee-track label">
            {Array.from({ length: 12 }).map((_, i) => (
              <span key={i} className="inline-flex items-center gap-8">
                <span>§ PROFILE · CONTENTS N° {(i + 1).toString().padStart(3, "0")}</span>
                <span aria-hidden className="opacity-40">✺</span>
              </span>
            ))}
          </div>
        </div>
      </div>

      {/* ─── Identity plate ─── */}
      <section className="mx-auto max-w-[1480px] px-6 md:px-10 pt-10 md:pt-14">
        <div className="grid grid-cols-12 gap-6 md:gap-10 pb-10 border-b-2 border-[color:var(--ink)]">
          {/* Portrait */}
          <div className="col-span-12 md:col-span-4 lg:col-span-3">
            <div className="sleeve aspect-[4/5] relative overflow-hidden">
              {profile?.image_url ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={profile.image_url}
                  alt={displayName}
                  className="h-full w-full object-cover"
                />
              ) : (
                <div className="flex h-full w-full items-center justify-center bg-[color:var(--ink)] text-[color:var(--paper)]">
                  <span className="font-display text-[clamp(5rem,18vw,14rem)] leading-none">
                    {initials || "P"}
                  </span>
                </div>
              )}
              <div className="absolute inset-x-0 bottom-0 bg-[color:var(--paper)] border-t border-[color:var(--ink)] px-3 py-2 flex items-center justify-between label">
                <span>REC.</span>
                <span className="flex items-center gap-2">
                  <span className="inline-block h-[7px] w-[7px] rounded-full bg-[color:var(--acid)] blink-dot border border-[color:var(--ink)]" />
                  <span>ON FILE</span>
                </span>
              </div>
            </div>
            <p className="label num mt-3 text-[color:var(--mist)]">
              PORTRAIT PLATE · 001
            </p>
          </div>

          {/* Identity type */}
          <div className="col-span-12 md:col-span-8 lg:col-span-9 flex flex-col justify-between">
            <div>
              <div className="flex flex-wrap items-center gap-x-8 gap-y-2 label num text-[color:var(--mist)]">
                <span>FILE N° {String(displayName.length * 41).padStart(5, "0")}</span>
                <span>COUNTRY / {profile?.country ?? "—"}</span>
                <span>EMAIL / {profile?.email ?? "—"}</span>
              </div>
              <h1
                className="font-display text-[clamp(3.2rem,12vw,10rem)] leading-[0.84] mt-5 rise"
                style={{ animationDelay: "0.1s" }}
              >
                <span className="block">
                  <span className="font-display-soft">Hello,</span>
                </span>
                <span className="block">{firstName}.</span>
              </h1>
            </div>

            <div className="grid grid-cols-12 gap-6 mt-10">
              <div className="col-span-12 md:col-span-7">
                <p className="font-display text-[1.35rem] leading-[1.25] max-w-[60ch] -tracking-[0.005em]">
                  A dispatch of your ten most-played songs, with a side of what
                  our machines think they say about you. Read it as a{" "}
                  <span className="font-display-soft">
                    listening notebook
                  </span>
                  &nbsp;— not a diagnosis.
                </p>
              </div>
              <div className="col-span-12 md:col-span-5">
                <div className="rule rule-thick mb-3" />
                <div className="flex flex-col gap-2 label">
                  <div className="flex items-center justify-between">
                    <span className="text-[color:var(--mist)]">TRACKS ON FILE</span>
                    <span className="num text-lg">
                      {tracks.length.toString().padStart(2, "0")}
                    </span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-[color:var(--mist)]">DISPATCH STREAK</span>
                    <span className="num text-lg">07 DAYS</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-[color:var(--mist)]">LAST SYNC</span>
                    <span className="num text-lg">just now</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ─── Taste profile tags ─── */}
      <section className="mx-auto max-w-[1480px] px-6 md:px-10 py-10">
        <div className="flex items-end justify-between">
          <span className="label">§ TASTE — EXTRACTED</span>
          <span className="label num text-[color:var(--mist)]">
            INFERRED FROM TOP 10
          </span>
        </div>
        <div className="flex flex-wrap gap-2 mt-5">
          {descriptors.map((d, i) => (
            <span
              key={d}
              className="border border-[color:var(--ink)] px-4 py-2 font-display text-lg rise"
              style={{ animationDelay: `${0.2 + i * 0.08}s` }}
            >
              <span className="font-display-soft">{d}</span>
            </span>
          ))}
        </div>
      </section>

      {/* ─── Contents: Top 10 ─── */}
      <section className="mx-auto max-w-[1480px] px-6 md:px-10 pb-20">
        <div className="flex items-end justify-between pb-4 border-b-2 border-[color:var(--ink)]">
          <div>
            <span className="label">§ 03 — CONTENTS</span>
            <h2 className="font-display text-5xl md:text-7xl leading-[0.9] mt-3">
              The top ten,{" "}
              <span className="font-display-soft">
                straight from your ear.
              </span>
            </h2>
          </div>
          <div className="hidden md:flex items-center gap-6 label num text-[color:var(--mist)]">
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
                className="relative group border-b border-[color:var(--line)]"
              >
                <a
                  href={t.album_url ?? undefined}
                  target={t.album_url ? "_blank" : undefined}
                  rel="noopener noreferrer"
                  className="grid grid-cols-12 gap-4 items-center py-5 md:py-6"
                >
                  {/* index */}
                  <span className="col-span-2 md:col-span-1 num font-mono text-[color:var(--mist)] text-sm">
                    {(i + 1).toString().padStart(2, "0")}
                  </span>

                  {/* cover + title block */}
                  <div className="col-span-10 md:col-span-7 flex items-center gap-4 min-w-0">
                    {t.image_url ? (
                      <div className="shrink-0 size-14 md:size-16 border border-[color:var(--line)] overflow-hidden">
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
                      <div className="shrink-0 size-14 md:size-16 border border-[color:var(--line)] flex items-center justify-center bg-[color:var(--ink)] text-[color:var(--paper)]">
                        <Disc3
                          size={28}
                          className={hovered === i ? "reel" : ""}
                        />
                      </div>
                    )}
                    <div className="min-w-0">
                      <p className="font-display text-2xl md:text-3xl leading-[1.05] truncate">
                        {t.title}
                      </p>
                      <p className="font-mono text-[0.78rem] text-[color:var(--mist)] truncate mt-1">
                        {t.artist_name}
                        {t.album_title ? ` · ${t.album_title}` : ""}
                      </p>
                    </div>
                  </div>

                  {/* dotted leader & metadata */}
                  <div className="hidden md:flex col-span-4 items-baseline">
                    <span className="dotted-leader" />
                    <span className="num label text-[color:var(--mist)]">
                      {formatDuration(t.duration_ms)}
                    </span>
                    <span
                      className={
                        "ml-4 inline-flex size-9 items-center justify-center border border-[color:var(--ink)] transition-colors " +
                        (hovered === i
                          ? "bg-[color:var(--acid)]"
                          : "bg-transparent")
                      }
                    >
                      <Play size={14} className="fill-current" />
                    </span>
                  </div>
                </a>
                {/* sweep */}
                <span
                  aria-hidden
                  className={
                    "pointer-events-none absolute left-0 top-0 h-full w-full origin-left bg-[color:var(--acid)]/15 transition-transform duration-500 " +
                    (hovered === i ? "scale-x-100" : "scale-x-0")
                  }
                />
              </li>
            ))}
          </ol>
        )}

        <div className="flex items-end justify-between pt-6">
          <span className="label text-[color:var(--mist)]">
            ↳ END OF CONTENTS · TURN THE PAGE
          </span>
          <a
            href="/dashboard"
            className="group inline-flex items-baseline gap-3 hover-rule"
          >
            <span className="label">NEXT UP</span>
            <span className="font-display text-3xl md:text-4xl -tracking-[0.02em]">
              Your recommendations{" "}
              <span className="font-display-soft">→</span>
            </span>
          </a>
        </div>
      </section>

      {/* ─── Vanity type ─── */}
      <section className="border-t-2 border-[color:var(--ink)] overflow-hidden">
        <div
          className="font-display leading-none text-[clamp(6rem,22vw,20rem)] tracking-[-0.06em] whitespace-nowrap text-center py-3"
          aria-hidden
        >
          {firstName.toLowerCase()}{" "}
          <span className="font-display-soft">/ on file</span>
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
          className="grid grid-cols-12 gap-4 items-center py-6 border-b border-[color:var(--line)]"
        >
          <span className="col-span-1 num label text-[color:var(--mist)]">
            {(i + 1).toString().padStart(2, "0")}
          </span>
          <div className="col-span-11 md:col-span-7 flex items-center gap-4">
            <div className="size-14 md:size-16 border border-[color:var(--line)] animate-pulse bg-[color:var(--ink)]/5" />
            <div className="flex flex-col gap-2 w-full">
              <div className="h-5 w-1/2 bg-[color:var(--ink)]/5 animate-pulse" />
              <div className="h-3 w-1/3 bg-[color:var(--ink)]/5 animate-pulse" />
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
      <span className="label">NO TRACKS ON FILE · YET</span>
      <p className="font-display text-4xl md:text-5xl leading-[1] max-w-[24ch]">
        Play a few songs on Spotify.{" "}
        <span className="font-display-soft">
          Your file fills itself.
        </span>
      </p>
      <a
        href="/dashboard"
        className="mt-2 inline-flex items-center gap-3 border border-[color:var(--ink)] px-5 py-3 font-display text-xl hover:bg-[color:var(--ink)] hover:text-[color:var(--paper)] transition-colors"
      >
        Head to your dispatch{" "}
        <span className="font-display-soft">→</span>
      </a>
    </div>
  );
}
