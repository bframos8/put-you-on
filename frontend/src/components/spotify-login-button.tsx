import { ArrowUpRight } from "lucide-react";

/**
 * Login entry point. It only ever navigates to the backend's Spotify login URL,
 * so it's a plain anchor — no client JS needed. Rendering it as a server
 * component keeps the home page (its only caller) free of a client bundle.
 */
export function SpotifyLoginButton({
  className = "",
  label = "Put me on",
}: {
  className?: string;
  label?: string;
}) {
  return (
    <a
      href={`${process.env.NEXT_PUBLIC_API_URL}/api/v1/auth/spotify/login`}
      className={
        "group inline-flex items-center gap-3 bg-[color:var(--pink)] px-7 py-4 text-black transition-shadow duration-300 hover:shadow-[0_0_0_2px_var(--white)] " +
        className
      }
    >
      <span className="display text-2xl leading-none">{label}</span>
      <ArrowUpRight
        size={22}
        strokeWidth={2.5}
        className="transition-transform duration-300 group-hover:rotate-45"
      />
    </a>
  );
}
