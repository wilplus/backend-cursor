/**
 * Copy to: src/app/api/homework/session/[sessionId]/self-rating/route.ts
 * Post-recording self-rate 1–10 or skip. Completion (report + coach email) runs when job is done.
 * Body: { "rating": 1-10 } or { "student_rating_1_10": 1-10 }, or { "skipped": true }.
 * Passes through 4xx/5xx body. Response: { status: "ok", session_completed: boolean, student_rating_1_10?: n, skipped?: true }.
 */
import { NextRequest, NextResponse } from "next/server";
import { getV2AccessToken, getBackendUrl } from "../../../../getAuth";
import { proxyResponse } from "../../../../proxyResponse";

export async function POST(
  request: NextRequest,
  { params }: { params: { sessionId: string } }
) {
  const token = await getV2AccessToken();
  if (!token) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const { sessionId } = params;
  if (!sessionId) return NextResponse.json({ error: "Missing sessionId" }, { status: 400 });
  const body = await request.json().catch(() => ({}));
  const backendRes = await fetch(`${getBackendUrl()}/v2/homework/session/${sessionId}/self-rating`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return proxyResponse(backendRes);
}
