/**
 * Copy to: src/app/api/homework/session/[sessionId]/recording-upload-url/route.ts
 * Passes through 4xx/5xx body so 409 shows backend payload (code, error, status).
 */
import { NextRequest, NextResponse } from "next/server";
import { getV2AccessToken, getBackendUrl } from "../../../../getAuth";
import { proxyResponse } from "../../../../proxyResponse";

export async function POST(
  _request: NextRequest,
  { params }: { params: { sessionId: string } }
) {
  const token = await getV2AccessToken();
  if (!token) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const { sessionId } = params;
  if (!sessionId) return NextResponse.json({ error: "Missing sessionId" }, { status: 400 });
  const body = await _request.json().catch(() => ({}));
  const upstreamRes = await fetch(`${getBackendUrl()}/v2/homework/session/${sessionId}/recording-upload-url`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return proxyResponse(upstreamRes);
}
