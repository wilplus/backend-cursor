/**
 * Copy to: src/app/api/homework/session/[sessionId]/warm-up-task/route.ts
 */
import { NextRequest, NextResponse } from "next/server";
import { getV2AccessToken, getBackendUrl } from "../../../../../getAuth";

export async function GET(
  _request: NextRequest,
  { params }: { params: { sessionId: string } }
) {
  const token = await getV2AccessToken();
  if (!token) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  const sessionId = params.sessionId;
  const backend = getBackendUrl();
  const res = await fetch(`${backend}/v2/homework/session/${sessionId}/warm-up-task`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    return NextResponse.json(data, { status: res.status });
  }
  return NextResponse.json(data);
}
