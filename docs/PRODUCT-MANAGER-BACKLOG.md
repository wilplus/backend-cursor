# Product-manager backlog — recurring processes and deferred unlocks

**Last updated:** 2026-08-06.

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
| **speaker sex** | ✅ **collected** | `user_settings.profile_sex`, migration `0223`. Values `female \| male \| prefer_not_to_say \| NULL`, where `prefer_not_to_say` is a hard opt-out distinct from NULL |
| **native language (L1)** | ⚠️ **column written, not yet captured** | `user_settings.profile_native_language`, migration `0248` (2026-08-05). Column exists once the migration runs; **no UI asks for it yet** — that is the remaining work |

**Nativeness is derived, never stored as a boolean.** *"Is this speaker native?"* has no user-level
answer — a native Polish speaker is native presenting in Polish and non-native presenting in English.
So the column holds the speaker's **L1**, and nativeness for a recording is:

```
native  <=>  user_settings.profile_native_language = recordings.transcription_language
```

This is also strictly more informative than a boolean: it permits stratifying by language family later,
which is the level at which transfer effects actually operate.

**`recordings.language` is not a substitute.** It is the *transcription* language — a native Polish
speaker presenting in English is `language=en`. Using it as a nativeness proxy would put fluent
non-natives and natives in the same stratum and hide exactly the DIF we are looking for.

Needed before stage 5 unlocks: a self-declared, optional L1 / native-speaker attribute, following the
same design as `profile_sex` — an explicit "prefer not to say" that is distinct from never-asked, and
excluded from strata rather than folded into a group.

Both are protected-adjacent attributes. Collect only with clear consent, store separately from the
labels themselves, and never surface either in a payload. Note that `profile_sex` already carries the
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

### PM-6 · The verbal corpus — parked on speaker diversity, not on analysis
**Cadence:** check the trigger when new speakers arrive. **No further analysis until then.**
**Source:** SPEC D20/D21; `scripts/corpus_base_rates.py`.

**Trigger to resume:** **≥ 10 distinct speakers AND ≥ 50,000 words** from the `recordings`
source. The script prints the speaker count and refuses to call the numbers a population below 3.

**What happened.** The corpus pull ran and worked. It read 412 transcripts / 41,551 words — and
they are essentially **one speaker** (the founder, recording tests). So:

- the rates are **one person's rates**, not a population;
- a D20 prior fitted here would shrink every other user's posterior toward the founder's speech;
- `CORPUS_REL` thresholds built on it would be self-referential.

The tell was already in the output and was missed for a round: with many speakers at different
rates, **pooled φ sits far above within-speaker φ** — that gap *is* the between-speaker term.
Measured 5.61 pooled against 6.12 within, a 10% gap in the wrong direction, which is what a
single-speaker corpus looks like.

**Do not keep re-running it.** More iterations on the same data reproduce one person's speech with
better arithmetic, and each round invites locking a number that cannot be right.

**What is NOT blocked by this** — worth stating, because it is most of the value:

| | |
|---|---|
| the **drift layer** | **unaffected.** PSI and the p-chart watch for the *pipeline* changing — an ASR upgrade, a VAD change shifting word bucketing. One speaker's distribution moving still detects that, arguably more cleanly. This is the piece guarding F1 |
| the three lexicons | **validated.** The strict top-terms read as coherent linguistics — `i think / maybe / a little bit / i suppose` for HEDGE, `uh / um / mmm / basically` for TIC |
| the D20 machinery | correct and tested; only its *prior* is unfitted |
| the ~2,400-word window floor | holds as a **lower bound** at φ=1, which is 68× a snippet — so "never a per-snippet intervention" is safe regardless of what the real numbers turn out to be |

**The better unblock than waiting: the cold-start / bootstrap lane.** `training_import` is the coach
labelling external audio — other people's speech. That is speaker diversity for the acoustic side
**and**, if those imports are transcribed, corpus diversity for the text side. Two blockers, one
lane.

---

### PM-7 · The OFF list — dimensions switched off by decision *(added 2026-08-06)*

**Cadence:** reviewed at PM-1 (quarterly), and whenever a re-enable condition is claimed to be met.
**Source:** `services/dimension_registry.py` — `enabled` / `disabled_reason`, surfaced by `registry.disabled()`.

**Why this exists.** "Off because the numbers were wrong" and "off because we haven't built it" are
different states, and a reader who cannot tell them apart will eventually build the thing that was
deliberately switched off. The registry now separates them: `computed=False` is not-built,
`enabled=False` is off-by-decision, and `validate()` rejects an off with no reason. `can_fire()` is
the single gate — it requires a threshold **and** that nobody switched the dimension off. Measurement
is deliberately *not* gated: a disabled dimension keeps writing telemetry, because that telemetry is
what would justify a threshold worth re-enabling it for.

| Dimension | Off since | Why | Re-enable condition |
|---|---|---|---|
| `pronoun_profile` (D7a / D7b) | 2026-08-06, founder | **The threshold cannot resolve its own band.** Steffens & Haslam separate winners (12.7/1,000w) from losers (7.4) — a gap of 5.3. The contract fires below 8.0 and clears above 10.0: a band of **2.0**. SD of a rate ≈ r/√k, so at the row's own 200-word precondition SD ≈ **7.1**/1,000w and the decision is whether the speaker said *we* once or twice. At 1,000 words ≈ 3.2, still wider than the band. First resolves near **10,000 words (~77 min)** — and that is the Poisson floor, before any clustering | **D20's Beta-Binomial posterior** against the corpus prior, firing on posterior mass. **Not** a larger *n* — raising the word gate does not fix a band narrower than the sampling error, it just moves the cliff |
| `conf` (E10 / CONF) | pre-existing | `voice_confidence` is ranking-inert until validated (ENGINE-MAP E10, flag off) | Validation against the coach panel — see PM-1 |

**The re-enable rule:** a dimension comes back on the way it went off — by a founder decision naming
the condition that changed, recorded in `disabled_reason` being *removed* rather than edited around.
`validate()` fails a `disabled_reason` left behind on an enabled dimension, so the two cannot drift.

**Nothing can fire today regardless** — no live dimension has a `fire_at` at all, so `can_fire()`
returns False across the board. The off-list is what stays off *after* thresholds land.

---

### PM-8 · Persist the experiment arms — **BLOCKING on the manager going live** *(locked 2026-08-06)*

**Cadence:** one-time, before the manager is wired to the scoring path. Then reviewed at PM-1.
**Source:** Appendix H.12; decisions log §B (`γ_control`, intervention randomisation).
**Status:** **LOCKED.** Not a nice-to-have and not deferrable past the manager going live.

**Running the controls without persisting the arms is strictly WORSE than not running them at all.**

That is the whole reason this is locked rather than filed. Once the manager is live, 12% of (user, dimension) pairs receive nothing and 20% of notes that won triage are deliberately withheld. Those users are paying a real cost — less feedback — and the only thing that buys is the ability to make a causal claim later. **If the arm assignment is not stored next to the outcome, they pay the cost and we get nothing back**, and it looks from the outside exactly like a working experiment. That is the most expensive failure mode available here: invisible, ongoing, and unrecoverable after the fact.

**What `arbitrate()` already returns and something must store:**

| Field | Why it cannot be reconstructed later |
|---|---|
| `control_held` | Which dimensions were held out this session |
| `withheld` | Which notes won and were deliberately not shown — **the untreated condition**, and the only record that it occurred |
| `counterfactual` | What would have surfaced without the ε_explore swap |
| `exploration` | Whether this session's note was a rank-2 probe |
| `arms.*` | The rates **and both salts** in force at the time |

**The salts are the part most likely to be dropped, and the one that makes the data un-analysable without it.** Assignment is a pure function of `(salt, user_id, dimension)`, so a row written under `willab-gamma-v1` and a row written after a salt change belong to **two different experiments**. Without the salt stamped per row there is no way to tell them apart afterwards — the same defect as `benchmark_version` in the evaluation key (D30b): without it, a threshold change and population drift are indistinguishable.

**Minimum shape.** One row per (session, dimension) considered — not per surfaced note, or the untreated arm has no rows at all and the table records only the treatment group:

```
session_id · user_id · dimension_id · arm (TREATED | CONTROL | WITHHELD | EXPLORE)
priority · would_have_surfaced (bool) · surfaced (bool)
control_salt · withhold_salt · gamma · withhold_rate
evaluated_at
```

**Do not reuse `dimension_evaluations`.** That table is *measurements* (Appendix G); this is *decisions and arms*. Joining them is right; merging them puts two different grains and two different retention arguments in one place.

**The check that this is working:** `SELECT arm, COUNT(*) ... GROUP BY arm` should show roughly 12% CONTROL and 20% WITHHELD among what would have surfaced. **An empty CONTROL arm means the controls are running and the record is not** — the exact silent failure this item exists to prevent.

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
| **Migration `0247`** `add_dimension_evaluations.sql` | **must run before the drift layer ships.** Creates `dimension_evaluations` + `reference_distribution`. Safe to run early — nothing writes them until the drift build lands |
| **Migration `0248`** `add_profile_native_language.sql` | run any time; not urgent. The column is inert until a UI asks for L1 (PM-4) |
| **The cut** — retire the legacy binary instrument | approved (D22); queued as **four additive commits**, not one pass: add alongside → update test doubles → swap readers → rewrite behaviour tests |
| **Corpus pull** for `r̂` and `φ̂` (hedge/booster/tic base rates) | **PARKED — see PM-6.** The measurement ran; the corpus turned out to be one speaker |
| **§13 deployment channel** — B2C vs B2B | **open.** Two legal constraints now attach to B2B: EU AI Act Art. 5(1)(f) and CRA 1991 §106 |
