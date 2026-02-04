/**
 * Copy to: src/app/api/homework/session/start/route.ts
 * Required for "Start homework" — without this, the frontend gets 404 HTML and shows "Backend returned invalid JSON".
 */
import { NextResponse } from "next/server";
import { getV2AccessToken, getBackendUrl } from "../../../../getAuth";

export async function POST() {
  const token = await getV2AccessToken();
  if (!token) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  const backend = getBackendUrl();
  const res = await fetch(`${backend}/v2/homework/session/start`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({}),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    return NextResponse.json(data, { status: res.status });
  }
  return NextResponse.json(data, { status: res.status });
}
