/**
 * BFF route: POST /api/admin/students/[id]/coach-suggestions
 * Proxies to Flask POST /v2/admin/students/<user_id>/coach-suggestions
 *
 * Body: { message: string }
 * Response: { status, homework_message, task_suggestion, video_script, raw_text }
 */
import { NextRequest, NextResponse } from "next/server";

export async function POST(req: NextRequest, { params }: { params: { id: string } }) {
  const body = await req.json();
  const res = await fetch(
    `${process.env.BACKEND_URL}/v2/admin/students/${params.id}/coach-suggestions`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: req.headers.get("Authorization") || "",
      },
      body: JSON.stringify(body),
    }
  );
  const data = await res.json();
  return NextResponse.json(data, { status: res.status });
}

/**
 * BFF route: GET /api/admin/students/[id]/coach-suggestions/history
 * Proxies to Flask GET /v2/admin/students/<user_id>/coach-suggestions/history
 *
 * Response: { status, user_id, messages: [{role, content, timestamp}], updated_at }
 */

/**
 * BFF route: DELETE /api/admin/students/[id]/coach-suggestions/history
 * Proxies to Flask DELETE /v2/admin/students/<user_id>/coach-suggestions/history
 *
 * Response: { status, message }
 */
