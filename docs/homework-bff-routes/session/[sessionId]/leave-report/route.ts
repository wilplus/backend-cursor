/**
 * Copy to: src/app/api/homework/session/[sessionId]/leave-report/route.ts
 * Call when the user leaves the report (e.g. clicks "Send the homework to the coach!"). Returns the step-0 payload (same shape as GET session/status with no active session). Use the response to update app state and show the start screen.
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
