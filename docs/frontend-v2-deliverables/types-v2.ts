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
