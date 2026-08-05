# Speech Coaching System — Canonical Specification

**Version:** v3. Supersedes v1 and v2 entirely.
**Status:** v1.0 scope locked. Build to this document.
**Audience:** implementing engineer / coding agent.
**Read §0 and §1 before anything else.**

**Companion documents (normative, not optional):**
- [Appendix A — Verbal Computations](SPEC-APPENDIX-A-verbal-computations.md)
- [Appendix B — Feedback Progression](SPEC-APPENDIX-B-progression.md)
- [Appendix C — Intervention Contract](SPEC-APPENDIX-C-intervention-contract.md)
- [Appendix D — Fire-Up Benchmarks and Trigger Functions](SPEC-APPENDIX-D-benchmarks.md)
- [Appendix E — Research Findings and Required Amendments](SPEC-APPENDIX-E-research.md)
- [Decisions log — settled after v3](SPEC-DECISIONS-LOG.md)

---

## §0 · Decisions settled in review — do not relitigate

| # | Decision | Consequence |
|---|---|---|
| D1 | **North star changed.** F2's construct moves from challenge/threat to **confidence**. Founder re-locked L2 explicitly, in the same breath, which `NORTH-STAR LOCK` permits. | The filter's north-star gate is satisfied. Do not re-apply it to this change. |
| D2 | **Re-point the existing pipes. No hard deletions.** | Challenge/threat plumbing is reused, not removed. Existing `training_labels` rows are archived under their original construct, never dropped. |
| D3 | **Ternary (yes / no / neutral) is the v1.0 instrument.** | 2AFC paired comparison is a v2 backlog item. Do not build pair selection, pair-shaped responses, or a pair table. |
| D4 | **Comment reveal is sequential, gated on a committed blind rating.** | §3.3. "Alongside" was wrong and is removed. |
| D5 | **Coach budget: one sourcing pass, two labels.** | Not a budget split. §1.1. |
| D6 | **Triage `readiness` is a bounded decay factor, never a zeroing multiplicand.** | §8.2. |
| D7 | **Triage effectiveness anchors on deterministic change detection or ΔSE.** Machine score at N+1 is **banned** as a target. | §12.2. |
| D8 | **Human and machine confidence carry separate weights, selected between, never summed.** | §7.2. |
| D9 | **Severity is dropped from the presentation signature.** Presentation = `f(intervention_type, state)`. | One note per session means no ordering exists for severity to encode. Amends Appendix C.1, C.4, C.7. |
| D10 | **Lexical overlap / verbatim slide text routes to `CUT`,** not `REWRITE`. | The remedy is stop saying the slide's words. Amends Appendix C.2. |
| D11 | **Four template bands, not three — 32 templates.** `FRAGILE` gets its own. | Appendix B.1 already defines four states; B.2's parameter table is missing the FRAGILE column. Amends both. |
| D12 | **A pending auto-comment is withheld, not shown flagged.** The moment still plays; it plays silent until adjudicated. | At ~15 labels/week most moments are never adjudicated. Amends §3.3 and Appendix C.4. |
| D13 | **An embedding layer is added.** Semantic alignment becomes deterministic, cheaper per call than an LLM read, and version-stampable. | No embeddings exist in the repo today. §3.5. |
| D14 | **The confidence question is** *"Does the speaker sound confident here?"* | Single-barrelled. The earlier "confident **and authoritative**" was two constructs, which §1.3 forbids. |
| D15 | **`APPRENTICE` (low performance, high calibration) is a first-class state** routed to practice scaffolding, not more feedback. | Already correct in Appendix B.1; B.2 must gain its column. |
| D16 | **Graduation is anchored externally** — deterministic change detection, never the state machine's own counter. | Otherwise the system grades its own homework. Amends Appendix B.8. |
| D17 | **The GRADUATE cohesion fade is a tunable defaulting to no fade.** | The evidence has a knowledge × skill interaction (O'Reilly & McNamara, N=143): high-knowledge *skilled* readers do better with *high* cohesion. Amends Appendix B.2. |
| D18 | **Policy parameters fixed:** "as you go" = **takes recorded, banded** · "max 50%" = **per feedback-eligible slide-moment** · `effect_size` = **A 1.0 / B 0.6 / C 0.0**. | `C = 0.0` makes the §11.1 routing gate arithmetic, so the gate and the formula cannot drift apart. |

**Still open — do not assume:** deployment channel, B2C vs B2B (§13). Cross-user peer consent is **resolved** — the privacy policy and the pre-game agreement cover data use for this purpose.

---

## §1 · The binding constraint

**Coach labelling capacity is ~20 labels/week nominal, ~15 effective. The founder is the coach.** This is the bottleneck — not compute, not model choice.

Settled consequences:

- **v1.0 ships exactly one cognitive state: CONFIDENCE.** Provisional at ~100 labels, trusted at ~200.
- **Splitting the budget across states means nothing reaches provisional for months.** Three half-built recognizers instead of one that works. Confidence gates the Album Engine, the ranking term, and the product thesis.
- **The schema is state-generic.** Build tables and interfaces to take `state_id`; populate only `confidence`.
- **A second state accumulates for free via the game lane** — a question asked of the *recording owner only*, never of the coach. Ships as plumbing with **no question attached** (§14).

### 1.1 · How the Feedback Engine gets a learning loop without splitting the budget

Resolved by **sequencing, not splitting**:

```
one clip, one coach session:
  1. adjudicate confidence  — BLIND, no model output in payload
  2. submit                 — label committed and immutable
  3. reveal the auto-comment for the same clip
  4. approve or edit it     — yields the DPO pair + any label correction
```

One sourcing pass, two labels. Costs time-per-label — ~20/week nominal, expect ~15 effective — but does not divide the confidence corpus.

**Step 2 must commit before step 3 renders.** If the comment can influence the confidence rating, I1 is breached and the corpus is contaminated at the source.

### 1.2 · v1.0 finding set — six findings, total

Finding IDs use the north-star table's dimension codes, which are already stable. Where Appendix A defines an equivalent, the mapping is noted.

| `finding_id` | Dimension | Engine | Type | Computation | Grade |
|---|---|---|---|---|---|
| `D10` | conversational style | FEEDBACK | `REWRITE` | 2nd-person address + contractions + direct-address per 100w vs formal 3rd-person markers | **A** (d = 1.00) |
| `A2` | lexical overlap with slide *(≡ Appendix A V15)* | FEEDBACK | `CUT` | bi/trigram overlap between spoken window and on-screen text, length-normalised. **Low is good.** | **A** |
| `D7` | pronoun profile | FEEDBACK | `REWRITE` | I-rate, we-rate, ratio, per 100w | **A** (d ≈ −0.85) |
| `D1` | concreteness | FEEDBACK | `REWRITE` | mean Brysbaert over lemmatised content words, **plus coverage %** | **A** |
| `A6` | topic discipline | FEEDBACK | `CUT` | proportion of utterance time semantically distant from the stated thesis | **A** (d = 0.86) |
| `CONF` | vocal confidence | ALBUM | `NOTICE` | `services/voice_confidence.py` v2 composite → panel-adjudicated | **B** |

**`D1` coverage % is load-bearing.** If under half the content words are in the Brysbaert norms, the mean is unreliable and the writer must not generate a claim from it. Threshold and behaviour are declared in the detector.

Five of the eight intervention types have no producer in v1.0. Ship the enum complete (C3 — the set is closed); **do not build the affordances nothing emits into** (`TWO_OPTIONS`, `INLINE_INSERT`, `CALENDAR`).

### 1.3 · Deferred, with reasons — do not reintroduce

| Candidate | Why not |
|---|---|
| Feeling-of-knowing | Best *scientific* second target — terminal contour is a cleaner, less confounded marker (Smith & Clark; Brennan & Williams) and `f0_mid_end_delta` is already computed. Worst *first* target: no composite, no external anchor, and it needs the hedge extractor. |
| Audience modelling | **No vocal channel.** Jargon density and assumed-knowledge against the brief — pure text. Cannot be a listening question. Belongs to the Feedback Engine. |
| Cognitive load | Acoustic and real, but **filler rate is not computed**. Needs an extractor. |
| Verbal confidence (hedges / boosters / tag questions) | Same reasoning as cognitive load, applied consistently. Hyland's published lists make it a day's work — but a day is not zero. |
| Emotion | Carries the Article 5 exposure (§13). It is the only Album-eligible deferred construct remaining, which is why the owner-only lane ships with **no question attached** rather than committing to it by default. |

### 1.4 · Construct hygiene

Draft questions have already drifted from the states they claimed to measure:

- *"Did this voice break while speaking?"* measures **vocal strain**, not cognitive load.
- *"Was this clear?"* measures **clarity** — the single most confounded item with generic "sounds good" on the list.
- *"...confident **and authoritative**"* is **two constructs** in one question (fixed by D14).

**Rule: every panel question must trace to a written operational definition of the named state, and must ask exactly one thing.** If the definition isn't written, the question cannot ship. A question that measures something adjacent creates a new undefined construct while appearing to build a defined one.

---

## §2 · System overview

One shared recognizer, two engines, separated by **what kind of claim the label is** — not by subject matter.

### The routing principle

> **ALBUM** = a perceptual event requiring witnesses. There is no fact of the matter without listeners; the panel *constitutes* the truth.
>
> **FEEDBACK** = a checkable defect requiring an expert. There is a fact of the matter; one qualified coach can state it; the remedy is an edit.

Vocal/verbal is a reliable proxy, **not** the rule. Test new dimensions against the principle, not the modality.

### Engine assignment

| Construct | Signature | Engine | v1.0 |
|---|---|---|---|
| Confidence — vocal | amplitude range, terminal contour, latency, f0 | ALBUM | **YES** |
| Structural / wording dimensions | text + slides | FEEDBACK | **five only — §1.2** |
| Confidence — verbal | hedges, boosters, tag questions | FEEDBACK | deferred (extractor) |
| Feeling-of-knowing | terminal contour + latency + hedges | ALBUM | deferred |
| Emotion + vocal/verbal congruence | acoustic, panel-adjudicated | ALBUM | deferred (Article 5) |
| Cognitive load | vocal, within-speaker paired contrast | ALBUM | deferred (extractor) |
| Audience modelling | lexical only | FEEDBACK | deferred |
| Construal / attentional focus | lexical only | FEEDBACK | deferred |

---

## §3 · Measurement design

### 3.1 · Acoustics are candidate generators, not claims

**The acoustic detectors do not need to be valid state classifiers.** In the Album Engine they generate candidates; the blind panel is ground truth.

A detector at 60% precision is useless as a claim and adequate as a search heuristic, because everything it flags is adjudicated before the user sees anything. This is what makes the Album Engine defensible despite the weak vocal-state literature.

**Do not build as if detector output were the finding.** The detector's job is recall. The panel's job is truth.

### 3.2 · Instrument: ternary, single clip (D3)

- Response schema: **yes / no / neutral** on one clip
- Answer labels are **identical across all states**; the question carries the state
- The **question text is versioned** exactly as composite weights are. Changing the wording starts a new corpus; mixing versions silently is the same defect as mixing v1 and v2 confidence scores
- A **"no" answer is a positive finding**, not a null: the acoustic change was sub-perceptual and did not occur in any sense that matters. Store it as data
- **"Can't rate — audio unclear" is a separate control, outside the answer space.** It is a flag on the row, not a fourth value. This keeps the ternary clean, preserves abstention rate as a rater-quality signal, and stops unrateable audio being booked as "neutral"

**What must change to support this** — v2 of this document wrongly listed these as unchanged:

| Component | Today | Required |
|---|---|---|
| `game_engine.answer_round(..., answer_is_key)` | takes a **boolean**, writes `key_moment`/`neutral` | ternary parameter, ternary label |
| `snippet_peer_labels.label` | binary enum | ternary enum — **migration** |
| `training_labels.VALID_VALUES` | `("threat","ambiguous","challenge")` | `("no","neutral","yes")` — **data migration, not a comment change** |
| `_arc_moments` | keys via `resolve_direction` → challenge-labelled | re-pointed to confidence |
| `stratified_label_queue` | single clips across four score bands | unchanged ✓ |

**2AFC paired comparison is backlogged to v2.** It is the better measurement — materially better inter-rater reliability — and it needs pair selection, a pair-shaped response and a different table. Do not partially implement it.

### 3.3 · Comment reveal — the sequential gate (D4, D12)

The comment is the *justification for the choice*, revealed after the choice is committed. It is never an input to the rating.

**Game lane (owner or peer):**

```
album-flagged span appears
  → modal opens: label it (yes / no / neutral)   ← BLIND
  → submit, committed
  → comment revealed as justification            ← only if verified
```

**Coach lane:** as §1.1.

**Unadjudicated moments play silent (D12).** Until a coach has adjudicated, **no comment is shown at all** — the moment still plays, it simply carries no text. v2 specified a `pending` marker; at ~15 labels/week most moments are never adjudicated, so a pending marker would be the default state rather than the exception, and a mostly-unverified surface trains users to ignore the distinction.

### 3.4 · Band quotas — staged

`stratified_label_queue` keeps its four bands (confident / neutral / doubtful / unscored), but the quota shifts with corpus size:

- **Below ~50 labels:** extremes-heavy. There is no boundary to sample around yet, and extreme clips are rated more reliably by humans.
- **Above ~50 labels:** boundary-heavy. Everything a classifier doesn't know lives in the middle; extremes are the cheapest labels and teach the least.

The within-band pick stays hash-deterministic and the final order stays band-shuffled — an ordering tell would anchor labels exactly as a visible score would.

**Note for evaluation:** if the corpus is drawn extremes-heavy, its agreement rate is **not** comparable to the Jiang & Pell listener benchmark, which was measured on a balanced set. Re-weight before comparing, or the validation gate reads better than it is.

### 3.5 · The embedding layer (D13)

Semantic distance requires a semantic representation. There are **no embeddings anywhere in the repo today** — `A6` (topic discipline) and slide concept alignment currently run through LLM reads (`snippet_stickiness`, `slide_alignment`), which are model-version-dependent and not reproducible.

Add one embedding model. Embed each spoken window and each slide's text; cosine for alignment; distance-from-thesis for `A6`. Cheaper per call than an LLM read, deterministic, and version-stampable like every other composite.

**The LLM then does what it is good at:** reading `alignment = 0.34, drifting_span = [142s–171s]` and writing the sentence about it. It is a **verbalizer over a structured score object, never a scorer** (§8.3).

### 3.6 · Within-speaker contrast (deferred load state)

When cognitive load is built, compare **the same speaker, easy vs hard segment**. Speaker identity cancels. Absolute load classification is speaker-dependent and fails (single-sentence AUC ≈ 0.61); within-speaker contrast is the design that produced the clearest results in the literature.

---

## §4 · Scope tiers — enforce in code

Scoring a talk-level dimension on a snippet produces a confident number with no referent. The scorer must refuse.

```python
class Scope(Enum):
    SNIPPET = "snippet"
    TALK    = "talk"
    CONTEXT = "context"
```

| Scope | Dimensions |
|---|---|
| **SNIPPET** | slide concept alignment, lexical overlap w/ slide, given–new ordering, syntactic load, concreteness, abstraction, pronoun profile, hedge/booster balance, conversational style, filler position, rhetorical format *presence*, macro-signposting *presence*, vocal confidence percept |
| **TALK** | arc reversal, peak lateness, ending strength, curiosity gaps (open **and** resolve), refutational two-sidedness (raise **and** answer), topic discipline, orientation & closure, segmentation, term seeding, narrative/expository ratio, affective density, lexical diversity, metaphor density |
| **CONTEXT** | target-group stickiness, register fit, cohesion fit to prior knowledge, purpose alignment |

**Invariant:** `score(dimension, unit)` raises if `dimension.scope != unit.scope`. No silent coercion.

---

## §5 · Normalisation and fairness

### 5.1 · Speaker-relative normalisation is primary

Score **deviation from this speaker's own baseline**, not a population norm. Handles high-voiced men, low-voiced women, trans speakers, illness, recording conditions; needs no protected attribute for most users. Matches the literature — the validated charisma predictor is *proportion of the speaker's own range used*, not absolute pitch.

### 5.2 · Sex enters at the calibration layer only

**Permitted:** group-conditional reference distributions, per-group thresholds, per-group precision/recall as a standing dashboarded metric. Auditable, monotone, inspectable, version-stamped.

**Not permitted:** sex as a free input feature to a learned scoring head, where it can absorb correlations that cannot be inspected.

**Rationale — this is a de-biasing measure, not a bias source.** "Fairness through unawareness" fails: hiding the attribute removes the ability to detect and correct disparate impact, not the impact itself. Human confidence ratings penalise women's natural vocal range (vocal-fry penalties significantly larger for women; low-pitch preference stronger for female speakers). A model trained blind on those labels inherits the penalty.

### 5.3 · `services/voice_confidence.py` v2 is explicitly compliant — do not remove it

A builder reading §5.2 in isolation could read the v2 sex-routed cue table as a violation and strip it. **It is not a violation.** It is the permitted case, and it is the one piece of code in the repo that prevents systematically mis-scoring one sex.

The justification is the **sign flip**. Every cue is *already* within-speaker z-scored — and **cue 1 reverses direction by sex** (pitch range trends confident in female talkers, unconfident in male). A sign reversal is mathematically not absorbable by normalisation, however well calibrated. Sex-blind weights mis-score one sex no matter what.

It qualifies because it is hand-weighted, literature-sourced, `version`-stamped, carries `sex_source` provenance on the blob, has a kill-switch scoped to the acoustic fallback only, and falls back to sex-blind v1 weights for anything not resolved to exactly `female`/`male`.

Per-sex re-fit keys on `version` + `sex_source`. Preserve both.

---

## §6 · Data model (state-generic)

```python
@dataclass
class Snippet:
    id: str
    recording_id: str
    speaker_id: str          # splits are BY SPEAKER, never by clip
    t_start: float
    t_end: float

@dataclass
class StateCandidate:
    snippet_id: str
    state_id: str            # v1.0: only "confidence"
    detector_version: str
    certainty: float
    features: dict
    flagged: bool            # False for randomised control samples (I4)

@dataclass
class TernaryRating:         # D3 — single clip, 3-class
    candidate_id: str
    rater_id: str
    lane: Literal["bootstrap", "coach", "game_peer", "game_owner"]
    question_id: str         # traceable to a written operational definition
    question_version: str    # §3.2 — wording changes start a new corpus
    value: Literal["yes", "no", "neutral"] | None
    unrateable: bool         # the separate control — not a fourth value
    latency_ms: int
    saw_model_output: bool   # MUST be False for the rating step
    probe_score_at_time: float
    model_version_at_time: str

@dataclass
class AggregatedLabel:
    candidate_id: str
    state_id: str
    value: float             # mapped +1 / 0 / -1, aggregated
    agreement: float         # KEEP — see I10
    n_raters: int
    quality: float           # f(n_raters, agreement) — feeds §7.2
    label_source: Literal["human", "machine"]
```

### 6.1 · Re-point without deletion (D2)

`training_labels` rows carrying challenge/threat labels are **not dropped**. They are stamped with their original `construct` / `construct_version` and excluded from confidence training **by query, not by DELETE**. They remain available if the north star moves again, and they are the only record of what the shipped model was trained on.

**~130 files** reference challenge / breakthrough / direction across the repo (excluding `venv/` and worktrees); 68 in `services/` + `routes/` alone. The pipes — `challenge_threat.py`, `moment_direction.py`, `game_engine.py`, `training_labels.py`, `power_phrase_ranking.py` — are re-pointed in place. What changes is what the label *means*, plus the enum strings (§3.2). Not the transport.

**The cost of D1, stated plainly:** existing direction labels die. A "challenge" label is not a "confident" label and cannot be reinterpreted. The count of rows in `training_labels` at cutover is the price paid for the north-star change.

### 6.2 · The four lanes

| Lane | Who | Asks about | Budget | Blind? |
|---|---|---|---|---|
| **Bootstrap** | founder, manual upload | confidence | shares the ~15/week | partially — see below |
| **Coach** | founder | confidence (blind) → then comment review | ~15/week effective | yes, for step 1 |
| **Game (peer)** | cross-user | confidence, ternary | free at scale | **yes** — answer-then-reveal |
| **Game (owner)** | recording owner | *nothing in v1.0 — plumbing only* | free | n/a |

**The bootstrap lane is not panel-grade.** It is one rater on a model-proposed candidate — the model is not a second judgment (§3.1). It exists to break the cold-start circle: the panel cannot run until there is a detector worth adjudicating, and there is no detector without labels.

Its rules:
- `lane = "bootstrap"` on every row
- **Excluded from agreement statistics** — one rater has no agreement
- **Never drawn into the gold set** — it is the training seed, so it cannot be the holdout
- Once panel data exists, bootstrap labels are **down-weighted or frozen, never deleted** (same principle as D2)

**Known limit of v1.0, stated for the record:** the founder is the coach. The corpus is one person's perceptual model, and that person also designed the system. This is the only option available at this stage and it is honest, but it makes two things load-bearing that would otherwise be merely good — the **blind protocol** (the key stays closed until the sheet returns) and the **Jiang & Pell anchor**, which is the only external check on a single-rater corpus.

---

## §7 · `power_score` after the re-point

### 7.1 · What exists today

```python
_COACH_TERM     = {"strong": 1.0, "to_work_on": -1.0}
_DIRECTION_TERM = {"challenge": 1.0, "threat": -1.0, "ambiguous": 0.0}
_W_C, _W_A, _W_S = 2.0, 1.0, 0.6
_W_D, _W_B       = 1.0, 2.5
_W_V             = 1.0     # contributes 0 today: flag defaults OFF
```

The file documents an **ordering of authority**: coach verdict dominant (`_W_C` swing = 4.0) > breakthrough bonus (2.5) > everything else, and `_W_V` was sized so its full swing (2.0) cannot cross the coach gap. **That invariant survives the re-point.**

### 7.2 · The blend after the change

Three terms change. Everything else is untouched.

**`_W_D` (direction) retires.** `is_challenge()` becomes `is_confident()` — the surfacing filter now shows confident moments; unconfident ones inform ranking and are never shown to the user. The filter's *job* is unchanged: it is what stops the app being a list of your failures.

**`_W_B` (breakthrough, 2.5) survives with a new definition.** It fires when a clip **clears the album quorum** — multi-rater agreement — not when one person calls it confident. That distinction is what keeps it out of I11's double-count ban: `_W_CONF_PANEL` is *one* aggregated judgment on a clip; `_W_B` is a *consensus event*.

**Confidence enters exactly once, panel-sourced or machine-sourced, never summed (D8):**

```python
if panel_label is not None:
    conf   = panel_label.value                      # +1 / 0 / -1
    weight = _W_CONF_PANEL * panel_label.quality    # quality = f(n_raters, agreement)
    source = "human"
else:
    conf   = machine_est                            # continuous, tanh w/ dead zone
    weight = _W_CONF_MACHINE
    source = "machine"
```

```python
_W_CONF_PANEL   = 1.5   # swing 3.0 — above machine, below the coach gap (4.0)
_W_CONF_MACHINE = 1.0   # swing 2.0 — unchanged from _W_V
```

**Weights are separate because the scales are.** The panel emits three discrete values; the machine emits continuous −1…+1 through a tanh dead zone. One shared weight over two signals of different scale *and* different reliability is a scale mismatch.

**The panel term scales with label quality.** A two-rater split decision must not move ranking as much as a five-rater unanimous one. `quality` is a function of `n_raters` and `agreement` — both already stored (I10). This also means the peer lane strengthens the term automatically as it grows, with no weight change.

```python
_QUALITY_SHRINKAGE = 2.0   # k

def quality(n_raters: int, agreement: float) -> float:
    """Bounded (0, 1), monotone in both terms, SAMPLE SIZE DOMINATES."""
    return (n_raters / (n_raters + _QUALITY_SHRINKAGE)) * (0.5 + 0.5 * agreement)
```

**Sample size dominates agreement, by decision.** A five-rater panel at 60% agreement (0.57) outweighs a two-rater unanimous one (0.50). That is the correct statistical intuition for a perceptual construct: the panel is estimating a *population percept*, so more independent witnesses beats fewer confident ones. Two people agreeing is a small sample, not a strong finding.

| n_raters | agreement | quality |
|---|---|---|
| 1 | 1.00 | 0.33 |
| 2 | 1.00 | 0.50 |
| 5 | 0.60 | **0.57** |
| 5 | 1.00 | 0.71 |
| 10 | 1.00 | 0.83 |

The agreement term never zeroes the product — a genuinely ambiguous moment still carries half its size-derived weight, because ambiguity is a finding (I10), not an absence of one.

**Do not bucket the machine score into three classes** — that destroys the variance needed to break ties across the unlabelled majority, which is most of the corpus.

**The coach is a peer for confidence.** There is no privileged expert vote on a percept — §2's routing principle says the panel constitutes the truth. The coach's ternary rating carries the same weight as any peer's inside the aggregate.

**`_COACH_TERM` / `_W_C = 2.0` stays privileged.** `strong` / `to_work_on` is not a percept — it is an expert assessment of whether the phrase is good, which is Feedback-type by the same routing principle. Expert authority is appropriate there.

> **Precision for implementers:** `_COACH_TERM` is a *tag on a snippet*. DPO pairs come from `admin_annotation_events` (`ai_original_text` → `coach_final_text`). Same **lane** — the coach's expert Feedback judgment — but not the same **object**. Do not wire the tag into the DPO exporter.

Ties among panel-labelled clips (only three possible values) fall through to `activation` and `slide_stickiness`, as they already do.

`label_source` is stamped on the blob beside `sex_source`.

### 7.3 · The flag

`VOICE_CONFIDENCE_RANKING_ENABLED` stops meaning "does `_W_V` contribute" and starts meaning **"is the machine fallback trusted yet"** — which is the question the validation gate actually answers. Default stays OFF until validation passes. With it off, unlabelled clips contribute 0 for confidence and rank exactly as they do today.

---

## §8 · Feedback Engine

1. **Score** → structured score object. Scope, certainty, timestamp span, and the evidence that produced it. Never prose at this stage.
2. **Triage** → select exactly one finding (§8.2).
3. **Write** → comment conditioned on the finding **and its evidence** (§8.3).
4. **Coach reviews** — after the blind confidence step (§1.1). Approve or edit.
5. **Capture both signals from one edit:**
   - Rewritten text → `(original = rejected, corrected = chosen)` DPO pair.
   - Changed *finding* ("this isn't structure, it's slide alignment") → **label correction for the recognizer.** More valuable than the DPO pair. Do not discard it.

### 8.1 · Naming discipline

Only step 5 is DPO. Steps 1–4 are a multi-task recognizer, a triage policy and a score-conditioned generator. Describe the system as **"a triage-gated, score-conditioned generator aligned from expert edits."** Do not call the whole engine a DPO engine in external material.

### 8.2 · Triage priority — bounded decay, never zero (D6)

```
priority = (deviation × effect_size × remediability)
         × R(k, Δt)          # short-term, within-session inaction
         × G(state)          # long-term, per-dimension  (Appendix B.4)
```

`R` is a **factor with a hard floor**, not a multiplicand that can zero the product.

```
R(k)     = max(0.20, 1.0 − 0.35·k)                     # v1.0 — in-session form
R(k, Δt) = max(0.15, γ^k + (1 − e^(−Δt/τ))),  γ = 0.5  # once session cadence data exists
```

where `k` = consecutive unacted impressions, `Δt/τ` = time/session recovery.

**Hard invariants, unit-tested:**
- `priority` can **never** be 0.0 from user inaction
- An unacted note (`k = 1`) is demoted relative to new notes but stays above 0
- A deviation spike ≥ 2× overcomes the decay penalty and resurfaces the note regardless of `k`
- **The floor is asserted on the product `R × G`, not on each factor** (Appendix B.4). Two suppressors each above their own floor still multiply below both

**Definitions (D18):**
- `deviation` — distance from target on that dimension
- `effect_size` — **A = 1.0, B = 0.6, C = 0.0.** `C = 0.0` makes the §11.1 grade gate arithmetic, so the gate and the formula cannot drift apart
- `remediability` — does the fix fit inside one rehearsal cycle. Boolean in v1.0, ordinal later

### 8.3 · The writer contract

**The LLM is a verbalizer over a structured score object, never a scorer.** It receives numbers and spans; it emits prose. Three things are declared per dimension:

**(a) The computation** — formula, inputs, output range, version stamp.

**(b) The evidence payload** — exactly what the writer receives. Not the transcript: the score, the speaker's own baseline for that dimension, the specific spans that drove it, and the comparison target.

**(c) The presentation contract — a closed vocabulary.** If the writer may emit arbitrary markup it will invent formatting per call and no two comments will look alike. Permitted: `**bold**` for the exact words at issue, and a span reference for the timestamp. Nothing else.

> **On emoji:** a trailing ✅ or ⚠️ is a **verdict token**, and AC-9 bans surfaced verdicts. A neutral marker is fine; anything valenced or graded is a score wearing a costume. If emoji are wanted, the set must carry no direction.

Templates are keyed on `intervention_type × state band` (Appendix C.6), **never** on `finding_id`.

### 8.4 · Learning per stage

| Stage | Method |
|---|---|
| Recognizer | active learning (least-certain / head-disagreement to the coach) + label correction |
| Triage | contextual bandit, off-policy from logged outcomes, **with an exploration quota** — a fixed % of sessions surface rank 2 or 3; log the counterfactual |
| Writer | online DPO, after SFT. **Never DPO from stock** — it optimises a preference direction, it does not teach the task |

**One writer, not two.** Control token for `FEEDBACK` vs `ALBUM`. Two writers halves scarce preference data.

**Instrument `DpoExportStats.too_similar` from day one.** Tight templating is good for consistency and makes coach edits comparable, but `ml_dpo_export.py` drops any pair with similarity ≥ 0.985. At ~15 labels/week, template-induced corpus starvation must show up in week 2, not week 12.

**User accept/reject is not a DPO pair.** A dismissal is a dispreferred output with no preferred counterpart — there is no triplet. It feeds cross-take consistency and segmentation (§12.4), or filters the DPO set. It never becomes half of an invented pair.

---

## §9 · Album Engine

1. **Detect key moments** — highlight detection. v1.0 confidence parameters: terminal contour on assertions, amplitude-range collapse, elevated speaker-relative mean f0, latency spikes.
2. **Route to raters** — ternary, blind, plus the I4 unflagged control stream.
3. **Aggregate + retain agreement** (I10), and compute `quality` for §7.2.
4. **Then write, then DPO.** Order is a hard constraint: perceptual label first, comment second. DPO on a comment whose label was never validated teaches the writer to phrase an unverified claim more persuasively — the failure mode that most resembles success.
5. **Feed the self-regulation loop** — validated moments become anchored review examples.

### 9.1 · Quorum and the override path

A moment enters the album at **three-way agreement** — model, coach, peer. The model's vote is **asymmetric by design**: it can help a moment in, never keep one out.

**The override path:** where the coach marks a moment the model rejected and a peer confirms it, **two humans is sufficient** and the model is overridden. This is what preserves discovery — the album can contain moments the model missed.

**Log the override rows separately from day one.** Every "coach yes, model no, peer confirms" is a labelled model miss with two independent human confirmations. That is the blind-spot corpus, and it will be the most valuable few hundred rows in the system.

### 9.2 · Presentation

- **The album never names the state.** "You sounded confident here" is a verdict about the user under AC-9. The moment plays; the qualitative framing carries the meaning.
- **The album is uncapped and grows.** Nothing ages out. A moment that cleared quorum stays.
- **Predict-then-reveal is a mandatory hard gate** before any playback. Harvey et al. found no corrective shift without cognitive preparation, and anxious users anchor on flaws — without the gate the album makes them worse, not better.

**Structure — two levels, both recency-first:**

| Level | Contains | Ordering |
|---|---|---|
| **Per project** (arc) | every qualified moment from that arc | most recent first; the 5 most recent displayed at the top |
| **Pool** | every qualified moment the user owns, across all arcs | most recent first; the 5 most recent displayed at the top |

The five-most-recent rule is a **display** rule, not a retention rule. Everything is kept; recency decides what the user meets first. That matters for the mechanism — self-modelling works on *mastery experience*, and the most recent evidence that you can do the thing is the strongest form of it.

**Consequence for `_W_B` (§7.2):** because nothing ages out, "cleared the album quorum" and "is in the album" are the same predicate. The bonus fires once a moment clears quorum and does not decay. Had the album rotated, ranking would drift for reasons unconnected to the speech.
- The gate's by-product is the **calibration** measure (Appendix B) and the **self-observer discrepancy** segmentation axis (§12.4), at no extra instrumentation cost.

### 9.3 · What the album is for

Audio self-modelling — Dowrick's positive self-review; Bellini & Akullian's 23-study synthesis. **The active ingredient is the editing out of failure, not the watching.** The mechanism is Bandura's mastery experience, which is why the outcome measure is self-efficacy (§12.3) and not "did you like it."

**Open empirical question:** nearest-to-own-baseline versus a set spanning several states. Default to **nearest-to-baseline** pending the A/B (§12.3) — micro-mastery just above baseline is the closest available proxy to a mastery experience — but this is a prior, not a finding.

---

## §10 · Non-negotiable invariants

### Load-bearing — never cut

**I1 · Blind-stream integrity.** The rating step never receives model scores or model comments. **Enforce at the data layer** — the score object and the comment are not in the payload served for a rating. The comment is a separate fetch, available only after the rating is committed (§3.3). Every future UI change will want to "add context." Make it structurally impossible.

**I2 · Frozen gold set.** A versioned, fully adjudicated hold-out, never trained on, evaluated on a schedule, inspected rarely. See §12.4 — there are four distinct sets and only one is I2.

**I3 · Outcome anchor in the triage reward.** Deterministic change detection or ΔSE only. See §12.2. Machine score at N+1 is banned.

### Standard

**I4 · Randomised unflagged stream.** A fixed proportion of snippets the detector did **not** flag go to raters anyway. Without negatives you measure precision and never recall, and "no" answers mean nothing. Also the only thing that lets dynamic thresholds adjust toward reality rather than toward themselves. Start at 20%.

**I5 · Speaker-independent splits.** Split by `speaker_id`, enforced in the data loader — not in a convention someone remembers.

**I6 · Seeded probes.** Pre-adjudicated segments into the game panel. **Probe the peers, not the coach** — honeypots are a scale technique, and spending scarce single-expert capacity probing your only expert is not a good trade.

**I7 · Approvals are weak signal.** An un-edited approval is not an edit. Weight edits far above approvals; cap the un-edited proportion of any training batch. Training on accepted own-output at scale causes writer collapse.

**I8 · Periodic retrain from base.** Fixed cadence: retrain from the base checkpoint on the full corpus, compare to the incremental model on the gold set, ship whichever wins.

**I9 · Full label provenance.** Rater, timestamp, model version, whether model output was visible, latency, probe score, lane, question version. Without this a contaminated cohort is unidentifiable and poisons the corpus permanently.

**I10 · Keep disagreement.** Low agreement is a finding — the moment is genuinely ambiguous. Store `agreement` alongside `value`. A model that predicts ambiguity beats one that fakes certainty.

**I11 · No construct enters a composite twice.** Every term declares its construct; assert at composite build time. Plus a correlation matrix over the gold set in CI flagging any term pair above threshold, and a **declared-vs-effective weight report** tracked over time. The third is what catches silent drift — declared weights flat while effective weight climbs as a detector improves.

**I12 · Labels are never tied to a feature version.** Store `(audio_segment_path, question_version, answer, rater, timestamp)`. Raw audio is retained indefinitely. This is the single cheapest piece of insurance in the design: it is what lets the recognizer move from logistic regression to a fine-tuned audio encoder later without re-labelling from zero.

---

## §11 · Intervention delivery constraints

Enforced structurally by the router, not by convention.

```
if mode == LIVE:
    suppress all mechanical delivery cues        # choking, r = .59–.64
    permit only sparse external-focus cues, ≥20s apart
per session:
    surface exactly ONE finding
playback:
    predict-then-reveal gate MANDATORY before any footage
    good takes first, before anything negative
framing:
    task-level only — never person-level praise  # self/praise d = 0.14
    criterion-referenced — never normative, never leaderboards
    fade frequency toward ~50% as skill develops   # per feedback-eligible slide-moment (D18)
    fade specificity: granular early, coarse later
    replay requested AFTER the attempt, never pre-scheduled
```

**Never auto-fix.** Surface the problem, offer two contrasting orderings, the user chooses and says why. Auto-reordering removes the generative work where the learning happens.

**`criterion-referenced, never normative` is enforced, not documented.** It is a constraint on copy, and the repo already has the pattern — a regex fence plus a CI probe, as `_CONSTRUCT_RE` does for the retired charisma vocabulary. A guideline in a document will erode; a failing test will not.

**The 24 policy interventions live outside the Finding contract.** Fade frequency, bandwidth feedback, criterion-referenced framing, timing by task type — these are router behaviour. They have no finding, no anchor and no evidence, and must not be routed through `Finding`.

### 11.1 · Routing gate

```python
def route(snippet, finding, mode, session) -> Engine | None:
    if not scope_valid(snippet, finding):  return None
    if mode == Mode.LIVE:                  return None   # except sparse external cues
    if finding.is_perceptual:
        if detector.certainty < THRESHOLD: return None
        return Engine.ALBUM
    if finding.dimension.grade in {"A", "B"}:            # C = effect_size 0.0 (D18)
        if session.already_surfaced:       return None
        if not wins_triage(finding):       return None
        return Engine.FEEDBACK
    return None   # ← the overwhelming default. Not a failure state.
```

Score forty dimensions, surface one.

---

## §12 · Evaluation

Write the eval **before** the model.

### 12.1 · General

- **Three baselines, always:** random/majority, simple heuristic, human. A number without them is uninterpretable
- **Metrics: Cohen's κ or balanced accuracy, never raw agreement.** With three classes, chance is 33% — and if 70% of moments are "neutral," a model that always says neutral scores 70% and has learned nothing. `corpus_summary()` already flags this failure in the opposite direction
- **Splits:** by `speaker_id`, enforced in the loader (I5)
- **Error analysis:** read 50 failures by hand every cycle. Highest-value hour in the project
- **Album-specific:** inter-rater agreement is a first-class metric. Detector **recall** comes from the I4 unflagged stream — precision alone is not a result

### 12.2 · Triage effectiveness anchor (D7, I3)

```
PRIMARY      deterministic change detection — did the flagged thing actually
             change in the next take, on a dimension with a deterministic
             extractor (lexical overlap, pronoun rate, concreteness)?
SECONDARY    ΔSE — pre/post self-efficacy shift, for the album
DEFERRED     human longitudinal scoring of successive attempts (needs budget)
BANNED       Machine_Score(N+1) as an evaluation target
```

**Why the primary works:** the circularity problem exists only for *model-predicted* dimensions. Lexical overlap, pronoun ratio and concreteness are **deterministic counts, not predictions** — so "did the flagged thing change" is a fact, not the model grading itself. Free, non-circular, available today.

v2 of this document proposed `ΔD_human` on the 40-clip gold holdout. That is incoherent: a gold holdout is a fixed set of clips, and attempts N and N+1 are a user's successive recordings. You cannot measure a user's improvement on a static benchmark.

### 12.3 · Success and kill criteria

**Working:**
- **Recognizer:** κ against coach ground truth on the frozen gold set, compared to the Jiang & Pell anchor (>83% listener agreement; means 4.52 / 3.24 / 2.05 on a 1–5 scale). Re-weight first if the corpus was drawn extremes-heavy (§3.4)
- **Album:** statistically significant positive ΔSE, pre/post exposure

> **Caveat on the album number:** entry requires the owner's own earlier judgment in the game, so the album contains only moments the user already endorsed. The **absolute** ΔSE will read high. The §9.3 A/B comparison is unaffected — the filter applies to both arms equally.

**Kill:**
- **Rule 1 (noise):** ICC below 0.40 across repeated takes of identical content **within a session**. Across sessions is confounded — if coaching works, take 5 *should* differ from take 1, and a state would be killed for succeeding
- **Rule 2 (convergence):** κ < 0.20 after 100 valid human labels. Not raw accuracy

Test-retest proves **stability, not validity** — a consistently wrong measure is consistently stable. It is a cheap first-pass killer, never evidence that a state is real.

### 12.4 · Four distinct sets — do not conflate

| Set | Purpose | Frozen? | Costed? |
|---|---|---|---|
| **Gold hold-out (I2)** | recognizer evaluation | yes — never trained on, never tuned against | — |
| **40-clip coach pass** | external anchoring, blind protocol | yes | **yes** |
| **Jiang & Pell validation anchor** | confidence-composite external validity | yes | no |
| **Album A/B set** | instrument comparison, threshold tuning | **no** — A/B-ing against a set unfreezes it | no |

Only the 40-clip pass is costed. The moment you A/B against a set it stops being frozen — which is why the fourth cannot be any of the first three.

### 12.5 · Segmentation — logged now, built later

Patterns → profiles → treatment matching is the right sequence. **Latent profile analysis needs users in the hundreds** for stable classes; with a small cohort the clusters are noise you then build product on. So segmentation is gated on **user volume, not architecture**.

Log the inputs now: per-user dimension aggregates, calibration, response to each intervention.

**20% of intervention assignments are randomised from day one.** This is the only item in the whole specification that gets permanently more expensive with delay — confounded data cannot be un-confounded, and without randomisation you can never establish which intervention *causes* improvement for whom.

**Once segments exist, randomisation must move inside each segment.** Global 20% estimates an average treatment effect; segment-specific effects need within-segment randomisation.

**The first segmentation axis already exists for free:** self-observer discrepancy from the predict-then-reveal gate — the variable Harvey et al. found predicts who benefits from self-modelling. Same measurement as Appendix B's calibration. One instrument, two jobs.

### 12.6 · Cross-take consistency — a free first-pass filter

Compute the intraclass correlation of each state's reading across takes of the same content by the same user. **It needs no human labels at all.** Low ICC → the state is measuring noise; kill it before spending coach attention. See §12.3 Rule 1 for the within-session constraint.

---

## §13 · Compliance

- **B2C personal-development:** state inference is high-risk under EU AI Act Annex III → transparency and conformity obligations. Consent and disclosure do real work here
- **B2B sold to employers for staff assessment or training:** Article 5(1)(f) **prohibits** emotion inference in workplace and education contexts. **Consent does not cure a prohibited practice.** This is a deployment-model decision, not a UX one. Resolve before any enterprise pilot
- All state inference is opt-in, explained, and disabled by default
- **Data use consent is in place** — the privacy policy and the pre-game agreement cover use of recordings for this purpose
- **Emotion carries the Article 5 exposure.** It is the only Album-eligible deferred construct remaining, which is why §14 ships the owner-only lane as plumbing with no question attached rather than committing to it by default

---

## §14 · Do not build

| Item | Reason |
|---|---|
| Honesty / integrity / sincerity scoring | Vocal trustworthiness has near-perfect rater consensus and near-zero accuracy. Pitch is unrelated to Honesty-Humility, trust-game behaviour, or trustworthy intentions |
| Flow state detection | No validated acoustic or linguistic marker exists |
| Challenge-vs-threat as a *scored construct* | Superseded by D1. **The pipes stay** (D2) — re-pointed, not deleted |
| Vocal/verbal emotion *incongruence* as a deception or quality signal | The channel-leakage cue. Near-zero validity. Permitted only as a panel-adjudicated Album question, where the panel — not the acoustics — is the claim |
| Filler *count* as a competence score | Natural range 1.2–88.5 per 1,000 words; disfluent idea units are *more* recalled. Score position (medial vs initial), not count |
| Sentence-length variance | Writing-craft folklore. No causal evidence, not a Coh-Metrix component |
| 6×6, 10-20-30, words/seconds per slide | No controlled study establishes any optimal figure |
| Gesture counts | Non-peer-reviewed consultancy claim. Mayer's image principle is his weakest (d = 0.19, negative in 3 of 7 tests) |
| Leaderboards, percentile scores, person-level praise | Normative comparison flips the sign of feedback effects |
| 2AFC pair infrastructure | v2 backlog (D3). Do not partially implement |
| Affordances with no producer | `TWO_OPTIONS`, `INLINE_INSERT`, `CALENDAR` — nothing emits into them in v1.0 |

**Charisma is a separate case and is *not* on this list.** It is a perceptual construct — constituted by being perceived — so charisma ratings are valid measurements of a perception, unlike vocal trustworthiness, where the perception has an external referent it fails to track. The Dr. Fox caution is narrower than it looks: charisma ratings and *learning outcomes* are different variables and the first does not predict the second. Measuring it is fine; treating it as evidence the talk worked is not. The `CONSTRUCT` fence stands for its own separate reason — a surfaced number implies precision about a perception, and a visible number gets gamed.

**Owner-only game lane:** ships as **plumbing with no question attached**. The second state is not named in v1.0. Naming it commits to a construct, and the only remaining Album-eligible candidate is emotion.

---

## §15 · Build order

The critical path is **labelling, not code** — ~16 weeks at ~15 effective labels/week, and the clock cannot start until the bootstrap panel asks the confidence question.

| Slice | Scope | Live-loop risk | Unblocks |
|---|---|---|---|
| **1** | State-generic label schema + bootstrap panel asking confidence | **none** — purely additive | **starts the 16-week clock** |
| **2** | The five verbal extractors (§1.2) | none — additive | Feedback Engine |
| **3** | Embedding layer (D13) | none — additive | deterministic `A6` + slide alignment |
| **4** | The re-point: ranking + game (§3.2, §6.1, §7) | **high** — live loop, ~130 files, FE copy | everything user-facing |
| **5** | Album surface + predict-then-reveal gate | medium | the album |

**Slice 1 does not require the re-point.** The bootstrap panel is a separate coach-only page. Writing to a new state-generic label table (`state_id='confidence'`, `lane='bootstrap'`, full I9 provenance) touches neither `training_labels`, `power_score` nor `game_engine`. The clock starts immediately; the risky migration follows while labels accumulate.

**Slice 4 needs its own gated PR with a rollback story**, and founder copy sign-off (`LIVE LOOP`) for the `BreakthroughsOverlay` rename and the game modal wording.

### 15.1 · Timeline

At ~15 effective labels/week: 40-clip pass ≈ 2.7 weeks → provisional (100 labels) ≈ +6.7 → trusted (200) ≈ +13.

**Ship at provisional (~week 9) behind the flag.** A trusted head is not required to start delivering value — human labels reach ranking from week 3, and the machine fallback stays off until it earns its place (§7.3).

**Do not cut the 40-clip pass to save time.** It is the only thing that makes every later number interpretable, and it is the sole external check on a single-rater corpus (§6.2).

### 15.2 · Recommended first addition beyond v1.0

**Appendix A's build order has a dependency defect.** Its Tier 1 is V11, V12, V13, V22 — but V11 and V12 both require `S_voc`, which is V2 in Tier 2, and V13 requires device detection from V11/V12. Only **V22 (unrefuted counterargument)** is genuinely dependency-free: pure text pattern matching, A-graded (Allen, k=19, N=5,624), and it detects a defect that is *worse than not raising the objection at all*.

V22 is the obvious sixth Feedback finding. It is not in v1.0 scope and is noted here so the sequencing is deliberate rather than accidental.

---

## §16 · Open

1. **Deployment channel** — B2C vs B2B. Gates §13
2. `THRESHOLD` for Album detector certainty — set empirically after week 5, not now
3. I4 proportion — start 20%, tune down once recall is estimable
4. τ and the choice between the two `R` forms in §8.2 — start with the simplified in-session form
5. Whether V22 joins v1.0 (§15.2)

---

## §17 · Operational definitions

**This section is the registry §1.4 requires.** Every `question_id` on a `TernaryRating` resolves to an entry here. A question with no entry cannot ship. Entries are versioned; changing the wording starts a new corpus (§3.2), so a change means a **new version**, never an edit in place.

### `conf-q-v1` — vocal confidence

| | |
|---|---|
| **`state_id`** | `confidence` |
| **Construct** | How **assured the speaker sounds in their delivery** of this moment. A property of the voice, not of the content. |
| **Question text** | *"Does the speaker sound confident here?"* |
| **Answers** | `yes` · `no` · `neutral` — plus the separate `unrateable` control (§3.2) |
| **Engine** | ALBUM — perceptual, requires witnesses |
| **External anchor** | Jiang & Pell 2017, Speech Communication 88:106–126. Listener panel reached >83% agreement; mean ratings 4.52 / 3.24 / 2.05 across confident / close-to-confident / unconfident items on a 1–5 scale |

**What it is not.** Three constructs sit adjacent and must not be folded in:

- **Not authority.** Someone can sound entirely sure of themselves without sounding commanding. The earlier draft asked "confident **and authoritative**", which is two questions in one — the defect §1.4 exists to prevent (D14).
- **Not feeling-of-knowing.** That is certainty about *what is being said*; this is assurance in *how it is said*. A speaker can deliver a wrong answer confidently — Tenney's finding, where confident-and-wrong collapsed to 2.8 credibility once the error surfaced.
- **Not correctness, likeability, or charisma.** None of those is what the panel is being asked.

**Rater guidance — deliberately thin.** Raters get the moment and the question, and nothing else (I1). No band, no score, no acoustic hint, no worked examples of "what confident sounds like." Worked examples would anchor the panel to whoever wrote them, and the panel is supposed to *constitute* the truth, not ratify an author's.

- **`yes`** — it sounds assured
- **`no`** — it sounds unsure or tentative
- **`neutral`** — it sounds middling; neither reads
- **`unrateable`** — you cannot judge it, usually because of the audio. **Not** a synonym for `neutral`: `neutral` is a judgment about the moment, `unrateable` is a judgment about your ability to make one

### Adding an entry

A new entry requires, in order: the construct written out; what it is explicitly *not*, naming the adjacent constructs it will be confused with; the single-barrelled question; the answer semantics; the engine; and an external anchor if one exists. Then the lane, then the capacity.

**Adding a `NOTICE` entry is a scope decision, not a detector** (Appendix C.8).

---

## Amendments to the appendices

The decisions in §0 amend the companion documents. Where they conflict, **this document wins.**

| Appendix | Section | Amendment |
|---|---|---|
| **A** | A.9 | X2, X3, X4, X6 route to ALBUM — all four are **deferred**, since v1.0's Album is confidence-only |
| **A** | A.10 | Tier 1 has a dependency defect — see §15.2 |
| **B** | B.2 | Add the **FRAGILE** column (D11/D15). Its parameters differ from GRADUATE: it is *not* faded; it receives more predict-then-reveal, replay and self-explanation |
| **B** | B.2 | Explanation cohesion for GRADUATE is a **tunable defaulting to no fade** (D17), not a hard-coded drop |
| **B** | B.8 | Graduation is anchored to **deterministic change detection**, never the state machine's own counter (D16) |
| **C** | C.1, C.4, C.7 | **Severity is dropped** from the presentation signature (D9). Presentation = `f(intervention_type, state)` |
| **C** | C.2 | Lexical overlap / verbatim slide text routes to **`CUT` only** (D10). It appeared under both `REWRITE` and `CUT`, violating C2 |
| **C** | C.4 | Add an **`ALBUM` surface** to the registry. `GAME_MODAL` is the labelling surface; the album is a separate review surface |
| **C** | C.4 | No `pending` presentation — unadjudicated comments are **withheld** (D12) |
| **C** | C.6 | **Four bands, 32 templates** (D11), not three |
| **C** | C.8 | **Carve-out:** the one-file rigidity test holds for FEEDBACK findings only. Adding a `NOTICE` finding requires an operational definition, a panel question, a label lane and panel capacity — it is a scope decision, not a one-file change |
