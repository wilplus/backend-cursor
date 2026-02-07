# Pitch variance + custom metric questions (backend spec)

Implements: **pitch_variance** (real-time) + **3 user-editable metric questions** (LLM-analyzed at session end). Other metric definitions (pace, strength, fillers, emotion_achieved, keywords_used) are not part of this flow.

---

## Data model

### User (v2_student_overrides)

- **metric_question_1**, **metric_question_2**, **metric_question_3** (TEXT) — user’s three custom questions (default empty).
- **pitch_variance_ideal** (FLOAT, optional) — display/config for pitch variance scale.

### Session (v2_sessions)

- **session_metric_question_1**, **session_metric_question_2**, **session_metric_question_3** — snapshot at session start.
- **question_1_analysis**, **question_1_score**, **question_2_analysis**, **question_2_score**, **question_3_analysis**, **question_3_score** — filled at session end (LLM results).
- **pitch_variance_avg** (FLOAT, optional) — average from real-time stream.

---

## API

### 1. Get user metric questions

- **GET** `/user/metric-questions` (auth required)
- **Response:** `{ "metric_question_1": "", "metric_question_2": "", "metric_question_3": "", "pitch_variance_ideal": null }`

### 2. Update user metric questions

- **PATCH** `/user/metric-questions`
- **Body:** `{ "metric_question_1": "...", "metric_question_2": "...", "metric_question_3": "...", "pitch_variance_ideal": 0.5 }` (all optional)
- **Response:** Updated object.

### 3. Session start

- On **POST /v2/homework/session/start**, the backend copies the current user’s **metric_question_1**, **metric_question_2**, **metric_question_3** into the new session as **session_metric_question_1/2/3**.

### 4. Session end (post-recording)

- When the user submits **POST /v2/homework/session/:id/post-answers**:
  1. Transcript is taken from recording_2.
  2. Backend loads **session_metric_question_1**, **2**, **3** for that session.
  3. For each non-empty question, it calls **analyze_custom_questions(transcript, [q1, q2, q3])** (LLM), then stores **question_1_analysis**, **question_1_score**, etc.
  4. Response includes: **report_text**, **performance_score_end**, **performance_metrics**, and **question_1_analysis**, **question_1_score**, **question_2_analysis**, **question_2_score**, **question_3_analysis**, **question_3_score**.

### 5. Real-time metrics chunk

- **POST** `/v2/homework/session/:sessionId/recording-metrics-chunk`
- Response includes **pitch_variance** (0–1) in addition to **pause_score**, **voiced_ratio**, **pause_detected**. See **REALTIME-METRICS-CONTRACT.md**.

---

## LLM: analyze_custom_questions(transcript, questions[])

- **Input:** Full transcript (string), array of 3 question strings (empty allowed).
- **Per non-empty question:** Prompt asks for a short analysis and a score 0–10; response parsed as JSON `{"analysis": "...", "score": N}`.
- **Output:** List of 3 items `{ "analysis": str, "score": float }` (empty question → `{"analysis": "", "score": 0}`).

---

## Migration

Run **`migrations/v2_pitch_variance_and_custom_metrics.sql`** to add:

- **v2_student_overrides:** metric_question_1, metric_question_2, metric_question_3, pitch_variance_ideal
- **v2_sessions:** session_metric_question_1/2/3, question_1_analysis, question_1_score, question_2_analysis, question_2_score, question_3_analysis, question_3_score, pitch_variance_avg

---

## Checklist

- [x] DB: user has metric_question_1, 2, 3; session has question_1_analysis, question_1_score, etc.
- [x] GET and PATCH for the three custom questions (under /user).
- [x] On session start: snapshot 3 questions into session.
- [x] On session end (post-answers): run analyze_custom_questions(transcript, [q1,q2,q3]), store and return the 6 result fields.
- [x] Real-time response includes pitch_variance.
