# Coaching redesign: from score-based to need-based tasks

How the plan maps to the existing codebase and what to implement next.

**Status:** See **`docs/COACHING-REDESIGN-STATUS.md`** for what’s implemented vs not, and the exact Step 3 (performance profile) implementation outline.

---

## Where things live today

| Piece | Location | Current behavior |
|-------|----------|------------------|
| **Focus task selection** | `services/db.py` → `v2_select_student_focus_task_for_score(user_id, performance_score_1)` | Eligible = tasks where `max_performance_score >= score`; pick first by `order_index`. Fallback: `services/v2_flow_service.py` → `select_focus_task_for_performance_score_1` (v2_tasks by `min_task_score`). |
| **When it runs** | `services/recording_1_job.py` (after Whisper + metrics) | Has: `wpm`, `filler_count`, `performance_score_1`, `transcript_text`, `context_short`. Picks one focus task, writes `selected_task_id` to session. |
| **Focus task data** | `v2_focus_tasks` (per-student), `v2_focus_task_pool` | Columns: `text`, `order_index`, `max_performance_score`. No `targets`, `difficulty`, or `tags`. |
| **Student memory** | `v2_student_coaching_memory` (Step 2 done) | No “last N sessions”, “recent focus tasks”, or “recurring issues”. |
| **Final task text** | `services/openai_service.py` → `generate_final_task(...)` | Uses `context_short`, focus task, metric answers; template-style output. |

---

## Implementation map

| Plan step | What to do in this repo |
|-----------|-------------------------|
| **1. Performance profile** | In `recording_1_job`: derive `pace_level`, `filler_level`, etc. from WPM + filler count (+ optional LLM). Store in `v2_sessions.performance_profile` (new JSONB) or in a small “session summary” table. |
| **2. Student memory** | New table `v2_student_coaching_memory` (e.g. `user_id`, `recent_focus_task_ids`, `last_n_scores`, `recurring_issues`, `updated_at`) **or** a JSONB column on `v2_speaker_profiles`. Update at end of each completed session (e.g. in post-answers completion path). |
| **3. Multi-factor task selection** | Replace the “eligible = score band, pick first” logic in `v2_select_student_focus_task_for_score` with a **scoring function**: for each candidate task, compute weakness_match + novelty + progression + topic_relevance + difficulty_alignment; return best. Requires task metadata (`targets`, `difficulty`) and student memory. |
| **4. Warm-up logic** | Same idea: in `select_warm_up_task` (and wherever warm-up is chosen), use last session’s weakness / recurring_issues / category instead of only `performance_score_end`. |
| **5. Final task text** | Change `generate_final_task` prompt (and optional 2–3 structure variants) so output is less template-y (“Based on X… Focus especially on…” → more natural, still controlled). |
| **6. Student intent** | New optional field from frontend (e.g. “what to improve today”) passed into session start or recording-1; feed into task scoring. |
| **7. Student archetype** | After N sessions, classify and store (e.g. in `v2_speaker_profiles` or coaching_memory); use in task selection. |

---

## Minimal first step (recommended)

Implement these three in order:

1. **Prevent repeating the same focus task twice in a row**  
   - In `v2_select_student_focus_task_for_score`, load the last 1–2 completed sessions’ `selected_task_id` for this user.  
   - Filter out those task ids from the eligible list before picking.  
   - No new tables; only a new query + selection change.

2. **Store last 5 sessions’ “weakness” summary**  
   - Add `v2_sessions.performance_profile` JSONB (e.g. `pace_level`, `filler_level` from WPM + fillers in `recording_1_job`).  
   - Add `v2_student_coaching_memory` (or one JSONB on speaker_profile) with `last_5_scores`, `recent_focus_task_ids` (from last 5 sessions), updated when a session completes.  
   - Use this later in the multi-factor scorer (recurring issues, novelty).

3. **Use context_short topic tags**  
   - In `recording_1_job`, after `generate_context_short`, add an LLM call (or keyword pass) to get `context_tags: ["pitch", "persuasion", …]`; store on session.  
   - Add optional `targets` / `tags` to `v2_focus_tasks` (and pool).  
   - In task selection, score or filter by overlap between `context_tags` and task `targets`.

---

## Next step to do now

**Step (1) and (2) implemented:** no-repeat focus task + student coaching memory.

- No-repeat: last 2 sessions’ task IDs excluded (fallback when memory empty).
- Memory: `v2_student_coaching_memory` with last_5_scores, recent_focus_task_ids; upsert on completion; focus selection uses up to 5 recent task IDs when memory exists.

**Next:** Step 3 — add **performance profile** (recording_1_performance_profile on session: pace_level, filler_level from WPM/fillers). See `docs/COACHING-REDESIGN-STATUS.md` for the exact implementation outline. Then (4) recurring weakness detection and (5) context/topic tags.
