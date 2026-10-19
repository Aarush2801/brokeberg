// POST /api/query is the one endpoint that spends LLM credits, so it does not ride the blanket
// /api/* rewrite in next.config.mjs: this server-side handler forwards it with the shared secret
// (QUERY_SECRET, server env only, never sent to the browser). App routes win over rewrites.
// Locally QUERY_SECRET is unset and the dev API has no secret, so no header is needed.

const API_URL = process.env.API_URL ?? "http://localhost:8000";

// RSCH synthesis can take a while; the Lambda allows 2 minutes.
export const maxDuration = 120;

export async function POST(req: Request): Promise<Response> {
  const headers: Record<string, string> = { "content-type": "application/json" };
  if (process.env.QUERY_SECRET) headers["x-brokeberg-query-key"] = process.env.QUERY_SECRET;
  let upstream: Response;
  try {
    upstream = await fetch(`${API_URL}/api/query`, {
      method: "POST",
      headers,
      body: await req.text(),
      cache: "no-store",
    });
  } catch {
    return Response.json({ detail: "API unreachable — start it with `make api`." }, { status: 502 });
  }
  return new Response(upstream.body, {
    status: upstream.status,
    headers: { "content-type": upstream.headers.get("content-type") ?? "application/json" },
  });
}
