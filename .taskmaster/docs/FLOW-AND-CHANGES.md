# Backend flow and what changed

This document is the **taskmaster record** of what was in place before the post-answers / resume / “finish without post-questions” work, what is in place now, and how the backend flow behaves end-to-end.

---

## 1. What was in place (before)

- **Post-answers:** Backend required `session.status === post_questions`. If status was `warm_up` (e.g. stale DB or frontend ahead of backend), POST post-answers returned **409 INVALID_SESSION_STATE** with no recovery.
- **After post-answers:** Frontend called GET session/status and applied the response. **Completed** sessions are not returned by GET status (`active` = warm_up, task_block, final_task_ready, post_questions only), so the client could end up with no session / step 0 instead of showing the report.
- **Step 4 with no questions:** Student could click “See my report” to send `answers: []`; backend already accepted empty answers. There was no automatic “finish without post-questions” (user had to click).
- **409 on post-answers:** Error message was generic (“Session must be in post_questions for post-answers”); no hint for the user (e.g. “Complete the main recording first”).
- **Recording_2 duration:** Backend used transcript duration for the 60–300 s check after overwriting with transcript; client sending ~58 s could get 422 when the UI showed 60 s.
- **recording-metrics-chunk:** No BFF route; legacy/cached clients that still called this URL got 404 and showed many failed requests in the Network tab.

---

## 2. What is in place now

### Backend

- **Post-answers recovery:** If `session.status` is `warm_up`, `task_block`, or `final_task_ready` but the session has **recording_2_id**, the backend treats the session as logically past step 3: it **updates status to `post_questions`** and then processes post-answers (saves answers, generates report, sets **completed**). So “lesson already started, just fetch and let it finish” works even when status was out of sync.
- **409 when recovery does not apply:** If status is wrong and there is **no** recording_2_id, backend returns **409** with a **hint** in the response body, e.g.  
  `"hint": "Complete the main recording (step 3) first, then return to reflective questions."`
- **Empty post-answers:** Backend explicitly allows **empty `answers`** (e.g. no reflective questions configured). Report is still generated; `post_answers` is stored as provided.
- **post_question_ids fallback:** If the session has no `post_question_ids` (e.g. GET questions was never called because status was wrong), backend derives question ids from the submitted **answers** so emotion_achieved and persistence still work.
- **Recording_2 duration:** Range check uses **client-supplied** `duration_seconds` (JSON path). Backend accepts **≥ 58 s** (2 s tolerance below 60) to avoid 422 when the UI shows 60 s but the client sends slightly less. Transcript duration is still used for WPM/scoring after the range check.
- **Idempotency unchanged:** Already completed → POST post-answers returns 200 with existing report. Recording-2 / metric-answers idempotency as before.

### BFF (frontend app)

- **recording-metrics-chunk:** A **no-op BFF route** exists at  
  `GET/POST /api/homework/session/[sessionId]/recording-metrics-chunk`.  
  It returns **204 No Content** immediately (no backend call). Legacy or cached clients that still request this URL no longer see failed requests; wheel remains client-side only.

### Frontend

- **After post-answers success:** Frontend **does not** call GET session/status to show the report. It uses the **POST post-answers response body** (`report_text`, `performance_score_end`) and sets step to **5** and report content from that. So the report is always shown correctly even though GET status does not return completed sessions.
- **Step 4 with zero questions:** When step is 4 and **GET questions** returns an empty list, the frontend **auto-submits** POST post-answers with `answers: []` and then shows the report (step 5) from the response. The user can “finish without post-questions” without clicking “See my report.”
- **409 on post-answers:** Frontend parses the backend **hint** and appends it to the error message. On **409 INVALID_SESSION_STATE**, it **refetches GET session/status** and applies the response so the UI step syncs with the backend (e.g. back to step 3 if the main recording was never completed).
- **Ref reset:** The auto-submit-on-zero-questions path is gated by a ref so it runs only once per session; the ref is reset on Start over / Abandon.

---

## 3. How the backend flow looks (explicit)

### Status machine (unchanged)

- **warm_up** → after start; recording_1 not yet submitted.
- **task_block** → after recording_1; waiting for metric answers.
- **final_task_ready** → after metric-answers; waiting for recording_2.
- **post_questions** → after recording_2; waiting for post-answers.
- **completed** → after post-answers; report generated.

**Active** = status in `('warm_up','task_block','final_task_ready','post_questions')`.  
**GET /v2/homework/session/status** returns the current **active** session only; **completed** is not active, so GET status never returns a completed session.

### Step-by-step backend behavior

1. **GET status**  
   Returns active session (if any) with `session_id`, `session` (raw row), `warm_up_task`. Never creates a session.

2. **POST start**  
   Creates or returns existing active session; snapshots warm-up; status = **warm_up**.

3. **POST recording-upload-url**  
   Body `{ "recording": "1" | "2" }`. Requires status **warm_up** for "1", **final_task_ready** for "2". Returns bucket + storage_path.

4. **POST recording-1**  
   Requires status **warm_up**. On success: creates recording, updates session (recording_1_id, performance_score_1, context_short, selected_task_id, **status = task_block**). Returns recording_id, performance_score_1, task_block.

5. **POST metric-answers**  
   Requires status **task_block** (or idempotent 200 if already final_task_ready with final_task_text). On success: stores metric_answers, generates final_task_text, **status = final_task_ready**.

6. **POST recording-2**  
   Requires status **final_task_ready** (or idempotent 200 if already post_questions/completed with recording_2_id). Validates **client** duration: **58–300 s** (tolerance below 60). On success: creates recording_2, updates session (recording_2_id, performance_score_2, **status = post_questions**). Returns recording_id, performance_score_2.

7. **GET questions**  
   Requires status **post_questions** or **completed**. Returns list of post-recording questions; may store post_question_ids on session.

8. **POST post-answers**  
   - **Idempotent:** If status is **completed**, returns 200 with existing report (report_text, performance_score_end, etc.).
   - **Recovery:** If status is **warm_up**, **task_block**, or **final_task_ready** and session has **recording_2_id**, backend sets **status = post_questions** and then continues.
   - **Normal:** If status is **post_questions**, processes answers (may be empty), recomputes metrics if needed, generates report, writes to session (post_answers, context_long, performance_score_end, report_id, etc.), sets **status = completed**.
   - **409:** If status is wrong and there is **no** recording_2_id, returns 409 with `code: INVALID_SESSION_STATE`, `error`, `status`, and optional **hint** (e.g. “Complete the main recording (step 3) first…”).
   - Response body always includes **report_text**, **performance_score_end** (and optionally question analyses/scores). Frontend uses this response to show the report; it does **not** rely on GET status after post-answers.

9. **GET status (after post-answers)**  
   Session is now **completed**, so it is **not** in the active set. GET status returns `has_active_session: false`, `session: null`. Frontend uses this to show “Start” for the next session; the report for the just-finished session was already shown from the post-answers response.

### Summary table (backend)

| Step | Endpoint / action        | Required status       | On success: new status   |
|------|--------------------------|------------------------|---------------------------|
| 0→1  | POST start               | —                      | warm_up                   |
| 1    | POST recording-1         | warm_up                | task_block                |
| 2    | POST metric-answers      | task_block             | final_task_ready          |
| 3    | POST recording-2        | final_task_ready       | post_questions            |
| 4    | POST post-answers        | post_questions (or recovery) | completed        |

**Recovery:** POST post-answers accepts status **warm_up** / **task_block** / **final_task_ready** when **recording_2_id** is set; it then sets status to **post_questions** and processes the request.

---

## 4. Where this is reflected in the taskmaster

- **APP_DESCRIPTION.md:** §6 (step 5 report from post-answers response; “after post-answers” no longer says “frontend calls GET status” for the report), §8 (recording_2 duration 58–300 s, client duration), §11/§15 (post-answers recovery, empty answers, 409 hint), §14 (optional BFF recording-metrics-chunk no-op), §16 (frontend: use post-answers response for report; step 4 with 0 questions auto-submit; on 409 refetch status).
- **AUDIT-AND-BFF-GLOW.md:** Mutations + refetch updated to note “after post-answers, frontend uses response for report”; BFF list can mention recording-metrics-chunk no-op for legacy clients.
- **This file (FLOW-AND-CHANGES.md):** Single place for “what changed” and the explicit backend flow.

**End of FLOW-AND-CHANGES.md**
