/**
 * File: src/app/api/recordings/upload/route.ts
 * Proxies multipart/form-data to backend. Request must be FormData with session_id, task_id, audio.
 */
import { NextResponse } from "next/server";
import { getV2AccessToken, getBackendUrl } from "../../getAuth";

export async function POST(request: Request) {
  const token = await getV2AccessToken();
  if (!token) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  const formData = await request.formData();
  const backend = getBackendUrl();

  const body = new FormData();
  const sessionId = formData.get("session_id");
  const taskId = formData.get("task_id");
  const audio = formData.get("audio");
  if (!sessionId || !taskId || !audio || !(audio instanceof Blob)) {
    return NextResponse.json(
      { code: "INVALID_INPUT", error: "session_id, task_id, and audio required" },
      { status: 400 }
    );
  }
  body.append("session_id", String(sessionId));
  body.append("task_id", String(taskId));
  body.append("audio", audio, (audio as File).name || "audio.webm");

  const res = await fetch(`${backend}/v2/recordings/upload`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    return NextResponse.json(data, { status: res.status });
  }
  return NextResponse.json(data);
}
