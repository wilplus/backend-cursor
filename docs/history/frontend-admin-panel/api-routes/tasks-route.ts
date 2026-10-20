/**
 * Copy to: src/app/api/admin/tasks/route.ts
 * IMPORTANT: Path must be api/admin/tasks (so the URL is /api/admin/tasks). Do NOT put under api/v2/admin/tasks.
 * Responses include _debug so you can see in Network tab whether this BFF route ran and what the backend returned.
 */
import { NextRequest, NextResponse } from "next/server";
import { getV2AccessToken, getBackendUrl } from "../../getAuth"; // from api/admin/tasks/ → api/getAuth or your auth path

const BFF_DEBUG_HEADER = "X-BFF-Route";
const BFF_DEBUG_VALUE = "admin-tasks";

function debugPayload(backendUrl: string, backendStatus: number) {
  try {
    const host = backendUrl ? new URL(backendUrl).host : "unknown";
    return { bffRoute: "admin/tasks", backendHost: host, backendStatus };
  } catch {
    return { bffRoute: "admin/tasks", backendHost: "(invalid-url)", backendStatus };
  }
}

export async function GET() {
  let backend = "";
  let token = "";
  try {
    token = (await getV2AccessToken()) || "";
    if (!token) {
      return NextResponse.json(
        { error: "Unauthorized", code: "NO_TOKEN", _debug: { bffRoute: "admin/tasks", stage: "getAuth", message: "getV2AccessToken returned empty" } },
        { status: 401, headers: { [BFF_DEBUG_HEADER]: BFF_DEBUG_VALUE } }
      );
    }
    backend = getBackendUrl() || "";
    if (!backend) {
      return NextResponse.json(
        { error: "Backend URL not configured", code: "NO_BACKEND", _debug: { bffRoute: "admin/tasks", stage: "getBackendUrl", message: "getBackendUrl returned empty" } },
        { status: 500, headers: { [BFF_DEBUG_HEADER]: BFF_DEBUG_VALUE } }
      );
    }
  } catch (e) {
    const message = e instanceof Error ? e.message : String(e);
    return NextResponse.json(
      { error: "BFF setup error", code: "BFF_ERROR", _debug: { bffRoute: "admin/tasks", stage: "getAuth_or_getBackendUrl", message } },
      { status: 500, headers: { [BFF_DEBUG_HEADER]: BFF_DEBUG_VALUE } }
    );
  }
  const res = await fetch(`${backend}/v2/admin/tasks`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const data = await res.json().catch(() => ({}));
  const response = NextResponse.json(
    res.ok ? data : { ...data, _debug: debugPayload(backend, res.status) },
    { status: res.status }
  );
  response.headers.set(BFF_DEBUG_HEADER, BFF_DEBUG_VALUE);
  return response;
}

export async function POST(request: NextRequest) {
  let backend = "";
  let token = "";
  try {
    token = (await getV2AccessToken()) || "";
    if (!token) {
      return NextResponse.json(
        { error: "Unauthorized", code: "NO_TOKEN", _debug: { bffRoute: "admin/tasks", stage: "getAuth" } },
        { status: 401, headers: { [BFF_DEBUG_HEADER]: BFF_DEBUG_VALUE } }
      );
    }
    backend = getBackendUrl() || "";
    if (!backend) {
      return NextResponse.json(
        { error: "Backend URL not configured", code: "NO_BACKEND", _debug: { bffRoute: "admin/tasks", stage: "getBackendUrl" } },
        { status: 500, headers: { [BFF_DEBUG_HEADER]: BFF_DEBUG_VALUE } }
      );
    }
  } catch (e) {
    const message = e instanceof Error ? e.message : String(e);
    return NextResponse.json(
      { error: "BFF setup error", code: "BFF_ERROR", _debug: { bffRoute: "admin/tasks", stage: "init", message } },
      { status: 500, headers: { [BFF_DEBUG_HEADER]: BFF_DEBUG_VALUE } }
    );
  }
  const body = await request.json().catch(() => ({}));
  const res = await fetch(`${backend}/v2/admin/tasks`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  const response = NextResponse.json(
    res.ok ? data : { ...data, _debug: debugPayload(backend, res.status) },
    { status: res.status === 201 ? 201 : res.status }
  );
  response.headers.set(BFF_DEBUG_HEADER, BFF_DEBUG_VALUE);
  return response;
}
