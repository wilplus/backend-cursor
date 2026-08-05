# PROMPT — IRT, CAT and DIF (deferred; do not execute until a trigger fires)

**Last updated:** 2026-08-05.

**Status:** written in advance, deliberately not scheduled.
**Spec:** `SPEC-APPENDIX-G-telemetry.md` §G.1, §G.4, §G.6, §G.10. Triggers: `PRODUCT-MANAGER-BACKLOG.md`
Part 2.

**Why this file exists now.** The triggers below are volume milestones that may fire months apart. If
the design work waits until a trigger fires, it gets done under time pressure and the reasoning in
Appendix G has to be rediscovered. The specification is therefore written while the reasoning is fresh
and parked until the numbers arrive.

**Before executing any section: verify the trigger with the SQL in the backlog.** Building a stage early
produces a precisely calibrated wrong answer — every model here needs its sample size to mean anything.

**Read first, every time:** §G.1.1. IRT on machine decisions audits **targeting and redundancy, not
validity.** Nothing in this file tells you a dimension measures something real.

---

## §1 · Elo/Glicko bridge
**Trigger:** ≥ 50 users with ≥ 3 scored recordings.

> Implement online learner/item rating updates (Pelánek) so ability and difficulty estimates exist from
> response one, without batch calibration. Both ratings update after every evaluation; new users and new
> dimensions join gracefully with a default rating and a high uncertainty term.
>
> - Per-**dimension** ability. Never a pooled global ability — Appendix B.0 makes expertise per-dimension
>   and B.6 lists global-level leakage as a failure mode.
> - Learning rate `k` **may** be global, shrunk toward the population:
>   `k_user = w·k_observed + (1−w)·k_population`, `w` rising with `n_attempts`.
> - Noisier than IRT. It is a **bridge**, not a destination — everything it produces is internal, and no
>   population claim may be made from it (`n_gate` in §G.9 still applies and Elo does not satisfy it).

## §2 · Rasch / 1PL
**Trigger:** ≥ 150 evaluations per dimension (30 is the bare minimum for ±1 logit; 150 gives ±0.5).

> Calibrate item difficulty `b` per dimension from the full `dimension_evaluations` response matrix.
>
> **Deliverables in priority order:**
> 1. **Unidimensionality test — do this first and report it prominently.** If a single θ explains most of
>    the variance across all dimensions, **our N dimensions are measuring one thing** and the table is
>    redundant. This is the highest-value finding available at zero label cost, and it is the one the
>    original brief never asked for. Report the variance explained by the first factor.
> 2. Item difficulty `b` per dimension, with SE.
> 3. **Mistargeting report:** any dimension whose `b` sits far outside the θ distribution — everyone
>    passes (no information) or everyone fails (we are blaming users for a bad threshold).
> 4. Item information `I(θ)`, used to gate dimension eligibility by ability band — the computed
>    replacement for Appendix B.2's guessed "3–5 dimensions eligible for a NOVICE."
>
> **Do not** feed `b` back into a T1 or T2 benchmark. Per D24 those never adapt; a mistargeted T1 is a
> PM-1 agenda item for a human, not an automatic correction.

## §3 · 2PL + Mantel-Haenszel DIF
**Trigger:** ≥ 400 evaluations per dimension **AND** ≥ 200 users per subgroup with the flag stored.

> Add discrimination `a` (2PL), then run the fairness audit.
>
> **Subgroup availability — check before starting:**
> - **speaker sex: already collected.** `user_settings.profile_sex` (migration `0223`), values
>   `female | male | prefer_not_to_say | NULL`. `prefer_not_to_say` is a hard opt-out and must be
>   **excluded from DIF strata**, never folded into either group.
> - **native/non-native: NOT collected.** `recordings.language` is the *transcription* language — a
>   native Polish speaker presenting in English is `language=en`. PM-4 must ship first.
>
> **Method:** Mantel-Haenszel with θ deciles as the matching strata. Logistic regression
> (Swaminathan & Rogers) additionally where non-uniform DIF is suspected — MH only detects uniform DIF,
> and a dimension that penalises a group *only at low ability* is exactly the case MH misses.
>
> **ETS classification** on MH D-DIF = −2.35·ln(OR):
> ```
> A  negligible       |D-DIF| < 1, or not significant at p < .05
> B  slight/moderate  significant AND |D-DIF| >= 1
> C  moderate/large   |D-DIF| >= 1.5  AND  (|D-DIF| - 1) / SE > 1.645
> ```
> Implement the **full** C rule including the SE term. The triage-only form in the original brief
> (magnitude without the SE condition) over-flags on small strata.
>
> **D25 — this reports, it never acts.** A category C finding holds the dimension and raises a PM-2
> agenda item. A sustained category A on the sex-conditional calibration is *evidence* the §5.2
> adjustment may be unnecessary (Appendix E-3 anticipates this) — it does **not** release the one-way
> valve. **No automated weight change on a protected attribute, in either direction, ever.**

## §4 · Sympson-Hetter exposure control
**Trigger:** after §3.

> Replace randomesque top-k selection with simulation-calibrated per-item exposure probabilities.
> Realised exposure ceiling ~0.3 at a given θ; ~0.4 for middle-difficulty high-discrimination items,
> which need the strictest throttling.
>
> Until this ships, **randomesque (k = 3) is the exposure control** and it is also the exploration quota
> — do not build a second, separate randomisation on top of it.

## §5 · Half-Life Regression
**Trigger:** after §2.

> Settles & Meeder (ACL 2016): `p = 2^(−Δ/h)`, `h = 2^(Θ·x)` learned from practice history. Schedule
> re-practice when predicted recall crosses a threshold rather than on a fixed calendar. Replaces
> Appendix B's frequency fade and upgrades Appendix A's spaced-rehearsal scheduler.

---

## Constraints that apply to every section

- **AC-9.** θ, `b`, `a`, percentiles, D-DIF and every derived quantity are **internal**. None may enter a
  client-facing schema, payload or comment. The §G.9 contract test must keep passing.
- **D24.** T1/T2 thresholds never adapt, whatever IRT says. T3 and CORPUS_REL may.
- **D25.** DIF reports; the founder releases the valve.
- **`n_gate(p)`** (§G.9) gates every population-anchored claim: `max(200, 10/min(p,1−p))`. A 99th
  percentile claim needs ~1,000 in cohort. Below the gate, strengths come from **within-user ranking
  across dimensions** — which per §G.2.1 is the permanent answer for every dimension without a T1/T2
  absolute bar, not a stopgap.
- **3PL is never built.** No clean interpretation of "guessing" for a speech dimension, and ~1,000
  responses per item to estimate it badly.

## Expected filter verdict (for whoever executes this later)

```
VERDICT:  DEFER  ->  JUSTIFIED-SCAFFOLDING once the stated trigger has fired
CATEGORY: SCAFFOLDING
WHY:      serves adaptive pacing and fairness auditing. Neither is per-slide transcription nor
          best-per-slide ranking, so it is not F1 by mechanism. It becomes buildable — not urgent —
          when its volume trigger fires. Executing before the trigger is R11 ("it's a foundation")
          with the sample size to prove it.
REDIRECT: while deferred, the F1-advancing work is the drift layer (PROMPT-drift-layer.md), which
          guards the measurement pipeline F1 piece (a) depends on and needs no volume at all.
```
