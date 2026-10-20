/**
 * Copy to: src/app/api/homework/session/status/route.ts
 * Passes through 4xx/5xx body.
 */
import { NextResponse } from "next/server";
import { getV2AccessToken, getBackendUrl } from "../../../getAuth";
import { proxyResponse } from "../../../proxyResponse";

export async function GET() {
  const token = await getV2AccessToken();
  if (!token) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  const backend = getBackendUrl();
  const upstreamRes = await fetch(`${backend}/v2/homework/session/status`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return proxyResponse(upstreamRes);
}
