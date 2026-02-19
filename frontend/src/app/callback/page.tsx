"use client";

import { useEffect, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";

export default function Callback() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const code = searchParams.get("code");
    const errorParam = searchParams.get("error");

    if (errorParam) {
      setError(`Spotify authorization failed: ${errorParam}`);
      return;
    }

    if (!code) {
      setError("No authorization code received");
      return;
    }

    const exchangeCode = async () => {
      try {
        const response = await fetch("/api/auth/spotify", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            code,
            redirect_uri: "https://127.0.0.1:3000/callback",
          }),
        });

        const data = await response.json();

        if (!response.ok) {
          setError(data.error || "Failed to authenticate");
          return;
        }

        // Store tokens - in production, use httpOnly cookies instead
        localStorage.setItem("spotify_access_token", data.access_token);
        localStorage.setItem("spotify_refresh_token", data.refresh_token);

        // Redirect to home or dashboard
        router.push("/dashboard");
      } catch (err) {
        setError("Failed to complete authentication");
      }
    };

    exchangeCode();
  }, [searchParams, router]);

  if (error) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-green-950">
        <div className="text-center text-white">
          <p className="text-red-400">{error}</p>
          <button
            onClick={() => router.push("/")}
            className="mt-4 text-emerald-400 underline"
          >
            Go back
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-green-950">
      <p className="text-white">Logging you in...</p>
    </div>
  );
}
