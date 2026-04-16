/**
 * Copy to: src/app/api/admin/copilot/students/[id]/drafts/[draftId]/pipeline-status/route.ts
 *
 * Proxies GET so the browser polls same-origin /api/... (avoids CORS "Failed to fetch" on direct BACKEND_URL).
 */
import { NextRequest, NextResponse } from "next/server";
import { getV2AccessToken, getBackendUrl } from "../../../../../../../getAuth";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string; draftId: string }> }
) {
  const token = await getV2AccessToken();
  if (!token) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  const { id, draftId } = await params;
  const backend = getBackendUrl();
  const res = await fetch(
    `${backend}/v2/admin/students/${id}/drafts/${draftId}/pipeline-status`,
    {
      method: "GET",
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
    }
  );
  const data = await res.json().catch(() => ({}));
  return NextResponse.json(data, { status: res.status });
}
