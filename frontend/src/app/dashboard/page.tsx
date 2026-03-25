"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { SongRecCarousel } from "@/components/song-rec-carousel";

export default function Dashboard() {
  const router = useRouter();
  const [user, setUser] = useState<{ display_name: string; email: string } | null>(null);

  useEffect(() => {
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
      .then(setUser)
      .catch(() => {});
  }, [router]);

  if (!user) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-green-950">
        <p className="text-white">Loading...</p>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-green-950 font-sans">
      <main className="flex w-full max-w-3xl flex-col items-center justify-center">
        <h1 className="text-2xl font-bold text-white">
          Welcome, {user.display_name}
        </h1>
        <SongRecCarousel/>
        <p className="mt-2 text-emerald-400">{user.email}</p>
      </main>
    </div>
  );
}
