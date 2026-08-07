# OPS — feature flags and what is waiting on a release decision

Every boolean flag the backend reads, what it gates, and — for the ones that
are OFF — **what has to happen before they go on**. A flag with no owner and
no exit condition becomes permanent by accident: nobody can reconstruct what
it was protecting against, so nobody dares flip it.

Flags live in Railway environment variables. A flip is a config change, not a
deploy — reversible in seconds, and scoped to one environment. That is why the
code defaults are conservative and mostly left alone.

**Reading a row:** `default` is what the code returns with the variable
*absent*. An explicit `0` in the environment always wins.

---

## ⚠ Waiting on a decision

### `MANAGER_CONTROLS_ENABLED` — default OFF

**Founder 2026-08-07: stays off until the locking/rehearsal loop is built.**

Arms the manager engine's three randomisations (`services/manager_engine.py`,
Appendix H). This is **not a safety dial — it starts a live experiment**, and
the unit is the *lane*:

| arm | rate | effect on a real user |
|---|---|---|
| `gamma_control` | 12% | that (user, lane) pair receives **nothing from that lane, permanently** |
| `intervention_randomisation` | 20% | a note that WON the budget is deliberately **not shown** |
| `epsilon_explore` | 10% | rank 2 surfaces instead of rank 1 |

**Two things must ship in the same change as the flip, not after it:**

1. **Persist `arm_rows()`.** `manager_engine.arm_rows()` and
   `db.record_intervention_arms()` both exist and nothing calls them. The
   module is explicit that running the arms without storing them is *strictly
   worse than not running them*: users pay the cost in withheld feedback, and
   with no arm stored next to the outcome no causal claim is recoverable —
   while it looks from the outside exactly like a working experiment.
2. **Pass a `roll`.** `intervention_candidates.select()` passes `roll=None`,
   so `arbitrate()` skips the exploration branch entirely. The quota is not
   running today. That is deliberate (the adapter is pure), but it means
   "10% exploration" is currently 0% and the flag alone does not change it.

**Before flipping, also settle:** the arms would be keyed on `lane:polish`,
`lane:wording` etc., **not** on registry dimensions. That is an RCT on LLM
lanes, which is a different question from "does feedback on `wpm` work". If
the intent is the latter, wait for a dimension that `can_fire()`.

**Salts are versioned** (`CONTROL_SALT`, `WITHHOLD_SALT`). Changing one
reshuffles every assignment and splices two incompatible experiments together,
so a salt change is a new experiment with a new name, never an edit.

---

## Flags that are ON by default

| flag | gates |
|---|---|
| `LLM_USAGE_ENABLED` | LLM call accounting |
| `PIECES_CANONICAL_ENABLED` | pieces as the canonical document unit |
| `SENTENCE_BOUNDARY_SPLIT_ENABLED` | sentence-boundary piece splitting |
| `VOICE_CONFIDENCE_ENABLED` | the voice-confidence measure (computed) |
| `VOICE_CONFIDENCE_SEX_INFERENCE_ENABLED` | its speaker-sex normalisation |

---

## Flags that are OFF by default

Off for different reasons, and the difference matters. "Not built on the other
side yet" is not the same as "we turned this off because it was wrong".

| flag | gates | why it is off |
|---|---|---|
| `LIVING_TRANSCRIPT_ENABLED` | the document IS the full transcript; also the entire `changes` block | **already ON in prod.** The code default stays 0 because flipping it also swaps the document source for every environment at once |
| `MASTER_DOCUMENT_ENABLED` | the persistent master document + block upgrade offers | needs a migrated skeleton; degrades gracefully when off |
| `MOMENT_SUGGESTIONS_ENABLED` | the star machinery the other suggestion lanes reuse | prerequisite for the two below |
| `POLISH_AS_SUGGESTIONS_ENABLED` | serve verbatim text + offer the polish as approvable stars | on top of `MOMENT_SUGGESTIONS_ENABLED` |
| `DELIVERY_STARS_ENABLED` | delivery advice stars | |
| `STRUCTURAL_STARS_ENABLED` | structural advice stars | |
| `BLOCK_VARIANTS_ENABLED` | the per-block variants picker | |
| `INSTANT_IDEAL_TEXT_ENABLED` | machine draft served free at take 3 | needs FE variant handling (deploy order: BE → FE → flip) |
| `ASYNC_ANALYSIS_ENABLED` | the async analysis queue | see `OPS-PIPELINE-QUEUE-RUNBOOK.md` |
| `COACH_PREFILL_ENABLED` | coach review prefill | |
| `DELIVERY_ALIGNMENT_ENABLED` | delivery alignment pass | |
| `TAKE_ALIGNMENT_ENABLED` | cross-take alignment pass | |
| `TOKEN_PRICING_ENABLED` | token-priced credits | see `PRICING-TOKENS-PLAN.md` |
| `VOICE_CONFIDENCE_RANKING_ENABLED` | voice confidence as a RANKING term | **off by decision** — ranking-inert until validated (`dimension_registry`: `conf`, `disabled_reason`) |

---

## Retired

| flag | what happened |
|---|---|
| `KEY_POINTS_ENABLED` | **removed 2026-08-07.** The presentation-mode cue sheet was deferred: a highlighted verbatim opening phrase is indistinguishable on screen from an intervention that explains nothing. The call site is gone, so the variable does nothing — deleted from Railway. `services/key_points.py` and its tests are kept; re-wiring needs the E-2 full↔key-words toggle first |

---

## When you add a flag

Put it in this table in the same commit. A flag that only exists in
`os.getenv` is a flag nobody will find when they are deciding what to turn on,
and the reason it was off will be gone long before the flag is.

If it is OFF, write the **exit condition** — what has to be true to turn it on
— not just what it gates.
