# Appendix G — Silent Population Telemetry

**Last updated:** 2026-08-05.

**Status:** locked 2026-08-05. Normative.
**Companion to:** SPEC.md v3, Appendix B (progression), Appendix D (benchmarks), Appendix F (windows).
**Source:** founder-supplied research brief, amended by six conflict resolutions found in review (G.11).

**What this appendix is for, in the founder's words:** *"ensure the product is not wrong all the time
without knowing it, and that we are able to spot the hidden patterns even if not explicitly surfacing
them to the user."*

That sentence contains two different jobs, and G keeps them separate throughout:

| Job | Mechanism | Human labels needed | Buildable now |
|---|---|---|---|
| **Know when we break** | drift layer — PSI + p-chart | **zero** | **yes** |
| **Spot hidden patterns** | IRT structure, DIF fairness | zero for IRT, subgroup flags for DIF | gated on user volume |

---

## G.0 · The correction that matters most

The brief argues that hiding the percentile is what protects the user. **It contributes, but it is not
the active ingredient.**

Feedback Intervention Theory's mechanism is **attention-based**: normative feedback harms by diverting
attention from the task to the self. A 2021 goal-framing meta-analysis found a self-referenced standard
alone did **not** reliably outperform performance framing — what carried the effect was **task-focused,
mastery-oriented content**.

**Consequence for our fence.** AC-9 bans the *number*. It does not ban:

> "your pacing was weak this time"

which is self-referenced, number-free, AC-9-compliant, and still harmful. **AC-9 is necessary and not
sufficient.** See D27 for the companion rule this creates.

Supporting evidence, retained from the brief:
- **SDT** (Deci, Koestner & Ryan 1999): tangible/expected rewards undermine intrinsic motivation at
  **d ≈ −0.36 to −0.40**; *informational* verbal feedback helps at **d = 0.31–0.33**. The moderator is
  controlling vs informational framing.
- **Gamification** meta-analyses: small effect on intrinsic motivation (**g = 0.257**), leaderboards
  specifically flagged for embarrassing low performers.
- **The counter-case is weak.** "Without an external reference users can't calibrate" is undercut by the
  Dunning-Kruger literature: low performers largely fail to revise self-assessment *even when handed the
  comparison data*. Showing percentiles would not fix the calibration problem it claims to fix.

---

## G.1 · Three of the four pillars are solved problems in psychometrics

| Pillar | Established framework | What it buys |
|---|---|---|
| 4 · "is the threshold broken or is the user weak?" | **IRT** — item difficulty `b`, person ability `θ`, one scale | `b` is estimated from the full response matrix independently of any individual |
| 3 · adaptive pacing | **CAT** + exposure control | ~50% fewer items for equal precision; Sympson-Hetter/randomesque *is* the exploration quota |
| — · "does this dimension unfairly flag non-native speakers?" | **DIF** | detects an item behaving differently across groups **matched on ability**, with ETS cutoffs already defined |
| 1 · silent benchmarking | percentiles + IRT | see G.2 — the pillar with a flaw in it |

**Adopt the vocabulary.** "Item difficulty" rather than "threshold health" means a future engineer can
look up what to do.

### G.1.1 · What IRT can and cannot tell us — read before trusting it

Our "responses" are **machine evaluations** (`dimension_evaluations.fired`), not human-scored items.
This changes what the model licenses:

**It CAN detect:**
- **Mistargeting** — a `b` far from the θ distribution means everyone passes (no information) or
  everyone fails (we are blaming users for a bad threshold).
- **Redundancy.** If a single θ explains most of the variance across all dimensions, **our N dimensions
  are measuring one thing.** This is the highest-value hidden pattern available at zero label cost, and
  the original brief does not mention it. Test unidimensionality explicitly.

**It CANNOT detect:**
- **Validity.** There is no external criterion in the loop. IRT cannot tell us a dimension measures
  anything real — only how its threshold sits relative to our own population.

**Therefore: PSI, the p-chart and IRT are collectively a _regression_ detector, not a _correctness_
detector.** They catch the pipeline changing under us. Correctness requires human labels, which is the
~15/week bottleneck (SPEC §1). Do not let a green dashboard be read as "the dimensions are right."

---

## G.2 · Pillar 1 — silent benchmarking, and the flaw in it

**A percentile is not a quality statement.** If the whole population paces badly, the 99th percentile
still paces badly — and we would have told a user their greatest strength is something they are
objectively poor at, and trained them to protect it.

**Dual gate.** A dimension may be named a strength only if both hold:

```python
is_strength = (percentile >= P_HIGH) and (absolute_score >= ABS_ADEQUATE)
```

### G.2.1 · The dual gate is unimplementable for most of our table — and that is the finding

`ABS_ADEQUATE` requires an absolute bar. Per Appendix D, most of our benchmarks are **T3 (direction
only)** or **CORPUS_REL** — no absolute bar exists to check. The gate can therefore never pass for them,
and by the gate's own logic we must not make population-anchored strength claims on those dimensions.

> **Within-user ranking across dimensions is not a cold-start stopgap. It is the permanent answer for
> every dimension without a T1/T2 absolute bar.** It needs no population at all, and it is what a coach
> would say anyway.

Strength claims are also **tail statements**, and tails are expensive (G.7). Population-anchored strength
claims sit behind `n_gate(p)` (G.9) even where an absolute bar exists.

---

## G.3 · Pillar 2 — self-relative front end

Aligns with Appendix B. Two constraints:

- **Progress is per-dimension**, matching B.0. A single global progress bar reintroduces the
  global-level leakage B.6 lists as a failure mode.
- **The internal metric is `Δ(own past)`, never `Δ(target)`.** Distance-to-target is a disguised
  normative statement — the target came from the population.

Surfacing rules for the delta are D23 (§G.3.1). The delta itself is **never rendered as a digit.**

### G.3.1 · The 80/20 comment rule (D23)

The founder's decision: measure the delta, and let the user know they are improving *and* that there is
room — without ever showing a number.

```
80%  ABSOLUTE statement       — task-focused, mastery-oriented, no comparison of any kind
20%  COMPARATIVE statement    — qualitative only, and NORMALIZING rather than RANKING
 0%  any digit, ever
```

**The distinction that makes the 20% safe.** Population language may **normalize the difficulty**. It may
never **rank the user**. Both convey "you're improving, there's room"; only the first avoids the FIT
attention-shift, because only the second is about the self.

| | Template | Why |
|---|---|---|
| ✅ **ALLOWED** | "Most speakers take a while to steady their pacing — yours is steadier than it was." | normalizes the difficulty; the comparison is to the user's own past |
| ✅ **ALLOWED** | "This is generally the hardest part to control, and you're holding it longer than before." | normalizes; self-referenced progress |
| ❌ **BANNED** | "Your pacing is steadier than most speakers'." | ranks the user against the population |
| ❌ **BANNED** | "You're in the top group for pacing." | rank without a number is still rank |
| ❌ **BANNED** | "8% steadier than last week." | digit |
| ❌ **BANNED** | "Your pacing was weak this time." | G.0 — evaluative, self-referenced, and still harmful |

**Implementation constraints:**
1. The 80/20 choice is **seeded on `(user_id, dimension_id, session_id)`** so a re-render shows the same
   comment. An unseeded random re-roll makes the system look inconsistent to the only person who reads
   every one of its outputs.
2. The comparative slot is **suppressed until a self-baseline exists** — B.3's `M ≥ 5` attempts and 3
   consecutive scored attempts. Before that there is no delta to speak qualitatively about, and the
   template would be asserting a trend from noise.
3. **Every template string in both bands requires founder sign-off** before it ships (LIVE LOOP). This
   appendix fixes the *rule*; it does not sign off the *copy*.

---

## G.4 · Pillar 3 — adaptive pacing is CAT

### The conflict, resolved

The brief proposes global "fast learner / slow learner" cohorts. Appendix B.0 establishes that expertise
is **per-dimension**, and global levels are a failure mode (B.6, global-level leakage).

**Resolution — separate ability from rate:**
- **Ability `θ` is per-dimension. Always. Never pooled.**
- **Learning rate may be global, with shrinkage.** A user who acquires skills fast tends to do so across
  dimensions — a legitimate global prior, but shrunk toward the population mean so a single fast
  dimension does not accelerate feedback everywhere.

```python
k_user = w * k_observed(user) + (1 - w) * k_population     # w rises with n_attempts
```

### Item selection and exposure

CAT selects the next item to maximise Fisher information at the current θ̂:

```
I(θ)    = a² · P(θ) · (1 − P(θ))          # 2PL
SE(θ̂)  = 1 / √Σ I(θ)
```

Pure max-information selection serves every user at a given θ the same two or three dimensions forever —
the entrenchment problem the exploration quota exists to prevent.

- **Randomesque** — choose randomly among the top-k most informative (k = 3 typical). No calibration
  phase. **Use at cold start.**
- **Sympson-Hetter** — per-item exposure probability calibrated by simulation, realised exposure under a
  ceiling (~0.3 at a given θ; ~0.4 for middle-difficulty high-discrimination items). **Once volume
  supports calibration.**

**Item information also answers a question Appendix D could not.** A dimension whose `I(θ)` peaks only at
θ > 1 is uninformative for novices and should not be in a novice's eligible set — a computed replacement
for B.2's guessed "3–5 dimensions eligible for a NOVICE."

### Feedback frequency

Duolingo's **Half-Life Regression** (Settles & Meeder, ACL 2016) predicts recall decay as `p = 2^(−Δ/h)`
with `h = 2^(Θ·x)` learned from practice history, scheduling re-practice when predicted recall crosses a
threshold rather than on a fixed calendar. A direct upgrade to Appendix B's frequency fade and Appendix
A's spaced-rehearsal scheduler. **Deferred with the rest of the IRT stage.**

---

## G.5 · Pillar 4 — the threshold audit

### The architectural catch

**For `CORPUS_REL` thresholds (Appendix D's T3), failure rate carries no information.** If the threshold
*is* the 10th percentile, ~10% fail by construction. Monitoring it tells you nothing.

**The macro-audit is informative only for `ABSOLUTE` (T1/T2) thresholds and for IRT-calibrated
difficulty.** Do not dashboard a number that is definitionally pinned.

### G.5.1 · Adaptation is bounded by provenance tier (D24)

`effective_threshold` shifts `fire_at` by ability. Applied to a T1 benchmark, the value that fires is no
longer the literature-measured one — while still being labelled T1. That silently voids the tier system.

**Locked rule:**

| Tier | Adapts? | Rationale |
|---|---|---|
| **T1** (measured threshold) | **NEVER** | the point of the tier is that it fires where a study put it |
| **T2** (measured population values) | **NEVER** | same |
| **T3** (direction only) | **yes** | nothing measured is being overwritten |
| **CORPUS_REL** | **yes** | already ours |

> **If a scientific benchmark is failing our users, a human decides — not a script.** Recurring review
> lives in the product-manager backlog (`PRODUCT-MANAGER-BACKLOG.md`, process PM-1).

```python
def effective_threshold(dim, user) -> tuple[float, float]:
    b = BENCHMARK[dim]
    if b.tier in ("T1", "T2"):
        return b.fire_at, b.clear_at          # D24 — measured thresholds do not move

    shift = LAMBDA * (user.theta[dim] - b.difficulty)      # LAMBDA ~ 0.25
    widen = 1.0 + MU * (1.0 - k_user_shrunk(user))         # MU ~ 0.3
    fire  = b.fire_at  + shift * widen
    clear = b.clear_at + shift * widen

    # NEVER below the perceptual floor (Appendix E-6). A sub-JND change is
    # unperceivable regardless of ability; the panel will rate "no difference"
    # and the detector will look broken when it is the physics that is wrong.
    fire = max(fire, PERCEPTUAL_FLOOR[dim])
    return fire, clear
```

**The floor clamp is not optional.**

### Standard-setting is the discipline

Cut scores are set by **Angoff** (judges estimate the probability a borderline candidate passes each
item) or **bookmark**, and both traditions treat cut scores as **living artefacts requiring periodic
review**. Our 40-clip coach pass is a small Angoff round. **Schedule it** — PM-1.

---

## G.6 · DIF — the fairness tool the brief was missing

DIF detects an item behaving differently across groups **matched on ability** — precisely "is this
dimension penalising non-native speakers for something other than the skill it claims to measure?"

| Method | Detects | Sample size |
|---|---|---|
| **Mantel-Haenszel** | uniform DIF | **N ≥ 200 smaller group / 500 total** exploratory; **300 / 700** operational |
| **Logistic regression** (Swaminathan & Rogers) | uniform + **non-uniform** (θ × group) | similar |
| IRT-based (Lord's χ², Raju's area) | both | hundreds per group, full separate calibrations |

**ETS A/B/C on MH D-DIF** (= −2.35·ln OR):

```
A  negligible       |MH D-DIF| < 1, or not significant at p < .05
B  slight/moderate  significant AND |MH D-DIF| >= 1
C  moderate/large   |MH D-DIF| >= 1.5  AND  (|MH D-DIF| - 1) / SE > 1.645
```

**Groups to test, at minimum:** speaker sex (§5.2 already assumes an asymmetry — DIF is how we *measure*
it rather than assume it), native vs non-native, talk-length band.

### G.6.1 · DIF reports; it never acts (D25)

DIF interacts with the founder's **one-way valve**, which constrains protected weights during re-fit so
biased human labels cannot dissolve the sex-conditional calibration. DIF is the one evidence source that
could legitimately retire that calibration (and Appendix E-3 suggests it might).

**Locked: the valve is released by founder decision only.**

- A category **C** finding is a **blocking defect** on that dimension: it is flagged, surfaced on the
  audit dashboard, and the dimension is held — but no weight changes automatically.
- A sustained category **A** result is *evidence* that the sex adjustment may be unnecessary. It is
  reported. It does not release the valve.
- **For anything touching protected classes, the dashboard flags and the founder holds the keys.**

Recurring review lives in the product-manager backlog (PM-2).

---

## G.7 · Statistical failure modes

### Tail percentiles are expensive

```
Var(Q̂_p) ≈ p(1−p) / [ n · f(Q_p)² ]
```

Tail SEs run **3–10× the median's** for the same n, because the density `f(Q_p)` thins faster than
`p(1−p)` shrinks. Practically: **n ≳ 10/min(p, 1−p)** for a barely-usable tail estimate; **hundreds to
low thousands** for a stable 99th percentile. At n = 100 the 99th-percentile CI is unusable — one data
point sits above it.

### Streaming quantiles

Do not store raw data for N running distributions.

- **DDSketch** — formal α-relative-error guarantee at *every* quantile including extremes; fully
  mergeable across shards (~10 µs). **Chosen**, because bottom-5%/top-5% flags matter.
- **t-digest** — rank-error based; broader ecosystem support (Postgres, Elasticsearch). Lighter default.
- GK: rank-error, not tail-optimised. Reservoir sampling: fine for the body, noisy at extremes.

### Drift — PSI

```
PSI = Σᵢ (Actualᵢ% − Expectedᵢ%) · ln(Actualᵢ% / Expectedᵢ%)     over deciles

PSI < 0.10          no meaningful shift
0.10 ≤ PSI < 0.20   moderate — investigate
PSI ≥ 0.20–0.25     major — retire or refit the reference
```

Run per-dimension weekly against the frozen reference. Use exponentially-weighted quantiles rather than a
hard sliding window.

### Cohort confounding — the most likely real harm

If non-native speakers are 20% of users and score systematically lower on fluency-adjacent dimensions, a
**pooled percentile flags typical non-native performance as "below average"** — conflating *different
from the pooled mean* with *deficient*. Textbook Simpson's paradox, and for a speech product it is the
most likely real harm in the whole design.

Pooling is valid only when the covariate is unrelated to the dimension. It is not, here.

---

## G.8 · Stratification — and why the brief's dilemma does not apply to us

The brief poses: silent within-group renorming (bad) vs stratify-and-disclose (good), naming the
reference group — *"compared with speakers giving talks of similar length in your language setting."*

**We take neither.** Disclosing the reference group **surfaces a normative comparison**, which is the
Kluger & DeNisi attention-shift this whole appendix exists to avoid, and which G.3.1 bans as *ranking*.

> **Locked (D28): stratify internally, surface nothing comparative. The brief's dilemma only exists for
> products that show the user the comparison. Ours never does.**

Stratification is real and required — it is how thresholds and reference distributions are computed
without Simpson's paradox. It simply never appears in a payload or in copy.

**Legal note, parked at founder instruction.** Civil Rights Act of 1991 §106 makes score adjustment on
the basis of protected class unlawful for **employment-related** testing. It does not bind a coaching
product. It becomes a second constraint on any B2B hiring/performance channel, alongside EU AI Act
Article 5(1)(f) (§13). Recorded, not re-opened here; §13 remains the open item.

---

## G.9 · Implementation spec

### Schema — the boundary

```python
# ── internal only, never serialised to any client-facing schema ──
@dataclass(frozen=True)
class PopulationContext:
    dimension_id: str
    percentile: float
    cohort_id: str
    n_in_cohort: int
    theta: float                 # IRT ability
    item_difficulty: float       # IRT b
    self_relative_delta: float   # D23 — MEASURED here, never rendered
    computed_at: datetime

# ── the only thing that crosses the boundary ──
@dataclass(frozen=True)
class UserFacingFinding:
    intervention_type: InterventionType
    anchor: Anchor
    comment: str                 # already-rendered qualitative copy (G.3.1)
    comment_band: Literal["absolute", "comparative"]   # which of the 80/20 fired
    # NO percentile. NO cohort. NO rank. NO theta. NO delta. NO number of any kind.
```

**`self_relative_delta` lives on the INTERNAL side (D23).** The brief placed it in the client-facing
struct as "the only comparative number" — that is an AC-9 breach, and the brief's own contract test
(`percentile|rank|cohort|percent_of_users|theta`) would not have caught it. The delta is measured, and it
*selects* which qualitative line renders. It never crosses.

**Enforce structurally, three ways:**
1. `PopulationContext` lives in a module the serialisation layer does not import. A circular-import
   error is a better guard than a code review.
2. A contract test asserts no client-facing schema contains a field matching
   `percentile|rank|cohort|percent_of_users|theta|delta|self_relative|score`.
3. Population types are absent from the client schema entirely — not merely annotated internal.

### Gradual introduction gates

```python
def population_insight_unlocked(user, dimension) -> bool:
    return (
        user.attempts_on(dimension) >= 5                  # B.3's M >= 5
        and user.has_stable_self_baseline(dimension)      # 3 consecutive scored attempts
        and cohort_n(dimension, user.cohort) >= n_gate(target_percentile)
    )

def n_gate(p: float) -> int:
    """Tail claims need far more data than median claims."""
    return max(200, int(10 / min(p, 1 - p)))
    # p=0.50 ->   200
    # p=0.90 ->   200
    # p=0.99 -> 1,000
```

Before the gate: strengths and weaknesses by **within-user ranking across dimensions** — which per G.2.1
is the permanent answer for most dimensions, not a stopgap.

### Macro-audit queries

See `PROMPT-drift-layer.md` for the build-now specification. The three queries are:
1. **p-chart** on fire rate — `ABSOLUTE` (T1/T2) thresholds only; `CORPUS_REL` excluded by construction.
2. **PSI** on the input distribution vs a frozen reference.
3. **Mantel-Haenszel DIF** — deferred (G.10), specified in `PROMPT-irt-dif-deferred.md`.

**Division of labour: PSI watches the input distribution; the p-chart watches the output decisions.**
Both are needed — a stable input with drifting decisions means the model changed, and vice versa.

---

## G.10 · Build order and the unlock triggers (D26)

Calibration sample sizes rule out IRT at launch:

| Model | Responses per item | Precision |
|---|---|---|
| **Rasch / 1PL** | **30** min (±1 logit); **100–150** for ±0.5; **250** operational | difficulty only |
| **2PL** | **250–500** | + discrimination |
| **3PL** | **≥ 1,000** | + guessing |

**A "response" is a machine evaluation** (`dimension_evaluations.fired`), not a coach label. **These
stages are therefore gated on USER VOLUME, not on the ~15 labels/week** — a different and much more
favourable constraint than the rest of the spec.

| Stage | Unlock trigger | Status |
|---|---|---|
| **1 · Cold start** | now | Appendix D corpus deciles · randomesque exploration · **no population claims** · within-user dimension ranking only |
| **2 · Drift layer** | **now — BUILD** | PSI + p-chart + DDSketch. Zero labels, works at any n. `PROMPT-drift-layer.md` |
| **3 · Elo/Glicko bridge** | ≥ 50 users with ≥ 3 scored recordings | online learner/item ratings from response one, no batch calibration (Pelánek). **Deferred** |
| **4 · Rasch** | ≥ 150 evaluations per dimension | real item difficulty; threshold audit becomes meaningful; item information gates dimension eligibility. **Deferred** |
| **5 · 2PL + MH DIF** | ≥ 400 evaluations per dimension **AND** ≥ 200 users per subgroup with the flag stored | discrimination + the fairness audit turns on. **Deferred** |
| **6 · Sympson-Hetter** | after stage 5 | replaces randomesque. **Deferred** |

**3PL is never worth it here** — a "guessing" parameter has no clean interpretation for a speech
dimension, and it costs 1,000 responses per item to estimate badly.

Stages 3–6 are tracked in `PRODUCT-MANAGER-BACKLOG.md` with their triggers, and their build
specification is written in advance at `PROMPT-irt-dif-deferred.md` so no design work is repeated when a
trigger fires.

**Blocking prerequisite for stage 5:** DIF cannot run without a stored subgroup flag. `language` on
recordings is the transcription language, **not** native/non-native — a native Polish speaker presenting
in English is `language=en`. Capturing native/non-native is a prerequisite, not a detail. Tracked as
PM-4.

---

## G.11 · Corrections applied to the brief

| # | Issue in the brief | Resolution |
|---|---|---|
| **1** | "Greatest strength" from percentile alone can name something the user is objectively bad at | dual gate — percentile **and** absolute adequacy (G.2) |
| **2** | Global fast/slow-learner cohorts contradict Appendix B's per-dimension keying | θ per-dimension; learning rate global **with shrinkage** (G.4) |
| **3** | "If 90% fail the threshold is broken" is uninformative for CORPUS_REL — the rate is pinned | audit ABSOLUTE + IRT difficulty only (G.5) |
| **4** | Pooled percentiles will systematically flag non-native speakers | stratify internally; **never surface the reference group** (G.8, D28) |
| **5** | Tail claims need n in the hundreds–thousands; no n-gate | `n_gate(p)` before any population claim (G.9) |
| **6** | No fairness audit at all | DIF with ETS A/B/C; category C blocks the dimension (G.6) |
| **7** | Adaptive widening could push a threshold below the perceptual JND | clamp to `PERCEPTUAL_FLOOR` (G.5.1) |
| **8** | Hiding percentiles framed as the protective mechanism | it contributes; **mastery framing is the active ingredient** (G.0, D27) |
| **9** | B2B channel has a second legal constraint | recorded; §13 stays open, parked at founder instruction (G.8) |
| **10** | "Decouple percentiles from the payload" | stronger — they never enter it; module boundary + contract test (G.9) |
| **11** | **`self_relative_delta` placed in the client-facing schema** | **AC-9 breach.** Moved to `PopulationContext`; contract regex extended (G.9, D23) |
| **12** | **"Stratify and disclose" surfaces a normative comparison** | dilemma dissolved — we surface nothing comparative at all (G.8, D28) |
| **13** | **Adaptive thresholds silently void the T1/T2 provenance tiers** | T1/T2 never adapt (G.5.1, D24) |
| **14** | **The dual gate is unimplementable where no absolute bar exists** | within-user ranking is the **permanent** answer there, not a stopgap (G.2.1) |
| **15** | **DIF vs the one-way valve — the valve blocks its own evidence** | DIF reports, founder releases (G.6.1, D25) |
| **16** | **IRT on machine decisions is presented as answering "is the threshold broken?"** | it audits **targeting and redundancy, not validity** (G.1.1) |
