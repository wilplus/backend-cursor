/**
 * Copy to: src/app/api/homework/session/status/route.ts
 */
import { NextResponse } from "next/server";
import { getV2AccessToken, getBackendUrl } from "../../../../getAuth";

export async function GET() {
  const token = await getV2AccessToken();
  if (!token) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  const backend = getBackendUrl();
  const res = await fetch(`${backend}/v2/homework/session/status`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    return NextResponse.json(data, { status: res.status });
  }
  return NextResponse.json(data);
}
