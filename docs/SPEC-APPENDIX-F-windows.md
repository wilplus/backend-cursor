# Appendix F — Measurement Windows

**Last updated:** 2026-08-06.

**Answers the "4 filler words in *what*?" problem.** Companion to SPEC.md v3 and Appendix D.

---

## F.0 · Yes, science can define the window — and it changes the architecture

A rate without a denominator is uncodeable, and a threshold of 0.15 that fires instantly on a sentence and never on a five-minute recording is not a threshold, it is a bug waiting for a corpus.

Speech has **genuine natural units**, established independently of any product need. The better news — and the part that changes the design — is that the strongest empirical result in this area says **do not lengthen the window at all.**

> **Quatieri et al. (Interspeech 2015), cognitive load, 13 subjects, 324 trials:** single-sentence AUC **0.61**. Aggregating per-trial classifier scores from the same subject: median AUC **0.83 at 10 trials**, **0.91 at 20**, and AUC > 0.9 for every subject by 35 trials.
>
> Reliability came from **summing many short decisions**, not from computing statistics over one long window.

That is the architectural finding. Measure on the natural short unit, decide repeatedly, aggregate the decisions. It is also why the earlier "load needs minutes of speech" framing was slightly wrong: it needs *many samples*, which takes minutes — a different thing with a different implementation.

---

## F.1 · Five window classes, each with a basis

```python
class Window(Enum):
    FRAME        = "frame"         # 20–60 ms   signal processing
    UNIT         = "unit"          # ~1.6 s     intonation unit
    CYCLE        = "cycle"         # ~18 s      planning cycle
    PROPORTIONAL = "proportional"  # % of total relative segmentation
    SESSION      = "session"       # whole recording
```

### FRAME — 20–60 ms

openSMILE/ComParE convention: **25 ms frame / 10 ms step** for energy, MFCC, spectral; **60 ms frame** for pitch. Inherited from ASR practice.

**Honest status: convention, never validated for paralinguistics.** No paper systematically compares frame lengths for ComParE LLDs and reports an optimum. It is a defensible default, not evidence of one. Do not change it, and do not cite it as principled.

### UNIT — ~1.6 s · the intonation unit

**This is the best-established natural unit in speech, and it is new.**

Inbar, Grossman & Landau (2025), *PNAS* 122 — **650+ recordings, 48 languages, 27 families**, automatic IU detection on spontaneous speech: a spectral peak at **~0.6 Hz**, i.e. intonation units recur roughly every **1.6 s**, with little variation by sex or age. Chafe's much older estimate converges: mean **4.84 words** per substantive IU, realised over 1–2 s.

Two independent confirmations that this is the right atomic unit:

- **Perceptual**: Pöppel's temporal integration window ≈ **3 s**; echoic memory **2–4 s** (Darwin, Turnbull & Crowder 1972). The IU sits inside both.
- **Empirical**: Diemerling et al. (2024) — models reach human-comparable emotion accuracy from **1.5 s clips**, matching the human perceptual minimum.

**Every point event and every per-decision detector operates on the IU.** Not on a fixed 1-second window, not on a sentence.

### CYCLE — ~18 s (range 11–39 s) · the planning cycle

Henderson, Goldman-Eisler & Skarbek (1966), *Language and Speech* 9(4). Speech alternates between a **hesitant phase** (long pauses, short bursts — active planning) and a **fluent phase** (short pauses, long runs). A cycle boundary is where the pause-length and utterance-length trends reverse slope.

**This is the binding constraint on every pause- and disfluency-based rate.** A window shorter than one cycle catches either a planning phase or an execution phase, so the measured rate oscillates violently with window placement rather than with speaker behaviour. Filler rate over 5 seconds is noise. Over 30 seconds it is a measurement.

**Minimum window for any pause/disfluency rate: 30 s** (covers the mean cycle plus margin). Preferred: 40 s.

Caveat: this rests on small, older, English-only corpora. Treat ~18 s as an order-of-magnitude timescale, not a constant.

### PROPORTIONAL — relative segmentation, not absolute seconds

**Schuller et al. (Interspeech 2006), EMO-DB — the cleanest windowing comparison available:**

| Segmentation | Accuracy |
|---|---|
| **Relative thirds (global + 3 relative segments)** | **96.5%** |
| Whole utterance | 87.5% |
| Middle third alone | 81.9% |
| **Absolute fixed 500 ms windows** | **67.2%** |

**Duration-normalised segmentation beat both fixed-absolute windows and whole-utterance analysis.** Fixed short windows lose the most.

This is the basis for every trajectory measure — arc shape, peak position, ending strength. Divide the talk into **deciles of total duration**, never into fixed 30-second blocks. A 4-minute talk and a 20-minute talk have the same ten segments.

### SESSION — the whole recording

Where proportions, lexical measures and talk-level structure live — subject to the minimum-length gates in F.2.

---

## F.2 · Minimum-length gates — "is there enough data to compute this at all?"

A window is only half the answer. The other half is refusing to compute when the sample is too small.

| Measure | Minimum | Status | Source |
|---|---|---|---|
| **MTLD** (lexical diversity) | **100 tokens** | **Empirical.** Sensitivity is non-trivial at 50–100 tokens (ηp² = 0.10), negligible above 100 | Yang, *Vocabulary Learning and Instruction* 1.1; McCarthy & Jarvis state "as short as 100 tokens" |
| **HD-D / vocd-D** | **> 42 tokens** structurally | Structural — HD-D's fixed sub-sample is 42 | McCarthy & Jarvis 2007 |
| **MATTR** window | 50 is **clinical convention**; Covington & McFall themselves recommend **500** for general use, and give MATTR ∝ W^−0.2 | **Inherited, not their finding** | Covington & McFall 2010; the 50 traces to aphasia research where samples are short |
| **Low-base-rate lexical category** (1% base rate) | **~1,000 words** for SE ≈ 0.3%; at 100 words SE ≈ 1% — *100% relative error* | Binomial arithmetic, not a citation | SE = √(p(1−p)/n) |
| **Full lexical reliability** | **10 min / ~91 C-units** → r ≥ .93. At 3 min r ≤ .83; at 1 min **r ≤ .54** | **Empirical, strongest duration-vs-reliability curve found** | Guo & Eisenberg, *LSHSS* 2015 |
| **Readability formulas** | ~100 words | **Validation-era convention** from Dale-Chall, not a modern stability study | DuBay 2004 |
| **Referential cohesion** | ≥ 2 sentences structurally | No published stability minimum exists | — |
| **Coh-Metrix generally** | **No published minimum at all** | **Genuine gap.** Any figure you use is invented | Graesser et al. 2004; the 2014 book |
| **LTAS / spectral emphasis** | ~30–60 s connected speech, commonly cited | **Inherited convention**, the underlying duration sweep could not be verified | Löfqvist lineage |
| **LIWC categories** | **No manual states one.** The 25-word figure in LIWC2015 is a data-cleaning cutoff, not a reliability recommendation | Field acknowledges the problem without a fix (Tausczik & Pennebaker report α = .14 for function-word categories) | — |

**The 1%-base-rate row is the one that bites hardest in practice.** Several dimensions — metaphor density, hedge markers, macro-signposts — are low-frequency categories. At a typical 130 wpm, 1,000 words is **~7.7 minutes of speech**. Below that, a "hedge rate" is mostly sampling noise with a decimal point.

**AMENDMENT F-1.** Every rate-based lexical dimension carries `min_tokens`. Below it, the detector returns `INSUFFICIENT_DATA` — not a value, not a zero, and never a fired finding. `INSUFFICIENT_DATA` must be a first-class state in the score object, because on a two-minute clip most lexical dimensions will legitimately be in it.

---

## F.3 · The denominator problem

A window is not enough — the **denominator** must also be declared, and the two common choices disagree systematically.

```
per_minute      →  penalises fast speakers   (more words, same time)
per_1000_words  →  penalises slow speakers   (same words, more time)
```

For a speaker at 100 wpm versus one at 180 wpm, the same behaviour yields rates differing by 80% depending which you pick. Both are defensible; **mixing them across dimensions is not.**

**Rule:**

- **Lexical dimensions** (anything counting words or word categories) → **per 1,000 words**. The construct is about word choice, so words are the natural denominator.
- **Temporal dimensions** (pauses, fillers, disfluency, emphatic stress) → **per minute**. The construct is about time, so time is the denominator.
- **Never both for one dimension**, and never a mix inside a composite.

Note this puts filler rate on a per-minute basis, which matters: Clark & Fox Tree's register comparison is per-minute (lectures 3.23/min vs conversation 5.18/min), while Conrad's credibility threshold is per-100-words (1.28). **Those two are not directly comparable and Appendix D quotes both.** Convert Conrad's to per-minute at your corpus's median speech rate, and stamp the conversion.

---

## F.4 · Per-dimension window assignment

| Dimension | Window | Denominator | Minimum | Notes |
|---|---|---|---|---|
| Vocal confidence (CONF) | **UNIT**, aggregated | — | 10+ units before a talk-level verdict | Quatieri: sum per-unit decisions |
| Pitch variability (E1) | CYCLE | — | ~~30 s~~ → see F.4.1 | Needs multiple IPs to estimate **range** |
| Loudness dynamics (E2) | CYCLE | — | ~~30 s~~ → see F.4.1 | — |
| Vocal effort / spectral (E3) | SESSION | — | **30–60 s** | LTAS needs a minimum sample |
| Pause architecture (E4) | **CYCLE** | per minute | **30 s, prefer 40 s** | Below one planning cycle this is noise |
| Speech rate (E5) | CYCLE, and PROPORTIONAL for variation | wpm | 30 s | — |
| Filler density + position (E6) | **CYCLE** | per minute | **30 s** | Same cycle constraint |
| Terminal contour (E7) | UNIT | proportion of assertions | 10 assertions | It's a proportion, not a rate |
| Emphasis alignment (V1–V5) | UNIT for residuals; SESSION for `r_align` | — | 20 units | `r_align` is TALK scope per §4 |
| Arc / peak / ending (V6–V10) | **PROPORTIONAL** (deciles) | — | whole talk | Never fixed seconds |
| Rhetorical devices (V11–V13) | UNIT (event) | count per 1,000 w | — | Events, not rates — count them |
| Slide alignment (V14–V17) | slide display span | — | — | Window = the slide's own duration |
| Given–new debt (V18) | CYCLE | seconds of debt per minute | 30 s | — |
| Topic seams (V20) | segment boundaries | — | ≥ 3 segments | Boundary-anchored, not windowed |
| Refutation (V22) | SESSION (event) | binary | — | An event, never a rate |
| Concreteness (D1) | SESSION | per content word | **100 tokens** | — |
| Abstraction (D2) | SESSION | per predicate | 100 tokens | — |
| Lexical diversity (D6) | SESSION | MTLD | **100 tokens** | Use MTLD; it is length-independent by design |
| Pronoun profile (D7) | SESSION | **per 1,000 words** | **1,000 words** | Low base rate — see F.2 |
| Hedge / booster (D8) | SESSION | per 1,000 words | **1,000 words** | Low base rate |
| Metaphor density (D9) | SESSION | per 1,000 words | **1,000 words** | Low base rate; the Mio benchmark is per-word |
| Conversational style (D10) | SESSION | per 1,000 words | 500 words | — |
| Affective density (C1) | PROPORTIONAL for the curve; SESSION for the mean | per 1,000 words | 500 words | — |

---

## F.4.1 · The minimum belongs to a QUANTITY, not to a row's name *(added 2026-08-06)*

**The table above contradicted F.2, and the code inherited the contradiction.** F.2 states the minimum as *"minimum window for any pause/disfluency **rate**: 30 s"* — the justification is Henderson's planning cycle, and it is an argument about **rates**: a window shorter than one cycle catches either a planning phase or an execution phase, so the rate oscillates with window placement instead of with the speaker. The F.4 table then printed "30 s" against **E1 and E2**, which are not rates. F.5 already conceded the weakness of that row — *"the CYCLE assignment for E1/E2 is inference from the planning-cycle result, not a direct finding"* — but the 30 s figure was copied across anyway.

`services/dimension_registry.py` reproduced it faithfully, which is how all six live dimensions came to carry a 30 s gate. A snippet is **6.55 s** (median, measured — see F-9). Every level measure was therefore written `insufficient_data` on every snippet, for an argument about a different quantity.

**The gate now follows the quantity:**

| Live dimension | Gate | Because |
|---|---|---|
| `wpm` (E5) · `fillers` (E6) · `pause_ms` (E4) | **30 s** | Rate or pause behaviour — the cycle argument applies |
| `dynamic_db` (E2) · `pitch_center` (E1) · `energy` (unfiled) | **none** | A **level**. A mean is stable well inside one cycle; the cycle argument does not reach it |

### The reason the wrong gate looked right

Three live measures **are not the quantity their cited row specifies.** A name match was passing as a spec match:

| We compute | The row says | Consequence |
|---|---|---|
| `pitch_center` — mean f0, a **level** | E1 is pitch **variability** (range/SD) | "Needs multiple IPs to estimate a range" is an argument about estimating a *range*. It does not transfer to a mean. |
| `energy` — snippet-mean **level** at CYCLE | **No row at all.** It was filed under E2, which `dynamic_db` already holds | Two dimensions cannot be one row. Appendix D has no E2 benchmark either — E2 exists only in F.4's window table. It is Jiang & Pell's energy-contour *cue* reduced to a mean, with nothing to inherit from anywhere. |
| `pause_ms` — mean pause **length** (ms) | E4 is pause **rate** (per minute) | Different quantity. The 30 s gate is kept anyway — the cycle argument covers pause behaviour either way. |

The registry now carries a `spec_mismatch` field for exactly this, and `validate()` refuses a starred appendix id with an empty mismatch, or an inherited minimum with nothing justifying the transfer. **A row's minimum may not be inherited by a measure that is not that row's measure.**

### Denominator vs unit

Same defect, one layer down. `denominator` was carrying two different things: the unit a number is *expressed in*, and the divisor the roll-up *applies*. `wpm` declared `denominator="wpm"` and aggregated as a mean — the field said "this is a rate, divide by something" and the code divided by nothing. Split: **`unit`** is descriptive; **`denominator`** is what `rollup()` actually applies, and is non-null **iff** the aggregation is a rate form. Only `fillers` (÷ minutes) and the lexical dimensions (÷ words) have one.

### What is still not settled

`terminal_contour` (E7) gates on **10 assertions** — a count the registry can express in neither seconds nor tokens, so `meets_minimum()` cannot gate it and the extractor must. Flagged in the registry note rather than converted, because converting assertions to seconds assumes a speech rate, which is F.3's error.

---

## F.5 · What the science does *not* settle

State these plainly rather than papering over them:

- **The prosodic integration window** — over what span listeners integrate pitch and loudness into an impression — has **no established figure.** Adjacent auditory work suggests hundreds of ms to ~1 s; nothing prosody-specific is validated.
- **f0 statistic stability vs sample duration** could not be retrieved (Horii 1975 and the ASHA sample-duration paper are both paywalled). The CYCLE assignment for E1/E2 is inference from the planning-cycle result, not a direct finding.
- **Coh-Metrix minimum length** — no published figure exists.
- **The "10–15 minute attention span"** is folklore. Wilson & Korn (2007) reviewed the underlying studies and found they "provide little support" for it. Bunce et al. (2010, clicker self-report, n=186 across 3 courses) instead found a first lapse at **~30 s**, a second at **~4.5 min**, then lapses recurring every **3–4 min** and shortening toward the end. **Do not build a 10-minute segmentation rule.** If anything justifies segmentation cadence, it is the 3–4 minute figure — and it is self-report.
- **Reagan's sentiment window is 10,000 words**, book-scale. It does not transfer to a talk. Any short-text sentiment window is an ad hoc adaptation and must be labelled one.

---

## F.6 · Schema

Every dimension declares its window contract, and it is not optional:

```python
@dataclass(frozen=True)
class WindowSpec:
    window: Window                    # FRAME | UNIT | CYCLE | PROPORTIONAL | SESSION
    denominator: Literal["per_minute", "per_1000_words", "proportion", "count", "none"]
    min_tokens: int | None
    min_seconds: float | None
    min_units: int | None             # e.g. 10 IUs before aggregating a verdict
    aggregation: Literal["mean", "sum_of_decisions", "max", "curve"]
    basis: Literal["empirical", "convention", "invented"]
    source: str | None
```

**`basis` is the field that keeps this honest.** Roughly half the numbers above are `convention` or `invented` — MATTR's 50-word window, openSMILE's frame lengths, the LTAS minimum, every Coh-Metrix threshold. A reader must be able to tell those from the IU's 1.6 s (48 languages) and MTLD's 100 tokens (measured) without going back to the literature.

`aggregation = "sum_of_decisions"` is the Quatieri pattern and should be the default for any state detector: decide per UNIT, sum the scores, threshold the sum. Not: average the features over a long window, then decide once.

---

## F.7 · Summary — the four numbers worth remembering

| | |
|---|---|
| **1.6 s** | The intonation unit. 48 languages, 27 families. The atomic unit of both production and perception. Point events live here. |
| **~18 s** | The planning cycle (11–39 s) — NOT the snippet, which is 6.55 s (F-9). **No pause or disfluency rate is meaningful below ~30 s** of window. |
| **~1,000 words** | ≈ 7.7 min of speech. What a 1%-base-rate lexical category needs before its estimate stops being noise. |
| **10 → 20** | Quatieri's aggregation curve: AUC 0.61 → 0.83 → 0.91. **Aggregate short decisions; do not lengthen the window.** |

---

## F.8 · Consequences for this codebase (added on review)

**F-2 · The piece and the window are orthogonal — do not unify them.** The ≤200-char piece is the **F1 segmentation unit**: slide-aligned, load-bearing for per-slide transcription and ranking. Measurement windows are a separate axis from segmentation; both are needed and neither replaces the other.

> ~~At ~40 words / ~18 s it happens to sit almost exactly at one planning CYCLE. That makes it well-sized for CYCLE-scoped measures and roughly 10× too long for UNIT-scoped ones.~~
> **RETRACTED 2026-08-06 — measured, and false.** The median snippet is **6.55 s** (p10 3.52, p90 17.42; `duration_ms` over `charisma_snippets`). That is **0.36 of a planning cycle**, and even the 90th percentile is still under one. The piece is **not** well-sized for CYCLE-scoped measures — it is roughly a third of one, which is precisely the regime F.2 says a rate must not be computed in. It remains ~4× too long for UNIT-scoped ones, not 10×.

**F-3 · CONF changes implementation.** Currently the composite is computed once per piece. Under F.4 it decides **per intonation unit and aggregates ~10 decisions** (`sum_of_decisions`). Quatieri's curve says that is worth AUC 0.61 → 0.83 — the single largest reliability gain available anywhere in this design, and it costs no new data.

**F-4 · Measure at UNIT, play at PIECE.** The album's playback span stays the piece — you cannot play 1.6 s and have it mean anything. The measurement window shrinking does not shrink the playback window.

**F-5 · `INSUFFICIENT_DATA` is a first-class score state**, distinct from both a value and a null. The manager must not read it as "nothing to say here" — it is a coverage gap, and a dimension sitting in it repeatedly is a signal about the corpus, not about the speaker.

**F-6 · D7 cannot fire on a practice take.** At 1,000 words / ~7.7 min, the pronoun profile — including D7a, the one T2 absolute with a real published threshold — is `INSUFFICIENT_DATA` on any normal-length take. Of the four day-one absolutes, **B6, E5a and E5b survive; D7a does not.**

**F-7 · Appendix D's E6a threshold needs converting and stamping.** D quotes Conrad per-100-words and Clark & Fox Tree per-minute. Under F.3, filler is a temporal dimension → per minute. Convert Conrad's 1.28/100w at the corpus median speech rate and stamp the conversion factor, or the two numbers will be silently compared.

**F-8 · A minimum belongs to a quantity, not to a row's name** *(2026-08-06)*. The F.4 table printed 30 s against E1/E2, which are not rates, while F.2 scoped that minimum to *rates* and F.5 already conceded the E1/E2 assignment was inference. The registry inherited it and marked every level `INSUFFICIENT_DATA` on every ~18 s snippet. Corrected in F.4.1. **The general rule: before inheriting a row's window or minimum, check that you are computing that row's quantity.** Three live measures were not — see the F.4.1 table.

**F-9 · MEASURED. The snippet is 6.55 s, not ~18 s** *(2026-08-06, same day)*. The 18 s was 200 chars ÷ an assumed speech rate and had never been checked against `duration_ms`, which was on every snippet the whole time. Real distribution: **p10 3.52 s · median 6.55 s · p90 17.42 s.** Three consequences, in order of severity:

1. **F-2's conclusion is retracted** (above). A snippet is 0.36 of a planning cycle, not one.
2. **Half the live set can never produce a value at snippet grain.** `wpm`, `fillers` and `pause_ms` gate at 30 s; the *90th percentile* snippet is 17.4 s. Every per-snippet row they write is `insufficient_data` — not occasionally, essentially always. `dimension_evaluations` therefore holds **no usable value for three of six live dimensions**, and PSI and the p-chart will report nothing for them forever *while looking perfectly healthy* — the exact failure G.1.1 warns about. `registry.measurable_in_a_snippet()` and a test now state this rather than letting it stay silent.
3. **The fix is a coarser emission grain, not a smaller gate.** The 30 s minimum is right; the grain we ask it at is wrong. Rate measures should be emitted at session (or rolling ~40 s) grain, levels at snippet grain. **Founder decision pending.**

The three *levels* are unaffected: `dynamic_db` is a percentile spread (`p95 − p05` of voiced frame dB), which converges with more samples rather than growing the way an extremum would, so 6.55 s is ample. That objection was checked, not waved away — had it been a true min/max range the no-gate call would have been wrong.

**F-11 · A wrong citation is the one error no test catches** *(2026-08-06)*. The fix above shipped with `energy`'s mismatch claiming *"A6 is energy front-load"*. **A6 is topic discipline** (Appendix D, Mayer coherence d=0.86) and no energy front-load row exists anywhere; the claim was inherited from a "NOT A6" disambiguation that was itself miscited, and it reached this appendix before it was caught. A citation is prose — `validate()` cannot check it against a document. What it *can* check is the structural shadow: **two dimensions claiming the same appendix row**, which is exactly the shape this took (`energy` and `dynamic_db` both on E2). That rule is now in `validate()`. Everything else in a citation is read by a human or not at all.

**F-10 · The chain is cut at the far end** *(2026-08-06)*. The registry answers *window → enough data?* for all six live dimensions and *threshold → intervention* for none: no live dimension has a `fire_at`, so `dimension_evaluations.fired` is NULL on every row and nothing is chartable. That is the outstanding half of D31, not a wiring defect. `validate()` now rejects a threshold that fires into nothing and an intervention nothing can trigger, so the two must land together.
