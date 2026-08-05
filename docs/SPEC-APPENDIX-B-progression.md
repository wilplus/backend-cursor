# Appendix B — Feedback Progression: Novice to Expert

**Last updated:** 2026-08-05.

**Companion to SPEC.md v3.** Governs every parameter of the Feedback Engine over a user's lifetime. Inherits §8 (triage), §10 (invariants), §11 (delivery constraints).

> **Amended by SPEC.md §0 decisions D11, D15, D16, D17.** `FRAGILE` gains its own parameter set (B.2.1) — it is a band, not a point on the fading arc. The GRADUATE cohesion fade becomes a tunable defaulting to no fade. Graduation anchors externally, never on the state machine's own counter. Applied inline below. Where this document and SPEC.md conflict, **SPEC.md wins.**

---

## B.0 · Two principles that determine the whole design

### 1 · Expertise is per-dimension, never global

A user can be expert at structure and novice at vocal variety. A single global "level" would apply expert-mode fading to a dimension they have never once received feedback on — and silently withhold the help they need.

**The state model is keyed on `(user_id, dimension_id)`.** There is no user level. Anything that reads a global skill number is wrong.

### 2 · Two axes, not one — performance and calibration

Performance says *are they good at this*. Calibration says *do they know whether they're good*.

Fading exists to hand self-monitoring back to the user. A user who cannot self-monitor is not ready for less scaffolding **however well they are performing** — they will regress and not notice.

Calibration comes free from the predict-then-reveal gate (§3.3): the gap between what they predicted and what was scored. No extra instrumentation.

```
calibration = 1 − mean(|predicted − actual|)   over the last N attempts, per dimension
```

---

## B.1 · The four states

|  | **Low calibration** | **High calibration** |
|---|---|---|
| **Low performance** | **NOVICE**<br>Full scaffolding. They don't know what good is and can't tell where they are. | **APPRENTICE**<br>The ideal coaching state — they know they're weak and are asking. Correction-weighted valence is welcome here. |
| **High performance** | **FRAGILE**<br>**Do not fade.** Performing well, cannot tell why or when. Fading here produces regression the user won't detect. | **GRADUATE**<br>Fade to near-zero. Bandwidth feedback only. |

**FRAGILE is the state most systems get wrong**, because performance alone looks like readiness. It's the inverse of the Dr. Fox finding: there, students rated a lecture highly while accurately knowing they'd learned nothing. Here the user performs well while not knowing what they're doing — and a naive fader graduates them straight into a plateau.

---

## B.2 · What changes across the arc

Every parameter below is per-dimension and driven by the state.

| Parameter | NOVICE | APPRENTICE | GRADUATE | Evidence |
|---|---|---|---|---|
| **Frequency** | every attempt | ~75% | **~50%** or bandwidth-only | Winstein & Schmidt: faded 50% KR produced **35% less error at 24 h retention** (F(1,56)=6.24, p<.01) *despite equal or worse performance during acquisition*. Grade **A** |
| **Specificity** | granular — the exact word, the exact timestamp | moderate — the pattern | coarse — "your transitions again" | Goodman et al.: specificity helped practice (η²=.36) but **nothing on transfer**, and suppressed both systematic (p=.034) and unsystematic exploration (η²=.24). Grade **A** |
| **Valence weighting** | encouragement-weighted | balanced | correction-weighted | Finkelstein & Fishbach (7 studies): experts sought negative feedback **92–100%** of the time vs novices **73–74%**, and each group's performance rose with the matching valence. Grade **A** |
| **Goal type** | **learning** goals ("find three ways to open") | mixed | **performance** goals ("hit 8/10 on signposting") | Seijts & Latham: the Locke–Latham finding **flips for complex novel tasks** — performance goals induce tunnel vision at the expense of the strategy discovery a novice still needs. Grade **A** |
| **Timing** | immediate | immediate | delayed, reflective | Shute: immediate suits procedural correction and struggling learners; delayed favours conceptual transfer in advanced learners. Grade **B** |
| **Locus of control** | system surfaces | system surfaces, user can request more | **user requests, after the attempt** | Carter & Ste-Marie: choose-after retention error **10.04 cm** vs choose-before **29.18 cm** — and choose-before was no better than yoked control. Autonomy isn't the mechanism; the post-attempt error-estimation window is. Grade **B** |
| **Support form** | annotated exemplars, worked examples | contrasting pairs | nothing — diagnosis only | Worked-example effect g = 0.48 (k=55) for novices; **expertise reversal** makes the same supports neutral or harmful for advanced learners. Grade **A** |
| **Attribution** | system names the cause | system asks, then names | user self-explains, system confirms | Self-explanation g = 0.55, k = 64 reports. Grade **A** |
| **Explanation cohesion** | **high** — every link spelled out | moderate | **tunable, default = no fade** (D17) | The reverse cohesion effect is *conditional*, not monotone. High-knowledge **low-skill** readers learn more from low-cohesion text; O'Reilly & McNamara (N=143) found high-knowledge **skilled** readers do better with *high* cohesion after all. GRADUATE is high-performance and high-calibration — which reads as high-skill — so the fade may point the wrong way for exactly the users it targets. Keep the dial, don't hard-code the direction; flip it only if graduation rates say otherwise. Grade **B**, with a known interaction |
| **Dimensions eligible** | 3–5 highest-effect only | ~10 | all | Feedback complexity has negative returns past a point (Shute). A novice shown forty dimensions learns none. Grade **B** |

**Still exactly one note per session at every level** (§11). Progression changes *which* note and *how it's phrased* — never *how many*.

### B.2.1 · FRAGILE — a band, not a point on the arc (D11, D15)

The table above is the **fading arc**: NOVICE → APPRENTICE → GRADUATE, three points on one continuum of decreasing scaffolding. `FRAGILE` is not on it. It has no promotion path (B.3), and its problem is not performance — so "how much to fade" is the wrong question for it entirely.

It is nonetheless a full band for template purposes: **8 intervention types × 4 bands = 32 templates** (Appendix C.6). Its parameters:

| Parameter | FRAGILE | Why |
|---|---|---|
| **Frequency** | **do not fade** — hold at APPRENTICE level | Performance looks like readiness and isn't. Fading here produces regression the user cannot detect |
| **Specificity** | hold at moderate | Coarsening removes the only signal they aren't generating themselves |
| **Valence weighting** | balanced | They are not failing; correction-weighting misreads the problem |
| **Goal type** | **calibration goals**, not performance or learning | "Predict your score before you look" is the intervention |
| **Locus of control** | system surfaces | They cannot yet tell when they need help, so they will not ask |
| **Support form** | **more predict-then-reveal, more replay, more self-explanation** | The three interventions that move calibration specifically |
| **Attribution** | user self-explains, system confirms or corrects | The correction is the calibration signal |
| **Explanation cohesion** | high | Gap-filling assumes they can tell where the gaps are |

**The only exit is sideways into GRADUATE, via calibration improving.** Performance is already fine; it is not the thing that needs work. A promotion rule that reads performance alone will graduate them into a plateau — which is the single most common way this class of system fails.

---

## B.3 · Promotion and demotion

### Promotion requires stability, not a good score

```
promote(user, dimension) if:
    score ≥ threshold  for N consecutive attempts     (N ≥ 3)
    AND calibration ≥ cal_threshold over the same window
    AND at least M attempts have occurred on this dimension  (M ≥ 5)
```

One good attempt is luck. Promoting on it fades support from someone who got lucky, and the regression that follows looks like the system causing harm — which, in that case, it did.

### Demotion must exist — this cannot be a one-way ratchet

```
demote(user, dimension) if:
    score < threshold for K consecutive attempts   (K = 2)
    OR calibration collapses (|predicted − actual| spikes)
```

**Without demotion a user who regresses gets no help precisely when they need it.** This is the same class of bug as the boolean `readiness` in §8.2 — a state that can only move one way eventually strands the user. Demotion is slightly hair-trigger by design (K=2 vs N=3): re-scaffolding is cheap, under-supporting a regressing user is not.

### FRAGILE has no promotion path

A high-performance, low-calibration user cannot promote to GRADUATE. They can only move sideways into GRADUATE by **calibration improving**, which is a separate intervention: more predict-then-reveal, more replay, more self-explanation. Performance is already fine; it isn't the thing that needs work.

---

## B.4 · Interaction with the triage decay (§8.2)

Two suppressors act on the same note. They must not compound into silence.

```
priority = (deviation × effect_size × remediability)
         × R(k, Δt)          # §8.2 — short-term, within-session inaction
         × G(state)          # this appendix — long-term, per-dimension
```

- `R` is **short-term**: this note was shown recently and not acted on.
- `G` is **long-term**: this user no longer needs this note often.

**Invariant:** `R × G` has the same hard floor as `R` alone — `ε = 0.15`. Both mechanisms are suppressors, and a GRADUATE-state dimension with one unacted impression must not fall through the floor twice. Assert on the product, not on each factor.

**And the same escape hatch applies:** a deviation spike ≥ 2× overcomes both. A graduate who suddenly falls apart on a faded dimension gets the note back immediately.

---

## B.5 · What each state must NOT receive

Fading is not only about giving less — some things are actively harmful at the wrong level.

**A NOVICE must not get:**
- Bandwidth/threshold feedback — they don't know the standard yet, so silence reads as approval
- Self-controlled timing — they don't know when to ask, so they won't
- Performance goals — tunnel vision before the strategies exist
- The full dimension list — negative returns on complexity
- Correction-weighted valence — Fong et al. (k=78, 431 effects): negative-vs-positive crushed perceived competence, g = −0.90 to −1.00

**A GRADUATE must not get:**
- Worked examples or annotated exemplars — expertise reversal makes them neutral-to-harmful
- High-cohesion explanations — removes the gap-filling that produces the deeper processing
- Encouragement-weighted valence — they want the correction and read praise as noise
- Auto-surfaced notes at all, outside bandwidth breaches

**Nobody, at any level, gets:**
- Person-level praise (d = 0.14)
- Normative comparison or leaderboards — sign-flipping moderator in Kluger & DeNisi
- Anything during LIVE mode beyond sparse external-focus cues

---

## B.6 · Failure modes to test for

| Failure | Symptom | Guard |
|---|---|---|
| **Premature fade** | user regresses shortly after promotion | N ≥ 3 consecutive + M ≥ 5 minimum attempts |
| **One-way ratchet** | regressing user receives nothing | demotion at K = 2, hair-trigger by design |
| **Compound suppression** | note never resurfaces | floor asserted on `R × G`, not each factor |
| **Global-level leakage** | expert-mode fading applied to an untouched dimension | state is keyed `(user, dimension)`; assert no global read |
| **Fragile graduation** | high scorer plateaus, never improves again | FRAGILE has no promotion path; calibration is the gate |
| **Cold-start over-scaffolding** | experienced user treated as a beginner for weeks | seed from the first 3 attempts, not from zero; a strong, well-calibrated debut promotes fast |

---

## B.7 · Telemetry required

Per `(user_id, dimension_id)`:

```
state                    NOVICE | APPRENTICE | FRAGILE | GRADUATE
score_history            last N attempts
predicted_history        from the predict-then-reveal gate
calibration              1 − mean(|predicted − actual|)
attempts_on_dimension    M
consecutive_above        N
consecutive_below        K
last_surfaced_at         feeds Δt in R(k, Δt)
unacted_impressions      k
state_changed_at         for auditing promotion/demotion behaviour
```

`state_changed_at` matters more than it looks: the population-level distribution of time-to-promotion is how you find out whether your thresholds are wrong, and it's the only way to distinguish "our users aren't improving" from "our promotion rule is too strict."

---

## B.8 · The endpoint

**The system is working when a user stops needing it on a dimension.**

That is an unusual product metric, and it should be an explicit one: *dimensions graduated per user over time*. Optimising for engagement on a coaching product optimises for users who never improve — which is the same proxy-target failure as optimising the writer on coach approval (§12.2).

**Graduation must be anchored externally (D16).** If the system controls both the graduation criteria and the metric it is measured by, it can graduate users cheaply and the number means nothing. Anchor promotion to **deterministic change detection** — did the flagged thing actually change in the next take, measured on a dimension with a deterministic extractor (lexical overlap, pronoun rate, concreteness) — never to the state machine's own promotion counter.

**Note the ceiling.** With five dimensions in v1.0 the metric tops out at five per user. That is not a flaw: it means the metric is telling you to add dimensions, not to graduate harder.

Retention should come from users bringing **new talks** and **new dimensions**, not from the same person receiving the same note forever.
