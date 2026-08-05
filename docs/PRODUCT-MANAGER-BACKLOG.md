# Product-manager backlog — recurring processes and deferred unlocks

**Status:** live. Created 2026-08-05 alongside Appendix G.
**Owner:** founder (currently also the coach and the product manager).
**Why this file exists:** several decisions in Appendix G deliberately keep a **human in the loop**
rather than automating a change. A decision that requires a human and has no scheduled moment is a
decision that never happens. This is that schedule.

---

## Part 1 — Recurring processes

### PM-1 · Scientific threshold review (T1/T2)
**Cadence:** quarterly.
**Source:** Appendix G, D24 / G.5.1.

T1 and T2 benchmarks **never adapt automatically** — the point of a measured threshold is that it fires
where a study put it. But cut scores are living artefacts: educational measurement (Angoff, bookmark)
treats periodic review as mandatory, not optional.

**The review asks:**
1. For each T1/T2 benchmark — what is its fire rate over the quarter, and is the p-chart in control?
2. Where the p-chart says OUT_OF_CONTROL, is the cause the threshold, the population, or an upstream
   pipeline change? (Cross-check PSI for the same dimension — see PM-3.)
3. Does the source study still support the value, or has newer work moved it?

**The rule:** *if a scientific benchmark is failing our users, a human makes the conscious decision to
change it — never a script.* A change here is a spec amendment with a new provenance note, not a config
tweak.

**The 40-clip coach pass is a small Angoff round.** Schedule it; do not run it once and treat the result
as permanent.

---

### PM-2 · Protected-class / DIF monitoring
**Cadence:** quarterly, once stage 5 unlocks (see Part 2). Until then: **no action, the data does not
exist.**
**Source:** Appendix G, D25 / G.6.1.

DIF reports. It never acts. **The dashboard flags; the founder holds the keys.**

**The review asks:**
1. Any dimension at ETS category **C** (|MH D-DIF| ≥ 1.5 with the SE condition)? → that dimension is a
   **blocking defect**. Hold it, investigate, decide.
2. Any dimension at category **B**? → watch-list, re-check next quarter.
3. Has the sex-conditional calibration (§5.2) shown **sustained category A**? That is *evidence* the
   adjustment may be unnecessary (Appendix E-3 anticipates this) — but it does **not** release the
   one-way valve. Only a founder decision does.

**Never automate a weight change on a protected attribute**, in either direction. The one-way valve
exists because biased human labels could otherwise dissolve a correction silently; the founder-only
release exists because DIF evidence could otherwise dissolve it silently too.

---

### PM-3 · Drift triage
**Cadence:** weekly, automated alert → human triage. Live as soon as the drift layer ships.
**Source:** Appendix G, G.5 / G.7 / `PROMPT-drift-layer.md`.

Two monitors, and **the pair is the diagnosis** — neither alone tells you what broke:

| PSI (inputs) | p-chart (decisions) | Reading |
|---|---|---|
| stable | stable | healthy |
| **shifted** | stable | the population changed; thresholds may now be mistargeted |
| stable | **out of control** | **the model or pipeline changed under us** — highest priority |
| **shifted** | **out of control** | upstream change (new ASR version, VAD change, segmentation edit) |

**Triage the third row first.** A stable input distribution with drifting decisions means something in
our own code moved, and that is the failure mode this whole layer exists to catch: *being wrong all the
time without knowing it.*

**PSI thresholds:** < 0.10 stable · 0.10–0.20 investigate · ≥ 0.20 refit or retire the reference.
**p-chart:** any 3-sigma breach, or a run-rule violation, is a trigger.

**Remember what this does not tell you.** Per G.1.1, the drift layer is a **regression** detector, not a
**correctness** detector. A green dashboard means "nothing changed," never "the dimensions are right."
Correctness needs human labels.

---

### PM-4 · Capture native/non-native speaker status
**Cadence:** one-off, blocking for stage 5.
**Source:** Appendix G, G.10.

DIF cannot run without a stored subgroup flag. Status of the two we need:

| Subgroup | Status | Detail |
|---|---|---|
| **speaker sex** | ✅ **already collected** | `user_settings.speaker_sex`, migration `0223`. Values `female \| male \| prefer_not_to_say \| NULL`, where `prefer_not_to_say` is a hard opt-out distinct from NULL |
| **native / non-native** | ❌ **missing** | no field exists |

**`recordings.language` is not a substitute.** It is the *transcription* language — a native Polish
speaker presenting in English is `language=en`. Using it as a nativeness proxy would put fluent
non-natives and natives in the same stratum and hide exactly the DIF we are looking for.

Needed before stage 5 unlocks: a self-declared, optional L1 / native-speaker attribute, following the
same design as `speaker_sex` — an explicit "prefer not to say" that is distinct from never-asked, and
excluded from strata rather than folded into a group.

Both are protected-adjacent attributes. Collect only with clear consent, store separately from the
labels themselves, and never surface either in a payload. Note that `speaker_sex` already carries the
right precedent in its own migration header: *"NOT SURFACED. It selects a weight vector, full stop."*

---

### PM-5 · Copy sign-off for the 80/20 comment bands
**Cadence:** before the comment writer ships, then on every template change.
**Source:** Appendix G, D23 / G.3.1; LIVE LOOP fence.

Appendix G fixes the **rule** (80% absolute / 20% comparative-qualitative / 0% digits, and normalizing
never ranking). It does **not** sign off the **strings**.

Every template in both bands needs founder review against three tests:
1. **No digit.** Ever.
2. **No ranking.** "Most speakers find this hard" is allowed; "steadier than most speakers" is not.
3. **Not evaluative** (G.0). "Your pacing was weak this time" is self-referenced, number-free, and still
   harmful. Mastery framing is the active ingredient, not the absence of a number.

---

## Part 2 — Deferred unlocks

Each stage has a **numeric trigger**. When it fires, the build specification already exists at
`PROMPT-irt-dif-deferred.md` — no design work is repeated.

| Stage | Trigger | What unlocks | Prompt |
|---|---|---|---|
| **2 · Drift layer** | **none — build now** | PSI + p-chart + DDSketch | `PROMPT-drift-layer.md` |
| **3 · Elo/Glicko bridge** | ≥ 50 users with ≥ 3 scored recordings | online learner/item ratings from response one; the bridge to IRT without batch calibration | `PROMPT-irt-dif-deferred.md` §1 |
| **4 · Rasch / 1PL** | ≥ 150 evaluations per dimension | real item difficulty; the threshold audit becomes meaningful; item-information gating of dimension eligibility; **unidimensionality test** | §2 |
| **5 · 2PL + MH DIF** | ≥ 400 evaluations per dimension **AND** ≥ 200 users per subgroup with the flag stored (PM-4) | discrimination; the fairness audit turns on | §3 |
| **6 · Sympson-Hetter** | after stage 5 | calibrated exposure control replacing randomesque | §4 |
| **7 · Half-Life Regression** | after stage 4 | recall-decay-scheduled re-practice replacing the fixed frequency fade | §5 |

**3PL is explicitly never built** — a "guessing" parameter has no clean interpretation for a speech
dimension and costs ~1,000 responses per item to estimate badly.

### How to check a trigger

```sql
-- stage 3
SELECT COUNT(*) FROM (
  SELECT user_id FROM v2_sessions WHERE analysis_state = 'scored'
  GROUP BY user_id HAVING COUNT(*) >= 3
) t;

-- stages 4 and 5
SELECT dimension_id, COUNT(*) AS evaluations
FROM dimension_evaluations GROUP BY 1 ORDER BY 2;
```

**A note on which constraint binds.** These triggers count **machine evaluations**, not coach labels.
They are gated on **user volume**, not on the ~15 effective labels/week that binds the rest of SPEC §1 —
a different and much more favourable constraint. Do not conflate the two when planning.

---

## Part 3 — Carried from earlier rounds

| Item | Status |
|---|---|
| **Migration `0246`** `add_state_generic_ratings.sql` | **must run before PR #346 merges.** Idempotent, no drops. Late = coach labels silently fail to save |
| **The cut** — retire the legacy binary instrument | approved (D22); queued as **four additive commits**, not one pass: add alongside → update test doubles → swap readers → rewrite behaviour tests |
| **Corpus pull** for `r̂` and `φ̂` (hedge/booster/tic base rates) | founder-owned; unblocks the verbal-CONF extractor (D20/D21) |
| **§13 deployment channel** — B2C vs B2B | **open.** Two legal constraints now attach to B2B: EU AI Act Art. 5(1)(f) and CRA 1991 §106 |
