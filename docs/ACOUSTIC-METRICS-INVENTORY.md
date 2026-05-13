# Acoustic Metrics Constitution

**Status:** authoritative as of Phase 17.
**Audience:** anyone editing scoring code or adding a new metric.
**Rule:** every change to scoring behaviour must update this document **in the same commit**.

This is the single source of truth for what every score on the platform means, where it lives, and which writer is canonical. When two scoring paths produce different numbers for the same user, that's metric drift — and the path documented here as **canonical** is the one to keep.

---

## Layer A — Raw acoustic + transcript features (per snippet)

These are the primitive measurements. They're computed once at snippet extraction time and live as columns or JSONB on `charisma_snippets`. **Never recompute them at read time; cache invalidation is harder than re-extraction.**

| Code | Field | Type | Source-of-truth file | Notes |
|---|---|---|---|---|
| A1 | `wpm` | float | `services/snippet_extraction.py::_compute_snippet_metrics` + `utils/metrics.py::compute_wpm` (transcript fallback at session-aggregate time, commit `02b4872`) | Words per minute. NULL when neither path ran. |
| A2 | `fillers` | int | `services/snippet_extraction.py` + `utils/metrics.py::count_fillers` (transcript fallback) | Filler-word count. NULL when neither ran. |
| A3 | `pause_ms` | int | `services/snippet_extraction.py` | Average pause length within the snippet. |
| A4 | `dynamic_db` | float | `services/snippet_extraction.py` | Dynamic range in dB. |
| A5 | `pitch_center_st` | float | `services/snippet_extraction.py` | Pitch centre in semitones. Sometimes mirrored as `pitch_center` on dedicated column. |
| A6 | `energy` / `energy_ratio` | float (0–1) | `services/snippet_extraction.py` | Center-hold ratio. Used as `center_hold_ratio` input to B7. |
| A7 | `emphasis_per_min` | float | `services/snippet_extraction.py` | Emphasis hits per minute. |
| A8 | `voiced_duration_sec` | float | `services/snippet_extraction.py` | How much of the snippet was voiced (vs silent/breathing). |
| A9 | `pause_ratio` | float (0–1) | `services/sniper_scoring.py` input | Live-coach metric, computed on the client. |
| A10 | `transcript` (and `transcript_excerpt`) | text | Whisper at upload | Optional but anchors most downstream signals. |

**Recap rules**
- Every Layer A field MAY be NULL on a given snippet row.
- The session-aggregate path falls back to transcript-derived A1/A2 when those columns are NULL (see `routes/v2_routes.py::_compute_session_global_metrics` post commit `02b4872`).
- **Never default a NULL Layer A field to a magic number** in downstream code. Either redistribute weights (Layer B) or propagate NULL.

---

## Layer B — Composite metrics (computed from Layer A)

These are the scoring constructs. **B6 is the canonical session score going forward.** Everything else is either an alias, a sub-component, or a deprecated path kept for backwards compatibility.

| Code | What | Source-of-truth file | Status |
|---|---|---|---|
| B1 | `normalize_pace(wpm)` → 0..1 | `services/metrics_v2.py` | active — feeds B6 |
| B2 | `normalize_strength(rms_or_db)` → 0..1 | `services/metrics_v2.py` | active — feeds B6 |
| B3 | `normalize_fillers(count)` → 0..1 | `services/metrics_v2.py` | active — feeds B6 |
| B4 | `normalize_emotion_achieved(bool)` → 0..1 | `services/metrics_v2.py` | active — feeds B6 |
| B5 | `normalize_keywords_used(transcript, keywords)` → 0..1 | `services/metrics_v2.py` | active — feeds B6 |
| **B6** | **`compute_metrics_v2(...)` → `performance_score` (0..1)** | **`services/metrics_v2.py`** | **CANONICAL — Master Score** |
| B7 | `compute_recording_performance_score(center_hold_ratio, filler_count, wpm)` → 0..100 | `services/metrics_v2.py` | active — powers `v2_sessions.kpi_score` (Phase 11.1 — refuses to score when inputs are NULL) |
| B8 | `build_recording_1_performance_profile(wpm, fillers)` → labels | `services/metrics_v2.py` | active — coaching labels (pace_level, filler_level). Not a score. |
| B9 | `score_flow + score_pace + combine_scores` | `services/sniper_scoring.py` | live-coach only — must NOT be persisted as the session score |
| B10 | `compute_simple_live(...)` → live-coach dict | `services/sniper_scoring.py` | live-coach only — same caveat as B9 |

**Canonical contract — B6 (the Master Score)**
- Function: `services.metrics_v2.compute_metrics_v2`
- Inputs: A1 (wpm), A2 (fillers), A4-or-A6 mapped to strength, the user's yes/no emotion answer, the user's transcript, the session's keyword list, plus the metric_definitions snapshot.
- Output: `{ metrics: {...}, performance_score: float|None, metric_labels_snapshot: {...} }`
- **NULL semantics (Phase 17, this commit):** when one or more component inputs are missing, the missing component's weight is REDISTRIBUTED proportionally across the components that DO have signal. Returns `performance_score=None` only when every component is missing. Replaces the prior behaviour of substituting 0.5 for missing components — which silently anchored low-signal sessions toward "fine".

**What "user-facing" means here**
- The Master Score belongs in: `v2_sessions.score`, the /results page strip, the admin session view, the email summary line, the Phase 16 baseline summary input.
- B7 (KPI) is allowed in admin diagnostic surfaces (and `v2_sessions.kpi_score` column) but **must not** be presented as "your score" to users.
- B9/B10 are live-coach signals only. They drive the ball position during recording and disappear when the recording ends.

---

## Layer C — LLM-generated scores

These are subjective measurements an LLM produces over text or audio metadata. They have different failure modes from Layer A/B (model regressions, prompt drift) so they live in distinct columns and never overwrite a B-class number.

| Code | What | Source-of-truth file | Persisted column |
|---|---|---|---|
| C1 | `exchange_score_v2`: specificity, emotional_movement, engagement + rationale + entities | `services/coaching_outcomes.py` + `services/llm_schemas.py::EXCHANGE_SCORE_SCHEMA` | `coaching_attempts.score`, `coaching_attempts.components`, `coaching_attempts.entities` |
| C2 | `awareness_turn_v1`: validation_bubble + challenge_bubble + advance | `routes/v2_routes.py::v2_coaching_turn` | Not persisted as a score; lives in coaching message history. |
| C3 | `baseline_summary_v1`: headline + themes + archetype + tension + coaching_handle | `services/baseline_summary.py` + `services/llm_schemas.py::BASELINE_SUMMARY_SCHEMA` | `user_settings.baseline_summary` |
| C4 | `session_topic_extraction_v1`: per-turn topics → stickiness | `services/stickiness.py` + `services/llm_schemas.py::SESSION_TOPIC_EXTRACTION_SCHEMA` | `v2_sessions.stickiness_top_topic`, `stickiness_score`, `stickiness_topic_distribution` |

**Rule:** an LLM score never replaces a Layer B number. They live side-by-side. If a user-facing surface needs both, the surface code combines them.

---

## Layer D — Classifier outputs (per snippet)

These come from the binary/probabilistic classifiers that label snippets at extraction time.

| Code | What | Source-of-truth file | Column |
|---|---|---|---|
| D1 | `classifier_confidence` (charisma classifier) | `services/charisma_snippet_service.py` | `charisma_snippets.classifier_confidence` |
| D2 | `classifier_stress_probability` + `classifier_confidence` (stress classifier) | `services/stress_snippet_service.py` | `stress_snippets.classifier_stress_probability`, `classifier_confidence` |

**Cross-layer guard (Phase 17 primitive, Phase 17.1 wiring):** when the B6 Master Score and the D1/D2 classifier confidence disagree by more than 40 percentage points on the same recording, the session is flagged for admin review (`v2_sessions.needs_admin_review = TRUE`) and the full diagnostic is stored in `v2_sessions.drift_diagnostic`. Implemented in `services.metrics_v2.detect_classifier_drift`; wired into `_compute_session_global_metrics` so every "Compute Metrics" click runs it. The flag is **non-blocking** — publish still succeeds, but admin surfaces show a banner and the drift_diagnostic carries the why. Future Phase 17.2 can promote this to a hard block behind a feature flag if desired.

---

## Where each user-facing surface reads from

| Surface | Field shown | Source column | Source layer |
|---|---|---|---|
| /results "score" strip | `v2_sessions.score` | (will become B6) | **B6** |
| /results coaching insights | `admin_comment` on snippets | manual | — |
| Admin "Compute Metrics" panel — KPI card | `v2_sessions.kpi_score` | B7 | B7 |
| Admin "Compute Metrics" panel — Stickiness card | `v2_sessions.stickiness_*` | C4 | C4 |
| Admin coaching-attempt strip | `coaching_attempts.score` | C1 | C1 |
| Email subject "N voice moments are ready" | snippet count, not a score | — | — |
| Live-coach ball during recording | computed client-side or per-chunk | B9/B10 | B9/B10 |

---

## How to add a new metric (process)

1. Decide which layer it belongs to (A = primitive, B = composite of primitives, C = LLM, D = classifier).
2. Pick a code: next free index inside that layer.
3. Write the implementation under the matching `services/` module — never in a route handler.
4. Add a row to the table above with the source-of-truth file path.
5. If it's a Layer B score with NULL-able inputs, follow the **weight redistribution** rule, not the **substitute 0.5** rule. Add a unit test for the redistribution case.
6. If it overlaps with an existing metric, mark the older one DEPRECATED in this doc *and* leave the code in place with an alias comment pointing at the canonical replacement. Don't delete in the same commit — give consumers a release to migrate.

---

## Deprecation queue

Logged here so a future cleanup pass can find them.

| Metric | Why deprecated | Canonical replacement | Safe to remove when |
|---|---|---|---|
| `v2_sessions.score` set from anywhere other than `compute_metrics_v2` (B6) | Drift between surfaces | B6 | After audit: every writer to `v2_sessions.score` traced and migrated to B6. |
| `v2_sessions.score_for_display` (legacy 0–100 mirror) | Pre-Phase-17 separate column | B6 × 100 at read time | After frontend stops reading `score_for_display`. |
| `compute_simple_live` `performance_score` field | Confused with session score | B9 directly when live signal needed, B6 when persisted | Now (rename in payload only). |

---

## Versioning

Edit this doc with the same commit that changes scoring behaviour. The `git log` on this file IS the change history.
