/**
 * Admin API client — calls Next.js BFF /api/admin/* (which proxy to Flask /v2/admin/*). No v2 in frontend path.
 * Use only in admin pages; BFF must send admin token.
 */

const getBase = () => (typeof window === "undefined" ? "" : "");

async function adminFetch<T>(
  path: string,
  options: RequestInit & { method?: string; body?: unknown } = {}
): Promise<T> {
  const { method = "GET", body, ...rest } = options;
  const url = `${getBase()}/api/admin${path}`;
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

/** Latest measured speech metrics for admin dashboard (GET /v2/admin/students/:id → measured_metrics). */
export interface MeasuredMetricsLatest {
  source: "session_sniper_metrics" | "recording" | null;
  session_id: string | null;
  captured_at: string | null;
  wpm: number | null;
  pause_ms: number | null;
  dynamic_db: number | null;
  emphasis_per_min: number | null;
  energy_ratio: number | null;
  voiced_duration_sec: number | null;
  pitch_center_st: number | null;
  pitch_frame_count: number | null;
  stage_score: number | null;
  student_rating_1_10: number | null;
  recording_id: string | null;
  filler_words_count: number | null;
  duration_ms: number | null;
}

export interface MeasuredMetricsBaselines {
  baseline_wpm?: number | null;
  baseline_pause_ms?: number | null;
  baseline_dynamic_db?: number | null;
  baseline_emphasis_per_min?: number | null;
  baseline_energy_ratio?: number | null;
  baseline_fatigue_sec?: number | null;
  realtime_pitch_baseline_st?: number | null;
}

export interface MeasuredMetricsPayload {
  latest: MeasuredMetricsLatest;
  baselines: MeasuredMetricsBaselines | null;
}

export interface StudentProfile {
  user_id: string;
  email: string | null;
  measured_metrics?: MeasuredMetricsPayload;
  overrides: {
    show_exercise_step?: boolean;
    skip_metric_questions?: boolean;
    skip_post_questions?: boolean;
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
    coach_grade?: number | null;
    /** Shadow AI score 0-100 from GPT-4o-mini (RLHF pipeline, not shown to students). */
    ai_task_score?: number | null;
    /** LLM justification for ai_task_score. */
    ai_scoring_justification?: string | null;
    /** Manual coach override 0-100 (authoritative over AI score when set). */
    coach_override_score?: number | null;
    recording_preview?: { performance_score_v2?: number; transcription_preview?: string };
    report_preview?: { report_text_preview?: string };
  }>;
  similar_students_by_wpm?: Array<{
    user_id: string;
    email: string;
    wpm: number;
    session_id?: string;
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

export interface WarmUpTask {
  id: string;
  user_id: string;
  text: string;
  order_index: number;
  max_performance_score?: number;
  pool_task_id?: string | null;
  created_at?: string;
}

/** Row in v2_warm_up_task_pool / v2_focus_task_pool (no user_id). */
export interface TaskPoolRow {
  id: string;
  text: string;
  order_index: number;
  max_performance_score?: number;
  created_at?: string;
}

export interface FocusTask {
  id: string;
  user_id: string;
  text: string;
  order_index: number;
  max_performance_score?: number;
  pool_task_id?: string | null;
  created_at?: string;
}

export interface MetricQuestion {
  id: string;
  position: 1 | 2;
  text: string;
  created_at?: string;
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

  sendAssignment: (userId: string, additionalUserIds?: string[]) =>
    adminFetch<{ status: string; additional_sends?: Array<{ user_id: string; status: string; email?: string }> }>(
      `/students/${userId}/send-assignment`,
      { method: "POST", body: additionalUserIds?.length ? { additional_user_ids: additionalUserIds } : undefined },
    ),

  getExercises: () =>
    adminFetch<{ exercises: Exercise[] }>("/exercises").then((r) => r.exercises),

  createExercise: (data: Partial<Exercise>) =>
    adminFetch<{ exercise: Exercise }>("/exercises", { method: "POST", body: data }),

  updateExercise: (id: string, data: Partial<Exercise>) =>
    adminFetch<{ exercise: Exercise }>(`/exercises/${id}`, { method: "PUT", body: data }),

  deleteExercise: (id: string) =>
    adminFetch<{ status: string }>(`/exercises/${id}`, { method: "DELETE" }),

  getPostQuestions: () =>
    adminFetch<{ questions: PostQuestion[] }>("/post-recording-questions").then((r) => r.questions),

  createPostQuestion: (data: Partial<PostQuestion>) =>
    adminFetch<{ question: PostQuestion }>("/post-recording-questions", { method: "POST", body: data }),

  updatePostQuestion: (id: string, data: Partial<PostQuestion>) =>
    adminFetch<{ question: PostQuestion }>(`/post-recording-questions/${id}`, { method: "PUT", body: data }),

  deletePostQuestion: (id: string) =>
    adminFetch<{ status: string }>(`/post-recording-questions/${id}`, { method: "DELETE" }),

  // Homework flow: warm-up tasks (per student). Backend returns task_warm_up (array or single on POST/PUT).
  getWarmUpTasks: (userId: string) =>
    adminFetch<{ warm_up_tasks?: WarmUpTask[]; task_warm_up?: WarmUpTask[] }>(
      `/students/${userId}/warm-up-tasks`
    ).then((r) => r.task_warm_up ?? r.warm_up_tasks ?? []),

  createWarmUpTask: (userId: string, data: { text: string; order_index?: number; max_performance_score?: number }) =>
    adminFetch<{ warm_up_task?: WarmUpTask; task_warm_up?: WarmUpTask }>(
      `/students/${userId}/warm-up-tasks`,
      { method: "POST", body: data }
    ),

  /** One call: pool row + sync to student (preferred over createWarmUpTask when tasks should live in the pool). */
  createWarmUpPoolTaskAndAssign: (
    userId: string,
    data: { text: string; order_index?: number; max_performance_score?: number; insert_at?: "end" | number }
  ) =>
    adminFetch<{
      task_warm_up_pool: TaskPoolRow;
      task_warm_up: WarmUpTask[];
      dropped_non_pool_tasks: number;
    }>(`/students/${userId}/warm-up-tasks/create-pool-and-assign`, { method: "POST", body: data }),

  updateWarmUpTask: (userId: string, taskId: string, data: { text?: string; order_index?: number; max_performance_score?: number }) =>
    adminFetch<{ warm_up_task?: WarmUpTask; task_warm_up?: WarmUpTask }>(
      `/students/${userId}/warm-up-tasks/${taskId}`,
      { method: "PUT", body: data }
    ),

  deleteWarmUpTask: (userId: string, taskId: string) =>
    adminFetch<{ status: string }>(`/students/${userId}/warm-up-tasks/${taskId}`, { method: "DELETE" }),

  createFocusPoolTaskAndAssign: (
    userId: string,
    data: { text: string; order_index?: number; max_performance_score?: number; insert_at?: "end" | number }
  ) =>
    adminFetch<{
      task_focus_pool: TaskPoolRow;
      task_focus: FocusTask[];
      dropped_non_pool_tasks: number;
    }>(`/students/${userId}/focus-tasks/create-pool-and-assign`, { method: "POST", body: data }),

  // Homework flow: metric questions (metric_question_1, metric_question_2)
  getMetricQuestions: () =>
    adminFetch<{ questions: MetricQuestion[] }>("/metric-questions").then((r) => r.questions),

  createMetricQuestion: (data: { position: 1 | 2; text: string }) =>
    adminFetch<{ question: MetricQuestion }>("/metric-questions", { method: "POST", body: data }),

  updateMetricQuestion: (id: string, data: { position?: 1 | 2; text?: string }) =>
    adminFetch<{ question: MetricQuestion }>(`/metric-questions/${id}`, { method: "PUT", body: data }),

  deleteMetricQuestion: (id: string) =>
    adminFetch<{ status: string }>(`/metric-questions/${id}`, { method: "DELETE" }),

  patchSession: (
    userId: string,
    sessionId: string,
    data: { coach_grade?: number | null; coach_override_score?: number | null }
  ) =>
    adminFetch<{ status: string; report_grade?: number | null; coach_override_score?: number | null }>(
      `/students/${userId}/sessions/${sessionId}`,
      { method: "PATCH", body: data }
    ),

  // AI Coach Suggestions
  sendCoachSuggestion: (userId: string, message: string) =>
    adminFetch<CoachSuggestionResponse>(
      `/students/${userId}/coach-suggestions`,
      { method: "POST", body: { message } }
    ),

  getCoachSuggestionHistory: (userId: string) =>
    adminFetch<CoachSuggestionHistory>(`/students/${userId}/coach-suggestions/history`),

  clearCoachSuggestionHistory: (userId: string) =>
    adminFetch<{ status: string }>(`/students/${userId}/coach-suggestions/history`, { method: "DELETE" }),
};

export interface CoachSuggestionResponse {
  status: string;
  homework_message: string;
  task_suggestion: string;
  video_script: string;
  raw_text: string;
}

export interface CoachSuggestionHistory {
  status: string;
  user_id: string;
  messages: Array<{ role: "user" | "assistant"; content: string; timestamp: string }>;
  updated_at: string | null;
}
