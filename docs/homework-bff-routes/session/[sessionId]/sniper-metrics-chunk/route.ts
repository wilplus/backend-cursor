/**
 * Copy to: src/app/api/homework/session/[sessionId]/sniper-metrics-chunk/route.ts
 * GET: probe that backend Sniper is ready (returns { ready: true }). Frontend can call GET first; if 404, use client-side-only wheel.
 * POST: proxies real-time Sniper PCM chunks. Body: raw PCM16 mono bytes. Headers: X-Sample-Rate, X-Seq, X-T-Ms, X-WPM, X-Debug.
 * Without this file the frontend gets 404 and the Sniper "never starts".
 */
export const runtime = "nodejs";
export const maxDuration = 30;
export const dynamic = "force-dynamic";

import { NextRequest, NextResponse } from "next/server";
import { getV2AccessToken, getBackendUrl } from "../../../../getAuth";
import { proxyResponse } from "../../../../proxyResponse";

export async function GET(
  _request: NextRequest,
  { params }: { params: { sessionId: string } }
) {
  const token = await getV2AccessToken();
  if (!token) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const { sessionId } = params;
  if (!sessionId) return NextResponse.json({ error: "Missing sessionId" }, { status: 400 });
  const backend = getBackendUrl();
  const backendRes = await fetch(`${backend}/v2/homework/session/${sessionId}/sniper-metrics-chunk`, {
    method: "GET",
    headers: { Authorization: `Bearer ${token}` },
  });
  return proxyResponse(backendRes);
}

export async function POST(
  request: NextRequest,
  { params }: { params: { sessionId: string } }
) {
  const token = await getV2AccessToken();
  if (!token) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const { sessionId } = params;
  if (!sessionId) return NextResponse.json({ error: "Missing sessionId" }, { status: 400 });

  const backend = getBackendUrl();
  const body = await request.arrayBuffer();
  const headers: Record<string, string> = {
    Authorization: `Bearer ${token}`,
  };
  const sampleRate = request.headers.get("X-Sample-Rate");
  if (sampleRate) headers["X-Sample-Rate"] = sampleRate;
  const seq = request.headers.get("X-Seq");
  if (seq) headers["X-Seq"] = seq;
  const tMs = request.headers.get("X-T-Ms");
  if (tMs) headers["X-T-Ms"] = tMs;
  const wpm = request.headers.get("X-WPM");
  if (wpm) headers["X-WPM"] = wpm;
  const debug = request.headers.get("X-Debug");
  if (debug) headers["X-Debug"] = debug;

  const backendRes = await fetch(`${backend}/v2/homework/session/${sessionId}/sniper-metrics-chunk`, {
    method: "POST",
    headers,
    body: body.byteLength ? body : undefined,
  });
  return proxyResponse(backendRes);
}
