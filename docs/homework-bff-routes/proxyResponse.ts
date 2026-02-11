/**
 * Pass through upstream response body (including 4xx/5xx) so backend error payload (code, error, status) is not lost.
 * Copy to src/app/api/homework/proxyResponse.ts (or next to getAuth). Use in all BFF routes that proxy to the backend.
 *
 * Optional debug (set NEXT_PUBLIC_BFF_DEBUG=1 or uncomment): add response headers so you can verify this helper
 * is deployed and upstream returned a body: X-BFF-ProxyResponse: 1, X-Upstream-Status, X-Upstream-Body-Len.
 */
import { NextResponse } from "next/server";

const BFF_DEBUG = process.env.NEXT_PUBLIC_BFF_DEBUG === "1";

export async function proxyResponse(upstreamRes: Response): Promise<NextResponse> {
  const text = await upstreamRes.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text ? { error: text } : null;
  }
  const headers: Record<string, string> = {};
  if (BFF_DEBUG) {
    headers["X-BFF-ProxyResponse"] = "1";
    headers["X-Upstream-Status"] = String(upstreamRes.status);
    headers["X-Upstream-Body-Len"] = String(text.length);
  }
  return NextResponse.json(data ?? {}, { status: upstreamRes.status, headers });
}
