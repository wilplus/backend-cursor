/**
 * Copy to: src/app/api/admin/copilot/students/[id]/drafts/[draftId]/approve-send/route.ts
 *
 * Async queue trigger: returns immediately while video pipeline runs in background.
 */
import { NextRequest, NextResponse } from "next/server";
import { getV2AccessToken, getBackendUrl } from "../../../../../../../getAuth";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string; draftId: string }> }
) {
  const token = await getV2AccessToken();
  if (!token) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  const { id, draftId } = await params;
  const body = await request.json().catch(() => ({}));
  const backend = getBackendUrl();
  const res = await fetch(
    `${backend}/v2/admin/students/${id}/drafts/${draftId}/approve-send`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body || {}),
      cache: "no-store",
    }
  );
  const data = await res.json().catch(() => ({}));
  return NextResponse.json(data, { status: res.status });
}
