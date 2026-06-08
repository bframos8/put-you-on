"use client";

import { ArrowUpRight } from "lucide-react";

export function SpotifyLoginButton({
  className = "",
  label = "Put me on",
}: {
  className?: string;
  label?: string;
}) {
  const handleLogin = () => {
    window.location.href = `${process.env.NEXT_PUBLIC_API_URL}/api/v1/auth/spotify/login`;
  };

  return (
    <button
      onClick={handleLogin}
      className={
        "group relative inline-flex items-center gap-3 bg-[color:var(--lime)] px-7 py-4 text-black transition-transform duration-300 hover:-translate-x-[3px] hover:-translate-y-[3px] " +
        className
      }
    >
      {/* hard violet print-offset behind the button */}
      <span
        aria-hidden
        className="absolute inset-0 -z-[1] translate-x-[7px] translate-y-[7px] bg-[color:var(--violet)] transition-transform duration-300 group-hover:translate-x-[11px] group-hover:translate-y-[11px]"
      />
      <span className="label text-black/55">[ Spotify ]</span>
      <span className="display text-2xl leading-none">{label}</span>
      <ArrowUpRight
        size={22}
        strokeWidth={2.5}
        className="transition-transform duration-300 group-hover:rotate-45"
      />
    </button>
  );
}
