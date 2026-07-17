import { LogOut } from "lucide-react";
import { AuthGate } from "@/components/auth-gate";
import { SongRecCarousel } from "@/components/song-rec-carousel";

export default function Dashboard() {
  return (
    <div className="relative min-h-screen pt-16 overflow-hidden">
      <AuthGate>
        {/* ─── The drop is the first thing you see ─── */}
        <section
          className="mx-auto max-w-[1320px] px-5 md:px-10 pt-12 md:pt-16 pb-24 rise"
          style={{ animationDelay: "0.1s" }}
        >
          <SongRecCarousel />
        </section>

        {/* ─── Footer / logout row ─── */}
        <section className="border-t-2 border-[color:var(--blue)]">
          <div className="mx-auto max-w-[1320px] px-5 md:px-10 py-14 grid grid-cols-12 gap-6 items-center">
            <div className="col-span-12 md:col-span-7">
              <span className="label text-[color:var(--blue)]">The plug</span>
              <p className="display text-2xl md:text-3xl leading-[1.15] max-w-[36ch] text-white mt-3">
                Chosen for how close they sound to what you already love.{" "}
                <span className="ink-pink">Nothing about charts.</span>
              </p>
            </div>
            <div className="col-span-12 md:col-span-5 flex md:justify-end items-center gap-6">
              <a href="/profile" className="label text-[color:var(--violet)] spray-link">
                Your top ten
              </a>
              <a
                href="/logout"
                className="inline-flex items-center gap-2 border border-white/40 px-4 py-2 label text-white hover:bg-white hover:text-black transition-colors"
              >
                <LogOut size={14} strokeWidth={2.5} />
                <span>Log out</span>
              </a>
            </div>
          </div>
        </section>
      </AuthGate>
    </div>
  );
}
