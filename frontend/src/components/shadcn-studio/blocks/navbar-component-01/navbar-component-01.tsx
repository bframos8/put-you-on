"use client";

import { useEffect, useState } from "react";
import { MenuIcon, X } from "lucide-react";
import Logo from "@/components/shadcn-studio/logo";

const navItems = [
  { title: "Dispatch", href: "/", num: "01" },
  { title: "Profile", href: "/profile", num: "02" },
  { title: "Queue", href: "/dashboard", num: "03" },
  { title: "Logout", href: "/logout", num: "04" },
];

const Navbar = () => {
  const [open, setOpen] = useState(false);
  const [time, setTime] = useState("");

  useEffect(() => {
    const tick = () => {
      const d = new Date();
      const hh = d.getHours().toString().padStart(2, "0");
      const mm = d.getMinutes().toString().padStart(2, "0");
      const ss = d.getSeconds().toString().padStart(2, "0");
      setTime(`${hh}:${mm}:${ss}`);
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <header className="fixed inset-x-0 top-0 z-[40]">
      <div className="bg-[color:var(--paper)]/75 backdrop-blur-md border-b border-[color:var(--line)]">
        <div className="mx-auto max-w-[1480px] px-6 md:px-10">
          <div className="flex items-center justify-between gap-6 py-4">
            <a href="/" className="shrink-0 hover-rule">
              <Logo />
            </a>

            <nav className="hidden md:flex items-center gap-8">
              {navItems.map((item) => (
                <a
                  key={item.href}
                  href={item.href}
                  className="group flex items-baseline gap-2 hover-rule"
                >
                  <span className="num label opacity-50 group-hover:opacity-100 transition">
                    {item.num}
                  </span>
                  <span className="font-display text-[1.05rem] tracking-tight">
                    {item.title}
                  </span>
                </a>
              ))}
            </nav>

            <div className="hidden md:flex items-center gap-3 shrink-0">
              <span className="relative flex h-2 w-2 items-center">
                <span className="absolute inline-flex h-full w-full rounded-full bg-[color:var(--acid)] blink-dot" />
              </span>
              <span className="label num">ON AIR · {time || "00:00:00"}</span>
            </div>

            <button
              type="button"
              aria-label="Menu"
              onClick={() => setOpen((v) => !v)}
              className="md:hidden size-10 border border-[color:var(--line)] flex items-center justify-center"
            >
              {open ? <X size={18} /> : <MenuIcon size={18} />}
            </button>
          </div>
        </div>

        {open && (
          <div className="md:hidden border-t border-[color:var(--line)]">
            <ul className="mx-auto max-w-[1480px] px-6">
              {navItems.map((item) => (
                <li
                  key={item.href}
                  className="border-b border-[color:var(--line)] last:border-none"
                >
                  <a
                    href={item.href}
                    className="flex items-baseline justify-between py-4"
                    onClick={() => setOpen(false)}
                  >
                    <span className="font-display text-2xl">
                      {item.title}
                    </span>
                    <span className="num label">{item.num}</span>
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
