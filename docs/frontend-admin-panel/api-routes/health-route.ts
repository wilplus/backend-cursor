/**
 * Copy to: src/app/api/admin/health/route.ts
 * Use to verify that /api/admin/* is reachable. If this returns 200, api/admin routing works; if 404, the folder or path is wrong.
 */
import { NextResponse } from "next/server";

export async function GET() {
  return NextResponse.json(
    { ok: true, route: "admin/health" },
    { headers: { "X-BFF-Route": "admin-health" } }
  );
}
