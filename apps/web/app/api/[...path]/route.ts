import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";
const allowed =
  /^(auth\/(login|logout|me|password)|organizations\/[a-f0-9-]{36}\/(members(\/[a-f0-9-]{36})?|audit|projects(\/[a-f0-9-]{36}(\/members(\/[a-f0-9-]{36})?)?)?))$/i;

function failure(status: number, message: string) {
  return NextResponse.json(
    { error: { code: `HTTP_${status}`, message } },
    { status, headers: { "Cache-Control": "no-store" } },
  );
}
async function proxy(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  const { path } = await context.params;
  const route = path.join("/");
  const catalogRoute =
    /^(companies(\/search|\/[a-f0-9-]{36}(\/(archive|history|duplicates|merge|evidence(\/[a-f0-9-]{36})?|technologies|products))?)?|catalog\/(sources|audit|taxonomy(\/(industries|technologies))?|imports(\/[a-f0-9-]{36}(\/retry)?)?|merges\/[a-f0-9-]{36}\/undo))$/i;
  const knowledgeRoute =
    /^organizations\/[a-f0-9-]{36}\/(knowledge\/search|projects\/[a-f0-9-]{36}\/(knowledge-members|documents(\/[a-f0-9-]{36}(\/(versions|download|chunks|permissions|retry))?)?))$/i;
  const agentRoute =
    /^(agents\/config|organizations\/[a-f0-9-]{36}\/projects\/[a-f0-9-]{36}\/agent-tasks(\/[a-f0-9-]{36}(\/(retry|cancel))?)?)$/i;
  const reportRoute =
    /^(reports\/templates|organizations\/[a-f0-9-]{36}\/projects\/[a-f0-9-]{36}\/reports(\/[a-f0-9-]{36}(\/(reviewer|submit|review|reviews\/[a-f0-9-]{36}|export|metrics(\/[a-f0-9-]{36}(\/review)?)?))?)?)$/i;
  const evaluationRoute =
    /^(evaluations\/definitions|organizations\/[a-f0-9-]{36}\/projects\/[a-f0-9-]{36}\/evaluations(\/[a-f0-9-]{36}(\/(runs|reviewer))?|\/runs\/[a-f0-9-]{36}(\/(retry|cancel|feedback|export))?)?)$/i;
  if (
    !evaluationRoute.test(route) &&
    !reportRoute.test(route) &&
    !agentRoute.test(route) &&
    !allowed.test(route) &&
    !catalogRoute.test(route) &&
    !knowledgeRoute.test(route)
  )
    return failure(404, "资源不存在");
  const headers = new Headers({ "Content-Type": "application/json" });
  const session = request.cookies.get("peclaw_session")?.value;
  if (session && /^[A-Za-z0-9_-]{32,128}$/.test(session))
    headers.set("Cookie", `peclaw_session=${session}`);
  for (const key of ["origin", "x-csrf-token"]) {
    const value = request.headers.get(key);
    if (value) headers.set(key, value);
  }
  let body: Uint8Array | undefined;
  if (!["GET", "HEAD"].includes(request.method) && request.body) {
    const reader = request.body.getReader();
    const chunks: Uint8Array[] = [];
    let size = 0;
    while (true) {
      const next = await reader.read();
      if (next.done) break;
      size += next.value.byteLength;
      const fileUpload =
        knowledgeRoute.test(route) &&
        /\/documents(?:\/[a-f0-9-]{36}\/versions)?$/i.test(route);
      if (
        size >
        (fileUpload
          ? 15 * 1024 * 1024
          : evaluationRoute.test(route)
            ? 2 * 1024 * 1024
            : reportRoute.test(route)
              ? 1024 * 1024
              : route === "catalog/imports"
                ? 2 * 1024 * 1024
                : 65536)
      ) {
        await reader.cancel();
        return failure(413, "请求内容过大");
      }
      chunks.push(next.value);
    }
    body = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) {
      body.set(chunk, offset);
      offset += chunk.byteLength;
    }
  }
  try {
    const base = process.env.API_INTERNAL_URL || "http://localhost:8000";
    const upstream = await fetch(
      `${base.replace(/\/$/, "")}/api/v1/${route}${request.nextUrl.search}`,
      {
        method: request.method,
        headers,
        body: body as BodyInit | undefined,
        cache: "no-store",
        redirect: "manual",
        signal: AbortSignal.timeout(
          knowledgeRoute.test(route) || reportRoute.test(route) ? 45000 : 15000,
        ),
      },
    );
    const resultHeaders = new Headers({
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
    });
    for (const key of [
      "content-type",
      "x-request-id",
      "content-disposition",
      "x-export-id",
      "x-content-sha256",
    ]) {
      const value = upstream.headers.get(key);
      if (value) resultHeaders.set(key, value);
    }
    for (const cookie of upstream.headers.getSetCookie())
      resultHeaders.append("Set-Cookie", cookie);
    return new NextResponse(upstream.body, {
      status: upstream.status,
      headers: resultHeaders,
    });
  } catch {
    return failure(503, "服务暂时不可用，请稍后重试");
  }
}
export {
  proxy as GET,
  proxy as POST,
  proxy as PATCH,
  proxy as PUT,
  proxy as DELETE,
};
