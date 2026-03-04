/**
 * V2 flow types — align with backend /v2/* responses.
 * Add to src/lib/api/types-v2.ts or merge into types.ts.
 */

export type UniversalAnswerType = "slider_0_1" | "scale_1_10" | "binary";
export type PostAnswerTypeV2 = "yes_no" | "scale_1_5" | "text";

export interface UniversalQuestionV2 {
  id: string;
  code: string;
  text: string;
  answer_type: UniversalAnswerType;
  position: number;
}

export interface ExerciseV2 {
  id: string;
  title: string;
  video_url: string | null;
  description: string | null;
}

export interface TaskV2 {
  id: string;
  title: string;
  prompt_text: string;
}

export interface PostRecordingQuestionV2 {
  id: string;
  code: string;
  text: string;
  answer_type: PostAnswerTypeV2;
}

export interface IntentPromptsV2 {
  intended_emotion: string;
  keywords: string;
}

export interface UniversalAnswersPlanV2 {
  task_score: number;
  exercise: ExerciseV2 | null;
  selected_task: TaskV2 | null;
  task_options: TaskV2[] | null;
  intent_prompts: IntentPromptsV2;
  post_recording_questions: PostRecordingQuestionV2[];
}

export interface MetricLabelV2 {
  code: string;
  left_label: string;
  right_label: string;
}

export interface MetricValueV2 {
  raw?: number | string | boolean;
  normalized: number;
  label?: string;
}

export interface PerformanceMetricsV2 {
  pace?: MetricValueV2;
  strength?: MetricValueV2;
  fillers?: MetricValueV2;
  emotion_achieved?: MetricValueV2;
  keywords_used?: MetricValueV2;
}

export interface UploadRecordingResponseV2 {
  recording_id: string;
  performance_score: number;
  performance_metrics: PerformanceMetricsV2;
  metric_labels_snapshot: Record<string, { left_label: string; right_label: string }>;
}

export interface PostAnswersResponseV2 {
  report_text: string;
  performance_score: number;
  performance_metrics: PerformanceMetricsV2;
  metric_labels_snapshot: Record<string, { left_label: string; right_label: string }>;
}

export interface V2Session {
  id: string;
  user_id: string;
  status: string;
  universal_answers?: { mood?: number; readiness?: number; mode_preference?: number };
  task_score?: number;
  selected_exercise_id?: string | null;
  selected_task_id?: string | null;
  task_option_ids?: string[] | null;
  intended_emotion?: string | null;
  keywords?: string[] | null;
  post_question_ids?: string[] | null;
  recording_id?: string | null;
  report_id?: string | null;
  created_at?: string;
}

/** One metric question in the task block (from recording-1 response). */
export interface MetricQuestionItemV2 {
  id: string;
  text: string;
  order_index?: number;
}

/** Task block returned after POST recording-1. Use metric_question_1/2/3.text as labels. */
export interface TaskBlockV2 {
  context_short: string;
  focus_task: { id: string; title: string; prompt_text: string } | null;
  metric_question_1: MetricQuestionItemV2;
  metric_question_2: MetricQuestionItemV2;
  metric_question_3: MetricQuestionItemV2;
}

/** Response from POST session/:sessionId/metric-answers */
export interface MetricAnswersResponseV2 {
  final_task: string;
}

/** Response from POST session/:sessionId/post-answers (step 4). */
export interface PostAnswersResponseV2Homework {
  report_text: string;
  performance_score_end: number;
  performance_metrics?: PerformanceMetricsV2;
  question_1_analysis?: string;
  question_1_score?: number;
  question_2_analysis?: string;
  question_2_score?: number;
  question_3_analysis?: string;
  question_3_score?: number;
}

/**
 * Response from GET session/:sessionId/report (step 5 – report view).
 * Use score_for_display for the main "Your result" and for the performance chart;
 * do not use scores.final for the main number or it will not match the graph.
 */
export interface HomeworkReportResponseV2 {
  report_text: string;
  /** Single score only (Sniper Voice Alignment when available). */
  scores: { overall: number };
  /** Canonical score 0–100 for main display and chart. Same as last bar on performance_history. */
  score_for_display: number;
  performance_score_end: number;
  recording_count: number;
  final_recording: { id: string | null; audio_url: string | null };
  performance_history: Array<{ date: string; score: number }>;
  /** Admin/coach grade (1–10) when set via PUT .../grade; null otherwise. */
  admin_grade?: number | null;
  report_cta?: string;
  leave_report_path?: string;
  recording?: {
    id: string;
    audio_url: string | null;
    transcription_text: string;
    filler_words_count: { total: number; breakdown: Record<string, number> };
    words_per_minute: number;
  };
  context_short?: string;
  coach_insight?: string;
  tutor_feedback_deadline?: string;
  tutor_feedback_message?: string;
}
