/**
 * Copy to: src/app/api/admin/recordings/[recordingId]/stress-snippets/generate/route.ts
 */
import { NextRequest, NextResponse } from "next/server";
import { getV2AccessToken, getBackendUrl } from "../../../../../getAuth";

export async function POST(
  request: NextRequest,
  context: { params: { recordingId: string } }
) {
  const token = await getV2AccessToken();
  if (!token) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const body = await request.json().catch(() => ({}));
  const backend = getBackendUrl();
  const recordingId = context.params.recordingId;
  const res = await fetch(`${backend}/v2/admin/recordings/${recordingId}/stress-snippets/generate`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) return NextResponse.json(data, { status: res.status });
  return NextResponse.json(data);
}
