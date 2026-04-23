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
        <span className="label text-[color:var(--mist)]">§ SIGNAL LOST</span>
        <p className="font-display text-4xl md:text-5xl leading-[1] mt-3 max-w-[22ch]">
          {error}.
        </p>
        <button
          onClick={() => router.push("/")}
          className="mt-6 inline-flex items-center gap-2 border border-[color:var(--ink)] px-5 py-3 font-display text-lg hover:bg-[color:var(--ink)] hover:text-[color:var(--paper)] transition-colors"
        >
          ↩ Back to the masthead
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
      <Disc3 size={52} className="reel" />
      <span className="label mt-6 text-[color:var(--mist)]">§ TUNING IN</span>
      <p className="font-display text-5xl md:text-6xl leading-[0.95] mt-3">
        Catching the{" "}
        <span className="italic font-display-soft">signal…</span>
      </p>
      <p className="font-mono text-sm text-[color:var(--mist)] mt-4">
        Handshake with Spotify in progress. Don&rsquo;t touch that dial.
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
