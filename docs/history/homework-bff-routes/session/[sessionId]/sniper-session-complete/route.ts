/**
 * Copy to: src/app/api/homework/session/[sessionId]/sniper-session-complete/route.ts
 * Proxies session means (wpm, pause_ms, etc.) to the backend. Backend writes session_sniper_metrics and updates user_sniper_profile.
 */
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

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

  const backend = getBackendUrl();
  const body = await request.json().catch(() => ({}));
  const backendRes = await fetch(`${backend}/v2/homework/session/${sessionId}/sniper-session-complete`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  return proxyResponse(backendRes);
}
