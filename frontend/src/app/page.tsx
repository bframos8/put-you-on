import { ArrowUpRight } from "lucide-react";
import { SpotifyLoginButton } from "@/components/spotify-login-button";

const STEPS = [
  {
    n: "01",
    kicker: "Listen",
    title: "You play.",
    body:
      "Log in with Spotify and we look at the tracks you keep coming back to. That is the starting point, nothing else.",
    color: "pink",
  },
  {
    n: "02",
    kicker: "Match",
    title: "We match the sound.",
    body:
      "We line your music up against everything else and find the songs that actually sound close to it. Not the same genre tag. The same feel.",
    color: "blue",
  },
  {
    n: "03",
    kicker: "Drop",
    title: "You get put on.",
    body:
      "Ten songs, once a day. A short list you can finish, picked for how they sound next to what you already love.",
    color: "yellow",
  },
] as const;

const SAMPLE = [
  { t: "Sideways", a: "Citizen", d: "3:28" },
  { t: "Green Aphrodisiac", a: "Corinne Bailey Rae", d: "3:57" },
  { t: "Ivy", a: "Frank Ocean", d: "4:09" },
  { t: "Anthems for a Seventeen Year-Old Girl", a: "Broken Social Scene", d: "4:25" },
  { t: "Morning Dew", a: "Devendra Banhart", d: "2:45" },
];

const inkClass: Record<string, string> = {
  pink: "ink-pink",
  blue: "ink-blue",
  violet: "ink-violet",
  yellow: "ink-yellow",
};

export default function Home() {
  return (
    <div className="relative min-h-screen overflow-hidden">
      {/* ─── Hero — fits one screen ─── */}
      <section className="relative mx-auto max-w-[1320px] px-5 md:px-10 min-h-[calc(100svh-4.5rem)] flex flex-col justify-center pt-20 pb-12">
        <div className="relative">
          <span
            className="label text-[color:var(--pink)] inline-block fade"
            style={{ animationDelay: "0.05s" }}
          >
            A music plug · one drop a day
          </span>

          <h1
            className="mt-5 rise leading-tight"
            style={{ animationDelay: "0.14s" }}
          >
            <span className="display text-[clamp(1.8rem,5vw,3.8rem)] text-white align-baseline">
              Songs that{" "}
            </span>
            <span className="tag tag-pink text-[clamp(2.1rem,6vw,4.6rem)] align-baseline">
              sound like you.
            </span>
          </h1>

          <p
            className="font-body text-[1.05rem] md:text-[1.15rem] leading-relaxed text-white/70 mt-6 max-w-[44ch] rise"
            style={{ animationDelay: "0.3s" }}
          >
            Log in with Spotify and get ten songs a day, chosen for how close
            they sound to the music you already play on repeat.
          </p>

          <div
            className="flex flex-col sm:flex-row items-start sm:items-center gap-5 mt-9 rise"
            style={{ animationDelay: "0.4s" }}
          >
            <SpotifyLoginButton />
            <div className="flex items-center gap-3 label text-white/45">
              <span
                aria-hidden
                className="inline-block h-1.5 w-1.5 rounded-full bg-[color:var(--pink)] blink-dot"
              />
              <span>Free · no card</span>
            </div>
          </div>
        </div>

        {/* scroll cue in accent */}
        <span className="absolute bottom-6 left-5 md:left-10 label text-white/30">
          Scroll ↓ how it works
        </span>
      </section>

      {/* ─── How it works ─── */}
      <section className="relative mx-auto max-w-[1320px] px-5 md:px-10 py-20 md:py-28 border-t border-white/15">
        <div className="flex items-baseline justify-between gap-6">
          <h2 className="display text-3xl md:text-5xl text-white">How it works</h2>
          <span className="label text-[color:var(--blue)] hidden md:inline">
            Three steps
          </span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-12 md:gap-10 pt-16">
          {STEPS.map((s) => (
            <article key={s.n} className="flex flex-col">
              <div className="flex items-baseline justify-between">
                <span className={"num display text-2xl " + inkClass[s.color]}>
                  {s.n}
                </span>
                <span className={"tag text-[1.6rem] tag-" + s.color}>
                  {s.kicker}
                </span>
              </div>
              <div
                className="mt-4 pt-6 border-t"
                style={{ borderColor: `var(--${s.color})` }}
              />
              <h3 className="display text-3xl md:text-[2.2rem] text-white">
                {s.title}
              </h3>
              <p className="font-body text-[1rem] leading-relaxed text-white/65 mt-4 max-w-[34ch]">
                {s.body}
              </p>
            </article>
          ))}
        </div>
      </section>

      {/* ─── Sample drop ─── */}
      <section className="relative bg-[color:var(--blue)] text-black">
        <div className="mx-auto max-w-[1320px] px-5 md:px-10 py-20 md:py-28">
          <div className="flex flex-wrap items-baseline justify-between gap-4 pb-5 border-b-2 border-black/80">
            <div>
              <span className="tag text-3xl text-black">A real drop</span>
              <h2 className="display text-3xl md:text-5xl text-black mt-2">
                What a drop looks like
              </h2>
            </div>
            <span className="font-body text-[0.95rem] text-black/60 max-w-[22ch]">
              Yours will sound like you, not this.
            </span>
          </div>

          <ul className="mt-2">
            {SAMPLE.map((s, i) => (
              <li
                key={i}
                className="flex items-baseline border-b border-black/20 py-4 group"
              >
                <span className="num label w-10 text-black/55">
                  {(i + 1).toString().padStart(2, "0")}
                </span>
                <span className="display text-xl md:text-2xl text-black">
                  {s.t}
                </span>
                <span className="dotted-leader !border-black/30" />
                <span className="font-body text-[0.9rem] text-black/65 hidden md:inline">
                  {s.a}
                </span>
                <span className="num label w-16 text-right text-black/60">
                  {s.d}
                </span>
              </li>
            ))}
          </ul>
        </div>
      </section>

      {/* ─── Final CTA — the pink signal moment ─── */}
      <section className="relative bg-[color:var(--pink)] text-black">
        <div className="mx-auto max-w-[1320px] px-5 md:px-10 py-24 md:py-32">
          <span className="tag text-4xl md:text-5xl text-black">Get put on</span>
          <h2 className="mt-5 max-w-[14ch] display text-[clamp(2.6rem,8vw,6rem)] text-black leading-[0.92]">
            Ten songs a day, picked by how they sound.
          </h2>
          <div className="mt-12">
            <a
              href={`${process.env.NEXT_PUBLIC_API_URL ?? ""}/api/v1/auth/spotify/login`}
              className="group inline-flex items-center gap-3 bg-black px-7 py-4 text-white transition-transform duration-300 hover:-translate-y-[3px]"
            >
              <span className="display text-2xl leading-none">Plug me in</span>
              <ArrowUpRight
                size={22}
                strokeWidth={2.5}
                className="transition-transform duration-300 group-hover:rotate-45"
              />
            </a>
          </div>
        </div>
      </section>

      {/* ─── Footer ─── */}
      <footer className="border-t border-white/15">
        <div className="mx-auto max-w-[1320px] px-5 md:px-10 py-10 flex flex-col md:flex-row gap-4 items-start md:items-center justify-between">
          <span className="tag text-2xl">
            put you <span className="ink-pink">on.</span>
          </span>
          <span className="label text-white/30">© Put You On · 2026</span>
        </div>
      </footer>
    </div>
  );
}
