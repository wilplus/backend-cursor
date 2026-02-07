/**
 * Reference: "Answer these questions" screen (Step 2 of homework flow).
 *
 * Copy to your frontend (e.g. src/components/homework/AnswerMetricQuestionsScreen.tsx).
 * Uses task_block from POST recording-1 response: metric_question_1.text, metric_question_2.text,
 * metric_question_3.text as labels. Submits answer_1, answer_2, answer_3 to metric-answers.
 */

import React, { useState } from "react";
import type { TaskBlockV2, MetricAnswersResponseV2 } from "../types-v2";

interface AnswerMetricQuestionsScreenProps {
  sessionId: string;
  taskBlock: TaskBlockV2;
  onSuccess: (response: MetricAnswersResponseV2) => void;
  onError?: (message: string) => void;
}

export function AnswerMetricQuestionsScreen({
  sessionId,
  taskBlock,
  onSuccess,
  onError,
}: AnswerMetricQuestionsScreenProps) {
  const [answer1, setAnswer1] = useState("");
  const [answer2, setAnswer2] = useState("");
  const [answer3, setAnswer3] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const q1 = taskBlock.metric_question_1 ?? {};
  const q2 = taskBlock.metric_question_2 ?? {};
  const q3 = taskBlock.metric_question_3 ?? {};
  const label1 = (q1.text ?? "").trim();
  const label2 = (q2.text ?? "").trim();
  const label3 = (q3.text ?? "").trim();
  const questions = [
    { label: label1, value: answer1, setValue: setAnswer1 },
    { label: label2, value: answer2, setValue: setAnswer2 },
    { label: label3, value: answer3, setValue: setAnswer3 },
  ].filter((q) => q.label);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      const res = await fetch(`/api/homework/session/${sessionId}/metric-answers`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          answer_1: answer1.trim(),
          answer_2: answer2.trim(),
          answer_3: answer3.trim(),
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        onError?.(data?.error ?? "Failed to submit answers");
        return;
      }
      onSuccess(data as MetricAnswersResponseV2);
    } catch (err) {
      onError?.(err instanceof Error ? err.message : "Network error");
    } finally {
      setSubmitting(false);
    }
  };

  if (questions.length === 0) {
    return (
      <p className="text-muted">
        No metric questions for this task. You can still continue with the next step.
      </p>
    );
  }

  return (
    <div className="answer-metric-questions">
      <h2>Answer these three questions</h2>
      <p className="subtitle">Your answers will shape the focus for your second recording.</p>

      <form onSubmit={handleSubmit}>
        {questions.map((q, i) => (
          <div key={i} className="field">
            <label htmlFor={`metric-answer-${i + 1}`}>{q.label}</label>
            <input
              id={`metric-answer-${i + 1}`}
              type="text"
              placeholder="Your answer..."
              value={q.value}
              onChange={(e) => q.setValue(e.target.value)}
              disabled={submitting}
              autoComplete="off"
            />
          </div>
        ))}
        <button type="submit" disabled={submitting}>
          {submitting ? "Submitting…" : "Continue to next step"}
        </button>
      </form>
    </div>
  );
}
