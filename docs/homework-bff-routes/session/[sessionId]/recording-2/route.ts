/**
 * Copy to: src/app/api/homework/session/[sessionId]/recording-2/route.ts
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
  const formData = await request.formData();
  const backend = getBackendUrl();
  const res = await fetch(`${backend}/v2/homework/session/${sessionId}/recording-2`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: formData,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    return NextResponse.json(data, { status: res.status });
  }
  return NextResponse.json(data);
}
