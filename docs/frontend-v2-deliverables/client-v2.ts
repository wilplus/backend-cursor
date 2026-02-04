/**
 * API client — calls Next.js BFF /api/* (proxied to Flask /v2/*). No v2 in frontend path.
 * Add to src/lib/api/client-v2.ts (or client.ts).
 * Uses fetch with credentials so cookies/session are sent; BFF attaches Bearer token.
 */

import type {
  UniversalQuestionV2,
  UniversalAnswersPlanV2,
  V2Session,
  UploadRecordingResponseV2,
  PostAnswersResponseV2,
} from "./types-v2";

const getBase = () => {
  if (typeof window === "undefined") return "";
  return "";
};

async function v2Fetch<T>(
  path: string,
  options: RequestInit & { method?: string; body?: unknown } = {}
): Promise<T> {
  const { method = "GET", body, ...rest } = options;
  const url = `${getBase()}/api${path}`;
  const init: RequestInit = {
    ...rest,
    method,
    credentials: "include",
    headers: {
      ...(rest.headers as Record<string, string>),
      ...(body != null && typeof body === "object" && !(body instanceof FormData)
        ? { "Content-Type": "application/json" }
        : {}),
    },
  };
  if (body != null) {
    init.body = body instanceof FormData ? body : JSON.stringify(body);
  }
  const res = await fetch(url, init);
  if (!res.ok) {
    const err = (await res.json().catch(() => ({}))) as { error?: string; code?: string };
    throw new Error(err.error || err.code || `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export const v2Api = {
  getUniversalQuestions: () =>
    v2Fetch<UniversalQuestionV2[] | { questions: UniversalQuestionV2[] }>("/universal-questions").then(
      (r) => (Array.isArray(r) ? r : (r as { questions: UniversalQuestionV2[] }).questions ?? [])
    ),

  sessionStart: (sessionId?: string) =>
    v2Fetch<{ session: V2Session; session_id: string }>("/session/start", {
      method: "POST",
      body: sessionId ? { session_id: sessionId } : {},
    }),

  getSessionStatus: () =>
    v2Fetch<{ session: V2Session | null; session_id?: string; has_active_session: boolean }>(
      "/session/status"
    ),

  postUniversalAnswers: (
    sessionId: string,
    data: { mood: number; readiness: number; mode_preference: number }
  ) =>
    v2Fetch<UniversalAnswersPlanV2>(`/session/${sessionId}/universal-answers`, {
      method: "POST",
      body: data,
    }),

  postExerciseFeedback: (sessionId: string, exerciseLiked: boolean) =>
    v2Fetch<{ status: string }>(`/session/${sessionId}/exercise-feedback`, {
      method: "POST",
      body: { exercise_liked: exerciseLiked },
    }),

  postSelectTask: (sessionId: string, taskId: string) =>
    v2Fetch<{ task: { id: string; title: string; prompt_text: string }; status: string }>(
      `/session/${sessionId}/select-task`,
      { method: "POST", body: { task_id: taskId } }
    ),

  postIntent: (
    sessionId: string,
    data: { intended_emotion: string; keywords: string[] }
  ) =>
    v2Fetch<{ status: string }>(`/session/${sessionId}/intent`, {
      method: "POST",
      body: data,
    }),

  uploadRecording: (
    sessionId: string,
    taskId: string,
    audioBlob: Blob,
    filename: string = "audio.webm"
  ): Promise<UploadRecordingResponseV2> => {
    const form = new FormData();
    form.append("session_id", sessionId);
    form.append("task_id", taskId);
    form.append("audio", audioBlob, filename);
    return v2Fetch<UploadRecordingResponseV2>("/recordings/upload", {
      method: "POST",
      body: form,
    });
  },

  postPostAnswers: (
    sessionId: string,
    answers: Array<{ question_id: string; answer_text: string }>
  ) =>
    v2Fetch<PostAnswersResponseV2>(`/session/${sessionId}/post-answers`, {
      method: "POST",
      body: { answers },
    }),
};
