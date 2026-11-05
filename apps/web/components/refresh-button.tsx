"use client";
import { useRouter } from "next/navigation";
import { useTransition } from "react";
export function RefreshButton() {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  return (
    <button
      className="refresh"
      disabled={pending}
      onClick={() => startTransition(() => router.refresh())}
    >
      {pending ? "检查中…" : "↻  刷新状态"}
    </button>
  );
}
