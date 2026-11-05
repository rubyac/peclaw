export type Health = {
  status: "ready" | "not_ready" | "unreachable";
  checks: Record<string, "ok" | "error">;
};
export async function getHealth(
  baseUrl: string,
  fetcher: typeof fetch = fetch,
): Promise<Health> {
  try {
    const response = await fetcher(
      `${baseUrl.replace(/\/$/, "")}/api/v1/health/ready`,
      { cache: "no-store", signal: AbortSignal.timeout(10000) },
    );
    if (response.status !== 200 && response.status !== 503)
      throw new Error("Unexpected response");
    const data: unknown = await response.json();
    if (
      !data ||
      typeof data !== "object" ||
      !("status" in data) ||
      !("checks" in data)
    )
      throw new Error("Invalid health");
    const { status, checks } = data;
    if (
      (status !== "ready" && status !== "not_ready") ||
      !checks ||
      typeof checks !== "object"
    )
      throw new Error("Invalid health");
    const entries = Object.entries(checks);
    if (
      !["database", "redis", "object_storage"].every((k) =>
        entries.some(([key]) => key === k),
      ) ||
      entries.some(([, v]) => v !== "ok" && v !== "error")
    )
      throw new Error("Invalid checks");
    if (
      (status === "ready") !==
      (response.ok && entries.every(([, v]) => v === "ok"))
    )
      throw new Error("Inconsistent status");
    return { status, checks: checks as Health["checks"] };
  } catch {
    return { status: "unreachable", checks: {} };
  }
}
