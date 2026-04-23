import { SpotifyLoginButton } from "@/components/spotify-login-button";
import { ArrowDown } from "lucide-react";

const MARQUEE_ITEMS = [
  "VOL. 07",
  "DISPATCH N° 0412",
  "EST. 2025",
  "SIDE A",
  "LATE NIGHT EDITORIAL",
  "NO ALGORITHMS, JUST TASTE",
  "CURATED IN TRANSIT",
  "HEADPHONES RECOMMENDED",
];

const PROMISES = [
  {
    n: "01",
    title: "You listen.",
    body:
      "We pull your top tracks from Spotify — the ones on heavy rotation, the ones you can't stop playing.",
  },
  {
    n: "02",
    title: "We listen back.",
    body:
      "Audio embeddings, nearest-neighbor search, and a little editorial taste — we pick songs that share the feeling, not just the genre tag.",
  },
  {
    n: "03",
    title: "You get put on.",
    body:
      "Ten recommendations, delivered daily. No feed. No infinite scroll. A dispatch, not a doom loop.",
  },
];

const MASTHEAD_NUMBERS = [
  { k: "ISSUE", v: "N° 0412" },
  { k: "SIDE", v: "A" },
  { k: "TEMPO", v: "118 BPM" },
  { k: "SIGNAL", v: "FM 98.7" },
];

export default function Home() {
  return (
    <div className="relative min-h-screen pt-20">
      {/* ─── Top marquee ─── */}
      <div className="border-y border-[color:var(--line)] bg-[color:var(--paper)] overflow-hidden">
        <div className="marquee py-2">
          <div className="marquee-track label">
            {[...MARQUEE_ITEMS, ...MARQUEE_ITEMS, ...MARQUEE_ITEMS].map((m, i) => (
              <span key={i} className="inline-flex items-center gap-8">
                <span>{m}</span>
                <span aria-hidden className="opacity-40">✺</span>
              </span>
            ))}
          </div>
        </div>
      </div>

      {/* ─── Hero masthead ─── */}
      <section className="relative mx-auto max-w-[1480px] px-6 md:px-10 pt-10 md:pt-14">
        {/* masthead metadata row */}
        <div className="flex flex-wrap items-end justify-between gap-6 pb-6 border-b-2 border-[color:var(--ink)]">
          <div className="label num flex flex-wrap gap-x-8 gap-y-1">
            {MASTHEAD_NUMBERS.map((m) => (
              <span key={m.k}>
                <span className="opacity-55">{m.k} /</span>{" "}
                <span>{m.v}</span>
              </span>
            ))}
          </div>
          <span className="label">A MUSIC DISPATCH · FRI / SAT / SUN</span>
        </div>

        {/* hero typographic moment */}
        <div className="relative grid grid-cols-12 gap-4 md:gap-6 pt-10 md:pt-14 pb-6">
          {/* hero type */}
          <div className="col-span-12 lg:col-span-9">
            <h1 className="font-display text-[clamp(3.6rem,14vw,12.5rem)] leading-[0.82]">
              <span className="block rise" style={{ animationDelay: "0.05s" }}>
                Put <span className="italic font-display-soft">you</span>
              </span>
              <span
                className="block rise pl-[0.06em]"
                style={{ animationDelay: "0.2s" }}
              >
                on the songs
              </span>
              <span
                className="block rise"
                style={{ animationDelay: "0.35s" }}
              >
                <span className="acid-underline">you haven&rsquo;t</span>{" "}
                <span className="italic font-display-soft">heard</span>
              </span>
              <span
                className="block rise"
                style={{ animationDelay: "0.5s" }}
              >
                <span className="italic font-display-soft">yet.</span>
              </span>
            </h1>
          </div>

          {/* side pull-quote */}
          <aside
            className="col-span-12 lg:col-span-3 lg:pt-12 fade"
            style={{ animationDelay: "0.7s" }}
          >
            <div className="flex flex-col gap-5">
              <span className="label">{/* inline arrow */}— FROM THE EDITORS</span>
              <p className="font-display text-[1.3rem] leading-[1.25] -tracking-[0.01em]">
                A handpicked dispatch of music lifted straight from{" "}
                <span className="italic font-display-soft">your own ear</span>.
                Made by nearest-neighbor vectors and nights that went too long.
              </p>
              <div className="rule rule-animate" style={{ animationDelay: "1s" }} />
              <p className="font-mono text-[0.78rem] leading-relaxed text-[color:var(--mist)]">
                We don&rsquo;t care about your follower count. We care about
                track&nbsp;04 of the album you&rsquo;ve been replaying. That&rsquo;s
                the seed.
              </p>
            </div>
          </aside>
        </div>

        {/* CTA row */}
        <div
          className="flex flex-col md:flex-row items-start md:items-center justify-between gap-8 pt-2 pb-14 border-t border-[color:var(--line)] rise"
          style={{ animationDelay: "0.85s" }}
        >
          <div className="flex items-center gap-5">
            <span className="label num text-[color:var(--mist)]">[ 00:00 ]</span>
            <SpotifyLoginButton />
          </div>
          <div className="flex items-center gap-3 label text-[color:var(--mist)]">
            <span
              aria-hidden
              className="inline-block h-[9px] w-[9px] rounded-full bg-[color:var(--acid)] blink-dot border border-[color:var(--ink)]"
            />
            <span>SIGNAL ACQUIRED — AWAITING HANDSHAKE</span>
          </div>
        </div>
      </section>

      {/* ─── How it works ─── */}
      <section className="relative mx-auto max-w-[1480px] px-6 md:px-10 py-16 md:py-24">
        <div className="grid grid-cols-12 gap-6 md:gap-10">
          <div className="col-span-12 lg:col-span-3">
            <div className="lg:sticky lg:top-32">
              <span className="label">§ 01 — METHOD</span>
              <h2 className="font-display text-5xl md:text-6xl leading-[0.9] mt-4">
                How we{" "}
                <span className="italic font-display-soft">hear</span> you.
              </h2>
              <div className="rule mt-6" />
              <p className="font-mono text-[0.78rem] mt-4 text-[color:var(--mist)] leading-relaxed">
                Three moves. No tricks. No sponsored placements. No &ldquo;popular
                right now&rdquo;.
              </p>
            </div>
          </div>

          <ol className="col-span-12 lg:col-span-9 flex flex-col">
            {PROMISES.map((p, i) => (
              <li
                key={p.n}
                className="grid grid-cols-12 gap-4 md:gap-8 py-8 md:py-12 border-t border-[color:var(--line)] last:border-b group"
              >
                <div className="col-span-2 md:col-span-1 font-mono text-[color:var(--mist)]">
                  <span className="num text-lg">{p.n}</span>
                </div>
                <h3 className="col-span-10 md:col-span-5 font-display text-3xl md:text-5xl leading-[0.92]">
                  {p.title.split(" ").map((w, wi) => (
                    <span
                      key={wi}
                      className={
                        (i === 1 && wi === 0) || (i === 2 && wi === 2)
                          ? "italic font-display-soft"
                          : ""
                      }
                    >
                      {w}{" "}
                    </span>
                  ))}
                </h3>
                <p className="col-span-12 md:col-span-6 font-mono text-[0.85rem] leading-[1.65] text-[color:var(--ink)]/80 md:mt-3">
                  {p.body}
                </p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* ─── Sample tracklist aesthetic teaser ─── */}
      <section className="relative mx-auto max-w-[1480px] px-6 md:px-10 pb-20">
        <div className="flex items-end justify-between pb-4 border-b-2 border-[color:var(--ink)]">
          <div>
            <span className="label">§ 02 — SAMPLE DISPATCH</span>
            <h2 className="font-display text-4xl md:text-6xl leading-[0.9] mt-3">
              A page from{" "}
              <span className="italic font-display-soft">last week&rsquo;s</span>{" "}
              issue.
            </h2>
          </div>
          <span className="label num hidden md:inline text-[color:var(--mist)]">
            PP. 04 — 06
          </span>
        </div>

        <ul className="mt-6">
          {[
            { t: "Sideways", a: "Citizen", d: "3:28" },
            { t: "Comme des Garçons (Like the Boys)", a: "Rina Sawayama", d: "2:58" },
            { t: "Green Aphrodisiac", a: "Corinne Bailey Rae", d: "3:57" },
            { t: "Anthems for a Seventeen Year-Old Girl", a: "Broken Social Scene", d: "4:25" },
            { t: "Ivy", a: "Frank Ocean", d: "4:09" },
            { t: "Morning Dew", a: "Devendra Banhart", d: "2:45" },
          ].map((s, i) => (
            <li
              key={i}
              className="flex items-baseline border-b border-dashed border-[color:var(--line)] py-3 group"
            >
              <span className="num label w-10 text-[color:var(--mist)]">
                {(i + 1).toString().padStart(2, "0")}
              </span>
              <span className="font-display text-xl md:text-2xl leading-tight">
                {s.t}
              </span>
              <span className="dotted-leader" />
              <span className="font-mono text-[0.8rem] text-[color:var(--mist)] hidden md:inline">
                {s.a}
              </span>
              <span className="num label w-14 text-right">{s.d}</span>
            </li>
          ))}
        </ul>

        <p className="label mt-6 text-[color:var(--mist)]">
          ↳ your issue arrives tuned to your ear, not this one.
        </p>
      </section>

      {/* ─── Final CTA ─── */}
      <section className="relative border-y-2 border-[color:var(--ink)] bg-[color:var(--ink)] text-[color:var(--paper)] overflow-hidden">
        <div className="mx-auto max-w-[1480px] px-6 md:px-10 py-20 md:py-28 grid grid-cols-12 gap-6 items-center">
          <div className="col-span-12 md:col-span-8">
            <span className="label text-[color:var(--acid)]">[ JOIN THE DISPATCH ]</span>
            <h2 className="font-display text-[clamp(2.8rem,8vw,7rem)] leading-[0.88] mt-4">
              Ten songs.{" "}
              <span className="italic font-display-soft">Every day.</span>{" "}
              <span className="acid-underline text-[color:var(--ink)]">
                Yours.
              </span>
            </h2>
          </div>
          <div className="col-span-12 md:col-span-4 flex md:justify-end">
            <SpotifyLoginButton className="bg-[color:var(--paper)] text-[color:var(--ink)]" />
          </div>
        </div>

        {/* oversize vanity type at bottom */}
        <div className="overflow-hidden border-t border-[color:var(--paper)]/20">
          <div
            className="font-display leading-none text-[clamp(7rem,26vw,22rem)] tracking-[-0.06em] whitespace-nowrap text-center py-3"
            aria-hidden
          >
            P · Y · O <span className="italic font-display-soft">/ 2026</span>
          </div>
        </div>
      </section>

      {/* ─── Colophon ─── */}
      <footer className="mx-auto max-w-[1480px] px-6 md:px-10 py-10 grid grid-cols-12 gap-6">
        <div className="col-span-12 md:col-span-6 label flex items-center gap-3">
          <ArrowDown size={14} />
          <span>Scroll set · Printed on the web · No trackers</span>
        </div>
        <div className="col-span-12 md:col-span-6 label text-right text-[color:var(--mist)]">
          © PUT YOU ON — EDITORIAL, LTD.
        </div>
      </footer>
    </div>
  );
}
