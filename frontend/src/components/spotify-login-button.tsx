"use client";

import { ArrowUpRight } from "lucide-react";

export function SpotifyLoginButton({ className = "" }: { className?: string }) {
  const handleLogin = () => {
    window.location.href = `${process.env.NEXT_PUBLIC_API_URL}/api/v1/auth/spotify/login`;
  };

  return (
    <button
      onClick={handleLogin}
      className={
        "group relative inline-flex items-center gap-4 bg-[color:var(--ink)] px-7 py-5 text-[color:var(--paper)] transition-transform duration-300 hover:-translate-y-[3px] " +
        className
      }
    >
      <span
        aria-hidden
        className="absolute inset-0 -z-[1] translate-x-[6px] translate-y-[6px] bg-[color:var(--acid)] transition-transform duration-300 group-hover:translate-x-[10px] group-hover:translate-y-[10px]"
      />
      <span className="label num opacity-70">[ ENTER ]</span>
      <span className="font-display text-2xl leading-none tracking-tight">
        Log in with Spotify
      </span>
      <ArrowUpRight
        size={22}
        className="transition-transform duration-300 group-hover:rotate-45"
      />
    </button>
  );
}
