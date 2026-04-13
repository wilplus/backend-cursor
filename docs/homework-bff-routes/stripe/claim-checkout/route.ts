/**
 * Copy to: src/app/api/homework/stripe/claim-checkout/route.ts
 * Body: { "checkout_session_id": "cs_..." } (from Stripe success_url ?session_id=)
 */
import { NextResponse } from "next/server";
import { getV2AccessToken, getBackendUrl } from "../../../getAuth";
import { proxyResponse } from "../../../proxyResponse";

export async function POST(request: Request) {
  const token = await getV2AccessToken();
  if (!token) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  let body: unknown = {};
  try {
    body = await request.json();
  } catch {
    body = {};
  }
  const backend = getBackendUrl();
  const upstreamRes = await fetch(`${backend}/v2/homework/stripe/claim-checkout`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body && typeof body === "object" ? body : {}),
  });
  return proxyResponse(upstreamRes);
}
