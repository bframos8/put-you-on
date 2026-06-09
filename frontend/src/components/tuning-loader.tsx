import { Disc3 } from "lucide-react";

/**
 * Shared "we're checking your session" loader. Pure presentational, so it stays
 * a server component — it ships no client JS even when rendered inside a client
 * island (e.g. AuthGate, ProfileContent).
 */
export function TuningLoader({
  kicker = "Tuning in",
  title = "One second",
}: {
  kicker?: string;
  title?: string;
}) {
  return (
    <div className="relative min-h-screen pt-20 flex items-center justify-center">
      <div className="flex flex-col items-center gap-4 text-center">
        <Disc3 size={48} strokeWidth={1.5} className="reel text-[color:var(--pink)]" />
        <span className="label text-white/40">{kicker}</span>
        <p className="display text-4xl md:text-5xl text-[color:var(--pink)]">
          {title}
        </p>
      </div>
    </div>
  );
}
