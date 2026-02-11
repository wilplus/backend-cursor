/**
 * Copy to: src/app/api/homework/session/[sessionId]/post-answers/route.ts
 */
import { NextRequest, NextResponse } from "next/server";
import { getV2AccessToken, getBackendUrl } from "../../../../getAuth";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ sessionId: string }> | { sessionId: string } }
) {
  const token = await getV2AccessToken();
  if (!token) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const { sessionId } = typeof (params as Promise<{ sessionId: string }>).then === "function" ? await (params as Promise<{ sessionId: string }>) : (params as { sessionId: string });
  if (!sessionId) return NextResponse.json({ error: "Missing sessionId" }, { status: 400 });
  const body = await request.json().catch(() => ({}));
  const res = await fetch(`${getBackendUrl()}/v2/homework/session/${sessionId}/post-answers`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  return NextResponse.json(data, { status: res.status });
}
