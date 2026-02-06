/**
 * Copy to: src/app/api/homework/session/[sessionId]/recording-metrics-chunk/route.ts
 * Proxies binary PCM body and headers to backend for real-time metrics (Ambient Glow).
 * Includes CORS and OPTIONS so cross-origin requests and preflight succeed (fixes "access control checks" error).
 */
import { NextRequest, NextResponse } from "next/server";
import { getV2AccessToken, getBackendUrl } from "../../../../../getAuth";

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Sample-Rate, X-Seq, X-T-Ms, X-Recording-Slot, X-Debug",
  "Access-Control-Max-Age": "86400",
};

export async function OPTIONS() {
  return new NextResponse(null, { status: 204, headers: CORS_HEADERS });
}

export async function POST(
  request: NextRequest,
  { params }: { params: { sessionId: string } }
) {
  const token = await getV2AccessToken();
  if (!token) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401, headers: CORS_HEADERS });
  }
  const sessionId = params.sessionId;
  const backend = getBackendUrl();
  const body = await request.arrayBuffer();
  const headers: Record<string, string> = {
    Authorization: `Bearer ${token}`,
    "Content-Type": "application/octet-stream",
  };
  const xSampleRate = request.headers.get("X-Sample-Rate");
  const xSeq = request.headers.get("X-Seq");
  const xTMs = request.headers.get("X-T-Ms");
  const xRecordingSlot = request.headers.get("X-Recording-Slot");
  const xDebug = request.headers.get("X-Debug");
  if (xSampleRate != null) headers["X-Sample-Rate"] = xSampleRate;
  if (xSeq != null) headers["X-Seq"] = xSeq;
  if (xTMs != null) headers["X-T-Ms"] = xTMs;
  if (xRecordingSlot != null) headers["X-Recording-Slot"] = xRecordingSlot;
  if (xDebug != null) headers["X-Debug"] = xDebug;

  const res = await fetch(
    `${backend}/v2/homework/session/${sessionId}/recording-metrics-chunk`,
    { method: "POST", headers, body }
  );
  const data = await res.json().catch(() => ({}));
  const response = !res.ok
    ? NextResponse.json(data, { status: res.status })
    : NextResponse.json(data);
  Object.entries(CORS_HEADERS).forEach(([k, v]) => response.headers.set(k, v));
  return response;
}
