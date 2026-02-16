# Coaching redesign: what’s done vs what’s next

Single source of truth for implementation status and the next step.

---

## Implemented

### Step 1 — No-repeat focus task
- **`db.v2_get_last_completed_session_task_ids(user_id, limit=2)`** returns `selected_task_id` from the last 2 completed sessions.
- **`v2_select_student_focus_task_for_score`** excludes those task IDs so the same focus task is not repeated back-to-back.

### Step 2 — Student coaching memory (complete)
- **Table `v2_student_coaching_memory`**: `user_id` (PK), `last_5_scores` (JSONB), `recent_focus_task_ids` (JSONB), `updated_at`. One row per student; FK to `auth.users` with CASCADE.
- **`v2_get_student_coaching_memory(user_id)`** — returns memory row or `None`.
- **`v2_upsert_student_coaching_memory(user_id, session_id)`** — loads current completed session + last 4 *other* completed sessions (explicit `id != session_id`), builds `last_5_scores` and `recent_focus_task_ids` (oldest → newest, cap 5), upserts by `user_id`. Idempotent.
- **Completion hook:** In `homework_submit_post_answers`, right after `db.v2_update_session(..., session_update)`, we call `db.v2_upsert_student_coaching_memory(user_id, session_id)`.
- **Focus task selection:** `v2_select_student_focus_task_for_score` uses memory first: when `recent_focus_task_ids` exists, excludes up to 5 recent tasks; otherwise falls back to last 2 sessions. Score-band and “first eligible by order” logic unchanged.

**Result:** Longitudinal awareness (last 5 scores + last 5 focus tasks), stronger anti-repeat (5 sessions instead of 2), backward compatible when memory is empty.

### Step 3 — Performance profile (complete)
- **Column `v2_sessions.recording_1_performance_profile`** (JSONB): set by recording-1 job after Whisper + metrics. Shape: `{ "version": 1, "pace_level": "too_slow"|"optimal"|"too_fast", "filler_level": "low"|"medium"|"high" }`.
- **Thresholds** (in `services/metrics_v2.py`): pace &lt; 110 → too_slow, 110–170 → optimal, &gt; 170 → too_fast; fillers ≤3 → low, 4–8 → medium, &gt;8 → high. Aligned with `normalize_pace` / `normalize_fillers`.
- **`build_recording_1_performance_profile(wpm, filler_count)`** in `metrics_v2`; called from **`recording_1_job`** and stored in the same `v2_update_session` call as `performance_score_1` and `context_short`. Additive only; no change to selection logic yet.

**Result:** Every session with a completed recording-1 has behavioral labels. Enables Step 3.5 (recurring-issue derivation) and future multi-factor task selection.

### Step 3.5 — Recurring-issue derivation (complete)
- **Column `v2_student_coaching_memory.recurring_issues`** (JSONB, default `[]`): migration `add_recurring_issues_to_coaching_memory.sql`. Run after `add_recording_1_performance_profile`.
- **Derivation in `v2_upsert_student_coaching_memory`:** Loads last 5 completed sessions (current + 4 others) including `recording_1_performance_profile`. Builds `last_5_profiles` (oldest → newest). If `pace_level == "too_fast"` in ≥3 of 5 → add `"too_fast"`; same for `"too_slow"` and for `filler_level == "high"` → `"high_fillers"`. Caps at 3 issues. Upserts with `recurring_issues`.
- **Task selection unchanged:** Focus task still score band + anti-repeat. Next: multi-factor scorer using `recurring_issues` and task `targets`.

**Result:** Memory holds behavioral patterns (recurring_issues). Ready for need-based task weighting when tasks have `targets`.

### Step 4 — Multi-factor task scoring (complete)
- **Task metadata:** Migration `add_focus_task_targets_and_difficulty.sql` adds `v2_focus_tasks.targets` (JSONB, e.g. `["pacing"]`, `["fillers"]`) and `difficulty` (FLOAT, default 0.5).
- **Mapping:** too_fast/too_slow → pacing; high_fillers → fillers (`v2_flow_service.RECURRING_ISSUE_TARGETS`).
- **`score_and_pick_focus_task(candidates, recurring_issues, performance_score_1)`** in `v2_flow_service`: weakness match bonus; returns best task; tie-break = first in list.
- **Integration:** `v2_select_student_focus_task_for_score` uses scorer when memory has recurring_issues and any task has targets; else unchanged (first eligible by order). Backward compatible.

**Result:** Selection prefers tasks that match recurring weaknesses when metadata exists.

---

## Testing checkpoint (before topic tags)

**Now is the last stable baseline** before topic tags change selection. Validate adaptive behavior before adding semantic intelligence.

### Validate before adding topic tags

1. **Recurring-issue detection** — 5 sessions with high fillers → `recurring_issues = ["high_fillers"]`. 3+ sessions too fast → `"too_fast"`. Edge: only 2 of 5 → should NOT trigger.
2. **Weakness-based scoring** — When recurring issue = `"too_fast"` and tasks have `targets=["pacing"]`, pacing tasks are selected more often. Optional: enable temporary scoring log (see below) to inspect breakdown.
3. **Anti-repeat** — Run 6 sessions; confirm last 5 focus task IDs are not repeated.
4. **Baseline flow** — Warm-up loads, recording-1 job runs, final-task generates, report generates. No regressions.

### Do NOT add before validation

- Intent blending, warm-up logic changes, final-task text tweaks, difficulty alignment weighting, archetypes. All depend on confirming the core adaptive engine first.

### Optional: temporary scoring log

In `score_and_pick_focus_task()` (v2_flow_service), temporarily log per candidate: `task_id`, `weakness_score`, `total_score`. Remove after validation. Gives visibility before adding the topic dimension.

---

## Not implemented yet

| Area | Status | Notes |
|------|--------|--------|
| **Context / topic tags** | Not done | No tags from transcript/context_short; tasks blind to what the student talked about. |
| **Warm-up redesign** | Not done | Still first warm-up by `order_index`. Score-based `select_warm_up_task()` unused. |
| **Final task prompt** | Not done | Still fixed “Based on… / Focus especially on…”, verbatim metrics, rigid validation. |
| **Student intent** | Not done | No optional “what to improve today” from frontend. |
| **Student archetype** | Not done | No classification (e.g. energetic_scattered) or use in selection. |

---

## Maturity level

- **Before:** Stateless, reactive (one number → one task).
- **After Step 2:** Memory-aware reactive (last 5 scores + tasks, 5-session anti-repeat).
- **After Step 3:** Session-level behavioral labels (pace_level, filler_level) stored; selection still score-based.
- **After Step 3.5:** Memory includes `recurring_issues`; selection still score-based.
- **After Step 4:** Focus task selection uses weakness match when `recurring_issues` and task `targets` exist. No topic tags or difficulty alignment yet.
- **Next:** Context/topic tags, warm-up redesign, humanized final-task prompt; optional difficulty alignment and progression weight.

---

## Next step: Context/topic tags and beyond

- **Topic tags:** Extract tags from `context_short` (or transcript); store on session; optionally weight tasks by topic match when tasks have `tags`.
- **Warm-up intelligence:** Use `select_warm_up_task` (score + optional recurring_issues); warm-ups with `targets` or category.
- **Humanized final task:** Relax “Based on… / Focus especially on…”; allow natural phrasing.
- **Difficulty alignment:** Use `task.difficulty` and student level (e.g. avg of last_5_scores) in scorer.

---

## Decision matrix: what to do next

**Primary lens: coaching intelligence** (better targeting, relevance, and adaptation). Use the table for full trade-offs; the "If coaching intelligence is the top priority" order below focuses on that.

Use this to choose the next improvement by impact on **coaching intelligence**, **perceived intelligence (UX)**, **long-term skill progression**, and **retention**.  
Score: **H** = high impact, **M** = medium, **L** = low, **—** = minimal or indirect.

| Next option | Coaching intelligence | Perceived intelligence (UX) | Long-term skill progression | Retention | Effort | Recommendation |
|-------------|------------------------|------------------------------|-----------------------------|-----------|--------|-----------------|
| **Humanized final-task text** | L | **H** | L | **H** | M | **Do early.** User sees the final instruction every session; “Based on X, focus on Y” feels robotic. Natural phrasing (“You spoke about pitching. Now deliver with slower pacing and fewer fillers.”) makes the system feel human and increases trust and return. |
| **Warm-up intelligence** | **H** | M | M | M | M | Use `select_warm_up_task` + last score and/or `recurring_issues`; warm-ups with `targets`/category. Improves actual coaching (warm-up trains the weakness) and slight UX (“this warm-up feels chosen for me”). |
| **Topic/context tags** | **H** | M | M | M | M–H | Extract tags from `context_short`; weight tasks by topic. High coaching value (task matches what they’re practicing) and perceived smarts; needs LLM or keyword pass + task `tags`. |
| **Difficulty alignment** | M | L | **H** | M | M | Use `task.difficulty` and `last_5_scores` (or avg) in scorer; prefer “slightly above” current level. Best lever for long-term progression; less visible day-to-day. |
| **Student intent (“What to improve today?”)** | **H** | **H** | M | **H** | L (frontend) + M (backend) | One optional question; blend with recurring_issues in scorer. Strong for perceived intelligence and retention (“I chose; the app listened”); good for coaching. |
| **Student archetype** | M | L | M | L | H | Classify after N sessions; use in selection. More “real” intelligence but complex; lower immediate payoff than the above. |

**Suggested order (by benefit vs effort):**

1. **Humanized final-task text** — Highest perceived intelligence and retention for moderate effort; no new data model.
2. **Student intent** — High impact on coaching, UX, and retention; small frontend + backend change.
3. **Warm-up intelligence** — Improves real coaching and consistency with focus-task logic; reuses existing `select_warm_up_task` and memory.
4. **Topic/context tags** — Strong coaching and “it gets me” feel; more work (LLM or keywords + task tags).
5. **Difficulty alignment** — Best for long-term progression; add once the above are in.
6. **Student archetype** — Later, for deeper personalization.

**If coaching intelligence is the north star**, implement in this order (maximizes real adaptation before UX polish):

1. **Topic/context tags** — Add semantic awareness: *what* they speak about (pitch, persuasion, storytelling), not only *how* (pace, fillers). One short LLM call or keyword extraction from `context_short`; store on session; optional `tags` on tasks; weight in scorer. Constraint: don’t overcomplicate LLM usage (single call, store once, reuse).
2. **Warm-up A (pattern correction)** — Warm-up chosen by last score and/or `recurring_issues`; warm-ups with `targets`/category. Reinforces recurring weakness at session start. Simple, deterministic, no preview. Long-term option: Hybrid B-with-A-bias (lightweight pre-selection at start → warm-up aligned to predicted focus; fallback to recurring_issues).
3. **Student intent** — Optional “What do you want to improve today?”; blend with `recurring_issues` in scorer (e.g. 0.6 system + 0.4 intent). Prevents resistance, increases agency.
4. **Difficulty alignment** — Use `task.difficulty` and student level (e.g. avg of `last_5_scores`) in scorer; prefer tasks slightly above current level (growth zone).
5. **Humanized final-task text** — Improves perception and retention; lower impact on selection quality. Do after the above.
6. **Student archetype** — Deeper personalization; polish, not core targeting.

**Warm-up design:** Start with **A (pattern correction)**: warm-up reinforces **recurring_issues** (e.g. if too_fast, give a pacing warm-up) or (B) **align with the focus task they’ll get** (“warm-up trains the same dimension the focus task will emphasize”). For now: A only (pattern correction). Long-term **Hybrid B-with-A-bias**: **preview selection at start** (run focus-task selection at session start using last score + recurring_issues only, no current profile → pick a “likely” focus task, then choose a warm-up whose targets match that task), or keep (A) and match warm-up only to recurring_issues. Implement A first; add B-preview when ready.

**Strategic maturity trajectory:** Reactive (scores) → Pattern-aware (recurring issues) ✅ → Context-aware (topic tags) → Intent-aware (user choice) → Progression-aware (difficulty). Topic tags are the next step: they shift coaching from “You speak too fast” to “You speak too fast when pitching.”
