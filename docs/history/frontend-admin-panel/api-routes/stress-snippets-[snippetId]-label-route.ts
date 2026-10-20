/**
 * Copy to: src/app/api/admin/stress-snippets/[snippetId]/label/route.ts
 */
import { NextRequest, NextResponse } from "next/server";
import { getV2AccessToken, getBackendUrl } from "../../../../getAuth";

export async function PATCH(
  request: NextRequest,
  context: { params: { snippetId: string } }
) {
  const token = await getV2AccessToken();
  if (!token) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const body = await request.json().catch(() => ({}));
  const backend = getBackendUrl();
  const snippetId = context.params.snippetId;
  const res = await fetch(`${backend}/v2/admin/stress-snippets/${snippetId}/label`, {
    method: "PATCH",
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
