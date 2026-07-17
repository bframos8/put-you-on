"use client";

import { useEffect, useState } from "react";
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

function formatDuration(ms?: number | null): string {
  if (!ms) return "—:—";
  const total = Math.round(ms / 1000);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

function formatSyncTime(iso?: string | null): string {
  if (!iso) return "Never";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "Never";
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

/**
 * The data-bound core of the profile page. This is the only part that has to run
 * on the client: it reads the session body (`/auth/me`) for the identity header
 * and fetches the user's top tracks. The page wrapper and the static footer
 * (`footer` prop) are server-rendered and passed through untouched.
 */
export function ProfileContent({ footer }: { footer: React.ReactNode }) {
  const router = useRouter();
  const [authed, setAuthed] = useState(false);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [tracks, setTracks] = useState<TopTrack[]>([]);
  const [lastSync, setLastSync] = useState<string | null>(null);
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
          const t: TopTrack[] = (data.tracks ?? []) as TopTrack[];
          if (Array.isArray(t)) setTracks(t);
          setLastSync(data.last_synced_at ?? null);
        }
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [router]);

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
    <>
      {/* ─── Identity ─── */}
      <section className="mx-auto max-w-[1320px] px-5 md:px-10 pt-20 md:pt-28">
        <div className="grid grid-cols-12 gap-8 md:gap-12 pb-12 border-b border-white/15">
          {/* Portrait */}
          <div className="col-span-12 md:col-span-4 lg:col-span-3">
            <div className="paste lift relative aspect-[4/5] overflow-hidden">
              {profile?.image_url ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={profile.image_url}
                  alt={displayName}
                  className="h-full w-full object-cover"
                />
              ) : (
                <div className="flex h-full w-full items-center justify-center bg-[color:var(--blue)] text-white">
                  <span className="tag text-[clamp(5rem,18vw,14rem)] leading-none">
                    {initials || "P"}
                  </span>
                </div>
              )}
            </div>
          </div>

          {/* Identity type */}
          <div className="col-span-12 md:col-span-8 lg:col-span-9 flex flex-col justify-between">
            <div>
              <div className="flex flex-wrap items-center gap-x-8 gap-y-2 label num text-white/40">
                <span>Country / {profile?.country ?? "—"}</span>
                <span>Email / {profile?.email ?? "—"}</span>
              </div>
              <h1
                className="mt-6 leading-[0.88] rise"
                style={{ animationDelay: "0.1s" }}
              >
                <span className="block display text-[clamp(2.4rem,8vw,6rem)] text-white">
                  What&rsquo;s good,
                </span>
                <span className="block tag tag-pink text-[clamp(2.6rem,10vw,7.5rem)]">
                  {firstName.toLowerCase()}.
                </span>
              </h1>
            </div>

            <div className="grid grid-cols-12 gap-6 mt-12">
              <div className="col-span-12 md:col-span-7">
                <p className="font-body text-[1.05rem] leading-relaxed text-white/70 max-w-[52ch]">
                  Your ten most-played tracks. This is the sound we measure
                  everything else against when we put you on to something new.
                </p>
              </div>
              <div className="col-span-12 md:col-span-5">
                <div className="mb-4 border-t-2 border-[color:var(--blue)]" />
                <div className="flex flex-col gap-3 label">
                  <div className="flex items-center justify-between">
                    <span className="text-white/40">Tracks on file</span>
                    <span className="num text-lg text-[color:var(--yellow)]">
                      {tracks.length.toString().padStart(2, "0")}
                    </span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-white/40">Last sync</span>
                    <span className="num text-lg text-[color:var(--violet)]">
                      {formatSyncTime(lastSync)}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ─── Top 10 ─── */}
      <section className="mx-auto max-w-[1320px] px-5 md:px-10 pt-14 pb-24">
        <div className="flex items-end justify-between pb-5 border-b border-white/15">
          <div>
            <span className="label text-white/45">Your top ten</span>
            <h2 className="mt-3 leading-[0.95]">
              <span className="block display text-2xl md:text-4xl text-white">
                The sound you keep
              </span>
              <span className="block tag tag-pink text-4xl md:text-6xl mt-1">
                coming back to.
              </span>
            </h2>
          </div>
          <div className="hidden md:flex items-center gap-6 label num text-white/35">
            <span>Track</span>
            <span>Length</span>
          </div>
        </div>

        {loading ? (
          <LoadingList />
        ) : tracks.length === 0 ? (
          <EmptyTracks />
        ) : (
          <ol className="mt-2">
            {tracks.slice(0, 10).map((t, i) => (
              <li
                key={t.id}
                onMouseEnter={() => setHovered(i)}
                onMouseLeave={() => setHovered(null)}
                className="relative group border-b border-white/12"
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
                      <div className="shrink-0 size-14 md:size-16 border border-white/30 overflow-hidden">
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
                      <div className="shrink-0 size-14 md:size-16 border border-white/30 flex items-center justify-center bg-[color:var(--blue)] text-white">
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
                          "font-body text-[0.82rem] truncate mt-1 transition-colors " +
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
                        "ml-4 inline-flex size-9 items-center justify-center border transition-colors " +
                        (hovered === i
                          ? "bg-black text-[color:var(--pink)] border-black"
                          : "bg-transparent text-white border-white/40")
                      }
                    >
                      <Play size={14} className="fill-current" />
                    </span>
                  </div>
                </a>
                {/* pink sweep on hover */}
                <span
                  aria-hidden
                  className={
                    "pointer-events-none absolute left-0 top-0 h-full w-full origin-left bg-[color:var(--pink)] transition-transform duration-500 z-[1] " +
                    (hovered === i ? "scale-x-100" : "scale-x-0")
                  }
                />
              </li>
            ))}
          </ol>
        )}

        {footer}
      </section>
    </>
  );
}

function LoadingList() {
  return (
    <ol className="mt-2">
      {Array.from({ length: 6 }).map((_, i) => (
        <li
          key={i}
          className="grid grid-cols-12 gap-4 items-center py-6 border-b border-white/12"
        >
          <span className="col-span-1 num label text-white/30">
            {(i + 1).toString().padStart(2, "0")}
          </span>
          <div className="col-span-11 md:col-span-7 flex items-center gap-4">
            <div className="size-14 md:size-16 border border-white/20 animate-pulse bg-white/5" />
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
      <span className="label text-white/45">No tracks on file yet</span>
      <p className="display text-3xl md:text-5xl leading-[1] max-w-[24ch] text-white">
        Play a few songs on Spotify and{" "}
        <span className="ink-pink">this fills itself in.</span>
      </p>
      <a
        href="/dashboard"
        className="mt-2 inline-flex items-center gap-3 border border-white/40 px-5 py-3 display text-xl text-white hover:bg-[color:var(--pink)] hover:text-black hover:border-[color:var(--pink)] transition-colors"
      >
        Go to today&rsquo;s drop →
      </a>
    </div>
  );
}
