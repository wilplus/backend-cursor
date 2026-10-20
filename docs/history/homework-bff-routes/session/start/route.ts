/**
 * Copy to: src/app/api/homework/session/start/route.ts
 * Required for "Start homework". Passes through 4xx/5xx body (e.g. 422 NO_WARMUP_CONFIGURED).
 */
import { NextResponse } from "next/server";
import { getV2AccessToken, getBackendUrl } from "../../../getAuth";
import { proxyResponse } from "../../../proxyResponse";

export async function POST() {
  const token = await getV2AccessToken();
  if (!token) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  const backend = getBackendUrl();
  const upstreamRes = await fetch(`${backend}/v2/homework/session/start`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({}),
  });
  return proxyResponse(upstreamRes);
}
