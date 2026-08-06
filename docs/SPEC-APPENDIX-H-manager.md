# Appendix H — Manager Engine Parameters

**Last updated:** 2026-08-06. **Status:** founder-supplied, implemented in `services/manager_engine.py`.

**Six slots, each grounded.** Companion to SPEC.md v3 §8.2 / §11, Appendix B (progression), Appendix D (benchmarks), Appendix F (windows).

`fire_at` is a **submission gate**, not a surfacing decision. `registry.can_fire()` means *I have a candidate*. The manager arbitrates. Everything below is the arbitration policy.

---

## H.0 · The asymmetry that determines every parameter

Before any individual slot: **in this system a miss is cheap and a false positive is expensive, and they are not symmetric in kind.**

- A **miss** costs one opportunity. There will be another recording.
- A **false positive** costs trust — and not just in that detector.

Dixon, Wickens & McCarley (2007, n=32): false-alarm-prone automation damaged performance **more** than miss-prone automation, and critically, **false alarms degraded both compliance *and* reliance, while misses degraded only reliance.** Chancey et al. (2015) found trust mediates the reliability→compliance path *only* for false-alarm-prone systems.

Translated: a detector that misses things loses credibility for itself. A detector that cries wolf loses credibility **for the manager**, and therefore for every other detector behind it.

Signal detection theory gives the formal consequence:

```
β* = [ C(FA) · P(noise) ] / [ C(Miss) · P(signal) ]
```

With `C(FA) >> C(Miss)` and `P(signal)` low, the optimal criterion sits **high**. Every slot below inherits that. When a choice here is arguable, it goes toward silence.

---

## H.1 · Budget — how many may surface per recording

### Verdict: **flat cap. Do not scale with length. Default 1, hard ceiling 3.**

- **Kulhavy, White, Topp, Chan & Adams (1985)** manipulated feedback across four complexity levels. **"Complexity of feedback was inversely related to both ability to correct errors and learning efficiency."** The *simplest* feedback beat the most elaborate on both outcomes.
- **Composition research converges around 3–5.** Shuman (1979): no more than five comments per composition. Arnold (1964): no significant difference between marking every error and marking minimally. Harris (1978), Lamberg (1980): extensive commenting did not improve subsequent writing.
- **Cowan (2001)**: true chunk capacity for novel, un-rehearsed material is **3–5, centrally ~4** — not Miller's 7±2, which measured familiar chunkable items under rehearsal-friendly conditions.
- **Kang & Han (2015)** meta-analysis: focused **g = 0.628** [.398–.857], unfocused **g = 0.445** [.182–.708]. Numerically favours focused, **not significantly** (Q = 1.050, p = .305). Targeting fewer is proven *not worse*, at lower cost.

### On scaling to length: no evidence, and the theory argues against it

**No study varies performance length and measures the optimal feedback count** — not in writing, music masterclass, surgical debrief, or sports video review. The coaching "rule of three" is practitioner folklore.

The argument against scaling is structural: **the bottleneck is the coachee's uptake capacity, and that does not grow with recording length.** Cowan's ceiling is a property of the listener, not the material.

The untested counter-argument: a 40-minute lecture surfaces more genuinely *independent* skill domains than a 5-minute talk, so a flat cap may under-use signal. Which points at the right refinement —

### The refinement: budget on element interactivity, not count

```python
BUDGET_BASE = 1
def budget(user, findings) -> int:
    independent = max_independent_subset(findings)          # priority-sorted
    leading = independent[0].dimension if independent else None
    if user.state(leading) == NOVICE:                       # H.9.2
        return 1                    # never more, at any recording length
    return min(3, max(1, len(independent)))
```

A second note is permitted only when it is genuinely independent.

**Implementation note.** `max_independent_subset` and collision resolution (H.5) are **the same operation** and are one function in code. Greedy by priority: keep a candidate if it conflicts with nothing already kept. Pairwise resolution would be wrong for a transitive chain — A overlaps B, B overlaps C, A and C do not — where dropping B alone leaves both ends eligible.

**Flag: item *count* has never been directly studied.** Kulhavy manipulates elaboration per item, not number of items. The 3–5 convergence is inference across four adjacent literatures.

---

## H.2 · Certainty floor — the slot D7a failed

### Verdict: **PPV ≥ 0.70 absolute floor, target 0.85. Per-detector, not global.**

**0.70 is derived.** Wickens & Dixon (2007), meta-analysis of **20 studies / 35 data points**: **reliability 0.70 is the crossover below which automation produces worse performance than no aid at all.** Above it, benefit scales roughly **linearly** — no cliff. The effect is **stronger under high workload**.

Caveat from the same group: Wickens, Dixon & Johnson (2006) found 0.60 could still help in dual-task, low-priority conditions. 0.70 is a synthesised average crossover, not a physical constant.

### The floor must be stated in PPV, not accuracy

At low prevalence a nominally accurate detector is mostly wrong:

> **99% sensitivity, 99% specificity, 0.1% prevalence**: 100 true positives, 999 false positives → **PPV ≈ 9%.**

A "70% accurate" detector on a rare finding can have a PPV in the teens. **Set the floor on precision, calibrated per detector against its own candidate base rate.**

| Domain | Observed | Consequence |
|---|---|---|
| Clinical monitoring | **72–99% of alarms non-actionable** | 59,000 alarms in 12 days at one centre |
| Static analysis, untuned | 60–90% FP | Tools abandoned |
| Static analysis, tuned | 10–20% FP | Tools retained |
| Threshold of visible breakdown | **>40% suppressed without a code change** | "Something is broken" signal |
| Best-in-class design bar | **<5% FP** (DeepSource) | Deliberate target |

Dandoy et al. cut false-alarm proportion **95% → 50%** and median alarms/patient-day 180 → 40 — the direction is responsive.

**Bias upward for false-alarm-prone detectors specifically** (H.0).

---

## H.3 · Importance weighting — constant or contextual?

### Verdict: **per-dimension constant is evidenced. Context modifiers are thin — add only where a moderator is published.**

The per-dimension constant already exists: the evidence grade, `A = 1.0 / B = 0.6 / C = 0.0` (Appendix D.6, D18).

| Modifier | Evidence | Direction |
|---|---|---|
| **Audience expertise** | Expertise reversal (Kalyuga) | Down-weight scaffolding-type dimensions for expert audiences |
| **Material complexity** | Noetel et al. (29 reviews, 1,189 studies): design principles mattered **more** for complex material | Up-weight structural dimensions on technical content |
| **System-paced delivery** | Same meta-meta-analysis: effects stronger system-paced than self-paced | A live talk is system-paced — weight structure highly throughout |

**Does slide overlap matter more in a technical deck than a pitch?** Noetel's complexity moderator is the closest support and it is indirect. **Nobody has studied dimension importance by genre.** Treat a genre modifier as `T3-invented`, start at 1.0, let the outcome anchor move it.

```python
importance = EFFECT_SIZE[dim] * context_modifier(dim, brief)   # modifier defaults 1.0
```

---

## H.4 · Progress coupling — told three times, no movement

### Verdict: **do not escalate. Decay, then change the intervention type. Never repeat verbatim past ~3.**

The strongest evidence of the six, and it points against the intuitive answer.

- **Repetition has an inverted-U peaking near 3.** Cacioppo & Petty (1979): agreement **peaks at ~3 exposures and declines by 5**, driven by counterarguing and irrelevant-thought generation.
- **Message fatigue is meta-analytically confirmed.** Keating & Skurka (2024): **r = −.25** (k = 18, N = 24,236).
- **Escalation triggers reactance.** The reactance meta-analysis (2025/26): freedom-threatening language → anger **r = .21**, negative cognitions **r = .17**, both negatively predicting persuasion (**r = −.23 / −.18**). **Repeated behaviours provoke more reactance than one-off asks.**
- **Reminders can be net-negative on lifetime value.** Damgaard & Gravert: one reminder produced **+66% donations** but **+76% unsubscribes** — roughly **−33% lifetime donor value.**

### The finding that settles the design

A 2025 non-uptake study (n = 641) decomposed *why* feedback isn't acted on:

| Cause | Share | Does escalation fix it? |
|---|---|---|
| Reliably act on it | **14.3%** | — |
| Engage but fail to implement (**metacognitive gap**) | ~30% | **No.** They already believe they've complied |
| Motivated but **structurally unable** | ~23% | **No.** They need a smaller step, not volume |
| **Emotionally withdraw** | ~33% | **No — actively harmful.** Insistence accelerates disengagement |

**Escalation addresses none of the three failure modes.** For a third of users it makes things worse.

```python
def on_unacted(finding, k) -> Action:
    if k == 1:  return REPEAT_AS_IS          # within the peak
    if k == 2:  return REFRAME               # same point, different framing
    if k >= 3:  return CHANGE_INTERVENTION_TYPE
    # never: louder, longer, more insistent
```

Composes with `R(k, Δt)` in §8.2 — decay handles *priority*, this handles *form*. The decay floor still applies: the finding never vanishes, it stops winning.

**Flag: whether reframing genuinely resets wear-out has not been tested for feedback.** Inferred from advertising wear-out.

---

## H.5 · Collision — two candidates on one span

### Verdict: **same span → one wins. Trading dimensions → never both, ever. Independent + distant → permitted within budget.**

No study directly tests two feedback items on the same moment. The governing construct is **element interactivity**: two findings on one span are maximally interactive, because the user must hold both to act on either — precisely the load Kulhavy et al. showed degrades correction rate.

```python
def resolve_collision(a, b):
    if TRADES_AGAINST.get(a.dimension) == b.dimension:
        return max(a, b, key=priority)        # D1/D2: never both, at any distance
    if spans_overlap(a.anchor, b.anchor):
        return max(a, b, key=priority)        # same span: one wins
    return (a, b)                             # independent: both, subject to H.1
```

The D1/D2 rule is the right shape for **trading** dimensions — pairs whose targets move in opposite directions. Surfacing both is incoherent advice, not merely crowded. `TRADES_AGAINST` is explicit and short; a general rule would over-suppress.

---

## H.6 · Cooldown — refractory period

### Verdict: **yes, a refractory period. And a mastery gate that makes a fixed dimension go quiet permanently.**

**Going quiet is better for retention than staying on.** Winstein & Schmidt (1990): faded 50% knowledge-of-results produced **35% less error at 24-hour retention** (F(1,56) = 6.24, p < .01), *despite equal or worse performance during acquisition*. Continued feedback on a corrected behaviour is a crutch that suppresses the learner's own error detection.

**Mastery threshold**: Bayesian Knowledge Tracing uses **P(mastery) ≥ 0.95** (Corbett & Anderson 1995); a 2025 EDM paper argues 0.98. Use 0.95 and revisit.

**Spacing**: Cepeda et al.'s ridgeline puts the optimal gap at **~20% of the retention interval, shrinking toward ~5–6%** as it grows. For month-scale retention that is roughly 2–6 days — **a small number of sessions, not one.**

```python
COOLDOWN_SESSIONS = 2
MASTERY_THRESHOLD = 0.95
```

**Two escapes, both already specified:** a **deviation spike ≥ 2×** overrides cooldown (§8.2); **mastery is revocable** — `p_mastery` dropping below threshold returns the dimension to rotation, which is Appendix B's demotion rule at dimension granularity. A one-way ratchet strands the user.

---

## H.7 · The manager, in one function

Implemented verbatim as `manager_engine.arbitrate()`. Order matters: certainty gates before priority, because H.0 says the false positive is the expensive error — a loud, uncertain candidate must not survive on loudness.

```python
def arbitrate(candidates, user, recording) -> list[Finding]:
    live = [c for c in candidates if c.detector.ppv_estimate >= PPV_FLOOR]   # H.2
    live = [c for c in live                                                  # H.6
            if not in_cooldown(user, c.dimension)
            or c.deviation >= 2 * user.baseline_deviation[c.dimension]]
    for c in live:                                              # §8.2, B.4, H.3
        c.priority = (c.deviation * importance(c.dimension, recording.brief)
                      * c.remediability * R(c.k, c.delta_t) * G(user.state[c.dimension]))
        # floor asserted on the PRODUCT R×G, not each factor            (B.4)
    live = resolve_collisions(live)                                          # H.5
    selected = sorted(live, key=priority, reverse=True)[:budget(user, live)]  # H.1
    for c in selected:
        c.form = on_unacted(c, c.k)                                          # H.4
    return apply_exploration(selected, live)                                 # §8.3
```

**A spike bypasses both suppressors at full weight**, not merely to the floor — the point of the escape hatch is that a collapse resurfaces properly.

---

## H.8 · What is genuinely unstudied

| Slot | Gap |
|---|---|
| **Budget** | **Item *count* has never been directly manipulated.** Kulhavy varies elaboration per item. |
| **Budget · length** | **No study scales feedback count to performance duration** in any domain. |
| **Importance · genre** | **Nobody has studied dimension importance by talk genre.** |
| **Progress · reframing** | Whether reframing resets wear-out is **inferred from advertising**, not measured for feedback. |
| **Collision** | **No direct study of two feedback items on the same moment.** |
| **Certainty floor** | **No field-general minimum-PPV standard exists.** 0.70 is the automation crossover; 0.85 is calibrated from analogous tooling. |

Each is a place where the outcome anchor (§12.2) can produce **a first rather than a replication** — the manager is where the experiment nobody has run is cheapest, because the exploration quota already logs the counterfactual.

---

## H.9 · Conflicts this appendix created — all three settled *(founder, 2026-08-06)*

### H.9.1 · The budget conflict with §11 — **RESOLVED: §11 amended**

SPEC.md §11 said `per session: surface exactly ONE finding`, §11.1's router enforced it with `if session.already_surfaced: return None`, and Appendix B.2 restated it as *"never how many."* H.1 permits three, which made the ceiling a silent no-op.

**Decision: amend §11.** The one-per-session cap is removed. §11 now reads `surface UP TO THREE findings`; §11.1's gate becomes `if session.surfaced >= manager.budget: return None`. B.2's line is struck and replaced.

**Budget enforcement now lives in exactly one place** — `manager_engine.budget()`. That is the point of the amendment: a cap in the router *and* a cap in the manager is how the two silently disagree.

### H.9.2 · GRADUATE and FRAGILE — **RESOLVED: both may see three**

**Decision: only NOVICE is capped at one.** APPRENTICE, FRAGILE and GRADUATE may each see up to three.

The reasoning that makes this consistent with the fading arc: **the arc governs frequency and phrasing, not the per-session ceiling.** `G(state)` already suppresses a GRADUATE's candidates on *priority*, so fewer of them clear the bar in the first place. Two separate mechanisms, both applying — a per-session cap on top would be double-suppression, which is exactly the B.4 defect at a different level.

**Which state governs, given that B makes state per-dimension.** There is no single "user state" to branch on, so one has to be picked. `budget()` reads **the leading candidate's dimension** — the note that will certainly surface, so the user's competence *at that thing* is the load signal that matters.

The rejected alternative was the least-advanced dimension anywhere, which was in the first implementation. It fails the founder decision directly: one NOVICE dimension the user never sees would cap a GRADUATE at a single note forever. A dimension with **no recorded state** defaults to NOVICE and therefore to one — the safe direction under H.0.

### H.9.3 · `G(state)` values — **RESOLVED: approved as baseline**

```python
G_BY_STATE = {NOVICE: 1.0, APPRENTICE: 0.75, FRAGILE: 1.0, GRADUATE: 0.5}
```

Derived from the **Frequency** row of B.2 (*every attempt / ~75% / ~50% or bandwidth-only*), the only numeric anchor B gives; B.4 names `G(state)` without values. FRAGILE is 1.0 because B.2.1 says do not fade it.

**Founder-approved as the official baseline**, `T3-invented` tag removed. They still move on the outcome anchor rather than on preference — D24's rule that a measured threshold never adapts does **not** apply, because these are policy dials, not literature-measured values.

---

## H.11 · Manager behaviour specified elsewhere and NOT yet built

The decisions log §B sets four more manager dials. Two are implemented, two are not, and the gap is recorded here so it is not mistaken for completeness.

| Dial | Value | Status |
|---|---|---|
| **ε_explore** | ~10–20%, surface rank 2–3, log the counterfactual | **Built.** `EXPLORATION_RATE = 0.10`, bottom of the band per H.0 |
| **Objective** | maximise measured change take N → N+1; acceptance is a **constraint**, never the objective | **Built** by omission — nothing here optimises on acceptance |
| **γ_control** | ~10–15%, **per-dimension** — a share of (user, dimension) pairs get **nothing** | **NOT BUILT.** Without it you credit yourself with the practice effect: users improve by recording more, feedback or not |
| **Intervention randomisation** | 20% | **NOT BUILT.** The only route to causal attribution — confounded data cannot be un-confounded |
| **Dismissal ceiling** | TBD | Unset |
| **Lag weighting** | TBD | Unset. Acceptance arrives in seconds, change a take later; at equal weight the fast signal dominates by volume |

**γ_control and intervention randomisation are the two that cannot be retrofitted.** Both have to be running *while* the data accumulates or the accumulated data cannot answer the question — which is the same argument as the frozen drift reference (Appendix G.7).

---

## H.10 · What is built, and what it does not do

`services/manager_engine.py` is **pure** — no DB, no clock, no randomness of its own. The exploration roll is injected so the policy stays deterministic under test. 38 unit tests pin the derived constants and the invariants that fail silently.

**§11 is amended, so the ceiling is real** — the router no longer discards everything after the first finding, and budget enforcement lives only in `manager_engine.budget()`.

**It is not wired to anything.** No engine currently submits a candidate: no live dimension has a `fire_at`, so `registry.can_fire()` returns False across the board (Appendix F, F-10). The manager is complete and idle by construction — which is the correct order, since a manager built after the thresholds would be built to fit whatever they happened to produce.

**AC-9.** Nothing this module computes is user-facing. Priority values, PPV estimates, mastery probabilities and deviation multiples are internal arbitration inputs and must never reach a client-facing schema or user-visible copy.
