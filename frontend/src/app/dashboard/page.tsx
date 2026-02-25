"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { SongRecCarousel } from "@/components/song-rec-carousel";

export default function Dashboard() {
  const router = useRouter();
  const [user, setUser] = useState<{ display_name: string; email: string } | null>(null);

  useEffect(() => {
    const token = localStorage.getItem("spotify_access_token");

    if (!token) {
      router.push("/");
      return;
    }

    fetch("https://api.spotify.com/v1/me", {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((res) => {
        if (!res.ok) {
          localStorage.removeItem("spotify_access_token");
          localStorage.removeItem("spotify_refresh_token");
          router.push("/");
          throw new Error("Token expired");
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
        <iframe className="border-0 w-350px h-470px;" src="https://bandcamp.com/EmbeddedPlayer/album=1797632019/size=large/bgcol=ffffff/linkcol=0687f5/tracklist=false/transparent=true/" seamless><a href="https://togetherforpalestine.bandcamp.com/album/lullaby">Lullaby by TOGETHER FOR PALESTINE, NAI BARGHOUTI, LEIGH-ANNE &amp; NENEH CHERRY</a></iframe>
        <SongRecCarousel/>
        <p className="mt-2 text-emerald-400">{user.email}</p>
      </main>
    </div>
  );
}
