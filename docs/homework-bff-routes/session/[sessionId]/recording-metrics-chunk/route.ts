/**
 * Copy to: src/app/api/homework/session/[sessionId]/recording-metrics-chunk/route.ts
 * Proxies binary PCM body and headers to backend for real-time metrics (Ambient Glow).
 */
import { NextRequest, NextResponse } from "next/server";
import { getV2AccessToken, getBackendUrl } from "../../../../../getAuth";

export async function POST(
  request: NextRequest,
  { params }: { params: { sessionId: string } }
) {
  const token = await getV2AccessToken();
  if (!token) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
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
  if (xSampleRate != null) headers["X-Sample-Rate"] = xSampleRate;
  if (xSeq != null) headers["X-Seq"] = xSeq;
  if (xTMs != null) headers["X-T-Ms"] = xTMs;
  if (xRecordingSlot != null) headers["X-Recording-Slot"] = xRecordingSlot;

  const res = await fetch(
    `${backend}/v2/homework/session/${sessionId}/recording-metrics-chunk`,
    { method: "POST", headers, body }
  );
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    return NextResponse.json(data, { status: res.status });
  }
  return NextResponse.json(data);
}
