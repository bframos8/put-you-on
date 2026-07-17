"use client";

import { Suspense, useEffect } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { Disc3 } from "lucide-react";

function CallbackInner() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const errorParam = searchParams.get("error");

  useEffect(() => {
    if (!errorParam) router.push("/dashboard");
  }, [errorParam, router]);

  if (errorParam) {
    return (
      <Shell>
        <span className="label text-[color:var(--pink)]">Something went wrong</span>
        <p className="display text-4xl md:text-5xl leading-[1] mt-3 max-w-[22ch] text-white">
          Login failed: {errorParam}.
        </p>
        <button
          onClick={() => router.push("/")}
          className="mt-6 inline-flex items-center gap-2 border border-white/40 px-5 py-3 display text-lg text-white hover:bg-[color:var(--pink)] hover:text-black hover:border-[color:var(--pink)] transition-colors"
        >
          Back home
        </button>
      </Shell>
    );
  }

  return <Tuning />;
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="relative min-h-screen pt-20 flex items-center justify-center px-6">
      <div className="flex flex-col items-start text-left max-w-2xl w-full">
        {children}
      </div>
    </div>
  );
}

function Tuning() {
  return (
    <Shell>
      <Disc3 size={48} strokeWidth={1.5} className="reel text-[color:var(--pink)]" />
      <span className="label mt-6 text-white/45">Connecting</span>
      <p className="display text-5xl md:text-6xl mt-4 text-white">One moment</p>
      <p className="font-body text-[0.95rem] text-white/55 mt-4">
        Signing you in with Spotify.
      </p>
    </Shell>
  );
}

export default function Callback() {
  return (
    <Suspense fallback={<Tuning />}>
      <CallbackInner />
    </Suspense>
  );
}
