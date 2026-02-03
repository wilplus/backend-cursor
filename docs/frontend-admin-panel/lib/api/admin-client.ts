/**
 * Admin API client — calls Next.js BFF /api/v2/admin/* (which proxy to Flask /v2/admin/*).
 * Use only in admin pages; BFF must send admin token.
 */

const getBase = () => (typeof window === "undefined" ? "" : "");

async function adminFetch<T>(
  path: string,
  options: RequestInit & { method?: string; body?: unknown } = {}
): Promise<T> {
  const { method = "GET", body, ...rest } = options;
  const url = `${getBase()}/api/v2/admin${path}`;
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
  if (body != null) init.body = body instanceof FormData ? body : JSON.stringify(body);
  const res = await fetch(url, init);
  if (!res.ok) {
    const err = (await res.json().catch(() => ({}))) as { error?: string; code?: string };
    throw new Error(err.error || err.code || `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export interface StudentListItem {
  user_id: string;
}

export interface StudentProfile {
  user_id: string;
  email: string | null;
  overrides: {
    intended_emotion_prompt?: string;
    keywords_prompt?: string;
    emotion_check_question_text?: string;
    assigned_post_question_ids?: string[];
    assigned_next_exercise_id?: string;
    assigned_next_task_ids?: string[];
  } | null;
  speaker_profile: {
    main_goal?: string;
    motivation?: string;
    strong_points?: string;
    weak_points?: string;
    charismatic_traits?: string;
    hobbies_interests?: string;
    personality_type?: string;
    coach_notes?: string;
  } | null;
  sessions: Array<{
    id: string;
    created_at: string;
    status: string;
    recording_id?: string;
    report_id?: string;
    task_score?: number;
    recording_preview?: { performance_score_v2?: number; transcription_preview?: string };
    report_preview?: { report_text_preview?: string };
  }>;
}

export interface Exercise {
  id: string;
  title: string;
  video_url?: string | null;
  description?: string | null;
  min_task_score?: number;
  max_task_score?: number;
  is_active?: boolean;
  created_at?: string;
}

export interface PostQuestion {
  id: string;
  code?: string | null;
  text: string;
  answer_type: string;
  is_active?: boolean;
}

export const adminApi = {
  getStudents: (params?: { limit?: number; offset?: number }) =>
    adminFetch<{ students: StudentListItem[]; limit: number; offset: number }>(
      `/students?${new URLSearchParams(params as Record<string, string>).toString()}`
    ),

  getStudentProfile: (userId: string) =>
    adminFetch<StudentProfile>(`/students/${userId}`),

  putOverrides: (userId: string, data: Record<string, unknown>) =>
    adminFetch<{ status: string }>(`/students/${userId}/overrides`, { method: "PUT", body: data }),

  putSpeakerProfile: (userId: string, data: Record<string, unknown>) =>
    adminFetch<{ status: string }>(`/students/${userId}/speaker-profile`, { method: "PUT", body: data }),

  sendAssignment: (userId: string) =>
    adminFetch<{ status: string }>(`/students/${userId}/send-assignment`, { method: "POST" }),

  getExercises: () =>
    adminFetch<{ exercises: Exercise[] }>("/exercises").then((r) => r.exercises),

  createExercise: (data: Partial<Exercise>) =>
    adminFetch<{ exercise: Exercise }>("/exercises", { method: "POST", body: data }),

  updateExercise: (id: string, data: Partial<Exercise>) =>
    adminFetch<{ exercise: Exercise }>(`/exercises/${id}`, { method: "PUT", body: data }),

  deleteExercise: (id: string) =>
    adminFetch<{ status: string }>(`/exercises/${id}`, { method: "DELETE" }),

  getTasks: () =>
    adminFetch<{ tasks: unknown[] }>("/tasks").then((r) => r.tasks),

  getPostQuestions: () =>
    adminFetch<{ questions: PostQuestion[] }>("/post-recording-questions").then((r) => r.questions),
};
