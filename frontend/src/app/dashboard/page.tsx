"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { SongRecCarousel } from "@/components/song-rec-carousel";

export default function Dashboard() {
  const router = useRouter();
  const [authed, setAuthed] = useState(false);

  useEffect(() => {
    if (process.env.NEXT_PUBLIC_DEV_BYPASS_AUTH === "true") {
      setAuthed(true);
      return;
    }
    fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/v1/auth/me`, {
      credentials: "include",
    })
      .then((res) => {
        if (!res.ok) {
          router.push("/");
          throw new Error("Not authenticated");
        }
        return res.json();
      })
      .then(() => setAuthed(true))
      .catch(() => {});
  }, [router]);

  if (!authed) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-green-950">
        <p className="text-white">Loading...</p>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-green-950 font-sans">
      <main className="flex w-full max-w-3xl flex-col items-center justify-center">
        <SongRecCarousel />
        <button
          onClick={() => { window.location.href = `${process.env.NEXT_PUBLIC_API_URL}/api/v1/auth/logout`; }}
          className="mt-6 text-sm text-emerald-400 underline"
        >
          Logout
        </button>
      </main>
    </div>
  );
}
