/**
 * File: src/app/api/universal-questions/route.ts
 */
import { NextResponse } from "next/server";
// When copied to src/app/api/universal-questions/route.ts, import from "../getAuth" (if getAuth is in src/app/api/)
import { getV2AccessToken, getBackendUrl } from "../getAuth";

export async function GET() {
  const token = await getV2AccessToken();
  if (!token) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  const backend = getBackendUrl();
  const res = await fetch(`${backend}/v2/universal-questions`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    return NextResponse.json(data, { status: res.status });
  }
  return NextResponse.json(data);
}
