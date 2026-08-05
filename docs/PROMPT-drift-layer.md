# PROMPT — build the drift layer (execute now)

**Status:** ready to execute. No trigger; this is stage 2 of Appendix G.10 and it is unblocked.
**Spec:** `SPEC-APPENDIX-G-telemetry.md` §G.5, §G.7, §G.9. Backlog process: PM-3.
**Cost:** zero human labels. Works at any n.

---

## Paste-ready prompt

> Build the drift-monitoring layer specified in `docs/SPEC-APPENDIX-G-telemetry.md` (§G.5, §G.7, §G.9).
> Read that appendix and `docs/SPEC.md` §0 first. Run the WILLAB DECISION FILTER before starting and
> emit the verdict block.
>
> **Context you must verify before writing code — the spec's SQL is written against a table that does
> not exist.** `dimension_evaluations` is referenced throughout Appendix G but there is no such table in
> `migrations/`. Per-dimension numeric measures are currently scattered as individual columns
> (`wpm`, `pause_ms`, `energy_ratio`, `confidence_score`, `pitch_variance_ideal`, …) across several
> tables. **Task 1 is therefore to create the normalised evaluations table**, not to query one.
>
> ### Task 1 — `dimension_evaluations`
>
> New migration, idempotent, appended to `migrations/manifest.txt` (a migration not listed there never
> runs — `test_migrations` enforces this).
>
> One row per `(recording_id, dimension_id)`:
>
> ```sql
> CREATE TABLE IF NOT EXISTS public.dimension_evaluations (
>     id              BIGSERIAL PRIMARY KEY,
>     recording_id    TEXT NOT NULL,
>     session_id      TEXT NULL,
>     user_id         TEXT NOT NULL,
>     dimension_id    TEXT NOT NULL,
>     raw_value       DOUBLE PRECISION NULL,   -- the measure in its own units
>     decile          SMALLINT NULL,           -- 1..10 vs the frozen reference; PSI reads this
>     fired           BOOLEAN NOT NULL,        -- did the benchmark trigger
>     benchmark_tier  TEXT NOT NULL,           -- 'T1'|'T2'|'T3'|'CORPUS_REL' — the p-chart filters on this
>     benchmark_version TEXT NOT NULL,         -- so a threshold change is separable from a drift
>     window_class    TEXT NULL,               -- Appendix F: FRAME|UNIT|CYCLE|PROPORTIONAL|SESSION
>     n_units         INTEGER NULL,            -- denominator actually used (Appendix F.3)
>     insufficient_data BOOLEAN NOT NULL DEFAULT false,   -- F.5 is first-class, not a null
>     evaluated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
> );
> ```
>
> **`benchmark_version` and `insufficient_data` are load-bearing.** Without the first, changing a
> threshold looks identical to the population drifting. Without the second, "we could not compute this"
> is indistinguishable from "it did not fire," and PSI silently reads the gap as a distribution shift.
>
> Backfill is **not** required. Start collecting forward; the frozen reference (Task 2) is built from
> whatever accumulates.
>
> ### Task 2 — frozen reference distribution
>
> `reference_distribution (dimension_id, decile, pct, version, frozen_at)`. Populate `version='frozen_v1'`
> from the first 4 complete weeks of `dimension_evaluations`. **Freeze it and never recompute in place** —
> PSI against a moving reference always reads ~0 and the monitor becomes decorative. A new reference is a
> new `version` row, and `PROMPT`-driven refits (PSI ≥ 0.20) mint `frozen_v2`, keeping v1 readable.
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
> 1. Migration written, idempotent, in `manifest.txt`, and **called out for the founder to run** —
>    "on main" ≠ "run in prod".
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
