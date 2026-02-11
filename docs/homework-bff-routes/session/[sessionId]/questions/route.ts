/**
 * Copy to: src/app/api/homework/session/[sessionId]/questions/route.ts
 * Passes through 4xx/5xx body.
 */
import { NextResponse } from "next/server";
import { getV2AccessToken, getBackendUrl } from "../../../../getAuth";
import { proxyResponse } from "../../../../proxyResponse";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ sessionId: string }> | { sessionId: string } }
) {
  const token = await getV2AccessToken();
  if (!token) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const { sessionId } = typeof (params as Promise<{ sessionId: string }>).then === "function" ? await (params as Promise<{ sessionId: string }>) : (params as { sessionId: string });
  if (!sessionId) return NextResponse.json({ error: "Missing sessionId" }, { status: 400 });
  const upstreamRes = await fetch(`${getBackendUrl()}/v2/homework/session/${sessionId}/questions`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return proxyResponse(upstreamRes);
}
