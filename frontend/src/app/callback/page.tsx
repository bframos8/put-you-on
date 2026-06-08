"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { Disc3 } from "lucide-react";

function CallbackInner() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const errorParam = searchParams.get("error");
    if (errorParam) {
      setError(`Login failed: ${errorParam}`);
      return;
    }
    router.push("/dashboard");
  }, [searchParams, router]);

  if (error) {
    return (
      <Shell>
        <span className="label text-[color:var(--pink)]">◖ SIGNAL LOST</span>
        <p className="display text-4xl md:text-5xl leading-[1] mt-3 max-w-[22ch] text-white">
          {error}.
        </p>
        <button
          onClick={() => router.push("/")}
          className="mt-6 inline-flex items-center gap-2 border-2 border-white px-5 py-3 display text-lg text-white hover:bg-[color:var(--lime)] hover:text-black hover:border-[color:var(--lime)] transition-colors"
        >
          ↩ Back home
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
      <Disc3 size={52} strokeWidth={1.5} className="reel text-[color:var(--lime)]" />
      <span className="label mt-6 text-white/50">◖ PLUGGING IN</span>
      <p className="tag text-5xl md:text-6xl mt-4">HOLD UP…</p>
      <p className="font-body text-[0.95rem] text-white/60 mt-4">
        Shaking hands with Spotify. Don&rsquo;t touch that dial.
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
