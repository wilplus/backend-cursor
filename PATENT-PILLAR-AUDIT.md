# Patent-Pillar Implementation Audit

_Read-only audit of four claimed willab "pillars" against actual backend code at HEAD of `claude/audit-patent-implementation-Ug8Ti`. Generated as input for a patent-attorney consultation. The standard applied is adversarial honesty, not collaborative summary: every claim is grounded in file paths, function names, schema fields, or stated as "not present."_

## TL;DR

| Pillar | Implemented? | Depth | Matches description? | Gap to file |
|---|---|---|---|---|
| 1 — Triple Asymmetric Calibration | **No** | stub only | **No** | EEG ingest, peer-rater consensus layer, per-sample weighting function, weighted training loop, LOO-CV harness — all absent. Fine-tuning has never run (`PHASE-A0-FINDINGS.md`). |
| 2 — Async Micro-Slice Restructuring | **Partial** | prototype | **No** | Real-time feedback is the opposite of the claim — backend streams live metrics during recording. Stress/charisma snippets are extracted (0.5–5 s, never 10 s) and stored, but are admin-only artifacts; user never sees them. No F0/waveform/envelope visualization in any payload. No "cue reactivation" framing in code. |
| 3 — Biological Baseline Transition | **Partial** | prototype | **No** | A `baseline_established` flag exists but only routes question generation — it is never read by any scoring function. Transition is hardcoded at `turn_number == 4`, not stability-driven. No entropy/autocorrelation/variance-of-variance computation. No dual-timescale drift filtering. Stored EMA baselines (`user_sniper_profile`) are written but never read by scoring code. |
| 4 — Dynamic Hardware Compensation (AGC) | **No** | absent | **No** | Zero references to AGC anywhere. No device fingerprint captured on upload. No device-profile library. No session-start calibration phase. All Layer A features are reported in absolute units (dB FS, ms, Hz, WPM). No cross-device invariance test exists. |

**Prioritization for the attorney meeting (see §5):**
- **(a) Ready to file:** none.
- **(b) Close — 2–4 weeks of focused work:** none of the four reach this bar honestly. Pillar 2 has the most existing scaffolding, but bringing it to the claim still takes more than four weeks.
- **(c) Aspirational — months of new development:** all four. Pillars 1 and 4 are the largest gaps; Pillars 2 and 3 have prototype pieces but the patent-defining elements (cue-reactivation delivery, stability-driven transition) are absent.

---

## 1. Pillar 1 — Triple Asymmetric Calibration Pipeline

**Existence: NO. Depth: stub only. Distinctiveness: does not match.**

### Three independent label streams
- Snippet schemas store a **single** binary `coach_label` per snippet (`migrations/add_stress_snippet_labeling_pipeline.sql:20`, `migrations/add_charisma_snippet_pipeline.sql:22`).
- `migrations/add_user_charisma_label_to_snippets.sql:29-30` adds `user_charisma_label` — this is the **student's own** self-verification, not a peer-rater stream.
- `migrations/add_coaching_attempt_annotations.sql:29-67` allows multiple admins to annotate the same coaching attempt, but those rows are stored independently with no consensus logic, and they cover coaching-attempt evaluation, not snippet labeling.

### EEG-derived primary labels
- **Do not exist.** Grep for `EEG`, `electroencephal`, `neural label`, `biomarker label` finds matches only in `services/master_doc_rag.py`, and those are research-citation strings ("structurally unscalable beyond the laboratory") in a RAG corpus. There is no ingest pipeline, no schema column, no event stream from any EEG device anywhere in the codebase.

### Structured expert rubric
- `migrations/add_recording_reviews.sql:12` adds a `rubric_version` column, but it is a string tag (audit metadata). The rubric itself is not stored in code, not enforced in validation, and not versioned in any schema.

### Peer consensus
- **Does not exist.** No `peer_rating`, `peer_consensus`, `inter_rater_agreement`, or aggregation logic. The comment at `migrations/add_coaching_attempt_annotations.sql:23` mentioning "inter-rater agreement" is forward-looking language; no implementation follows.

### Sample-weight computation
- **Does not exist.** Grep for `sample_weight`, `label_weight`, `annotation_weight`, `confidence_weight` returns nothing. The only weights in the codebase are component weights in `services/coaching_outcomes.py:74-77` (`_W_SPECIFICITY=0.30` etc.) — these weight components of one composite score, not training samples.
- `scripts/train_stress_classifier_baseline.py:272-329` trains unweighted logistic regression. `_train_logreg()` at line 307 takes `x_train, y_train` only; the gradient update at line 315 is `(x_train.T @ (p - y_train)) / max(1, n)` — every sample weighted equally.

### Asymmetric weighting (peer disagreement reduces weight without modifying expert label)
- **Cannot exist** because peer consensus does not exist. No code reads peer and expert labels together, computes disagreement, and adjusts a weight.

### Has fine-tuning ever run?
- **No.** `PHASE-A0-FINDINGS.md` is unambiguous: `Promoted: False`, `admin_annotation_events: (no rows ... annotation capture has never fired)`, `NOT VIABLE`. Production runs stock `gpt-4o-mini`. The export plumbing in `services/ml_finetuning_export.py` and `services/ml_dpo_export.py` exists but has never produced a training corpus.

### Leave-one-participant-out CV
- **Does not exist.** No `cross_val`, `loo_cv`, `leave_one_out`, `kfold` in the tree. `scripts/train_stress_classifier_baseline.py:248-269` performs a single 80/20 group-stratified split (`_split_grouped`) — not a CV harness.

### Honesty-check divergences
1. "EEG-derived ground truth labels" — absent. Acoustic features are used as a proxy; no neural data exists.
2. "Structured rubric" — only a version-tag column; the rubric is not in code.
3. "Peer consensus" — absent.
4. "Asymmetric weighting" — absent (no weights, no consensus to weight against).
5. "Three independent labeling streams during calibration" — at most two label sources exist (admin + optional student self-label); they are not combined in any calibration step.
6. "Trains an acoustic classifier" — yes, a logistic-regression baseline exists, but training is unweighted single-label supervised learning. Fine-tuning of the LLM stack has never run.

### What it would take to file truthfully
EEG ingest + schema + validated label generation; peer-rater table with consensus aggregation; a `sample_weight` field and a weight-computation service that consumes (`expert_label`, `peer_consensus`, `peer_confidence`); a weighted training loop that consumes those weights; and a CV harness that holds out participants. None of these are partially built — they are all greenfield.

---

## 2. Pillar 2 — Asynchronous Cognitive Restructuring from Micro-Slices

**Existence: PARTIAL. Depth: prototype. Distinctiveness: does not match — in one critical respect, the code does the opposite of the claim.**

### Real-time feedback during recording — opposite of claim
- The backend **streams live acoustic metrics during recording**. `routes/homework.py:1139-1234` (`homework_sniper_metrics_chunk()`) accepts polled PCM chunks and returns `simple_live` with `flow_score`, `performance_score`, `coach_color`.
- `services/realtime_audio_metrics.py:1-343` is explicitly designed to compute live pause/voiced/pitch metrics at 4–10 Hz over a 10-second rolling window.
- No flag exists to suppress this (`show_live_feedback`, `suppress_realtime`, `post_only`, `hide_metrics_during` — none of these strings are in the codebase).
- The patent claim says the system **deliberately rejects** real-time biofeedback. The production code is **built to deliver it**. This is the most important divergence in the pillar.

### Anomaly detection — generic, not sympathetic-activation-specific
- `services/stress_snippet_service.py:340-437` (`_build_candidates`) flags moments using a heuristic mix of (a) VAD-detected pauses ≥240 ms, (b) filler-word density, (c) RMS energy variability.
- The scoring formula at line 800 is `0.45·filler_density + 0.35·pause_strength + 0.20·energy_norm`.
- An optional 17-feature sigmoid baseline classifier exists (lines 811-819), labelled as experimental.
- There are no autonomic-nervous-system markers, no pitch micro-tremor / jitter detection, no HRV, no GSR. Claiming "detects sympathetic activation" would be a generic acoustic-heuristic detector dressed up in neurophysiology language.

### Auto-segmentation of 5–10 s clips
- Real, but narrower than the claim. `services/stress_snippet_service.py:266-293` produces 0.5–5 s clips (defaults: `STRESS_SNIPPET_CLIP_SEC_DEFAULT=5.0`, min 0.5, max 5.0 at lines 27-29). The claim says 5–10 s; the code never reaches 10.
- Boundary logic is utterance-aware (respects VAD speech boundaries, lines 307-325). This part is real and functional.

### Storage and user-side retrieval
- Storage is real: `stress_snippets` table (`migrations/add_stress_snippet_labeling_pipeline.sql`), MP3 at `s3://[bucket]/stress_snippets/{recording_id}/{snippet_id}.mp3`.
- **Retrieval is admin-only.** The only endpoint returning a snippet payload is `/admin/stress-snippets/<id>` at `routes/v2_routes.py:2598-2607`. No user-facing endpoint exposes stress snippets in the results UI. So even though the artifact exists, the "deliver to the user later" half of the claim does not.

### Acoustic visualization on review
- `routes/v2_routes.py:264-304` (`_stress_snippet_payload`) returns `audio_url`, timestamps, scenario, and a `features` dict with three scalars (`pause_strength`, `filler_density`, `energy_std`).
- **No time-series telemetry** — no F0 trace, no energy envelope, no waveform array, no pause-structure timeline. The visualization the claim describes would need that telemetry shipped from the backend (or computed in the browser), and neither exists. Frontend type definitions in `docs/frontend-v2-deliverables/types-v2.ts` have no corresponding components.

### Delayed delivery
- A delay gate exists: `services/session_publish.py:301-304` (`results_published_at`). Users cannot see results until admin approval.
- But the docstring at lines 1-34 frames it as an **admin-moderation workflow**, not a therapeutic spacing for memory reconsolidation. No code comment, schema column, or doc anywhere uses the terms "reconsolidation", "cue reactivation", "calm setting", "asynchronous restructuring", "sympathetic activation". The framing is not in the code.

### Honesty-check divergences
1. "Deliberately rejects real-time biofeedback" — code does the opposite.
2. "Sympathetic activation" detection — generic acoustic heuristics.
3. "5–10 second" clips — actual range 0.5–5 s.
4. "Delivers to the user later in a calm setting" — clips are never delivered to the user; they are admin-only.
5. "Acoustic telemetry visualization (waveform, F0 trace, energy envelope, pause structure)" — no telemetry in payloads; no frontend components for it.
6. "Cue-provoked state reactivation for memory reconsolidation" — framing absent from code, schema, and docs.

### What it would take to file truthfully
A session-config flag that genuinely suppresses live metrics (and a frontend that respects it); a user-facing review endpoint that returns stress snippets after a deliberate delay; pre-computed F0/energy/pause time series in the payload; a UI for the review experience; and a meaningful sympathetic-activation classifier rather than a pause+filler heuristic. The snippet extraction itself is the only piece that ports cleanly into a filing.

---

## 3. Pillar 3 — Biological Baseline Transition Algorithm

**Existence: PARTIAL. Depth: prototype. Distinctiveness: does not match.**

### Per-user feature history
- `migrations/add_user_sniper_profile.sql:1-17` creates `user_sniper_profile` with EMA-updated baselines: `baseline_wpm`, `baseline_pause_ms`, `baseline_dynamic_db`, `baseline_emphasis_per_min`, `baseline_energy_ratio`, `baseline_fatigue_sec`.
- `session_sniper_metrics` (lines 22-35) stores per-session metrics.
- `services/db.py` (`update_sniper_profile`, `merge_sniper_metrics_into_profile`) updates baselines with `0.8·old + 0.2·new` EMA.
- **No per-session entropy, autocorrelation, or variance-of-variance** is computed or stored. Only running means.

### Scoring — population vs intra-speaker
- Only one scoring mode exists, and it is population-style (hard-coded thresholds), not intra-speaker.
- `services/sniper_scoring.py:15-60`: `score_flow(pause_ratio)` uses good band `[0.10, 0.35]`; `score_pace(wpm)` uses good band `[125, 165]`. Neither reads the user's baseline.
- `services/metrics_v2.py:86-126, 164-318`: normalizes against fixed `PACE_TARGET_LOW=120`, `PACE_TARGET_HIGH=160`.
- `services/session_diagnosis.py:53-78`: hardcoded `WPM_STRESSOR_MIN_EXCLUSIVE=170`, `WPM_OVERWHELMED_MAX_EXCLUSIVE=120`.
- **Critical finding:** the baseline columns in `user_sniper_profile` are **written via EMA but never read by any scoring function.** The personalization signal exists in the database but does not influence any user-visible score.

### Switch logic
- `baseline_established` flag exists (`migrations/add_baseline_established_to_user_settings.sql`) and is flipped at `routes/v2_routes.py:12603-12623` when `turn_number == 4`.
- It is read **only** to choose which question-generation prompt path to take. It is **never read** by `sniper_scoring.py`, `metrics_v2.py`, `session_diagnosis.py`, `scoring_service.py`, or `homework_completion.py`. So the "switch from population to intra-speaker scoring" the claim describes does not happen anywhere.

### Transition criterion
- Hardcoded: `if turn_number == 4`. Not data-driven.
- Zero entropy, autocorrelation, variance-of-variance, stationarity, saturation_threshold computation in the codebase. The claim's stability-metric machinery is absent.

### Dual-timescale drift detection
- A `drift` mechanism exists (`migrations/add_drift_flag_to_v2_sessions.sql`, `services/metrics_v2.py:333-387` `detect_classifier_drift`), but its purpose is **classifier-disagreement sanity-checking** (B6 master score vs D1/D2 classifier confidence, threshold `|Δ| > 0.40`). It is not a biological short-term-vs-long-term separation. No Kalman filter, no rolling-window z-score, no fatigue/illness vs improvement distinction.

### Population prior dataset
- None. `migrations/add_casual_voice_benchmarks.sql` stores per-user casual-speech metrics for stress-contrast against the user's own formal recording — it is not a normative population reference.
- Targets like `_IDEAL_WPM_MIN=125`, `_IDEAL_WPM_MAX=140` (`services/charisma_profile.py`) look hand-tuned to pedagogical ideals, not derived from an empirical distribution.

### Rolling normalization
- Not present. Only EMA smoothing of baselines. Features are never z-scored against a rolling window before scoring.

### Honesty-check divergences
1. "Automatic transition based on data-stability criterion" — actually `turn_number == 4`, a fixed rule.
2. "System decides when to stop comparing against population baseline" — only one scoring mode (population-style) exists; there is no second mode to switch to.
3. "Tracks stability metrics (entropy, autocorrelation, variance of variance)" — none of these are computed anywhere.
4. "Dual-timescale drift filtering" — the drift code that exists is classifier disagreement, not biological short/long-term separation.
5. "Long-term drift updates baseline; short-term drift is filtered via rolling normalization" — no rolling normalization, no filtering.
6. The personalization scaffolding (`user_sniper_profile` baselines) is plumbed into write paths but no read path uses it for scoring.

### What it would take to file truthfully
Add per-session entropy/autocorrelation/variance-of-variance columns and the code to compute them; add a stability-threshold service that decides when a user is "saturated"; gate the scoring mode on that signal (not `turn_number`); add a rolling-window z-score layer that filters transients; add a dual-timescale drift detector (e.g., EWMA at two time-constants, or Kalman state-space) separating fatigue from improvement; and actually wire the existing `user_sniper_profile` baselines into the scoring functions.

---

## 4. Pillar 4 — Dynamic Hardware Compensation (Dirty Audio Wall)

**Existence: NO. Depth: absent. Distinctiveness: does not match.**

This is the cleanest "does not exist" of the four. The architecture described in the claim has no implementation in the code at all.

### Session-start calibration (first ~3 s)
- Not present. `services/audio_metrics.py:194-203` (`analyze_audio`) decodes the complete audio blob and runs `_analyze_pcm` over the whole signal. No staged "first 3 s = characterization, then analysis" branch.
- `services/realtime_audio_metrics.py:208-243` maintains a 10-second rolling window per session, but for live pause aggregation, not device characterization.

### Device fingerprint capture
- Not captured. `routes/v2_routes.py:9508-9655` (trial recording endpoint) accepts only `audio_file` and `coaching_id`. No device_model, OS, browser, sample_rate, bit_depth, or mic identifier fields are read from the client.
- `migrations/add_recordings_v2_columns.sql` adds session/task/score columns; no device columns.
- `migrations/add_recording_1_performance_profile.sql:12-22` adds a JSONB profile with pace/filler/energy labels; no device fields.

### Device-profile library
- Does not exist. No table, no JSON config, no in-code dictionary. Grep for `device_profile`, `mic_response`, `ios_profile`, `android_profile`, `transfer_function`, `transfer_profile`, `noise_floor`, `frequency_response` returns no matches in services or migrations.

### On-the-fly device characterization
- None. No AGC curve estimation, no dynamic-range estimation, no headroom analysis.
- The single TODO at `services/session_diagnosis.py:28` (`# TODO(artur): calibrate against live acoustic logs. Placeholder dB value ...`) is about tuning a behavioral-classifier threshold (`DYNAMIC_DB_HEALTHY_THRESHOLD = 6.0`) once more sessions exist. It is orthogonal to device compensation.

### Feature units — absolute, not relative
The Layer A features in `services/audio_metrics.py` are all absolute or single-recording proportions:

| Feature | Source | Unit |
|---|---|---|
| `wpm` | `utils/metrics.py` (called by `audio_metrics.py:240`) | absolute words/min |
| `pause_ms` | `audio_metrics.py:93-109` | absolute ms |
| `dynamic_db` | `audio_metrics.py:112-116` | absolute dB FS (P95 − P5) |
| `emphasis_per_min` | `audio_metrics.py:119-141` | absolute count/min |
| `energy_ratio` | `audio_metrics.py:144-159` | proportion within one recording (not cross-device) |
| `pitch_center_st` | `audio_metrics.py:162-191` | semitones from fixed `PITCH_REF_HZ=100.0` |

None are z-scores against a device-aware baseline, percentiles of a normative distribution, or relative/geometric transformations of the kind the claim describes.

### Smoothing
- `_smoothstep` exists in `services/metrics_v2.py:18-21` and `services/realtime_audio_metrics.py:42-53`, but as **sigmoid easing for scoring band normalization**, not as a device-compensation filter applied to raw features. No EMA, moving-average, Savitzky-Golay, or Kalman filter is applied to the feature stream for compensation.

### Cross-device test data
- Does not exist. No fixture or assertion in `tests/` asserts "same speech, different devices ⇒ same features after compensation." Grep for `cross_device`, `device_invariant`, `mic_invariant` returns no matches.

### AGC awareness
- Zero references to `AGC`, `agc`, or `automatic gain control` in any Python file or in `docs/`. The codebase does not even name the problem, let alone solve it.

### Honesty-check divergences
1. "Compensates for AGC and nonlinear hardware distortions" — no AGC code of any kind.
2. "At session start, sample first ~3 seconds to characterize" — no calibration phase.
3. "Compute local transfer profile (AGC curve, frequency response, noise floor)" — none computed.
4. "Output features as relative/geometric values, not absolute units" — features are absolute (dB FS, Hz, ms, WPM).
5. "Adaptive smoothing that preserves relative geometric proportions" — smoothing exists, but it is scoring-band easing, not feature-stream compensation.
6. "Device-aware compensation specifically aimed at biomarker preservation" — no device awareness anywhere in the pipeline.

### What it would take to file truthfully
A session-start calibration module that consumes the first ~3 s of PCM and estimates AGC behavior + frequency response + noise floor; a device-profile table populated either by a known-device library or by on-the-fly estimation; client-side capture of device metadata in the upload route; an inverse-compensation filter applied before feature extraction; a relative/geometric feature representation as the canonical output; and a cross-device invariance regression test. All of this is greenfield.

---

## 5. Prioritization for the patent-attorney meeting

The honest read across all four pillars: **none of these are ready to file as written.** The framings in the claims describe systems that the code does not implement, in some cases (Pillar 2 real-time, Pillar 4 AGC) in directions opposite to what the code actually does.

### (a) Ready to file based on existing implementation
**None.** Filing any of the four as currently written would mean filing on aspirational descriptions. The biggest legal exposure is on Pillar 1 (claiming EEG-derived primary labels that do not exist) and Pillar 4 (claiming AGC compensation that does not exist in any form).

### (b) Close — 2-4 weeks of focused work would close the gap
Honestly, none of the four reach this bar. Pillar 2 is the closest, because the snippet-extraction half (utterance-aware 0.5–5 s clips around heuristic-flagged moments, plus admin storage) is functional. But the claim-defining elements — suppressed real-time, user-facing delayed delivery, acoustic-telemetry visualization, cue-reactivation framing — are each non-trivial multi-week efforts, and at least two of them (visualization payload + user delivery UX) require frontend work that is not in this repo. A truthful 2–4 week scope for Pillar 2 would file only on the snippet-extraction technique, which is unlikely to be patentable on its own (window-around-anomaly extraction with VAD-aware boundaries is well-established art).

### (c) Aspirational — months of new development
**All four.** Ranked by gap size:

- **Pillar 1** is the largest gap. EEG ingest requires hardware integration and an entirely new data plane; peer-rater consensus is greenfield; the weighting function and weighted training loop are greenfield; fine-tuning has never run and per `PHASE-A0-FINDINGS.md` the corpus is empty. Realistically multi-quarter.
- **Pillar 4** is the second-largest gap, and the most legally risky to claim aspirationally. Device profiling, calibration, inverse compensation, and a cross-device invariance test suite are all new. Realistically multi-quarter, plus a non-trivial measurement-engineering effort.
- **Pillar 3** has the most usable scaffolding (`user_sniper_profile`, `baseline_established`, EMA updates), but the patent-defining elements (stability-driven transition, dual-timescale drift) are absent and the existing baselines aren't even wired into scoring. Two to three months to do it credibly.
- **Pillar 2** has the most functional component (snippet extraction) but the highest framing-vs-code mismatch (real-time is the opposite of the claim, delivery is admin-only). Two to three months including frontend.

### Recommended posture for the attorney conversation
1. Pull Pillars 1 and 4 from the filing strategy in their current form. The legal-exposure-to-implementation-evidence ratio is bad.
2. Reframe Pillar 2 around the **snippet extraction + admin labeling pipeline** that actually exists, and decide separately whether the cue-reactivation system is worth building first then filing later.
3. Reframe Pillar 3 around the **EMA-baseline plus question-generation routing** that actually exists, and decide whether the stability-driven scoring transition is worth building.
4. Use the gap-to-file sections above as the build-then-file backlog for any pillar you want to preserve.

---

## 6. Honesty check — places where the claim and the code substantially diverge

These are the divergences a patent examiner or opposing counsel could verify in an afternoon. They are stated plainly here so they are not discovered later.

- **Pillar 1, EEG:** no EEG data is ingested, stored, or used as a label anywhere in the codebase. The "primary neural" stream does not exist.
- **Pillar 1, peer consensus:** no peer-rater table, no consensus aggregation, no inter-rater weighting. The "tertiary peer" stream does not exist.
- **Pillar 1, weighting:** no `sample_weight` exists in the training loop. Logistic regression in `scripts/train_stress_classifier_baseline.py` is uniformly weighted. Asymmetric weighting cannot exist because the inputs do not exist.
- **Pillar 1, fine-tuning:** `PHASE-A0-FINDINGS.md` confirms no fine-tune has ever been promoted; production runs stock `gpt-4o-mini`; the annotation-events table is empty.
- **Pillar 2, real-time:** the backend is built to stream live metrics during recording (`routes/homework.py`, `services/realtime_audio_metrics.py`). The claim's "deliberate absence" is the opposite of what the code does.
- **Pillar 2, delivery:** stress snippets are admin-only artifacts; no user-facing endpoint returns them. The "delivered to the user later in a calm setting" half of the claim is not implemented.
- **Pillar 2, visualization:** the snippet-review payload returns three scalar features and an audio URL — no F0 trace, no energy envelope, no waveform, no pause timeline. The visualization the claim describes does not exist.
- **Pillar 2, framing:** the words "cue reactivation," "memory reconsolidation," "sympathetic activation," "asynchronous cognitive restructuring," "calm setting" appear nowhere in code, schema, or docs.
- **Pillar 3, transition rule:** the trigger is `turn_number == 4`, not a data-stability threshold. No entropy or autocorrelation or variance-of-variance is computed anywhere.
- **Pillar 3, scoring switch:** `baseline_established` is read only by question-routing code; it does not influence any scoring function. The "switch from population to intra-speaker scoring" does not happen.
- **Pillar 3, baselines unused:** the EMA baselines in `user_sniper_profile` are written but never read by any scoring service. Personalization is stored, not applied.
- **Pillar 3, drift:** the `drift_flag` mechanism is a classifier-disagreement sanity check, not a biological short-term-vs-long-term separation. No rolling-window normalization filters transients.
- **Pillar 4, AGC:** the word "AGC" does not appear in any `.py` file or doc. There is no detection, estimation, or compensation of automatic gain control.
- **Pillar 4, calibration:** no session-start characterization phase exists. The pipeline analyzes the whole recording uniformly.
- **Pillar 4, device profile:** no device metadata is captured on upload; no device-profile table or library exists.
- **Pillar 4, feature units:** all Layer A features are absolute (dB FS, Hz, ms, WPM), not relative/geometric as the claim specifies.
- **Pillar 4, invariance test:** no test data and no test assertion that the same speech on different devices yields the same features.
