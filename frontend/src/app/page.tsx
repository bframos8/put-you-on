import { SpotifyLoginButton } from "@/components/spotify-login-button";

const MARQUEE_ITEMS = [
  "NO ALGORITHM SLOP",
  "10 SONGS A DAY",
  "STRAIGHT OFF YOUR TASTE",
  "NO INFINITE SCROLL",
  "PUT YOU ON",
  "FRESH PRESS DAILY",
  "HEADPHONES ON",
  "EST. 2026",
];

const STEPS = [
  {
    n: "01",
    kicker: "YOU PLAY",
    title: "You listen.",
    body:
      "We grab your heavy-rotation tracks off Spotify — the ones you can't stop replaying. That's the seed.",
    accent: "lime",
  },
  {
    n: "02",
    kicker: "WE DIG",
    title: "We dig.",
    body:
      "Audio embeddings, nearest-neighbor search, a little taste. We pull songs that share the feeling, not just the genre tag.",
    accent: "violet",
  },
  {
    n: "03",
    kicker: "YOU GET ON",
    title: "You get put on.",
    body:
      "Ten songs, dropped daily. No feed. No doom loop. A plug, not a algorithm.",
    accent: "pink",
  },
] as const;

const SAMPLE = [
  { t: "Sideways", a: "Citizen", d: "3:28" },
  { t: "Comme des Garçons", a: "Rina Sawayama", d: "2:58" },
  { t: "Green Aphrodisiac", a: "Corinne Bailey Rae", d: "3:57" },
  { t: "Anthems for a Seventeen Year-Old Girl", a: "Broken Social Scene", d: "4:25" },
  { t: "Ivy", a: "Frank Ocean", d: "4:09" },
  { t: "Morning Dew", a: "Devendra Banhart", d: "2:45" },
];

const accentClass = {
  lime: "ink-lime",
  violet: "ink-violet",
  pink: "ink-pink",
} as const;

const posterClass = {
  lime: "poster-lime",
  violet: "poster-violet",
  pink: "poster-pink",
} as const;

export default function Home() {
  return (
    <div className="relative min-h-screen pt-16 overflow-hidden">
      {/* ─── Top marquee ─── */}
      <div className="border-y-2 border-white bg-[color:var(--lime)] text-black overflow-hidden">
        <div className="marquee py-2">
          <div className="marquee-track label text-[0.78rem]">
            {[...MARQUEE_ITEMS, ...MARQUEE_ITEMS, ...MARQUEE_ITEMS].map((m, i) => (
              <span key={i} className="inline-flex items-center gap-6">
                <span>{m}</span>
                <span aria-hidden>✺</span>
              </span>
            ))}
          </div>
        </div>
      </div>

      {/* ─── Hero ─── */}
      <section className="relative mx-auto max-w-[1480px] px-5 md:px-10 pt-12 md:pt-16 pb-10">
        {/* halftone field behind the tag */}
        <div
          aria-hidden
          className="halftone absolute inset-x-0 top-0 h-[70%] opacity-60 pointer-events-none"
        />

        <div className="relative grid grid-cols-12 gap-6">
          <div className="col-span-12 lg:col-span-8">
            <span
              className="label text-[color:var(--lime)] stamp inline-block"
              style={{ animationDelay: "0.02s" }}
            >
              ◖ A MUSIC PLUG · DROPS DAILY
            </span>

            {/* the graffiti shout */}
            <h1 className="mt-5 leading-[0.85]">
              <span
                className="block tag text-[clamp(3.2rem,13vw,11rem)] stamp"
                style={{ animationDelay: "0.08s" }}
              >
                PUT YOU
              </span>
              <span
                className="block tag-lime text-[clamp(3.2rem,13vw,11rem)] stamp"
                style={{ animationDelay: "0.2s" }}
              >
                ON.
              </span>
            </h1>

            {/* refined accent line under the tag */}
            <p
              className="display text-[clamp(1.4rem,3.6vw,2.6rem)] mt-6 max-w-[18ch] text-white stamp"
              style={{ animationDelay: "0.34s" }}
            >
              Songs you haven&rsquo;t heard{" "}
              <span className="signal-mark-solid">yet.</span>
            </p>
          </div>

          {/* side note */}
          <aside
            className="col-span-12 lg:col-span-4 lg:pt-24 fade"
            style={{ animationDelay: "0.55s" }}
          >
            <div className="flex flex-col gap-4">
              <span className="label text-white/50">— FROM YOUR PLUG</span>
              <p className="font-body text-[1.05rem] leading-relaxed text-white">
                A handful of tracks lifted straight off{" "}
                <span className="ink-lime font-semibold">your own ear</span>.
                Made by nearest-neighbor vectors and nights that ran too long.
              </p>
              <div
                className="rule-signal rule-animate"
                style={{ animationDelay: "0.9s" }}
              />
              <p className="font-body text-[0.9rem] leading-relaxed text-white/55">
                We don&rsquo;t care about your follower count. We care about
                track 04 of the album you&rsquo;ve had on loop.
              </p>
            </div>
          </aside>
        </div>

        {/* CTA row */}
        <div
          className="flex flex-col md:flex-row items-start md:items-center justify-between gap-8 pt-10 mt-8 border-t-2 border-white rise"
          style={{ animationDelay: "0.7s" }}
        >
          <SpotifyLoginButton />
          <div className="flex items-center gap-3 label text-white/55">
            <span
              aria-hidden
              className="inline-block h-[10px] w-[10px] rounded-full bg-[color:var(--lime)] blink-dot"
            />
            <span>FREE · NO CARD · 30 SECONDS</span>
          </div>
        </div>
      </section>

      {/* ─── How it works: three pasted posters ─── */}
      <section className="relative mx-auto max-w-[1480px] px-5 md:px-10 py-16 md:py-24">
        <div className="flex items-end justify-between pb-6 border-b-2 border-white">
          <h2 className="display text-4xl md:text-6xl text-white">
            How we put you <span className="ink-lime">on.</span>
          </h2>
          <span className="label text-white/45 hidden md:inline">
            3 MOVES · NO TRICKS
          </span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-8 md:gap-7 pt-12">
          {STEPS.map((s, i) => (
            <article
              key={s.n}
              className={
                "paste paste-hover relative p-7 pb-9 " + posterClass[s.accent]
              }
              style={{
                transform: `rotate(${i === 1 ? "0.8deg" : i === 2 ? "-1deg" : "-0.4deg"})`,
              }}
            >
              <div className="flex items-baseline justify-between">
                <span className="num display text-6xl text-black/15">{s.n}</span>
                <span className="label text-black/45">{s.kicker}</span>
              </div>
              <h3 className="display text-4xl md:text-[2.6rem] mt-6 text-black">
                {s.title.split(" ").map((w, wi) => (
                  <span key={wi} className={wi === 0 ? accentClass[s.accent] : ""}>
                    {w}{" "}
                  </span>
                ))}
              </h3>
              <p className="font-body text-[0.98rem] leading-relaxed text-black/75 mt-4">
                {s.body}
              </p>
            </article>
          ))}
        </div>
      </section>

      {/* ─── Sample wall ─── */}
      <section className="relative border-y-2 border-white bg-[color:var(--violet)]">
        <div className="mx-auto max-w-[1480px] px-5 md:px-10 py-16 md:py-20">
          <div className="flex flex-wrap items-end justify-between gap-4 pb-5 border-b-2 border-white">
            <div>
              <span className="label text-white/70">A REAL DROP</span>
              <h2 className="display text-4xl md:text-6xl mt-3 text-white">
                Last week&rsquo;s{" "}
                <span className="text-[color:var(--lime)]">set.</span>
              </h2>
            </div>
            <span className="label text-white/60 hidden md:inline">
              YOURS WILL SOUND LIKE YOU
            </span>
          </div>

          <ul className="mt-2">
            {SAMPLE.map((s, i) => (
              <li
                key={i}
                className="flex items-baseline border-b border-white/25 py-3.5 group"
              >
                <span className="num label w-9 text-white/55">
                  {(i + 1).toString().padStart(2, "0")}
                </span>
                <span className="display text-xl md:text-2xl text-white group-hover:text-[color:var(--lime)] transition-colors">
                  {s.t}
                </span>
                <span className="dotted-leader" />
                <span className="font-body text-[0.85rem] text-white/70 hidden md:inline">
                  {s.a}
                </span>
                <span className="num label w-14 text-right text-white/70">
                  {s.d}
                </span>
              </li>
            ))}
          </ul>
        </div>
      </section>

      {/* ─── Final CTA ─── */}
      <section className="relative bg-black overflow-hidden">
        <div className="mx-auto max-w-[1480px] px-5 md:px-10 py-20 md:py-28 grid grid-cols-12 gap-8 items-center">
          <div className="col-span-12 md:col-span-8">
            <span className="label text-[color:var(--lime)]">[ GET ON THE LIST ]</span>
            <h2 className="mt-5 leading-[0.86]">
              <span className="block display text-[clamp(2.6rem,9vw,7rem)] text-white">
                Ten songs.
              </span>
              <span className="block tag text-[clamp(2.6rem,9vw,7rem)]">
                EVERY DAY.
              </span>
              <span className="block display text-[clamp(2.6rem,9vw,7rem)] text-[color:var(--lime)]">
                Yours.
              </span>
            </h2>
          </div>
          <div className="col-span-12 md:col-span-4 flex md:justify-end">
            <SpotifyLoginButton label="Plug me in" />
          </div>
        </div>

        {/* oversize vanity tag at the bottom */}
        <div className="overflow-hidden border-t-2 border-white">
          <div
            className="tag-flat leading-none text-[clamp(5rem,24vw,20rem)] whitespace-nowrap text-center py-4 text-white/10"
            aria-hidden
          >
            P·Y·O / 2026
          </div>
        </div>
      </section>

      {/* ─── Footer ─── */}
      <footer className="border-t-2 border-white">
        <div className="mx-auto max-w-[1480px] px-5 md:px-10 py-8 flex flex-col md:flex-row gap-4 items-start md:items-center justify-between">
          <span className="label text-white/55">
            ✺ MADE WITH EMBEDDINGS · NO TRACKERS
          </span>
          <span className="label text-white/35">© PUT YOU ON — 2026</span>
        </div>
      </footer>
    </div>
  );
}
