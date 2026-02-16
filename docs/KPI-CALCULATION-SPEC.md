# KPI calculation — backend implementation (definitive)

This document describes **exactly** how the “KPI” (performance score) is calculated in this backend, based on the code that actually runs in the **homework (v2)** flow. It corrects and supersedes any spec that mentions mood multipliers, resilience/awareness/progress bonuses, or the `performance_scores` table for the student-facing score.

---

## Summary

- **Student-facing “KPI”** = `performance_score_end` (0–1).
- **Where it’s computed:** `routes/homework.py` in `homework_submit_post_answers` (after `POST /v2/homework/session/<id>/post-answers`).
- **Formula (improvement-weighted):** `improvement = max(0, score2 - score1)`; `performance_score_end = 0.3*score1 + 0.6*score2 + 0.3*improvement`, then clamped to `[0, 1]`.
- **No** mood, readiness, Q1/Q2 reflection/awareness, or additive bonuses are used in this formula. All inputs come from recording analysis and (for score_2) one yes/no “emotion achieved” and keyword matching.

---

## 1. What the backend actually uses

| Concept | Used in homework KPI? | Where |
|--------|------------------------|--------|
| `performance_score_1` | Yes | From `metrics_v2.compute_performance_score_1` (recording 1 job). |
| `performance_score_2` | Yes | From `metrics_v2.compute_metrics_v2` (post-answers, recording 2). |
| `performance_score_end` | Yes | Average of the two, clamped. |
| Mood / readiness | No | Not used in homework flow. |
| Post Q1 (1–5 scale) | No | Not in performance formula; used for report context only. |
| Post Q2 (YES/NO noticed fillers) | No | Not in performance formula. |
| Resilience / awareness / progress bonuses | No | Not applied in homework flow. |
| `scoring_service` (filler 10, pacing bands, mood_multiplier, bonuses) | No | **Never imported**; legacy/unused. |
| `performance_scores` table / `final_kpi` | No | Table exists; `save_performance_score` is **never called** in this repo. |

So the “as just as possible” and “in very detail” answer for **this backend** is the metrics_v2 + average logic below.

---

## 2. performance_score_1 (after recording 1)

**Computed in:** `services/recording_1_job.py` → `services/metrics_v2.compute_performance_score_1(wpm, strength_raw, filler_count)`.

**Inputs:**

- `wpm`: words per minute from transcript + duration.
- `strength_raw`: from audio (RMS/dB). In recording_1 job it is **always `None`** (not yet computed), so strength component uses default.
- `filler_count`: total filler count from `count_fillers(transcript)`.

**Formula:**

```text
pace_n   = normalize_pace(wpm)
strength_n = normalize_strength(strength_raw) if strength_raw is not None else 0.5
fillers_n = normalize_fillers(filler_count)

performance_score_1 = (pace_n + strength_n + fillers_n) / 3.0
performance_score_1 = max(0.0, min(1.0, performance_score_1))
```

### 2.1 normalize_pace(wpm) — `metrics_v2.py`

- Constants: `PACE_TARGET_LOW = 120`, `PACE_TARGET_HIGH = 160`, `PACE_MIN = 60`, `PACE_MAX = 220`.
- If `wpm <= 0`: return `0.5`.
- If `120 <= wpm <= 160`: return `1.0`.
- If `wpm < 120`:  
  `t = (wpm - 60) / (120 - 60) = (wpm - 60) / 60`; return `_smoothstep(max(0, t))`.
- If `wpm > 160`:  
  `t = (220 - wpm) / (220 - 160) = (220 - wpm) / 60`; return `_smoothstep(max(0, t))`.

`_smoothstep(t)` = `t * t * (3.0 - 2.0 * t)` with `t` clamped to [0, 1]. So pace score is smooth, not linear, outside the 120–160 band.

### 2.2 normalize_strength(rms_or_db) — `metrics_v2.py`

- Used only when `strength_raw` is not None (recording_2 path). For recording_1, **strength_n = 0.5** always.
- If used: center `-25`, radius `15`; `t = (value - (center - radius)) / (2 * radius)`; return `_smoothstep(clamp(t, 0, 1))`.

### 2.3 normalize_fillers(filler_count) — `metrics_v2.py`

- If `filler_count <= 3`: return `1.0`.
- Else: `t = (10.0 - min(filler_count, 15)) / 10.0`; return `_smoothstep(max(0, min(1, t)))`.
- So: 4 fillers → t = 0.6 → smoothstep; 10 → t = 0; 15+ → t = 0. So **no** linear “threshold = 10” like in scoring_service; it’s a smooth decay and cap at 15.

---

## 3. performance_score_2 (after recording 2 + post-answers)

**Computed in:** `routes/homework.py` inside `homework_submit_post_answers`, via `compute_metrics_v2(...)`.

**Inputs:**

- Same as above: `wpm`, `strength_raw`, `filler_count` from recording_2.
- `emotion_achieved`: true iff the student’s answer to the post question with code `emotion_achieved_check` is one of `"YES"`, `"Y"`, `"1"`, `"TRUE"` (after strip + upper).
- `transcript`: recording_2 transcription.
- `keywords`: list of up to 3 keywords from metric answer 1 (comma/semicolon split, stripped).
- `metric_definitions`: from DB (for labels only; not used in the numeric formula).

**Formula:**

```text
pace_n     = normalize_pace(wpm)
strength_n = normalize_strength(strength_raw) if strength_raw is not None else 0.5
fillers_n  = normalize_fillers(filler_count)
emotion_n  = 1.0 if emotion_achieved else 0.0
keywords_n = normalize_keywords_used(transcript, keywords)

performance_score_2 = (pace_n + strength_n + fillers_n + emotion_n + keywords_n) / 5.0
performance_score_2 = max(0.0, min(1.0, performance_score_2))
```

Same `normalize_pace`, `normalize_strength`, `normalize_fillers` as above.

### 3.1 normalize_keywords_used(transcript, keywords, min_match=2)

- If no transcript or no keywords: return `0.0`.
- Normalize transcript: lowercase, replace non-word chars with space.
- Count how many of the first 3 keywords appear as whole words (regex `\b keyword \b`).
- If `seen >= min_match` (default 2): return `1.0`; else `0.0`.

So score_2 gives equal weight (1/5 each) to: pace, strength, fillers, emotion_achieved, keywords_used.

---

## 4. performance_score_end (final “KPI”)

**Computed in:** `routes/homework.py`, same handler. Improvement-weighted: recording 2 is weighted higher and positive improvement is rewarded so the score reflects coaching progress rather than a static average.

```python
performance_score_1 = float(session.get("performance_score_1") or 0)
performance_score_2 = float(session.get("performance_score_2") or final["performance_score"])
improvement = max(0.0, performance_score_2 - performance_score_1)
performance_score_end = (
    0.3 * performance_score_1
    + 0.6 * performance_score_2
    + 0.3 * improvement
)
performance_score_end = max(0.0, min(1.0, performance_score_end))
```

So:

- **Formula:** `improvement = max(0, score2 - score1)`; `performance_score_end = clamp(0.3*score1 + 0.6*score2 + 0.3*improvement, 0, 1)`.
- No mood multiplier, no bonuses, no Q1/Q2 in this number.
- This value is stored on the session as `performance_score_end`, returned in the post-answers JSON, and used for reports and for warm-up selection (last `performance_score_end`).

---

## 5. Order of operations in the backend

1. **Recording 1:** Job runs → WPM, filler count, (strength_raw = None) → `compute_performance_score_1` → `performance_score_1` stored on session.
2. **Recording 2:** User uploads recording_2; post-answers submitted with reflective answers.
3. **Post-answers handler:** Loads recording_2, gets WPM, filler count, strength_raw from `performance_metrics_v2`, derives `emotion_achieved` from post Q with code `emotion_achieved_check`, and `keywords` from metric answer 1.
4. Calls `compute_metrics_v2(...)` → `final["performance_score"]` = performance_score_2.
5. Updates recording_2 with `performance_score_v2`, `performance_metrics_v2`, `metric_labels_snapshot_v2`.
6. Reads `performance_score_1` from session; sets `performance_score_2 = final["performance_score"]`.
7. Computes improvement-weighted `performance_score_end` (0.3*score1 + 0.6*score2 + 0.3*max(0, score2-score1)), clamps to [0, 1].
8. Generates report, saves `performance_score_end` on session, returns it in the response.

---

## 6. Legacy / unused: scoring_service and performance_scores table

The detailed spec you had (mood multiplier, resilience/awareness/progress bonuses, filler threshold 10, pacing 120–180–200 bands, awareness from Q1/Q2) matches **`services/scoring_service.py`** and the **`performance_scores`** table schema in `db.py` (`save_performance_score`, `get_previous_performance_score`). However:

- **No route or service in this repo imports or calls `scoring_service`.** So that logic never runs for homework.
- **`save_performance_score` is never called.** So the `performance_scores` table is not populated by the current homework flow. `openai_service` may try to read `performance_scores` from recording history for report context; in homework-only use that join would typically return nothing.

So for “is it calculated somewhere in the backend?”:

- **Yes.** The number the student sees is calculated in the backend only: in `routes/homework.py` and `services/metrics_v2.py`.
- The **exact** formula is the one in sections 2–4 above (metrics_v2 normalizations + improvement-weighted combination for performance_score_end), not the scoring_service / solo-relevant doc formula.

---

## 7. Constants quick reference (metrics_v2)

| Constant | Value | Use |
|----------|--------|-----|
| PACE_TARGET_LOW | 120 | WPM lower bound of “optimal” band (score 1.0) |
| PACE_TARGET_HIGH | 160 | WPM upper bound of “optimal” band |
| PACE_MIN | 60 | Below 120: linear t from 60 to 120 then smoothstep |
| PACE_MAX | 220 | Above 160: linear t from 160 to 220 then smoothstep |
| Strength center | -25 | dB center for normalize_strength |
| Strength radius | 15 | dB radius for normalize_strength |
| Fillers “full” | ≤3 | fillers_n = 1.0 |
| Fillers decay | (10 - min(count,15))/10 | t for smoothstep (not a hard threshold 10) |
| Keywords min_match | 2 | At least 2 of first 3 keywords in transcript → 1.0 |

---

## 8. Frontend takeaway

- **KPI is calculated only in the backend.** Frontend should treat `performance_score_end` (and any displayed “KPI”) as read-only.
- The **single source of truth** for the homework “KPI” is:  
  **improvement-weighted combination** (0.3*score1 + 0.6*score2 + 0.3*max(0, score2-score1), clamped), where score1 and score2 come from **metrics_v2** (pace, strength, fillers; plus for score_2: emotion_achieved and keywords_used), with **no** mood or bonuses in the formula.

If you want, the next step can be a short “frontend contract” section (e.g. response shape and where to read `performance_score_end` and optional `performance_metrics`) or a one-page flow diagram of the calculation.
