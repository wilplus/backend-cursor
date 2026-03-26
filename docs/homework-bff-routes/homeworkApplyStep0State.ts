/**
 * Copy to your Next.js app, e.g. src/lib/homework/applyStep0State.ts
 *
 * Use with GET /api/homework/session/status when has_active_session is false (e.g. user
 * opened homework / dashboard after sign-in).
 *
 * Problem this fixes: merging the new step-0 JSON into old client state leaves
 * tutor_video_url truthy → video block stays until logout. Replace state instead.
 */

export type HomeworkStep0State = {
  status: string;
  review_pending: boolean;
  main_screen_state: string;
  main_screen_message: string | null;
  tutor_video_url: string | null;
  tutor_video_description: string | null;
  has_active_session: boolean;
  assigned_exercises: Array<{
    id?: string;
    title?: string;
    video_url?: string | null;
    description?: string | null;
  }>;
  session_id: string | null;
  recording_id: string | null;
  task: string | null;
};

function strOrNull(v: unknown): string | null {
  if (v == null) return null;
  const s = String(v).trim();
  return s.length ? s : null;
}

/**
 * Normalize backend step-0 (GET session/status) payload so missing fields become explicit nulls
 * (not undefined), which works better with React state resets.
 */
export function normalizeHomeworkStep0Payload(raw: Record<string, unknown>): HomeworkStep0State {
  const exercises = Array.isArray(raw.assigned_exercises) ? raw.assigned_exercises : [];
  return {
    status: typeof raw.status === "string" ? raw.status : "none",
    review_pending: Boolean(raw.review_pending),
    main_screen_state:
      typeof raw.main_screen_state === "string" ? raw.main_screen_state : "assignment_ready",
    main_screen_message: strOrNull(raw.main_screen_message),
    tutor_video_url: strOrNull(raw.tutor_video_url),
    tutor_video_description: strOrNull(raw.tutor_video_description),
    has_active_session: Boolean(raw.has_active_session),
    assigned_exercises: exercises as HomeworkStep0State["assigned_exercises"],
    session_id: strOrNull(raw.session_id),
    recording_id: strOrNull(raw.recording_id),
    task: strOrNull(raw.task),
  };
}

/**
 * Remove persisted report UI keys so step 0 cannot re-hydrate old video/report flags.
 * Pass the keys your app uses (sessionStorage / localStorage).
 */
export function clearHomeworkPersistedKeys(keys: readonly string[]): void {
  if (typeof window === "undefined") return;
  for (const k of keys) {
    try {
      sessionStorage.removeItem(k);
      localStorage.removeItem(k);
    } catch {
      /* ignore quota / private mode */
    }
  }
}

/**
 * Example CTA handler shape (adapt to your store):
 *
 *   const raw = await res.json();
 *   clearHomeworkPersistedKeys(['homework_report_snapshot', ...]);
 *   setStep0(normalizeHomeworkStep0Payload(raw));
 *   // Do not spread previous step0 into this object.
 */
