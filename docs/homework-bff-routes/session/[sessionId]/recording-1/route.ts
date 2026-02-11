/**
 * Copy to: src/app/api/homework/session/[sessionId]/recording-1/route.ts
 * Accepts multipart (audio file) or JSON (storage_path + duration_seconds for direct-to-storage).
 * Passes through 4xx/5xx body (e.g. 409 INVALID_SESSION_STATE).
 * Backend does Whisper + scoring; can be slow. Raise maxDuration to avoid Vercel 504.
 */
export const runtime = "nodejs";
export const maxDuration = 60;
export const dynamic = "force-dynamic";

import { NextRequest, NextResponse } from "next/server";
import { getV2AccessToken, getBackendUrl } from "../../../../getAuth";
import { proxyResponse } from "../../../../proxyResponse";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ sessionId: string }> | { sessionId: string } }
) {
  const token = await getV2AccessToken();
  if (!token) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const { sessionId } = typeof (params as Promise<{ sessionId: string }>).then === "function" ? await (params as Promise<{ sessionId: string }>) : (params as { sessionId: string });
  if (!sessionId) return NextResponse.json({ error: "Missing sessionId" }, { status: 400 });
  const backend = getBackendUrl();
  const contentType = request.headers.get("content-type") || "";
  let backendRes: Response;
  if (contentType.includes("multipart/form-data")) {
    const formData = await request.formData();
    backendRes = await fetch(`${backend}/v2/homework/session/${sessionId}/recording-1`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body: formData,
    });
  } else {
    const body = await request.json().catch(() => ({}));
    backendRes = await fetch(`${backend}/v2/homework/session/${sessionId}/recording-1`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  }
  return proxyResponse(backendRes);
}
