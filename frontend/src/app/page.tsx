import { SpotifyLoginButton } from "@/components/spotify-login-button";

export default function Home() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-green-950 font-sans dark:bg-black">
      <main className="flex min-h-screen w-full max-w-3xl flex-col items-center justify-center bg-green-950 dark:bg-black">
        <SpotifyLoginButton />
      </main>
    </div>
  );
}
