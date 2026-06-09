"use client";

import { useEffect, useMemo, useState } from "react";
import { usePathname } from "next/navigation";
import Link from "next/link";
import { MenuIcon, X } from "lucide-react";
import Logo from "@/components/shadcn-studio/logo";

type AuthState = "unknown" | "authed" | "anon";

const BYPASS_AUTH = process.env.NEXT_PUBLIC_DEV_BYPASS_AUTH === "true";

const BASE_ITEMS = [
  { title: "Home", href: "/", num: "01" },
  { title: "Your Taste", href: "/profile", num: "02" },
  { title: "Today", href: "/dashboard", num: "03" },
];

// Time remaining until the next 12 AM Pacific (when the daily drop refreshes).
function timeUntilPacificMidnight(): string {
  const now = new Date();
  const laNow = new Date(
    now.toLocaleString("en-US", { timeZone: "America/Los_Angeles" })
  );
  const nextMidnight = new Date(laNow);
  nextMidnight.setHours(24, 0, 0, 0);
  const diff = Math.max(0, nextMidnight.getTime() - laNow.getTime());
  const totalSec = Math.floor(diff / 1000);
  const hh = Math.floor(totalSec / 3600);
  const mm = Math.floor((totalSec % 3600) / 60);
  const ss = totalSec % 60;
  const pad = (n: number) => n.toString().padStart(2, "0");
  return `${pad(hh)}:${pad(mm)}:${pad(ss)}`;
}

const AUTHED_ITEM = { title: "Log off", href: "/logout", num: "04" };

const Navbar = () => {
  const [open, setOpen] = useState(false);
  const [time, setTime] = useState("");
  const [auth, setAuth] = useState<AuthState>(BYPASS_AUTH ? "authed" : "unknown");
  const pathname = usePathname();

  useEffect(() => {
    const tick = () => setTime(timeUntilPacificMidnight());
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    if (BYPASS_AUTH) return;
    const controller = new AbortController();
    fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/v1/auth/me`, {
      credentials: "include",
      signal: controller.signal,
    })
      .then((res) => setAuth(res.ok ? "authed" : "anon"))
      .catch((err) => {
        if (err?.name === "AbortError") return;
        setAuth("anon");
      });
    return () => controller.abort();
  }, [pathname]);

  const navItems = useMemo(() => {
    if (auth === "unknown") return BASE_ITEMS;
    if (auth === "authed") return [...BASE_ITEMS, AUTHED_ITEM];
    return [
      ...BASE_ITEMS,
      {
        title: "Login",
        href: `${process.env.NEXT_PUBLIC_API_URL}/api/v1/auth/spotify/login`,
        num: "04",
      },
    ];
  }, [auth]);

  const isActive = (href: string) => href.startsWith("/") && pathname === href;

  return (
    <header className="fixed inset-x-0 top-0 z-[40]">
      <div className="bg-black/80 backdrop-blur-md border-b border-white/15">
        <div className="mx-auto max-w-[1480px] px-5 md:px-10">
          <div className="flex items-center justify-between gap-6 py-4">
            <Link href="/" className="shrink-0">
              <Logo />
            </Link>

            <nav className="hidden md:flex items-center gap-9">
              {navItems.map((item) => (
                <a
                  key={item.href}
                  href={item.href}
                  className="group flex items-baseline gap-2"
                >
                  <span
                    className={
                      "spray-link font-accent text-[1.1rem] transition-colors " +
                      (isActive(item.href)
                        ? "text-[color:var(--pink)]"
                        : "text-white/85 group-hover:text-white")
                    }
                  >
                    {item.title}
                  </span>
                </a>
              ))}
            </nav>

            <div className="hidden md:flex items-center gap-2.5 shrink-0">
              <span className="relative flex h-1.5 w-1.5 items-center">
                <span className="absolute inline-flex h-full w-full rounded-full bg-[color:var(--pink)] blink-dot" />
              </span>
              <span className="label text-[0.6rem] text-white/55">
                Next drop {time || "00:00:00"}
              </span>
            </div>

            <button
              type="button"
              aria-label="Menu"
              onClick={() => setOpen((v) => !v)}
              className="md:hidden size-10 border border-white/40 flex items-center justify-center text-white"
            >
              {open ? <X size={18} /> : <MenuIcon size={18} />}
            </button>
          </div>
        </div>

        {open && (
          <div className="md:hidden border-t border-white/15 bg-black">
            <ul className="mx-auto max-w-[1480px] px-5">
              {navItems.map((item) => (
                <li
                  key={item.href}
                  className="border-b border-white/10 last:border-none"
                >
                  <a
                    href={item.href}
                    className="flex items-baseline justify-between py-5"
                    onClick={() => setOpen(false)}
                  >
                    <span
                      className={
                        "display text-3xl " +
                        (isActive(item.href)
                          ? "text-[color:var(--pink)]"
                          : "text-white")
                      }
                    >
                      {item.title}
                    </span>
                    <span className="num label text-white/35">{item.num}</span>
                  </a>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </header>
  );
};

export default Navbar;
