/**
 * Copy to: src/app/api/homework/session/[sessionId]/task-block/route.ts
 * Optional: get shaped task block (metric_question_1/2/3) for step 2. Passes through 4xx/5xx body.
 */
import { NextResponse } from "next/server";
import { getV2AccessToken, getBackendUrl } from "../../../../getAuth";
import { proxyResponse } from "../../../../proxyResponse";

export async function GET(
  _request: Request,
  { params }: { params: { sessionId: string } }
) {
  const token = await getV2AccessToken();
  if (!token) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const { sessionId } = params;
  if (!sessionId) return NextResponse.json({ error: "Missing sessionId" }, { status: 400 });
  const upstreamRes = await fetch(`${getBackendUrl()}/v2/homework/session/${sessionId}/task-block`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return proxyResponse(upstreamRes);
}
