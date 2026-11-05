import assert from "node:assert/strict";
import test from "node:test";
import { getHealth } from "./health";
const checks = { database: "ok", redis: "ok", object_storage: "ok" };
test("requests real readiness route and disables caching", async () => {
  const fetcher: typeof fetch = async (url, options) => {
    assert.equal(url, "http://api:8000/api/v1/health/ready");
    assert.equal(options?.cache, "no-store");
    return Response.json({ status: "ready", checks });
  };
  assert.equal((await getHealth("http://api:8000/", fetcher)).status, "ready");
});
test("preserves dependency failures", async () => {
  const result = await getHealth("http://api", async () =>
    Response.json(
      { status: "not_ready", checks: { ...checks, redis: "error" } },
      { status: 503 },
    ),
  );
  assert.equal(result.status, "not_ready");
  assert.equal(result.checks.redis, "error");
});
test("network failure and malformed responses are not reported as ready", async () => {
  for (const fetcher of [
    async () => {
      throw new Error("timeout");
    },
    async () => Response.json({ status: "ready" }),
    async () =>
      Response.json({ status: "ready", checks: { ...checks, redis: "error" } }),
  ]) {
    assert.equal(
      (await getHealth("http://api", fetcher)).status,
      "unreachable",
    );
  }
});
