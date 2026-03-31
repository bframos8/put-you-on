"use client";

import { Suspense } from "react";
import { useEffect, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";

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
      <div className="flex min-h-screen items-center justify-center bg-green-950">
        <div className="text-center text-white">
          <p className="text-red-400">{error}</p>
          <button onClick={() => router.push("/")} className="mt-4 text-emerald-400 underline">
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

export default function Callback() {
  return (
    <Suspense fallback={
      <div className="flex min-h-screen items-center justify-center bg-green-950">
        <p className="text-white">Logging you in...</p>
      </div>
    }>
      <CallbackInner />
    </Suspense>
  );
}
