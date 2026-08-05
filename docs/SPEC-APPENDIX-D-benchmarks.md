# Appendix D — Fire-Up Benchmarks and Trigger Functions

**Companion to SPEC.md v3.** Defines when a detector fires. Inherits §4 (scope), §5.1 (speaker-relative normalisation), §8.2 (triage), Appendix A (the computations), Appendix C (routing to intervention types).

> **Amended by Appendix E.** E-6 adds a perceptual floor to every SPEAKER_REL detector; E-7 adds the amplitude-masking guard; E-8 separates the 250 ms segmentation convention from the 600 ms firing threshold; E-12 marks the D.4 baseline minimum as unsourced. See E.7 for the consolidated list.

---

## D.0 · The honest problem: effect sizes are not thresholds

**Most of the research gives an effect size, not a trigger value.**

Mayer's personalisation principle is d = 1.00. That tells you conversational style matters a great deal and in which direction. It does **not** tell you that 2.1 second-person references per 100 words is fine and 1.9 is not. No study reports that, because no study was designed to.

Treating an effect size as a threshold is the most likely way this system ships confident nonsense. So every benchmark below carries a **provenance tier**, and the tier determines how much you're allowed to trust the number:

| Tier | Meaning | Count |
|---|---|---|
| **T1 — measured threshold** | The study reports a value at which behaviour changes | 2 |
| **T2 — measured population values** | The study reports what good and poor performers actually did, so a threshold can be derived | 6 |
| **T3 — direction only** | The study gives an effect size and a direction. The threshold must come from **your** corpus and is provisional until re-fit against panel labels | everything else |

**T3 is not a failure.** It is the correct state before you have data. What's wrong is dressing a T3 up as a T1 by writing a decimal next to it.

---

## D.1 · Four trigger kinds

Every benchmark must declare which.

```python
class TriggerKind(Enum):
    ABSOLUTE       = "absolute"        # vs a research constant
    SPEAKER_REL    = "speaker_rel"     # vs this speaker's own baseline
    CORPUS_REL     = "corpus_rel"      # vs the percentile in your corpus
    CONTRASTIVE    = "contrastive"     # vs another span in the same talk
```

```
ABSOLUTE     fire if  measured  outside  [lo, hi]                # research constant
SPEAKER_REL  fire if  |z(measured, speaker_baseline)| > k
CORPUS_REL   fire if  percentile(measured, corpus) < p           # or > (1−p)
CONTRASTIVE  fire if  measured(span_a) − measured(span_b) crosses a delta
```

**Getting this wrong on a speaker-relative cue mis-triggers systematically on anyone whose voice sits away from the population mean** — which is the entire reason §5.1 exists. The rule that resolves it:

> **If the validated predictor is expressed as a proportion of the speaker's own range, the trigger is SPEAKER_REL. If it is expressed as a population value, it is ABSOLUTE. If neither, it is CORPUS_REL.**

`CONTRASTIVE` is the one people forget. V11 (deflated three-part list) has no absolute target — item 3 just has to beat items 1 and 2 *in the same list*. Nothing about the speaker's baseline or the corpus enters. Same for V16 (slide lag) and the deferred within-speaker load contrast.

---

## D.2 · Never a point — always a band with hysteresis

A single threshold flickers at the boundary. A dimension sitting at 0.499 / 0.501 across attempts fires, clears, fires — and the user gets the same note three sessions running for no change in behaviour.

Every benchmark defines **two** values:

```python
fire_at   # crosses this → finding is generated
clear_at  # must cross back past this → finding stops being generated
```

with `clear_at` strictly inside `fire_at` — a Schmitt trigger. Suggested default gap: **0.4 σ** for `SPEAKER_REL`, **half a decile** for `CORPUS_REL`.

This is also the shape the spec already asks for elsewhere: bandwidth feedback (Lee & Carnahan) means speaking up only when a metric leaves its tolerance band, and a band needs two edges.

---

## D.3 · The benchmark table

Units are **per 1,000 words** for lexical rates unless stated, for comparability.

### T1 — measured thresholds (trust these)

| ID | Dimension | Kind | Benchmark | Fire / clear | Source |
|---|---|---|---|---|---|
| **E6a** | Filler density | ABSOLUTE | Credibility degrades above **12.8 / 1,000 words** (1.28 per 100) | fire > 12.8 · clear < 10.0 | Conrad et al., survey-interviewer field study |
| **E5a** | Speech rate ceiling | ABSOLUTE | Comprehension declines above **~275 wpm** | fire > 275 · clear < 255 | Foulke & Sticht |

**Note on E6a, and it matters:** the natural median in conversation is **17.3 per 1,000 words** (Clark & Fox Tree, London-Lund, 65 speakers, range 1.2–88.5). That is *above* Conrad's credibility threshold. So a naive absolute trigger fires on the majority of ordinary speakers. Two consequences: fire on **presentation** register only (lectures run 3.23/min vs conversation 5.18/min — speakers already self-regulate), and weight E6 by **position** (medial ≫ initial, Kirkland et al.) rather than by count alone. Count-only filler scoring is on the do-not-build list for exactly this reason.

### T2 — derived from measured population values

| ID | Dimension | Kind | Benchmark | Fire / clear | Source |
|---|---|---|---|---|---|
| **D7** | Collective pronoun rate | ABSOLUTE | Election winners **12.7 / 1,000 w** (1 per 79); losers **7.4 / 1,000 w** (1 per 136) | fire < 8.0 · clear > 10.0 | Steffens & Haslam, 43 Australian federal elections, 84 candidates |
| **D9** | Metaphor density | ABSOLUTE | Charismatic presidents **5.9 / 1,000 w** (.0059/word); low-charisma **3.0 / 1,000 w** | fire < 3.5 · clear > 4.5 | Mio et al., 36 inaugurals, r = .37 with rated charisma |
| **E8** | Emphatic stress rate | CORPUS_REL | Jobs ≈ **5.4 stressed content words/min** | reference point only — **do not fire on it** | Niebuhr, **single-subject case study** |
| **E5b** | Speech rate, persuasion band | ABSOLUTE | Fast ≈ 195 wpm, medium ≈ 140, slow ≈ 102–111 wpm | fire < 110 · clear > 125 | Miller et al. — and only marginal (p < .13); Smith & Shaffer show the effect **flips** by message type |
| **B4** | Given–new inference debt | ABSOLUTE | Each bridging violation costs **~130–180 ms** | fire when cumulative debt > **1.5 s/min** · clear < 1.0 s/min | Haviland & Clark: 835 ms direct vs 1,016 ms bridging; replicated at 137 ms and 65–74 ms |
| **E4** | Planning-cycle length | CORPUS_REL | Hesitant/fluent cycles run **11–39 s, mean ≈ 18 s** | fire when within-clause pause share exceeds corpus p75 | Goldman-Eisler; Henderson et al.; Butterworth |

**E8 is in the table to be explicitly disarmed.** A single-subject case study is a reference point, not a benchmark. Anyone who reads "Jobs did 5.4/min" as a target will build a detector that fires on every speaker who isn't Steve Jobs.

**E5b carries a live contradiction:** Miller et al.'s speed effect was marginal, and Smith & Shaffer showed it reverses depending on whether the message is counterattitudinal. Fire only at the extreme slow end (< 110 wpm), where it's a fluency signal rather than a persuasion one.

### T3 — direction only; threshold from your corpus

These have real effect sizes and no trigger value anywhere in the literature. **Bootstrap per D.5.**

| ID | Dimension | Kind | Direction | Effect size (why it matters) |
|---|---|---|---|---|
| **D10** | Conversational style | CORPUS_REL | higher is better | Mayer personalisation **d = 1.00**, 13/15 tests |
| **A2** | Slide lexical overlap | CORPUS_REL | **lower is better** | Keyword text **g = 0.99** vs near-verbatim **g = 0.21** (Adesope & Nesbit, k = 57, N = 3,452) |
| **A1** | Slide semantic alignment | CORPUS_REL | higher is better | Temporal contiguity **d = 1.22–1.31**. **Cap certainty** — best published auto-alignment is 54.7% vs 45.4% chance |
| **A3** | Jargon density | CORPUS_REL + CONTEXT | lower vs audience level | Bullock et al., N = 650, **η² = .11** on processing fluency — *even with definitions supplied* |
| **A6** | Topic discipline | CORPUS_REL | lower drift is better | Mayer coherence **d = 0.86**, 18–23/23 tests |
| **D1** | Concreteness | CORPUS_REL | higher is better | Packard & Berger: **+1 SD → 8.9%** higher satisfaction, ~30% higher 90-day spend. **Express the trigger in SDs of the Brysbaert distribution — that's the unit the effect is reported in.** Suggested fire at −0.5 SD |
| **D2** | Abstraction (LCM) | CORPUS_REL | context-dependent | Wakslak et al., **η² = .13–.21** for power. Trades against D1 — do not fire both |
| **B1** | Rhetorical format density | CORPUS_REL | higher is better | 68% of collective applause tied to seven formats; contrasts 33.2%, lists 12.6%; same content in a device 71% vs 29% |
| **B2** | Macro-signposting at seams | CONTRASTIVE | present at each seam | Chaudron & Richards — macro-markers aid recall, micro-markers don't. Signalling **d = 0.38–0.70** |
| **B6** | Refutational two-sidedness | ABSOLUTE (binary) | raise **and** answer | Allen, k = 19, N = 5,624: refutational **r = +.076**; non-refutational **r = −.060** — worse than one-sided. Fire on any unanswered concession |
| **C1** | Affective density | CORPUS_REL | higher is better | 2,962 TED talks: density **d = 0.21**, ~2× the effect of valence (d = 0.12) |
| **E1** | Pitch variability | SPEAKER_REL | higher is better | f0 SD predicted charisma p < .001; own-range use p < .01 (Rosenberg & Hirschberg). Niebuhr: F0 SD r = 0.64, percentile range r = 0.69 |
| **E3** | Vocal effort / spectral emphasis | SPEAKER_REL | higher is better | Niebuhr: a **25% shift** toward effortful voicing ↔ **70–100%** rise in perceived investment likelihood. n = 12, relaxed p ≤ .10 |

### Grade-C — computed, logged, never surfaced

| ID | Dimension | Why not surfaced |
|---|---|---|
| **C2** Arc reversal | Descriptive only, download proxy, never tested on talks |
| **C3** Peak lateness | Peak-end r = .581 across 174 effect sizes — but **never tested on a talk**, and no better than the simple average of the experience |
| **C4** Ending strength | Derived from C3 |
| **C7** Narrative staging | Boyd et al. establish the structure exists; explicitly do **not** show it predicts quality |
| **D5** Syntactic load | Strong theory (DLT, surprisal), no spoken-delivery RCT |

**Consequence of `effect_size(C) = 0.0` in the triage formula, stated so it isn't an accident:** these run, log, and never reach a user. That is correct for v1.0 and it is also how you accumulate the validation data to promote them later. Do not delete the detectors; do not surface them.

---

## D.4 · Speaker-relative: the confidence cues

CONF is the one dimension where the benchmark is *definitionally* speaker-relative, because the validated predictor is **proportion of the speaker's own range**, not absolute pitch.

```python
CONF_TRIGGER = TriggerKind.SPEAKER_REL
fire_at  = 1.5   # |z| against the speaker's own baseline
clear_at = 1.1   # 0.4σ hysteresis gap
```

Directional targets from Jiang & Pell (4 speakers, 96 statements × 4 confidence levels, 30 listeners) — **all directional, none absolute**:

| Cue | Unconfident | Confident |
|---|---|---|
| Mean f0 | **highest of all four conditions** | elevated vs neutral |
| Speech rate | **slowest** | slower than neutral |
| Amplitude range | — | **largest of any condition** |
| F0 range | trends widest (n.s.) | — |
| Terminal contour | rising on assertions | falling |

**Baseline requirements before SPEAKER_REL can fire at all:**

```
min 3 prior recordings  OR  min 8 minutes of banked speech for this speaker
below that → fall back to the sex-conditional cold-start prior (§5.2)
below both → do not fire; log only
```

Firing a speaker-relative trigger against a baseline of one recording measures that recording, not the speaker.

> ⚠ **E-12: these numbers have no source.** No paper in this literature publishes a minimum duration or utterance count for a stable speaker baseline. Mark `T3-cold`, derive empirically from the point a speaker's running z-score stabilises, and stop presenting it as a requirement with a basis.

---

## D.5 · Bootstrapping a T3 threshold — the procedure

For every `CORPUS_REL` dimension, in order:

**1 · Cold start (0 labels).** Fire at the **bottom decile** of your own corpus for that dimension. Not a guessed constant. The distribution is real even when the target isn't.

```python
fire_at  = corpus_percentile(dimension, 10)
clear_at = corpus_percentile(dimension, 15)   # half-decile hysteresis
```

**2 · Provisional (≥ 40 panel labels).** Fit the threshold to maximise agreement with the coach's "worth mentioning / not worth mentioning" verdict on the 40-clip pass. Re-stamp `benchmark_version`.

**3 · Trusted (≥ 200 labels).** Re-fit against the outcome anchor from §12.2 — human holdout delta or ΔSE — not against coach agreement. Coach agreement measures what coaches notice; the outcome anchor measures what changed.

**Every benchmark carries provenance, like `voice_confidence.py` carries `version` + `sex_source`:**

```python
@dataclass(frozen=True)
class Benchmark:
    dimension_id: str
    kind: TriggerKind
    tier: Literal["T1", "T2", "T3"]
    fire_at: float
    clear_at: float
    source: str | None          # citation for T1/T2; None for T3 cold start
    fit_stage: Literal["cold", "provisional", "trusted"]
    benchmark_version: str
    fitted_at: datetime | None
    n_labels_at_fit: int
```

A T3-cold benchmark and a T1 benchmark must never be indistinguishable at read time. `tier` and `fit_stage` are what stop a corpus decile from being quoted back as a research finding.

### The Stateless Baseline pattern (founder 2026-08-05) — how CORPUS_REL is computed

The evaluation engine must never `JOIN` or live-compare the active user against other users' records.

1. **Offline aggregator.** A batch job reads historical metrics, strips PII and `user_id`s in memory, computes the bottom-decile threshold per `CORPUS_REL` dimension, and exports static floats to a global config or fast-read cache.
2. **Live engine.** Scores the user's absolute rate, reads the static threshold, compares. At no point does one user's row touch another's.

**Four conditions on it:**

- **Versioned, not nightly.** A threshold that moves under a user who didn't change breaks the hysteresis band, breaks Appendix B's *consecutive attempts above threshold*, and produces notes with no cause. Recompute on a slow cadence, stamp `benchmark_version`, and pin a user's progression state to the version it was computed under.
- **Leave-one-user-out** while N is small, or a heavy user partly determines the bar they are judged against.
- **The decile carries an expiry.** Firing at p10 pins the firing rate to exactly 10% *by construction*, forever, regardless of quality — a corpus of excellent speakers still has a bottom 10%, and the system can never say "nothing to fix here." That collides with §11.1's property that `None` is the correct answer for almost every snippet. It is tolerable only because step 2 replaces it with a quality bar. Surface any dimension still at `fit_stage='cold'` past its label threshold, or the scaffold becomes the shipped trigger.
- **Provenance never reaches the comment.** *"You hedge three times in this sentence"* is criterion-referenced and fine. *"Your hedging is in the bottom decile of our users"* is normative and forbidden — Kluger & DeNisi's sign-flipping moderator, §11's *criterion-referenced, never normative*. Same threshold, opposite effect.

---

## D.6 · Composing with triage

The benchmark only decides **whether** a finding exists. It never decides whether it's shown.

```
finding fires         ← Appendix D (this document)
severity computed     ← deviation × effect_size          §8.2
suppressed short-term ← × R(k, Δt)                       §8.2
suppressed long-term  ← × G(state)                       Appendix B
one survivor shown    ← triage                           §11
```

**`deviation` is measured in trigger-kind-native units** — z-scores for SPEAKER_REL, percentile distance for CORPUS_REL, absolute distance normalised by the band width for ABSOLUTE. Mixing raw units across kinds makes `deviation × effect_size` incomparable between dimensions, which silently breaks the triage ordering. This is the most likely quiet bug in the whole chain.

`effect_size` is the grade tier: **A = 1.0, B = 0.6, C = 0.0**.

---

## D.7 · Rules

| # | Rule |
|---|---|
| **1** | Every benchmark declares `kind` and `tier`. No exceptions, no defaults. |
| **2** | A T3 threshold may never be cited to a user or a coach as a research value. |
| **3** | `clear_at` is strictly inside `fire_at`. Single-point thresholds are rejected at load. |
| **4** | SPEAKER_REL will not fire below the baseline minimum (D.4) — itself unsourced, see E-12. |
| **5** | `deviation` is normalised per trigger kind before entering triage. |
| **6** | Grade-C dimensions compute and log; they never surface while `effect_size(C) = 0.0`. |
| **7** | Re-fitting bumps `benchmark_version` and stamps `n_labels_at_fit`. A threshold with no fit provenance is not deployable. |
| **8** | E8 (emphatic stress) is a reference point and must not have a `fire_at` at all. |
| **9** | **(E-6)** Every SPEAKER_REL detector also clears a perceptual floor: `|z| > fire_at` **AND** `raw_delta > floor`. |
| **10** | **(E-7)** Suppress an f0-based finding when a ≥10 dB amplitude drop co-occurs within tens of ms. |
