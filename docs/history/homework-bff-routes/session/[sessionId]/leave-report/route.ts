/**
 * Copy to: src/app/api/homework/session/[sessionId]/leave-report/route.ts
 * Proxies POST /v2/homework/session/:id/leave-report. Frontend may call this from the
 * report CTA, then sign out and redirect to /logged-out (treat 404 like success if the
 * backend omits the route). Passes through 4xx/5xx body otherwise.
 */
import { NextResponse } from "next/server";
import { getV2AccessToken, getBackendUrl } from "../../../../getAuth";
import { proxyResponse } from "../../../../proxyResponse";

export async function POST(
  _request: Request,
  { params }: { params: { sessionId: string } }
) {
  const token = await getV2AccessToken();
  if (!token) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const { sessionId } = params;
  if (!sessionId) return NextResponse.json({ error: "Missing sessionId" }, { status: 400 });
  const upstreamRes = await fetch(`${getBackendUrl()}/v2/homework/session/${sessionId}/leave-report`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  return proxyResponse(upstreamRes);
}
