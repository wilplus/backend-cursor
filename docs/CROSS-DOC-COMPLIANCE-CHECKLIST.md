# Cross-doc compliance checklist (handoff to engineering)

Use this list to verify implementation matches the locked contract and related docs. References: **CONTRACT-HOMEWORK-FLOW.md**, **DATA-MAPPING-SCORING-TO-DB.md**, **OPENAPI-V2-STATUS.yaml**, **OPENAPI-V2-WRITE-ENDPOINTS.yaml**, **API-GET-STATUS-RESPONSE-SHAPE.md**, **MIGRATION-PLAN-MINIMAL-DIFF.md**.

---

1. **State transitions**  
   Session status uses exactly 5 values: `warm_up` → `task_block` → `final_task_ready` → `post_questions` → `completed`. No `report_ready` or other intermediate status. After recording_2 upload → `post_questions`; after post-answers submit → `completed`. Report is generated inside post-answers; there is no separate `/report` endpoint.

2. **Compute twice (recording_2)**  
   `performance_score_2` is computed on recording_2 upload with placeholders (`emotion_achieved: false`, `keywords: []`), then recomputed after post-answers when real emotion/keywords are available. Both the recording row and the session row are updated after the re-run.

3. **Sync invariant**  
   After any re-score operation:  
   - `v2_sessions.performance_score_2 == recordings.performance_score_v2` where `recordings.id = v2_sessions.recording_2_id`.  
   - `v2_sessions.performance_score_end == (performance_score_1 + performance_score_2) / 2` (clamped 0..1).  
   See **DATA-MAPPING-SCORING-TO-DB.md**.

4. **Minimal payload write responses**  
   Write endpoints (start, recording-1, metric-answers, recording-2, post-answers) return minimal payloads (e.g. session_id, recording_id, scores, final_task, report_text), **not** the full session row. Frontend uses **GET /v2/homework/session/status** as the source of truth for resume and current state.

5. **No transcripts in GET /status**  
   GET /v2/homework/session/status does **not** return full `transcription_text` or nested recording objects with transcript. Session object contains only v2_sessions columns (e.g. recording_1_id, recording_2_id). See **OPENAPI-V2-STATUS.yaml** and **API-GET-STATUS-RESPONSE-SHAPE.md**.

6. **Session start 422 when no warmups**  
   If the user has no warm-up tasks, POST /session/start returns **422** with `NO_WARMUP_CONFIGURED` and does **not** create a session. No “session created with null warmup” in MVP.

7. **POST /post-answers idempotency**  
   If the session is already `completed`, POST /post-answers returns **200** with existing `report_text`, `performance_score_end`, and question_* fields. It does **not** create a second report row or append to context_long_entries again.

8. **Score and storage mapping**  
   score_1 → `v2_sessions.performance_score_1` (3 metrics only). score_2 → `v2_sessions.performance_score_2` and `recordings.performance_metrics_v2` (recording_2 row). performance_score_end → `v2_sessions.performance_score_end` = (score_1 + score_2) / 2. `recordings.performance_metrics_v2` is populated only for the recording referenced by `v2_sessions.recording_2_id`. See **DATA-MAPPING-SCORING-TO-DB.md**.

9. **Metric answers payload**  
   POST /metric-answers accepts `answer_1`, `answer_2`, `answer_3` (or aliases `metric_answer_1/2/3`). Stored in session as `metric_answers` with keys `answer_1`, `answer_2`, `answer_3`. Transition to `final_task_ready`; `final_task_text` generated and persisted.

10. **Session start HTTP codes**  
    POST /session/start returns **201** when a new session is created and **200** when resuming an existing active session. OpenAPI allows both; backend must do so consistently.

---

*Run through this checklist when implementing or reviewing the homework flow to ensure alignment with the doc set.*
