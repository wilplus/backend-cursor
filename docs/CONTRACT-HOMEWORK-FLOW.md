# Homework flow: canonical contract (session, scoring, focus, report, admin, QC)

Single source of truth for backend and product. Implements the agreed decisions from the gap review.

**MVP scope (Option A — metrics-only):** This MVP uses deterministic scoring only. Session status uses exactly 5 values (`warm_up`, `task_block`, `final_task_ready`, `post_questions`, `completed`). End score is locked to `performance_score_end = (performance_score_1 + performance_score_2) / 2` (clamped 0..1). `score_transcription` / AI adherence scoring is not in MVP. Storage mapping is defined in `docs/DATA-MAPPING-SCORING-TO-DB.md`.

---

## 0. Resolved inconsistencies (MVP)

- **Focus threshold direction**
  - **Homework flow** uses table **`v2_tasks`** and field **`min_task_score`**.
  - **Eligibility:** task is eligible if **`min_task_score <= performance_score_1`** (student’s score meets or exceeds the task’s minimum bar). So “score_1 = 0.5” → any task with `min_task_score` in [0, 0.5] is eligible.
  - **No eligible task:** backend **picks easiest** (smallest `min_task_score`) so the flow never blocks. Implemented in `select_focus_task_for_performance_score_1`.
  - *Note:* Admin uses **`v2_focus_tasks`** (per-student, `max_performance_score`). Homework flow currently uses **`v2_tasks`** only. Unifying on `v2_focus_tasks` is a future product decision.

- **score_2 metric set**
  - **Exactly 5 metrics:** `pace`, `strength`, `fillers`, `emotion_achieved`, `keywords_used`.
  - **Source:** `services/metrics_v2.compute_metrics_v2`. Each metric normalized to 0–1; **aggregation = unweighted average** of the 5. Stored on recording as `performance_metrics_v2` and on session as `performance_score_2`.

- **Metric question source**
  - **Source:** table **`v2_metric_questions`** (global; positions 1, 2, 3). Fetched by **`v2_get_metric_questions_for_flow()`** (first 3 by position) for the task block and by **`v2_get_user_metric_questions(user_id)`** for session snapshot.
  - **Session snapshot:** at session start we store **`session_metric_question_1`**, **`session_metric_question_2`**, **`session_metric_question_3`** (text only) so report and resume use the same questions even if admin edits the pool later.

---

## 1. Session schema (Attempt entity)

**One canonical Attempt/Session entity** with all IDs and snapshots.

- **Table:** `v2_sessions`
- **Must hold (or reference):**
  - `user_id`, `status`
  - **Warmup:** `warm_up_task_id` (FK to `v2_warm_up_tasks`), `warm_up_task_text` (snapshot) — **persisted at session start** for resume/reproducibility
  - **Recording 1:** `recording_1_id` → `recordings` (transcript, WPM, fillers, etc.)
  - **Context 1:** `context_short` (AI summary of recording_1)
  - **Scores:** `performance_score_1`, `performance_score_2`, `performance_score_end`. **score_transcription** not in MVP (Option A; see §5).
  - **Focus task:** `selected_task_id` → `v2_tasks` (or future focus table)
  - **Generated task:** `final_task_text` (snapshot) — **persisted when metric-answers are submitted** for resume/reproducibility
  - **Metric Q&A:** `metric_answers` JSONB with keys **`answer_1`**, **`answer_2`**, **`answer_3`** (payload and storage; API may accept `metric_answer_1/2/3` as aliases). Submitted at transition `task_block` → `final_task_ready`. Question text snapshot in `session_metric_question_1/2/3`.
  - **Recording 2:** `recording_2_id` → `recordings`
  - **Context 2:** defined below (raw transcript on recording; optional `context_short_2` on session)
  - **Post Q&A:** `post_question_ids` (per-student question ids); answers in submit payload / report context
  - **Report:** `report_id` → `v2_reports`, `context_long_entries` (report history)

**Versioning:** Tasks/metrics/questions may be **versioned** or **snapshotted per session** for reproducibility (backend + product to implement). Past sessions are **not** re-scored when admin edits definitions.

---

## 2. Scoring spec & two metric paths (locked)

**Two paths:**

- **Path 1 — Recording 1 (real-time / no answers yet):** Strength, pacing, fillers only. No keywords or emotion (those need Q1/Q2 answers). **score_1 = avg(strength, pace, fillers)**. Use for focus selection and task block. Recording_1 response returns these 3 metrics (and optionally omits or returns 0/null for keywords_used and emotion_achieved so the payload shape is consistent).
- **Path 2 — Recording 2 (full rubric, after pre-answers):** Pacing (again), fillers, sticking to topic (keywords from Q1), emotions transferred (Q2), end CTA (Q3 if used). **score_2 = avg(pace, strength, fillers, emotion_achieved, keywords_used)** — i.e. the existing 5 metrics in `compute_metrics_v2`. CTA can be a separate metric later or folded into keywords/emotion for MVP.

**Locked:** score_1 uses **3 metrics only** (strength, pace, fillers). Score_2 uses **5 metrics** (pace, strength, fillers, emotion_achieved, keywords_used). No change to score_1 when Q1/Q2/Q3 are added; they only affect score_2 and the report.

- **Per-metric scale:** **0–1** (recommended and current).
- **Weights:** Unweighted average for score_1 (3) and score_2 (5). Product may define weights later.
- **Normalization:** Per-metric normalization to 0–1 inside `metrics_v2` (smoothstep, target bands).
- **Failure handling:**
  - **Transcription fail / silence / too short:** Define behavior (block vs fallback score). Backend should support: (a) optional min duration check, (b) fallback score when metrics cannot be computed (e.g. 0.5) so flow does not block unnecessarily.
  - **Missing strength / empty transcript:** Current fallback: strength → 0.5; pace uses WPM (can be 0.5 if WPM 0). Document in code and in this contract.

---

## 3. Focus task selection (“no eligible”)

- **Eligibility:** Task eligible if `min_task_score <= performance_score_1` (and optional `assigned_next_task_ids` filter).
- **When no task is eligible:** **Pick easiest** so the flow never blocks. Easiest = task with **smallest** `min_task_score` among active (and allowed) tasks.
- **When many qualify:** Current = random; product may later add rotation / LRU / curriculum.
- **Implementation:** Backend implements “no match → return easiest” in `select_focus_task_for_performance_score_1`.

---

## 4. context_1 / context_2

- **context_1:** Stored as **session.context_short** = AI **summary** of recording_1 transcript. Raw transcript stays on **recording** (`transcription_text`).
- **context_2:** Define exactly what is stored:
  - **Option A:** Only **raw transcript** on recording_2 (`transcription_text`); no second summary.
  - **Option B:** Add **session.context_short_2** (or `context_2`) = AI summary of recording_2; report prompt may use one or both (context_1 and context_2 / raw).
- **Retention:** Product defines retention policy; backend may add `transcript_retention_until` or consent flags when required.
- **Report prompt:** Uses context_1 (context_short); may use recording_2 transcript and, if present, context_2 summary. Explicitly document in report prompt which context fields are passed.

---

## 5. score_transcription vs score_2

- **score_2:** **Delivery/performance** rubric (pace, strength, fillers, emotion_achieved, keywords_used). Already implemented.
- **score_transcription:** **Not in MVP (Option A — metrics-only).** When added later: define so it does not overlap score_2 (recommended meaning: **task adherence**). Store on session (e.g. `score_transcription`) or recording; see **docs/DATA-MAPPING-SCORING-TO-DB.md**.
- **score_end:** See §6.

---

## 6. score_end formula

- **MVP (Option A — metrics-only):** **Locked:** `performance_score_end = (performance_score_1 + performance_score_2) / 2` (clamped 0..1). No score_transcription; no weighted formula.
- **Post-MVP options (when score_transcription exists):** B = weighted (e.g. 0.4×score_1 + 0.6×score_2); C = include score_transcription (e.g. weighted triple). Change only when product commits.

---

## 7. Report schema (backend prompt)

- **Structure:** Define in backend prompt: e.g. fixed sections (Summary / Evidence / Next steps) or free-form with rubric. Current: 3-paragraph homework rubric (performance overview, metric analysis, actionable next steps).
- **Evidence:** Whether to include **quotes** (transcript snippets) and where. Document in prompt.
- **Tone:** Supportive coach; concise; product may refine in prompt.
- **Inputs:** context_1, recording_2 transcript (and optional context_2), score_1/2/end, metric_answers, post_answers, admin_context. All explicitly listed in `generate_final_report` call and in this contract.

---

## 8. Admin policy

- **When edits apply:** **Next session only.** Admin edits (tasks, questions, metrics, overrides, speaker_profile, student_context) take effect when the user next starts or loads a session. No mid-session sync.
- **Retro re-scoring:** **None.** Past sessions keep stored scores and report; admin does **not** trigger re-score of old attempts. Recommended and current.
- **Audit trail:** **Required.** Log admin changes: who (admin user / auth), when, what (table/row/field or high-level action). Backend to implement (e.g. admin_audit_log table or append-only log).

---

## 9. State machine & API contract (locked)

- **Session status enum (exactly 5 values):**  
  `warm_up` → `task_block` → `final_task_ready` → `post_questions` → `completed`  
  Optional later: `abandoned`, `admin_reviewed` (product decision).
- **Transitions (no `report_ready` in V2):**  
  - recording_1 submitted → `task_block`  
  - metric_answers submitted → `final_task_ready` (generates and persists `final_task_text`)  
  - recording_2 submitted → **`post_questions`**  
  - post_answers submitted → **`completed`** (report is generated inside this step; there is no separate report step or status).
- **Recording_2 scoring (compute twice):** **performance_score_2** is computed **on recording_2 upload** with placeholders (`emotion_achieved: false`, `keywords: []`), then **recomputed after post_answers** when real emotion/keywords are available. Session and recording row are both updated after the re-run so the sync invariant holds (see **docs/DATA-MAPPING-SCORING-TO-DB.md**).
- **Session start:** If user has **no** warm-up tasks → **422 `NO_WARMUP_CONFIGURED`**; **do not create** a session. No “session created with null warmup” in MVP.
- **Recording_1:** One endpoint: transcription + score_1 (3 metrics) + context_short + focus selection → returns **task block** (focus_task + context_short + pre_questions). Does **not** generate final_task.
- **Metric-answers:** Saves answers (`answer_1`, `answer_2`, `answer_3`); **generates and persists `final_task_text`** (depends on answer_1/2/3); transition to `final_task_ready`.
- **Idempotency and async/failure policies:** See **§11** and **§12** below.

---

## 10. QC (backend-only)

- **Min duration:** Enforce minimum audio duration (e.g. 30 s); reject or warn below threshold. Backend-only.
- **Silence:** Optional silence detection (e.g. reject if > X% silence). Backend-only.
- **Language / length:** Optional language detection or max length; backend-only. Different rubrics per language = product decision later.
- **Plagiarism / off-topic:** Optional; backend-only if needed.
- **Behavior when QC fails:** Reject upload with clear code/message, or warn and allow (product decision). Document in API and this contract.

---

## 11. Idempotency (backend)

- **Session start (POST /session/start):** Creating a new session is non-idempotent (each call can create one new session). Resume returns existing session; no duplicate session for same user in active status. **Recommendation:** client only calls start once per “attempt”; if client retries, backend returns same active session (already implemented).
- **Recording upload (POST recording-1, POST recording-2):** Currently **not** idempotent: each POST creates a new recording. **Recommendation:** (a) Accept optional **`Idempotency-Key`** header (e.g. client UUID per “logical” upload); backend stores key + session_id + step, and if key already seen for that session+step, return 200 with existing recording instead of creating a new one. Or (b) **reject** duplicate: if session already has `recording_1_id` and request is for recording_1, return 409 or 200 with existing. Same for recording_2.
- **Metric answers (POST metric-answers):** Single submit per session; status moves to `final_task_ready`. **Recommendation:** if session already in `final_task_ready`, treat repeat POST as idempotent (return 200 with existing `final_task` from `session.final_task_text` if stored, or recompute). No second recording created.
- **Post-answers (POST post-answers):** Single submit per session; status moves to `completed`. **Implemented:** if session already `completed`, return 200 with existing `report_text`, `performance_score_end`, `performance_metrics`, and question_* fields; do **not** create a second report row.
- **Implementation:** Backend implements “already completed” for post-answers. Remaining: (1) optional `Idempotency-Key` for recording uploads and/or (2) “already has recording_1/2” checks that return success with existing data.

---

## 12. Async jobs and failure policies (backend)

- **Synchronous today:** Transcription, context_short, final_task, and report generation are **synchronous** in the request. If OpenAI or storage is slow, the request blocks.
- **Failure policy:** If **transcription** fails: return 5xx or 503 with clear code; client can retry. Do not persist a session state that assumes a transcript exists. If **generate_context_short** or **generate_final_task** fails: backend uses **fallback** (e.g. truncate transcript for context_short; fixed template for final_task) so the flow does not block. If **generate_final_report** fails: backend appends a short fallback sentence and still marks session completed; store fallback in `context_long_entries`.
- **Async (future):** Optionally move transcription or report generation to a **queue + worker**. Then: (a) accept upload, return 202 with `job_id`; (b) client polls or uses webhook for “transcript ready” / “report ready”; (c) session transitions when worker completes. For MVP, synchronous with fallbacks is acceptable; document retry guidance for client (e.g. retry once on 5xx for upload).

---

## Appendix A: Table fields (actual schema)

### v2_tasks (focus tasks used in homework flow)

| Column           | Type    | Notes |
|------------------|---------|--------|
| id               | UUID    | PK |
| title            | TEXT    | NOT NULL |
| prompt_text      | TEXT    | NOT NULL |
| min_task_score   | FLOAT   | DEFAULT 0. Eligibility: task shown if performance_score_1 >= min_task_score. |
| max_task_score   | FLOAT   | DEFAULT 1 (optional; some schemas add it). |
| is_active        | BOOLEAN | DEFAULT true |
| created_at       | TIMESTAMP | DEFAULT NOW() |

### v2_warm_up_tasks (per-student warm-up tasks)

| Column                   | Type    | Notes |
|--------------------------|---------|--------|
| id                       | UUID    | PK |
| user_id                  | UUID    | NOT NULL, FK auth.users |
| text                     | TEXT    | NOT NULL |
| order_index              | INT     | NOT NULL DEFAULT 0 |
| pool_task_id             | UUID    | FK v2_warm_up_task_pool, nullable |
| max_performance_score    | DECIMAL(3,2) | DEFAULT 1.00, CHECK 0..1. Used for selection: eligible if max >= student’s last score. |
| created_at               | TIMESTAMP | DEFAULT NOW() |

### v2_sessions (attempt/session)

| Column                   | Type    | Notes |
|--------------------------|---------|--------|
| id                       | UUID    | PK |
| user_id                  | UUID    | NOT NULL, FK auth.users |
| status                   | TEXT    | NOT NULL DEFAULT 'warm_up'. Enum: warm_up, task_block, final_task_ready, post_questions, completed. |
| created_at               | TIMESTAMP | DEFAULT NOW() |
| context_short            | TEXT    | context_1 (AI summary of recording_1). |
| context_long             | TEXT    | Latest report text (denormalized). |
| context_long_entries     | JSONB   | DEFAULT '[]'. Report history: [{ at, text }, ...]. |
| selected_task_id         | UUID    | FK v2_tasks (focus task chosen for this attempt). |
| recording_1_id           | UUID    | FK recordings. |
| recording_2_id           | UUID    | FK recordings. |
| performance_score_1      | FLOAT   | From 3 metrics (pace, strength, fillers). |
| performance_score_2      | FLOAT   | From 5 metrics (pace, strength, fillers, emotion_achieved, keywords_used). |
| performance_score_end    | FLOAT   | (score_1 + score_2) / 2. |
| session_metric_question_1| TEXT    | Snapshot of metric question 1 text. |
| session_metric_question_2| TEXT    | Snapshot of metric question 2 text. |
| session_metric_question_3| TEXT    | Snapshot of metric question 3 text. |
| metric_answers           | JSONB   | { answer_1, answer_2, answer_3 }. |
| question_1_analysis      | TEXT    | LLM analysis for custom question 1 (optional). |
| question_1_score         | FLOAT   | |
| question_2_analysis      | TEXT    | |
| question_2_score         | FLOAT   | |
| question_3_analysis      | TEXT    | |
| question_3_score         | FLOAT   | |
| pitch_variance_avg       | FLOAT   | Optional. |
| report_id                | UUID    | FK v2_reports. |
| post_question_ids        | UUID[]  | Per-student post-recording question ids for this session. |
| warm_up_task_id          | UUID    | FK v2_warm_up_tasks. Snapshot for resume/reproducibility. |
| warm_up_task_text        | TEXT    | Snapshot of warm-up task text. |
| final_task_text          | TEXT    | Snapshot of AI-generated final task instruction. |

---

## Appendix B: Function signatures

### select_focus_task_for_performance_score_1

**Module:** `services/v2_flow_service.py`

```python
def select_focus_task_for_performance_score_1(
    tasks: List[Dict],
    performance_score_1: float,
    assigned_task_ids: Optional[List[str]] = None,
) -> Optional[Dict]:
```

- **Eligibility:** task in `tasks` with `is_active` True and `min_task_score <= performance_score_1`; if `assigned_task_ids` is set, task id must be in that list.
- **Return:** One eligible task (random among ties), or if **none** eligible, the **easiest** task (smallest `min_task_score`). Returns None only if `tasks` is empty or all filtered out by `assigned_task_ids`.

---

### compute_metrics_v2

**Module:** `services/metrics_v2.py`

```python
def compute_metrics_v2(
    wpm: float,
    strength_raw: Optional[float],
    filler_count: int,
    emotion_achieved: bool,
    transcript: str,
    keywords: List[str],
    metric_definitions: List[Dict],
) -> Dict[str, Any]:
```

- **Returns:** `{ "metrics": { code: { raw, normalized, explanation } }, "performance_score": float (0..1), "metric_labels_snapshot": { code: { left_label, right_label } } }`.
- **Metric set:** pace, strength, fillers, emotion_achieved, keywords_used. **Aggregation:** unweighted average of the 5 normalized values.

---

### generate_final_task

**Module:** `services/openai_service.py` (method on OpenAI service instance)

```python
def generate_final_task(
    self,
    context_short: str,
    focus_task_title: str,
    focus_task_prompt: str,
    metric_answer_1: str,
    metric_answer_2: str,
    metric_answer_3: str = "",
) -> str:
```

- **Returns:** Single string (2 sentences): (1) Based on [context], your task is [focus_task]. (2) Focus especially on [metric answers]. Fallback if OpenAI fails: truncated context + focus task + “Focus especially on …”.

---

### generate_final_report

**Module:** `services/openai_service.py`

```python
def generate_final_report(
    self,
    transcript: str,
    pre_answers: list,
    post_answers: list,
    wpm: float,
    filler_count: int,
    filler_breakdown: dict,
    trend_sentence: str = None,
    user_id: str = None,
    admin_context: dict = None,
    recording_id: str = None,
    homework_context_short: str = None,
    homework_metric_answers: dict = None,
    homework_performance_score_1: float = None,
    homework_performance_score_2: float = None,
    homework_metric_1_name: str = "pacing",
    homework_metric_2_name: str = "vocal strength",
) -> str:
```

- **Returns:** Coach report string (150–250 words for homework flow). Uses `homework_*` params for 3-paragraph rubric when provided. Loads `admin_context` via `get_user_admin_context(user_id)` if not passed. Returns fallback string on failure.

---

## API / schema notes (for spec and migrations)

- **SessionStatusResponse.warm_up_task:** Keep **nullable** in OpenAPI/YAML for backward compatibility. In practice, after enforcing 422 on start when no warmups exist, it will be non-null whenever start succeeds; nullable still allows older clients or alternate flows.
- **GET /status and transcripts:** Do **not** return full `transcription_text` in GET /status (payload size). For MVP no change. Post-MVP: add `transcript_preview` (e.g. first 200 chars) on session/recording and/or **GET /recordings/{id}** for full transcript.
- **Minimal migration diff:** Exact current columns for `v2_sessions` and `recordings` (codebase naming) are in **docs/SCHEMA-COLUMNS-FOR-MIGRATION-DIFF.md**. Use that to produce a migration that only adds what’s missing and aligns field names.

---

## Implementation checklist

- [x] Focus “no eligible” → pick easiest (`v2_flow_service.select_focus_task_for_performance_score_1`).
- [x] Session: add `warm_up_task_id`, `warm_up_task_text`, `final_task_text`; persist at start and at metric-answers submit (migration `v2_sessions_resume_snapshots.sql`; schema + homework routes updated).
- [x] **Status enum:** exactly 5 values — warm_up, task_block, final_task_ready, post_questions, completed (see §9; OPENAPI-V2-STATUS.yaml).
- [ ] Scoring: document failure handling in code; add optional min duration / fallback score.
- [ ] score_transcription: post-MVP; implement when product defines (task adherence or other).
- [x] score_end: locked for MVP — average(score_1, score_2); switch to B/C only when score_transcription is added.
- [ ] Report prompt: document structure, evidence, tone in `openai_service` and this doc.
- [ ] Admin: add audit trail (table or log).
- [ ] Idempotency: add Idempotency-Key or “already has recording / completed” checks for POSTs (§11).
- [ ] QC: add min duration (and optional silence/language) and document behavior.
- [ ] Async/failure: document retry and fallback behavior for client (§12).

---

*This contract is the canonical reference for the homework flow. Backend and product should align implementations and prompts with it.*
