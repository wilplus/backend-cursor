# PROMPT — build the drift layer (execute now)

**Last updated:** 2026-08-05.

**Status:** ready to execute. No trigger; this is stage 2 of Appendix G.10 and it is unblocked.
**Spec:** `SPEC-APPENDIX-G-telemetry.md` §G.5, §G.7, §G.9. Backlog process: PM-3.
**Cost:** zero human labels. Works at any n.

---

## Paste-ready prompt

> Build the drift-monitoring layer specified in `docs/SPEC-APPENDIX-G-telemetry.md` (§G.5, §G.7, §G.9).
> Read that appendix and `docs/SPEC.md` §0 first. Run the WILLAB DECISION FILTER before starting and
> emit the verdict block.
>
> **The schema already exists — do not design it.** Appendix G's audit queries were written against a
> `dimension_evaluations` table that did not exist; per-dimension measures were scattered as individual
> columns (`wpm`, `pause_ms`, `energy_ratio`, `confidence_score`, `pitch_variance_ideal`, …) across
> several tables. Both tables are now written:
>
> | Migration | Creates | Status |
> |---|---|---|
> | `0247 add_dimension_evaluations.sql` | `dimension_evaluations` + `reference_distribution` | **on the branch; must be run in prod** |
> | `0248 add_profile_native_language.sql` | `user_settings.profile_native_language` (DIF stratum, deferred use) | on the branch; not needed for this build |
>
> **Read `migrations/add_dimension_evaluations.sql` before writing any query.** Four properties of that
> schema constrain the code and are not negotiable:
>
> 1. **`fired` is NULLABLE, and NULL iff `insufficient_data`** — enforced by
>    `ck_dimension_evaluations_fired_exclusive`. Writing `false` for a non-computation would book it as a
>    real negative, inflating the p-chart denominator and deflating every fire rate. Any INSERT must set
>    exactly one of the two states; any aggregate must decide explicitly how it treats the NULL rather
>    than letting SQL's default swallow it.
> 2. **Uniqueness is `(recording_id, dimension_id, benchmark_version)`.** Re-evaluating under the same
>    version replaces; a new version adds a row. This is what lets the p-chart group by
>    `benchmark_version` and see a threshold change as a discontinuity rather than as drift.
> 3. **`reference_distribution` blocks `UPDATE` by trigger.** A refit inserts `frozen_v2`; it never edits
>    `frozen_v1`. Do not write code that tries to update it — it will raise, and that is the point.
> 4. **RLS is ON with no policies** on both tables: service-role only. Nothing here is user-readable.
>
> ### Task 1 — populate `dimension_evaluations`
>
> Write the evaluation rows at the point where each dimension is scored. No backfill: start collecting
> forward. Every row needs its `benchmark_tier`, `benchmark_version`, `window_class` and the `n_units`
> actually used as the denominator (Appendix F.3) — a rate computed over a different unit count than the
> benchmark assumes is the exact error F.3 exists to catch, and it is only auditable if `n_units` is
> stored at write time.
>
> ### Task 2 — freeze the reference
>
> Populate `reference_distribution` at `version='frozen_v1'` from the first 4 complete weeks of
> `dimension_evaluations`, setting `n_at_freeze` so a later reader knows how much data the baseline rests
> on. PSI against a moving reference always reads ~0 and the monitor becomes decorative *while appearing
> to work* — the UPDATE trigger makes that failure loud rather than silent.
>
> ### Task 3 — `services/drift_monitor.py` (pure, no I/O, unit-tested)
>
> Mirror the shape of `services/state_ratings.py`: module docstring citing the spec sections, pure
> functions, no DB.
>
> ```python
> def psi(current: dict[int, float], reference: dict[int, float]) -> float
> def psi_verdict(value: float) -> str      # STABLE | MODERATE_SHIFT | MAJOR_SHIFT_REFIT
> def p_chart(weekly: list[dict]) -> dict   # {centre_line, ucl, lcl, points:[{wk,p_hat,signal}]}
> def triage(psi_verdict: str, chart_signal: str) -> str   # the PM-3 2x2
> ```
>
> **Edge cases that must be handled, not assumed away:**
> - a decile with `pct = 0` in either distribution — `ln(0)` is `-inf`. Use additive smoothing
>   (`pct = max(pct, 0.5/n)`) and document the choice; do not silently drop the decile, which
>   understates PSI.
> - `n_bar` small — the p-chart's control limits widen as `1/√n`. Below n = 20 per week, report
>   `INSUFFICIENT_N` rather than a limit nobody should act on.
> - `CORPUS_REL` and `T3` rows **must be excluded from the p-chart**. Their fire rate is pinned by
>   construction (§G.5) — a 10th-percentile threshold fails 10% of the time definitionally, and charting
>   it produces a monitor that can never signal. Filter on `benchmark_tier IN ('T1','T2')`.
>
> ### Task 4 — the weekly job and the triage output
>
> Emit the PM-3 2×2 as the primary output, not two independent numbers:
>
> | PSI | p-chart | verdict |
> |---|---|---|
> | stable | stable | `HEALTHY` |
> | shifted | stable | `POPULATION_MOVED` |
> | **stable** | **out of control** | **`PIPELINE_CHANGED` — highest priority** |
> | shifted | out of control | `UPSTREAM_CHANGE` |
>
> `PIPELINE_CHANGED` is the one this layer exists for: a stable input distribution with drifting
> decisions means our own code moved. Surface it loudest.
>
> ### Task 5 — storage
>
> Use **DDSketch** for the running quantiles (§G.7): formal relative-error guarantee at *every* quantile
> including the extremes, and mergeable across shards. t-digest is the fallback if a dependency is
> unacceptable. Do not store raw values for every dimension.
>
> ### Constraints — all hard
>
> - **AC-9.** Nothing built here is user-facing. No PSI value, decile, fire rate or control limit may
>   enter any client-facing schema or copy. This is an internal audit surface only.
> - **Never break the live loop.** New tables only; no drops, no column removals, no changes to the
>   record→transcribe→coach→read path.
> - **Migrations idempotent** (`IF NOT EXISTS`) and **listed in `manifest.txt`**.
> - The module is **pure and unit-tested** — no DB inside `drift_monitor.py`, following
>   `services/state_ratings.py`.
> - Do **not** build IRT, Elo, DIF, adaptive thresholds or any population-facing claim. Those are
>   deferred (`PROMPT-irt-dif-deferred.md`) behind the triggers in `PRODUCT-MANAGER-BACKLOG.md`.
>
> ### Definition of done
>
> 1. `dimension_evaluations` populated at scoring time, with `n_units` and `benchmark_version` set on
>    every row, and `fired`/`insufficient_data` respecting the XOR constraint.
> 2. `services/drift_monitor.py` pure and unit-tested, including the zero-decile and small-n cases.
> 3. The three queries from §G.9 working against the real table, with `CORPUS_REL`/`T3` excluded from
>    the p-chart.
> 4. The 2×2 triage as the job's headline output.
> 5. A short note in the PR body stating explicitly: **this is a regression detector, not a correctness
>    detector** (§G.1.1). A green dashboard means nothing changed — not that the dimensions are right.

---

## Expected filter verdict

```
VERDICT:  ADVANCE-F1-SURFACE
CATEGORY: F1-SURFACE
WHY:      PSI + p-chart guard the transcription/measurement pipeline that F1 piece (a) depends on. An
          ASR upgrade, VAD change or segmentation edit that shifts word bucketing shows up here and
          nowhere else. Hardens an existing F1 surface; needs zero labels, so it contends with nothing.
REDIRECT: n/a.
```
