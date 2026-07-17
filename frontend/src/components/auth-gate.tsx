"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { TuningLoader } from "@/components/tuning-loader";

/**
 * Client island that guards authed-only pages. Checks the session against the
 * backend, redirects home if it's missing, and renders `children` once we know
 * the user is in. Children can be server-rendered markup (it's passed straight
 * through), so wrapping static chrome in here keeps that chrome off the client
 * bundle.
 */
const BYPASS_AUTH = process.env.NEXT_PUBLIC_DEV_BYPASS_AUTH === "true";

export function AuthGate({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [authed, setAuthed] = useState(BYPASS_AUTH);

  useEffect(() => {
    if (BYPASS_AUTH) return;
    const controller = new AbortController();
    fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/v1/auth/me`, {
      credentials: "include",
      signal: controller.signal,
    })
      .then((res) => {
        if (!res.ok) {
          router.push("/");
          return;
        }
        setAuthed(true);
      })
      .catch((err) => {
        if (err?.name === "AbortError") return;
        router.push("/");
      });
    return () => controller.abort();
  }, [router]);

  if (!authed) return <TuningLoader />;

  return <>{children}</>;
}
