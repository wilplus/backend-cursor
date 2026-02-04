/**
 * File: src/app/api/session/[sessionId]/intent/route.ts
 */
import { NextResponse } from "next/server";
import { getV2AccessToken, getBackendUrl } from "../../../getAuth";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ sessionId: string }> }
) {
  const token = await getV2AccessToken();
  if (!token) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  const { sessionId } = await params;
  const body = await request.json().catch(() => ({}));
  const backend = getBackendUrl();
  const res = await fetch(`${backend}/v2/session/${sessionId}/intent`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    return NextResponse.json(data, { status: res.status });
  }
  return NextResponse.json(data);
}
