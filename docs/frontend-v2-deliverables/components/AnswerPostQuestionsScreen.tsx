/**
 * Reference: Post-recording questions screen (Step 4 of homework flow).
 *
 * Copy to your frontend (e.g. src/components/homework/AnswerPostQuestionsScreen.tsx).
 * Uses the same pattern as AnswerMetricQuestionsScreen: local state for each answer,
 * submit only on "Confirm" — do NOT refetch status or re-mount on every keystroke,
 * or the form will "block or refresh after a single letter".
 *
 * Backend expects POST body: { answers: [ { question_id: string, answer_text: string } ] }
 */

import React, { useState, useCallback } from "react";
import type { PostRecordingQuestionV2 } from "../types-v2";
import type { PostAnswersResponseV2Homework } from "../types-v2";

interface AnswerPostQuestionsScreenProps {
  sessionId: string;
  questions: PostRecordingQuestionV2[];
  onSuccess: (response: PostAnswersResponseV2Homework) => void;
  onError?: (message: string) => void;
}

export function AnswerPostQuestionsScreen({
  sessionId,
  questions,
  onSuccess,
  onError,
}: AnswerPostQuestionsScreenProps) {
  // Local state keyed by question id — only this component updates it; no parent refetch on keystroke
  const [answers, setAnswers] = useState<Record<string, string>>(() => {
    const init: Record<string, string> = {};
    questions.forEach((q) => {
      init[q.id] = "";
    });
    return init;
  });
  const [submitting, setSubmitting] = useState(false);

  const setAnswer = useCallback((questionId: string, value: string) => {
    setAnswers((prev) => ({ ...prev, [questionId]: value }));
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      const payload = {
        answers: questions.map((q) => ({
          question_id: q.id,
          answer_text: (answers[q.id] ?? "").trim(),
        })),
      };
      const res = await fetch(`/api/homework/session/${sessionId}/post-answers`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        onError?.(data?.error ?? data?.message ?? "Failed to submit answers");
        return;
      }
      onSuccess(data as PostAnswersResponseV2Homework);
    } catch (err) {
      onError?.(err instanceof Error ? err.message : "Network error");
    } finally {
      setSubmitting(false);
    }
  };

  if (questions.length === 0) {
    return (
      <p className="text-muted">
        No reflective questions for this step. You can continue to see your report.
      </p>
    );
  }

  return (
    <div className="answer-post-questions">
      <h2>Reflective questions</h2>
      <p className="subtitle">Your answers help shape your report.</p>

      <form onSubmit={handleSubmit}>
        {questions.map((q) => (
          <div key={q.id} className="field">
            <label htmlFor={`post-q-${q.id}`}>{q.text}</label>
            <input
              id={`post-q-${q.id}`}
              type="text"
              placeholder="Your answer..."
              value={answers[q.id] ?? ""}
              onChange={(e) => setAnswer(q.id, e.target.value)}
              disabled={submitting}
              autoComplete="off"
            />
          </div>
        ))}
        <button type="submit" disabled={submitting}>
          {submitting ? "Submitting…" : "Confirm"}
        </button>
      </form>
    </div>
  );
}
