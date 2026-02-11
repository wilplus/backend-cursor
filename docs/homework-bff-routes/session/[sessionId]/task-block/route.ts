/**
 * Copy to: src/app/api/homework/session/[sessionId]/task-block/route.ts
 * Optional: get shaped task block (metric_question_1/2/3) for step 2.
 */
import { NextResponse } from "next/server";
import { getV2AccessToken, getBackendUrl } from "../../../../getAuth";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ sessionId: string }> | { sessionId: string } }
) {
  const token = await getV2AccessToken();
  if (!token) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const { sessionId } = typeof (params as Promise<{ sessionId: string }>).then === "function" ? await (params as Promise<{ sessionId: string }>) : (params as { sessionId: string });
  if (!sessionId) return NextResponse.json({ error: "Missing sessionId" }, { status: 400 });
  const res = await fetch(`${getBackendUrl()}/v2/homework/session/${sessionId}/task-block`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const data = await res.json().catch(() => ({}));
  return NextResponse.json(data, { status: res.status });
}
