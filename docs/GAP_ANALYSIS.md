# Gap Analysis: Inconsistencies, Missing Pieces, and Broken Wiring

**Date:** 2026-04-08

---

## Part A — Route Mismatches (Frontend Expects → Backend Doesn't Serve)

### ~~1. Per-Student Copilot CRUD~~ — RESOLVED

All per-student copilot endpoints **DO exist** on the backend (found at lines 2854-2997):
- `GET/PUT /v2/admin/copilot/students/:id/drafts` — list and update drafts
- `GET/PUT /v2/admin/copilot/students/:id/audit` — insight audit with good_as_is / corrected_insight
- `POST /v2/admin/copilot/students/:id/approve` — sets state to Ready
- `POST /v2/admin/copilot/students/:id/send` — sends email and marks Sent

The audit endpoint also writes back to v2_sessions (`is_insight_audited`, `coach_corrected_insight`).

**If the Training Studio is still broken, the issue is BFF proxy routing, not missing backend endpoints.**

---

### ~~2. Copilot Cohort Students~~ — RESOLVED

Backend **DOES have** `GET /v2/admin/copilot/cohorts/:cohortId/students` (line 2738).
Accepts cohortId as `"profile::stage"` format (e.g. `"The Stressor::2"`).
Returns full student list with draft counts, profile data, and score_for_display.
Also backfills students from Auth who have no draft row yet (shown as state "Draft").

**If cohort drill-down is broken, check: (a) BFF proxy path, (b) cohortId format matching.**

---

### 3. Focus Tasks: Frontend Calls, Backend Returns Empty

Frontend's student detail page still calls:
- `getFocusTasks(id)` → `GET /api/admin/students/:id/task-focus`
- `getFocusTaskPool()` → focus pool endpoint

Backend returns `{"task_focus": [], "focus_tasks": []}` (stub routes for backward compatibility). The `POST .../create-pool-and-assign` variant returns **410 Gone**.

**Result:** Focus task section in student detail is always empty. The Training Studio task swap modal also references focus tasks indirectly. No crash, but dead UI elements.

**Fix needed:** Frontend must remove all focus task references. Replace with warm-up tasks throughout.

---

### 4. Annotation Chips: Backend Serves, Frontend Doesn't Call

Backend has `GET /v2/admin/copilot/annotation-chips` → returns static chip list:
```json
["misread_context", "overly_generic", "missed_specific_issue", "tone_mismatch", 
 "profile_incorrect", "stage_incorrect"]
```

`db.create_admin_annotation_event()` exists and is wired to 3 endpoints (insight-audit, profile-override, stage-override).

**But** the Training Studio does not call `getCopilotAnnotationChips` and does not include reason chips in its draft save payloads.

**Result:** Every admin correction that passes through Training Studio loses its DPO annotation. The `admin_annotation_events` table stays empty from Training Studio actions. Only the old admin panel's insight-audit path writes annotations.

**Fix needed:** Frontend Training Studio must fetch chips and include `reason_chip` in all correction payloads.

---

## Part B — Data Model Gaps (Tables/Columns That Exist But Aren't Used)

### 5. `acoustic_labels` Table: Created, Never Touched

The migration created the table with all columns (clip_source, recording_id, start_ms, end_ms, label_stress, label_charisma, confidence, labeled_by).

**No db.py functions read or write to it.** No route handler references it. The Acoustic Dojo's `next-clips` endpoint returns pending send drafts, not recording clips.

**Result:** The Acoustic Dojo tab has zero real acoustic data to show. "No clips available" is the permanent state.

**Fix needed:**
- Add `db.create_acoustic_label()`, `db.list_acoustic_clips_for_labeling()`, `db.get_acoustic_label_stats()`
- Add clip generation: slice recordings into 10s segments and insert into a clip queue
- Route: `POST /v2/admin/acoustic-dojo/labels` → write to `acoustic_labels`
- Route: `GET /v2/admin/acoustic-dojo/next-clips` → read from clip queue, NOT from send drafts

---

### 6. `admin_annotation_events` Table: Partially Wired

The table exists. `create_admin_annotation_event()` is called by exactly 3 routes:
- `PATCH .../insight-audit`
- `PATCH .../profile-classification`
- `PATCH .../stage-override`

**Not called by:**
- `PATCH .../sessions/:sid` (coach_override_score, grade, comment — no annotation event)
- Any Training Studio draft save/approve flow
- Any task swap action
- Any message edit action

**Result:** ~70% of admin corrections generate no DPO training signal. The annotation table captures insight/profile/stage corrections only.

**Fix needed:** Wire `create_admin_annotation_event()` into every PATCH endpoint that accepts a correction:
- `coach_override_score` → annotation with `section_type: "post_hoc_audit", field_name: "score"`
- `report_grade` → annotation with `section_type: "pre_hoc_approval", field_name: "grade"`
- `report_comment` → annotation with `section_type: "pre_hoc_approval", field_name: "comment"`
- Draft task edit → annotation with `section_type: "pre_hoc_approval", field_name: "task"`
- Draft message edit → annotation with `section_type: "pre_hoc_approval", field_name: "message"`

---

### 7. `coach_corrected_insight` + `is_insight_audited`: Wired But Not in Training Studio

Backend PATCH endpoint exists and works. The old admin panel's HITL cards use it.

**Training Studio** has an audit flow (`updateCopilotStudentAudit`) but it calls a frontend BFF route that proxies to `/v2/admin/copilot/students/:id/audit` — **which doesn't exist on the backend.** The actual backend endpoint is `/v2/admin/students/:id/sessions/:sid/insight-audit`.

**Result:** Training Studio audit button hits a 404. Only the old admin panel can audit insights.

**Fix needed:** Either add a backend alias at `/v2/admin/copilot/students/:id/audit` that proxies to the real insight-audit endpoint, or fix the frontend BFF route to call the correct backend path (needs session_id, not just student_id).

---

### 8. `student_profile` Table: Exists, Computed On-Read Only

`refresh_student_profile_state()` recomputes `behavioral_profile`, `computed_stage`, and `consecutive_below_threshold` every time the admin opens a student profile or the cohorts endpoint is hit.

**Not called during session completion.** The session completion pipeline (`homework_completion.py`) does not trigger `refresh_student_profile_state`.

**Result:** Profile and stage are stale until an admin manually views the student. A student who just completed session 10 might still show Stage 1 in the cohort view if no admin has opened their profile since session 5.

**Fix needed:** Call `refresh_student_profile_state(user_id)` at the end of `_complete_session_from_recording()` in `homework_completion.py`.

---

## Part C — Acoustic Dojo Is Fundamentally Miswired

### 9. `next-clips` Returns Send Drafts, Not Audio Clips

The endpoint `GET /v2/admin/acoustic-dojo/next-clips` calls `db.list_admin_student_send_drafts(status="pending")` and formats them as clips.

**These are homework assignment drafts, not audio segments.** The Dojo is supposed to show 10-second recording snippets for yes/no stress/charisma labeling.

**Result:** The Dojo shows "pending homework drafts" in a swipe UI designed for audio clips. Completely wrong data source.

**Fix needed:** Two separate endpoints:
- `/v2/admin/copilot/next-clips` → pending send drafts (for Copilot Inbox)
- `/v2/admin/acoustic-dojo/next-clips` → recording segments from `acoustic_clips` queue (for Dojo)

Currently they are aliased to the same handler. They must be split.

---

### 10. No Clip Generation Pipeline

Even after fixing the endpoint, there is no process that slices recordings into 10-second labeled segments.

**Needed:**
- A background job after `recording_1_job` that splits the audio into N segments
- An `acoustic_clips` table (or reuse `acoustic_labels` with a clip queue status)
- Priority logic: serve unreviewed clips first, then clips where confidence was low

---

## Part D — Missing Feedback Loops (Endpoints That Should Train AI But Don't)

### 11. `send-assignment` — No Pre-Fill, No Correction Tracking

`POST /v2/admin/students/:id/send-assignment` sends an email with video_url + video_description. The admin types everything from scratch or the frontend Training Studio fills in from a draft.

**Missing:**
- AI pre-fill: No GPT call generates the message/task/video script before the admin sees it
- Correction tracking: If admin edits the AI's draft, no annotation event is created comparing original vs final

**Result:** Every sent assignment is a black hole for the agentic pipeline — it has the final text but no signal about what the AI suggested vs what the admin changed.

**Fix needed:**
- Store `ai_draft_message`, `ai_draft_task`, `ai_draft_video_script` alongside final versions in `admin_student_send_drafts`
- On approve-send, if any field differs from the AI draft, auto-generate an annotation event

---

### 12. `report_grade` + `report_comment` — No AI Pre-Fill, No DPO Signal

Admin manually types grade and comment. No AI suggestion exists.

**Result:** No rejected/chosen pair. The AI never learns what grade Artur would give because there's no AI draft to compare against.

**Fix needed:**
- After session completion, GPT generates a draft grade + comment (stored as `ai_draft_grade`, `ai_draft_comment`)
- When admin saves grade/comment, if different from AI draft → annotation event

---

### 13. Task Selection — No Rejection Signal

When Training Studio's swap modal is used, the admin picks a different task from the pool. The cohort approve-task endpoint stores `master_task_text` but does not record what the AI originally suggested.

**Result:** The recommendation engine can't learn from task swaps because it doesn't know what was rejected.

**Fix needed:** Store `ai_suggested_task_id` + `ai_suggested_task_text` on the draft row. On swap, annotation event: `rejected = ai_suggested, chosen = coach_pick`.

---

### 14. `coach_override_score` — No Annotation Event

The PATCH session endpoint accepts `coach_override_score` and `coach_override_justification` but does NOT call `create_admin_annotation_event`.

**Result:** Score overrides are stored but don't appear in the DPO training export table.

**Fix needed:** Add `create_admin_annotation_event(section_type="post_hoc_audit", field_name="score", ai_original_text=str(ai_task_score), coach_final_text=str(coach_override_score))` to the PATCH handler.

---

## Part E — Frontend Dead Code and Stale References

### 15. Post-Recording Questions UI — Hidden But Loading

The student detail page wraps the post-recording questions UI in `{false && (...)}`. The load call `getStudentPostRecordingQuestions(id)` still fires on mount.

**Result:** Unnecessary API call on every student page load. Dead code.

**Fix needed:** Remove the `getStudentPostRecordingQuestions` call and the hidden JSX block.

---

### 16. Metrics Section — Hidden But Loading

Same pattern: `getUserMetricQuestions` fires but the MetricsSection component is wrapped in `{false && (...)}`.

**Fix needed:** Remove both.

---

### 17. Training Studio Local-Only State That Should Persist

| State | Current | Should Be |
|---|---|---|
| `selectedArchetype` (learning profile) | React state only | Saved via profile-classification endpoint |
| `"82% confidence"` | Static string in JSX | Read from `behavioral_profile_justification` or a confidence score |
| `"Review — Session 12"` / `"Plan — Session 13"` | Static labels | Dynamically read from session data |
| `queueRecency` | Mock strings by index | Computed from session `completed_at` |
| `metadata.reviewer_score` | Sent on draft PUT | Backend may not store it (depends on `draft_payload` JSONB structure) |

---

## Part F — The Score Inconsistency

### 18. `score_for_display` Computed on Read, Never Stored

Both `routes/homework.py` and `routes/v2_routes.py` compute `score_for_display` on every request using the triple sanity check. But `student_profile_service.py` reads `score_for_display` from the session row:

```python
.select("id, score, score_for_display, score_components, completed_at, created_at")
```

If `score_for_display` is never written to the DB, this column is always null, and the EMA used for stage calculation falls back to raw `score` — which is the old Layer 1 score, not the 50/50 blend.

**Result:** Stage computation uses raw `score` (0–1 float from recording job) instead of the actual display score the student sees. A student could see 74% on their report but the stage engine sees 28%.

**Fix needed:** Either:
- Persist `score_for_display` to the session row at completion time, OR
- Have `refresh_student_profile_state` compute it the same way the report endpoints do

---

## Summary: Priority Ranked

| # | Issue | Impact | Effort |
|---|---|---|---|
| 18 | ~~score_for_display never stored → stage uses wrong score~~ | **RESOLVED** — both completion paths now persist score_for_display; run `scripts/backfill_score_for_display.py` for historical rows | Done |
| 8 | Profile not refreshed on session completion | **High** — cohorts always stale | Small |
| 1 | Per-student copilot CRUD missing on backend | **High** — Training Studio broken | Medium |
| 2 | Per-cohort student list missing | **High** — cohort drill-down broken | Small |
| 9 | Dojo next-clips returns drafts not audio | **High** — Dojo completely broken | Medium |
| 7 | Insight audit BFF route → 404 | **High** — audit button broken | Small |
| 6 | Annotation events missing on most corrections | **High** — DPO data loss | Medium |
| 14 | coach_override_score → no annotation event | **Medium** — score DPO loss | Small |
| 11 | send-assignment no AI pre-fill / correction tracking | **Medium** — agentic pipeline blind | Medium |
| 12 | grade/comment no AI pre-fill | **Medium** — no draft to compare | Medium |
| 13 | Task swap no rejection signal | **Medium** — recommendation can't learn | Small |
| 10 | No clip generation pipeline | **Medium** — Dojo needs data | Large |
| 3 | Focus task dead references in frontend | **Low** — no crash, just empty | Small |
| 4 | Annotation chips served but not called | **Low** — chips exist, frontend ignores | Small |
| 5 | acoustic_labels table unused | **Low** — blocked by #10 | Blocked |
| 15-16 | Hidden UI still fires API calls | **Low** — wasted requests | Small |
| 17 | Training Studio local state not persisted | **Low** — cosmetic gaps | Small |
