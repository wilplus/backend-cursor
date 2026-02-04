# V2 homework flow — locked understanding and implementation plan

This document locks the product and technical decisions for the **homework flow** (the flow that **replaces** the current v2 “universal_questions → one recording → post_questions” flow). It aligns with the backend where the backend already supports it and specifies the changes needed where it does not.

---

## Your six decisions (locked)

### 1. task_warm_up: which one the student sees

- **Decision:** There is a **list** of warm-up tasks per student, but the student **only ever sees one**. The **admin decides** which task from that list is “allowed” / shown for the student (e.g. “this is the warm-up for the next run”).
- **Backend alignment:** The backend has a list: `v2_warm_up_tasks` (CRUD per student). It does **not** yet have a way to store “which one is assigned for this student.”  
- **Backend change needed:** Add **`assigned_warm_up_task_id`** (UUID, nullable) to **`v2_student_overrides`**. When the student starts a homework run, the backend returns the warm-up task with that id (if set); if not set, fallback can be “first by `order_index`” or require admin to assign. Admin UI: on the student profile, in the Warm-up tasks section, allow selecting one task as “assigned” (e.g. radio or dropdown).

### 2. focus_task eligibility (min_score vs performance_score_1)

- **Decision:** Focus tasks are eligible when their **min_task_score** is **≤ performance_score_1**. Example: if performance_score_1 is **0.1**, show only tasks whose min label is in that range (e.g. 0.05, 0.1), **not** tasks with min 0.2 or higher. So: **filter tasks where `min_task_score <= performance_score_1`**; if several match, pick one (e.g. `random.shuffle()` then pick one).
- **Backend alignment:** The design in `docs/FLOW-HOMEWORK-V2.md` and `services/v2_flow_service.py` already use “filter where min_task_score ≤ score”. For the homework flow we use **performance_score_1** instead of task_score. No change to the rule; when implementing homework flow we’ll filter assigned tasks by `min_task_score <= performance_score_1`.

### 3. metric_question_1 and metric_question_2

- **Decision:** They are **two fixed slots** (two editable texts). Admin edits the text of metric_question_1 and metric_question_2 in the Metrics section.
- **Backend alignment:** Table **`v2_metric_questions`** with **`position`** 1 and 2; admin CRUD exists. Aligned.

### 4. Five metrics for recording_2 (performance_score_2)

- **Decision:** The five metrics for recording_2 include the **same three** (strength, fillers, pacing) **plus two** derived from **metric_answer_1** and **metric_answer_2** (e.g. “how well recording_2 matches / addresses those self-ratings”). Exact formula can be defined later.
- **Backend alignment:** Backend has 5 metric codes (pace, strength, fillers, emotion_achieved, keywords_used) and `compute_metrics_v2`. The mapping of “two from metric answers” into those five (or into two additional inputs to the score) is for the **score formula** phase. Conceptually aligned; implementation in formulas TBD.

### 5. context_long: append with timestamps

- **Decision:** **Append** reports with **timestamps** so there is a **full history** of observations. Summarization (e.g. with AI) can be done later if it gets too long.
- **Backend alignment:** Currently **`context_long`** on **`v2_sessions`** is a single **TEXT** column (one blob per session). To support append-with-timestamps we need a **backend change**: store a **list of entries** (e.g. JSONB array like `[{ "at": "ISO8601", "text": "..." }]`). Each new report (or admin overwrite) **appends** an entry. Reading “the report” = latest entry (or full history for admin). Migration: add a new column **`context_long_entries`** JSONB default `'[]'` and use it for append; optionally keep `context_long` as a cached “latest text” for backward compatibility, or phase it out.

### 6. Dashboard: replace current v2 flow

- **Decision:** **Replace** the current v2 flow (universal_questions → one recording → post_questions) with this homework flow. The dashboard uses **only** this new flow (warm_up → recording_1 → task_text → final_task → recording_2 → questions → report → completed).
- **Backend alignment:** The **current** backend still implements the old v2 flow. When we implement the homework flow, we **replace** those student endpoints (or switch behavior so the same routes run the new flow). No conflict with the decision; implementation = replace old flow with new.

---

## Flow summary (aligned with backend where implemented)

| Step | Student sees / does | Admin | Backend status |
|------|---------------------|--------|----------------|
| 1 | One **task_warm_up** (chosen by admin from list) → records **recording_1** | List CRUD; **assign which one** is shown (assigned_warm_up_task_id) | List CRUD ✅; assigned_warm_up_task_id ❌ (add to overrides) |
| 2 | **context_short** (AI from rec1) + **focus_task** (min_task_score ≤ performance_score_1, shuffle if >1) + **metric_question_1** + **metric_question_2**; student answers the two | Focus tasks per student (v2_tasks + assigned_next_task_ids); Metrics: edit two texts | Tables ✅; selection logic when we have performance_score_1 ✅ |
| 3 | **final_task** (context + focus_task + metric_answer_1 + metric_answer_2) → records **recording_2** → **performance_score_2** (5 metrics) | — | Formulas TBD; 5-metrics pipeline exists for current flow |
| 4 | **Questions** (admin-assigned); if none, skip | Same as current post-recording questions (assign 3 or 0 = skip) | ✅ |
| 5 | **Report**: context_short + performance_score_end + answers; AI; store in **context_long** (append with timestamp) | View / edit / overwrite report; report stored as **append** in context_long | Report generation exists; context_long append ❌ (needs JSONB entries) |
| 6 | Done; report in admin history | History; change warm-up, focus_tasks, questions; **Re-send homework** | Send-assignment ✅; history/overwrite uses new context_long format |

---

## Backend changes needed to align fully

1. **assigned_warm_up_task_id**  
   - Add to **`v2_student_overrides`** (UUID, nullable, FK to `v2_warm_up_tasks.id` or no FK to allow unassign).  
   - Student “get warm-up task” endpoint: return the assigned task by id, or fallback (e.g. first by order_index) if null.

2. **context_long append with timestamps**  
   - Add **`context_long_entries`** JSONB on **`v2_sessions`** (e.g. `[{ "at": "ISO8601", "text": "..." }]`).  
   - When saving report (or admin overwrite): **append** one object to this array.  
   - “Get report” / “latest report” = last element of array. Admin “edit/overwrite” = append a new entry (or update last — product choice).  
   - Optionally keep **`context_long`** as a copy of the latest text for simple reads.

3. **Homework flow student endpoints** (not yet implemented)  
   - Get warm-up task (using assigned_warm_up_task_id).  
   - Submit recording_1 → context_short (AI) + performance_score_1 (placeholder then formula).  
   - Get task block (context_short + focus_task + metric_question_1/2).  
   - Submit metric answers → get final_task text.  
   - Submit recording_2 → performance_score_2 (placeholder then formula).  
   - Submit question answers (or skip if none).  
   - Generate report, compute performance_score_end, **append** to context_long_entries, return report.

4. **Admin: report overwrite**  
   - Endpoint to append (or update last) entry in **context_long_entries** for a session; UI in student history / session detail.

---

## Frontend (high level)

- **Flow states:** warm_up → recording_1 → task_text (context_short + focus_task + metric_question_1/2) → metric_answers → final_task → recording_2 → questions → report → completed.
- **API client:** New/updated endpoints for the homework flow; reuse admin client for students, warm-up tasks, focus tasks (tasks + assigned_next_task_ids), metric questions, post-recording questions, send-assignment.
- **Student profile (admin):** Warm-up tasks list + **“Assigned warm-up”** (single selection); focus tasks list (assigned_next_task_ids + task pool with min_task_score); re-send homework.
- **Metrics (admin):** Two fixed fields for metric_question_1 and metric_question_2 text.
- **History:** Show report (from context_long_entries, latest or full); edit/overwrite; “Re-send homework”.
- **Dashboard:** **Replace** old v2 flow with this homework flow (single flow only).

---

## Summary

- Your understanding and the six answers are **locked** and **aligned** with the intended design.
- **Backend:** Focus-task rule (min_task_score ≤ performance_score_1), two fixed metric questions, and existing tables/CRUD are aligned. Two backend changes are needed: **(1) assigned_warm_up_task_id** in overrides and **(2) context_long_entries** (append with timestamps). Then implement the homework flow student endpoints and admin report overwrite using that format.
- **Frontend:** Replace current v2 flow with this flow; add “assigned warm-up” and context_long history/overwrite in admin as above.

Once these backend changes and homework flow endpoints are in place, the backend will be fully aligned with this document.
