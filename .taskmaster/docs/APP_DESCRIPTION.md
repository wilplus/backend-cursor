# Homework / Speaking Coach — single source of truth

**Taskmaster is the only source of truth for this app.** All behavior, contracts, and implementation guidance are defined here. There are no other description or how-to docs; only this file and code (migrations, BFF reference routes) remain.

---

## 1. What the app is

- **Product:** Student homework flow for speaking practice. A student completes one **session** (attempt) in a fixed sequence: warm-up recording → 3 self-rating questions (metric answers) → final task recording → reflective post-questions → final report with score.
- **Users:** Students (Supabase Auth). Admin/coach features exist in separate flows; admin edits affect **next session only** (no retroactive rescores).
- **This repo:** Backend (Flask) and this doc. Frontend and BFF live in a separate app (e.g. Next.js).
- **Deployment:** Backend behind configurable base URL; audio in **Supabase Storage** (bucket `audio_recordings`); all other data in **Supabase (PostgreSQL)**.

---

## 2. What is missing (open / not specified / not in MVP)

- **score_transcription (task_execution_score):** Not in MVP. No LLM task-adherence score; no weighted final score (e.g. 0.65×metrics + 0.35×AI). When added: define storage and formula; never use neutral defaults on failure.
- **Warm-up selection algorithm:** Selection exists (e.g. anti-repetition last 3 finished sessions, difficulty vs last_score, tags/weakness). Exact prioritization and tie-break may still evolve; document in backend when locked.
- **Recording_1 duration gate:** Not locked (unlike recording_2’s 60–300 s). If added, define min/max and 422 behavior.
- **Full transcript in GET status:** MVP does not return full transcript in status; use **GET /v2/recordings/{id}** for transcript. Optional later: transcript_preview in status or dedicated endpoint.
- **Focus task snapshots on session:** Optional columns `selected_task_title_snapshot`, `selected_task_prompt_snapshot` improve determinism if admin edits tasks; add via migration when needed.
- **Idempotency-Key header:** Optional; not required. State-based idempotency (return existing when already past step) is the contract.
- **Pitch variance / pronunciation scoring:** Not part of locked MVP unless already in code.
- **Multi-language, embeddings, Claude:** Explicit non-goals for MVP.

---

## 3. Core flow (student)

1. **Start session** → backend selects and snapshots warm-up task + 3 pre-questions (session_metric_question_1/2/3).
2. **Recording_1 (warm-up)** → student records; backend transcribes, scores with **3 metrics** (strength, pace, fillers), computes **score_1**, stores context_short, selects focus task, returns task block.
3. **Metric answers** → student answers 3 questions (keywords, emotion, CTA); backend persists answers, generates and persists **final_task_text** (OpenAI).
4. **Recording_2 (main)** → must be **1–5 minutes**; backend transcribes, scores with **5 metrics**, computes **score_2** and **performance_score_end**; optionally re-runs metrics after post-answers with real emotion/keywords.
5. **Post-answers** → student answers all configured post-questions; backend saves answers, recomputes metrics if needed, generates **report** (OpenAI), appends to context_long_entries, sets status to **completed**. No separate /report endpoint.
6. **Report** → student sees report (session.context_long) and score (performance_score_end).

---

## 4. Entities & data model

- **v2_sessions:** One row per attempt. Holds: user_id, **status** (only source of truth for step), warm_up_task_id, warm_up_task_text, session_metric_question_1/2/3, recording_1_id, recording_2_id, context_short, selected_task_id, metric_answers (answer_1/2/3), final_task_text, post_question_ids, post_answers (JSONB), context_long, context_long_entries, performance_score_1, performance_score_2, performance_score_end, report_id.
- **recordings:** Transcript, WPM, fillers, performance_score_v2, performance_metrics_v2 (5-metric breakdown for recording_2 only).
- **v2_reports:** Report text linked by session.report_id.
- **v2_warm_up_tasks, v2_metric_questions, v2_student_post_recording_questions:** Config and per-student questions.

---

## 5. Status / state machine

**Exactly 5 values:** `warm_up` | `task_block` | `final_task_ready` | `post_questions` | `completed`.

- **warm_up** — after start; recording_1 not yet submitted.
- **task_block** — after recording_1; task block (context_short + focus + 3 questions) available; waiting for metric answers.
- **final_task_ready** — after metric-answers; final_task_text available; waiting for recording_2.
- **post_questions** — after recording_2; waiting for post-answers.
- **completed** — after post-answers; report generated.

**Active session:** Only sessions with status in `('warm_up','task_block','final_task_ready','post_questions')`. **Completed sessions are not returned** as the active session. GET status returns the single active session or `has_active_session: false`; next load then uses POST start for a **new** attempt.

---

## 6. Homework flow (steps) — detailed

| Step | Name           | Student action              | Backend status     | Main APIs |
|------|----------------|-----------------------------|--------------------|-----------|
| 0    | No session     | Clicks "Start"              | —                  | GET status, POST start |
| 1    | Warm-up        | Records warm-up; sees wheel | `warm_up`          | GET status, recording-upload-url (rec "1"), Storage upload, POST recording-1, POST recording-metrics-chunk (wheel) |
| 2    | Metric answers | Answers 3 questions         | `task_block`       | GET status, GET task-block (optional), POST metric-answers |
| 3    | Final task     | Records final task; wheel   | `final_task_ready` | GET status, recording-upload-url (rec "2"), upload, POST recording-2, POST recording-metrics-chunk |
| 4    | Post-questions | Answers reflective Qs       | `post_questions`   | GET status, GET questions, POST post-answers |
| 5    | Report         | Views report and score      | `completed`        | GET status (report from session.context_long, score from performance_score_end) |

- **Source of truth for step:** **GET session/status** → **session.status** only. Frontend must derive step from this and **overwrite** local state on every successful status response. No overriding from URL or cache.
- **After every step-advancing action** (recording-1, metric-answers, recording-2, post-answers), frontend calls **GET session/status** and applies the response.
- **Recording-upload-url:** Call with recording **"1"** only when step is 1; with **"2"** only when step is 3.

---

## 7. GET session/status — response shape

- **Always 200** unless server error (500).
- **No active session:** `{ "has_active_session": false, "session": null }`. Optional `session_id` omitted.
- **Active session:** `{ "has_active_session": true, "session_id": "<uuid>", "session": <raw v2_sessions row>, "warm_up_task": { "id": "<uuid>", "text": "..." } }`.
- **session** is the full `v2_sessions` row (snake_case). It does **not** include a shaped `task_block` object or a `final_task` object or a questions list. It includes: id, user_id, status, warm_up_task_id, warm_up_task_text, session_metric_question_1, session_metric_question_2, session_metric_question_3, recording_1_id, context_short, performance_score_1, selected_task_id, metric_answers, final_task_text, recording_2_id, performance_score_2, post_question_ids, context_long, context_long_entries, performance_score_end, post_answers, report_id, etc.

**Frontend mapping (minimal):**

- sessionId = `res.session_id ?? res.session?.id ?? null`
- status = `res.session?.status ?? null`
- step = from status: warm_up→1, task_block→2, final_task_ready→3, post_questions→4, completed→5
- warmUpText = `res.warm_up_task?.text ?? res.session?.warm_up_task_text ?? ""`
- Step 2 questions: build task block from `res.session?.session_metric_question_1`, `session_metric_question_2`, `session_metric_question_3` (or GET task-block if backend exposes it and block still missing)
- finalTaskText = `res.session?.final_task_text ?? ""`
- reportText = `res.session?.context_long ?? ""`
- performanceScoreEnd = `res.session?.performance_score_end ?? null`

Backend uses **snake_case** everywhere; frontend normalizes once (e.g. in applyStatusToState) and uses camelCase internally. The status response may have **no session** (`has_active_session: false`, `session: null`). Frontend must either call applyStatusToState only when `session != null`, or type applyStatusToState to accept `HomeworkSessionStatus | null` and clear state (show Start) when null.

---

## 8. Recording requirements

- **Recording_2:** Must be **60–300 seconds**. Backend returns **422 RECORDING_DURATION_OUT_OF_RANGE** if outside. Pace (WPM) is transcript-based: word_count / (duration_seconds/60).
- **Upload:** Backend returns **bucket** (e.g. `audio_recordings`) and **storage_path** (e.g. `{user_id}/{session_id}/{uuid}.webm`). Frontend must use that bucket and path; RLS allows INSERT (and UPDATE if upsert) for authenticated user under that path.

---

## 9. Scoring (MVP)

- **score_1 (warm-up):** 3 metrics only — strength, pace, fillers. `performance_score_1 = avg(3)`. Stored on session.
- **score_2 (main):** 5 metrics — strength, pace, fillers, emotion_achieved, keywords_used. `performance_score_2 = avg(5)`. Stored on session and on recording_2 row as performance_metrics_v2 / performance_score_v2. On recording_2 upload, first run may use placeholders for emotion/keywords; after post-answers, re-run with real answers and update session + recording so they stay in sync.
- **Final score:** `performance_score_end = (performance_score_1 + performance_score_2) / 2` (clamped 0..1). No score_transcription in MVP.
- **metric_answers:** Stored as **answer_1**, **answer_2**, **answer_3** (API may accept aliases; map to canonical before storing).

---

## 10. Warm-up and focus task selection

- **Warm-up:** At session start, backend selects one warm-up task (e.g. from v2_warm_up_tasks for user). If user has **0** warm-up tasks → **422 NO_WARMUP_CONFIGURED**; do not create a session. Selection may use last finished session score, anti-repetition (last 3 finished sessions), difficulty (max_performance_score vs last score), and optional tags/weakness. Exact algorithm is in backend code.
- **Focus task:** After score_1, backend selects from v2_tasks. Eligible: `min_task_score <= performance_score_1`. If none eligible, pick task with **smallest** min_task_score (easiest). Random among ties. Session stores selected_task_id.

---

## 11. Key contracts

- **Session identity:** session_id (top-level) and session.id (nested); same value. No session-scoped calls without valid sessionId.
- **Status → step:** Only from session.status; map to step 1–5 as above.
- **No task_block / final_task / report_text in status:** Use session.session_metric_question_1/2/3, session.final_task_text, session.context_long.
- **Step 4 questions:** Status has only post_question_ids; frontend must GET questions when step 4 and questions empty.
- **Idempotency:** If session already past a step, return **200** with existing data (no duplicate recording or report). Start returns existing active session if one exists.
- **One report per session:** At most one report per session (handler or DB guard). No duplicate reports on double submit.
- **GET /v2/recordings/{id}:** Canonical way to fetch a recording (including transcription_text). Owner-only; **404** for not found or not allowed (same for privacy).

---

## 12. Wheel (real-time measurement)

- **When:** Steps **1** and **3** only, while recorder is active. Start pipeline when entering step 1 or 3; stop when leaving or stopping recording.
- **API:** POST `/v2/homework/session/:sessionId/recording-metrics-chunk` (via BFF, same-origin). Auth required. Session status must be in warm_up, task_block, final_task_ready, post_questions.
- **Request:** Body = raw PCM16 mono; headers X-Sample-Rate (default 16000), X-Seq, X-T-Ms, optional X-Debug.
- **Response (200):** seq, t_ms, **pause_score** (0–1, primary for wheel), voiced_ratio, pause_detected, pitch_variance. Use **pause_score** to drive the wheel.
- **Backend config:** 16 kHz, 20 ms frames, frame silent if RMS < -45 dB; pause event ≥ 200 ms; 10 s rolling window; ideal band pause_ratio ≈ 0.20, pauses_per_min ≈ 11; silence gating when voiced_ratio < 0.15 → pause_score = 1. Rate limit **120 requests / 60 s** per (user_id, session_id).
- **Frontend/BFF:** POST to same-origin BFF only (never localhost in production). BFF forwards Authorization and body/headers. On 200, update wheel from response.pause_score.

**Why the wheel might have worked before and then stopped:** (1) **URL change** — frontend must POST to the **same-origin BFF** (e.g. `/api/homework/session/[sessionId]/recording-metrics-chunk`), not directly to the backend; if it was switched to the backend URL, CORS or wrong origin can block. (2) **Auth** — BFF must send `Authorization: Bearer <token>`; if token is missing or `getV2AccessToken()` returns null, backend returns 401. (3) **Session / step** — backend returns **404** if session not found (wrong or stale session_id) and **409** if session status is not in warm_up, task_block, final_task_ready, post_questions (e.g. completed); ensure wheel only runs in steps 1 and 3 and uses the current session_id from GET status. (4) **Next.js 15** — if the app was upgraded to Next 15, the BFF route must `await params` to get sessionId (see reference route). (5) **Rate limit** — 120 requests per 60 s per (user_id, session_id); if exceeded, backend returns 429.

---

## 13. Storage (Supabase)

- **Bucket:** `audio_recordings`. Path: `{user_id}/{session_id}/{uuid}.webm`. Frontend uses bucket and path from recording-upload-url response.
- **RLS:** Allow INSERT (and UPDATE if using upsert) for authenticated users where the first path segment equals auth.uid(). Example policy names: `audio_recordings_insert_own_folder`, `audio_recordings_update_own_folder`. If 403 on upload, path must match logged-in user id and policies must exist.

---

## 14. APIs (student homework)

| Method | Path | Purpose |
|--------|------|---------|
| GET | /v2/homework/session/status | Resume; returns has_active_session, session_id?, session?, warm_up_task? |
| POST | /v2/homework/session/start | Start or resume session; 422 if no warmups |
| POST | /v2/homework/session/:id/recording-upload-url | Get bucket + storage_path for recording "1" or "2" |
| POST | /v2/homework/session/:id/recording-1 | Upload warm-up; returns score_1, task block (context_short, focus, questions) |
| POST | /v2/homework/session/:id/metric-answers | Submit 3 answers; generates final_task_text; status → final_task_ready |
| POST | /v2/homework/session/:id/recording-2 | Upload main (60–300 s); returns score_2, performance_score_end; status → post_questions |
| POST | /v2/homework/session/:id/post-answers | Submit post-answers; generates report; status → completed |
| GET | /v2/homework/session/:id/questions | Get post-questions list (when step 4) |
| GET | /v2/homework/session/:id/task-block | Optional; get shaped task block if backend exposes it |
| POST | /v2/homework/session/:id/recording-metrics-chunk | Wheel: PCM in, pause_score out |
| GET | /v2/recordings/:id | Get recording (incl. transcription_text); owner-only; 404 if not found/not allowed |

All require auth. BFF must forward Authorization and relevant headers/body to backend.

---

## 15. What can go wrong

- **Wrong step / 409:** Frontend not deriving step from session.status only, or not overwriting on every GET status. Fix: status-first; overwrite; when has_active_session false, clear state and require POST start.
- **401 / 404 on session:** BFF not forwarding Authorization for a homework route. Fix: every BFF route must send Authorization: Bearer <token>.
- **Wheel not working:** Frontend posting to localhost instead of same-origin BFF; or BFF not forwarding auth; or frontend not updating from response.pause_score. Fix: same-origin BFF only; forward auth; use pause_score.
- **Blank screens (step 2/4/5):** Frontend expecting task_block object, final_task object, report_text, or questions in status. Fix: use session.session_metric_question_1/2/3, session.final_task_text, session.context_long; GET questions when step 4 and empty.
- **Post-answers not saved:** v2_sessions missing post_answers column. Fix: add column (e.g. `ALTER TABLE v2_sessions ADD COLUMN IF NOT EXISTS post_answers JSONB`).
- **403 on upload:** Wrong bucket or path; or Storage RLS missing. Fix: use bucket from API; path must start with user_id; add INSERT (and UPDATE) policies for authenticated user.
- **Recording_2 rejected:** Duration outside 60–300 s. Fix: enforce client-side or show 422 message.

---

## 16. Implementation checklist

- **Frontend:** applyStatusToState with mapping above; derive step only from session.status; overwrite on every GET status; when has_active_session false, clear state and show Start; refetch GET status after recording-1, metric-answers, recording-2, post-answers; call recording-upload-url only for rec "1" on step 1 and rec "2" on step 3; build task block from session_metric_question_1/2/3 or GET task-block if needed; GET questions when step 4 and empty; use bucket from API; wheel pipeline to same-origin BFF only; update wheel from response.pause_score.
- **BFF:** Proxy all homework endpoints; forward Authorization and body/headers (e.g. X-Sample-Rate, X-Seq, X-T-Ms for recording-metrics-chunk). Next 15: await params for sessionId.
- **Backend:** Already implements flow; ensure GET status excludes completed from "active"; ensure recording_2 duration 60–300 s; ensure one report per session; ensure post_answers column exists.

---

## 17. Code reference (no other docs)

- **Migrations:** Repo root `migrations/` — add only missing columns; do not rename. Run per environment.
- **BFF reference routes:** `docs/homework-bff-routes/` — copy/adapt into frontend app (status, start, recording-upload-url, recording-1, recording-2, recording-metrics-chunk, task-block, metric-answers, questions, post-answers). **Wheel must call BFF URL, not backend:** see `.taskmaster/docs/WHEEL-USE-BFF-URL.md`.

---

## 18. Database: required columns and migrations

**v2_sessions** must have at least these columns for the homework flow: id, user_id, status, created_at, context_short, context_long, context_long_entries, selected_task_id, recording_1_id, recording_2_id, performance_score_1, performance_score_2, performance_score_end, session_metric_question_1/2/3, metric_answers, final_task_text, post_question_ids, post_answers, warm_up_task_id, warm_up_task_text, report_id, question_1/2/3_analysis, question_1/2/3_score, pitch_variance_avg.

- **If post_answers is missing:** POST post-answers will fail or silently not persist. Run **`migrations/v2_sessions_add_post_answers.sql`** in Supabase SQL Editor (idempotent).
- **If selected_task_id is FK to v2_tasks only:** When the chosen task is a focus task (v2_focus_tasks), inserts/updates can fail. Run **`migrations/allow_focus_task_id_in_selected_task_id.sql`** to drop the FK so both v2_tasks and v2_focus_tasks ids are allowed.
- **Full schema:** Use **`supabase-schema-willab-complete.sql`** for a full idempotent schema (creates v2_sessions with base columns, then a DO block adds all optional columns). Ensure the DO block has run so all columns above exist.

**Verify:** In Supabase SQL Editor, run:  
`SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' ORDER BY ordinal_position;`  
Check that `post_answers` (and any other column you need) is in the list.

**End of taskmaster.** This is the only source of truth for the app.
