"use client";

import { Button } from "@/components/ui/button";

export function SpotifyLoginButton() {
  const handleLogin = () => {
    window.location.href = `${process.env.NEXT_PUBLIC_API_URL}/api/v1/auth/spotify/login`;
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
