"use client";

import { Button } from "@/components/ui/button";

export function SpotifyLoginButton() {
  const handleLogin = () => {
    const clientId = process.env.NEXT_PUBLIC_SPOTIFY_CLIENT_ID;
    const redirectUri = encodeURIComponent("https://127.0.0.1:3000/callback");
    const scopes = encodeURIComponent("user-read-email user-top-read");
    window.location.href = `https://accounts.spotify.com/authorize?client_id=${clientId}&response_type=code&redirect_uri=${redirectUri}&scope=${scopes}`;
  };

  return (
    <Button
      className="bg-emerald-500"
      variant="outline"
      size="lg"
      onClick={handleLogin}
    >
      Log in with Spotify
    </Button>
  );
}
