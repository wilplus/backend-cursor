# Appendix A — Verbal Computations for Misalignment and Mis-Emphasis

**Last updated:** 2026-08-05.

**Companion to SPEC.md v3.** Everything here inherits §3.1 (detectors are candidate generators, not claims), §4 (scope tiers enforced), §10 (invariants), and §11 (delivery constraints).

> **This appendix is a catalogue, not a v1.0 build list.** SPEC.md §1.2 ships **five** Feedback findings and one Album state. Everything else here is deferred and sequenced by §15. Two amendments apply, marked inline: the ALBUM-routed cross-modal items in A.9 are all deferred (v1.0's Album is confidence-only), and A.10's Tier 1 has a dependency defect. Where this document and SPEC.md conflict, **SPEC.md wins.**

---

## A.0 · The governing idea

**Mis-emphasis is not a property of either channel. It is a divergence between them.**

The verbal channel says *this is the important part* — through information density, novelty, rhetorical position, thesis proximity. The vocal channel says *this is where I got loud* — through pitch accent, intensity, lengthening, boundary strength.

A good speaker's two curves track each other. A bad one's don't, and **the shape of the mismatch names the fault**:

| Divergence | What it is | Costs |
|---|---|---|
| High vocal, low verbal | Emphasis on a function word, filler, or given information | Sounds theatrical, meaningless |
| High verbal, low vocal | The key point delivered flat | Comprehension — and nobody in the room notices |
| Both flat | Monotone | Attention |
| Both spiky but uncorrelated | Sing-song, learned cadence detached from content | Credibility |

Almost every computation below is a variation on: **build two curves, compare them, name the residual.**

The cross-modal terms in §A.8 are the ones that find things neither channel reveals alone. Those are the "hidden patterns."

---

## A.1 · Emphasis alignment — the core family

The single highest-value computation set. Everything else is either an input to it or a special case.

### V1 · Verbal salience curve `S_verb(t)`

**Detects:** where emphasis *should* land.
**Scope:** SNIPPET (windowed) → aggregates to TALK.
**Engine:** FEEDBACK.
**Grade:** B (components are A-graded; the composite is ours).

Per token, normalised to [0,1], then smoothed over a ~1.5 s window:

```
S_verb(t) = w1·surprisal(t)
          + w2·is_new(t)
          + w3·rhetorical_position(t)
          + w4·thesis_similarity(t)
          + w5·concreteness(t)
```

| Component | Computation | Source |
|---|---|---|
| `surprisal` | −log P(token \| context) from a small LM. High = informative. | Hale; Levy — expectation-based processing |
| `is_new` | Given–new status: does this referent have an antecedent in the prior N sentences? | Haviland & Clark |
| `rhetorical_position` | Boost for: item 3 of a three-part list, second element of a contrast, the punchline after a headline, the resolution of an open loop | Heritage & Greatbatch — these are the applause points |
| `thesis_similarity` | Cosine similarity of the sentence embedding to the stated purpose from the context brief | — |
| `concreteness` | Brysbaert norms, content words | Paivio dual coding |

Start `w = [0.3, 0.25, 0.25, 0.1, 0.1]`, hand-set and version-stamped, re-fit against panel data later. **Version-stamp it like `voice_confidence.py` does** — the weights are provisional and a later re-fit must key on the version.

### V2 · Prosodic emphasis curve `S_voc(t)`

**Detects:** where emphasis *actually* landed.
**Scope:** SNIPPET.
**Grade:** B.

All components speaker-relative (z-scored within-speaker, per §5.1):

```
S_voc(t) = z(f0_peak_prominence)
         + z(intensity_peak)
         + z(syllable_lengthening)
         + z(boundary_strength_pre)   # pause immediately before
         + z(spectral_emphasis)       # LTAS 1–5k / 5–8k ratio
```

Reuse `voice_confidence.py`'s within-speaker z-scoring machinery. Do not introduce a second normalisation path.

### V3 · Emphasis alignment coefficient

**Detects:** whether delivery tracks meaning at all.
**Scope:** TALK.
**Output:** `r ∈ [−1, 1]`, plus a per-window residual series.

```
r_align = pearson(S_verb, S_voc)  over the talk
residual(t) = S_voc(t) − S_verb(t)   (both z-scored first)
```

- `r_align` near 0 → emphasis is uncorrelated with content. This is the finding, not the individual spikes.
- `r_align` high but both curves flat → aligned and inert. **Check variance before reporting alignment as good** — a monotone speaker trivially "aligns."

### V4 · Misplaced emphasis events

**Detects:** stress landing on the wrong word.
**Scope:** SNIPPET. **Engine:** FEEDBACK (checkable — the transcript shows it).

```
flag where residual(t) > +1.5σ  AND  S_verb(t) < 40th percentile
```

Filter to cases where the emphasised token is a function word, a filler, or given information. Those are unambiguous. Emphasis on a content word with moderate salience is style, not error — do not flag it.

### V5 · Orphaned salience

**Detects:** the key point delivered flat.
**Scope:** SNIPPET. **Engine:** FEEDBACK.

```
flag where residual(t) < −1.5σ  AND  S_verb(t) > 80th percentile
```

**This is the highest-value single detector in the appendix.** It is the failure nobody in the room can name — the audience simply doesn't retain the thing that mattered, and the speaker has no idea because they *said* it. V4 is embarrassing; V5 is expensive.

---

## A.2 · Peak placement and arc

Their explicit ask: emphasis peaking in the middle instead of the end.

### V6 · Composite intensity envelope

**Scope:** TALK.

```
E(t) = z(affective_density(t)) + z(S_voc(t))
```
over normalised talk time `t ∈ [0,1]`, smoothed over ~5% of duration. Affective density is emotion-laden word rate — it predicted TED popularity roughly twice as strongly as valence (d = 0.21 vs 0.12).

### V7 · Peak position

```
peak_pos = argmax_t E(t)          # fraction of duration
```

- **Target: late.** `peak_pos > 0.75`.
- **Premature peak:** `peak_pos < 0.15` — the best material spent at minute one, with nothing left. Curiosity opens a talk better than a peak does.

### V8 · Peak-in-middle detection

**The specific fault named.**

```
flag if  0.30 < peak_pos < 0.70
     AND mean(E[0.9:1.0]) < mean(E)
```

Both conditions required. A mid-talk peak is fine if the ending is *also* strong — that's a legitimate two-peak shape. It is only a fault when the middle peak came *at the expense of* the close.

**Grade: C.** Peak-end is meta-analytically robust (r = .581 across 174 effect sizes, duration neglect confirmed) but has **never been tested on a talk** — it comes from colonoscopies and cold-pressor tasks. Flag it, phrase the comment as an observation, and let the panel adjudicate whether it mattered.

### V9 · Ending strength ratio

```
end_ratio = mean(E[0.9:1.0]) / mean(E)
```
Target > 1.2. Converges with recency for a continuous talk judged immediately at its close.

### V10 · Arc reversal presence

```
has_reversal = ∃ t1 < t2 : E(t1) < μ − 0.5σ  AND  E(t2) > μ + 0.5σ
```
A genuine trough followed by a rise. Reversal-containing arcs outperformed monotonic ones (Reagan et al., 1,327 texts) — **descriptive only, download proxy, never tested on talks.** Grade C. A flat-high talk is *worse* than one with a dip; do not report a trough as a defect.

---

## A.3 · Rhetorical device completion

Specific, actionable, and directly evidenced — 68% of collective applause tied to seven formats, contrasts 33.2%, three-part lists 12.6%.

### V11 · Three-part list detection and deflation

**Scope:** SNIPPET. **Engine:** FEEDBACK. **Grade:** A.

Detect via syntactic parallelism + enumeration markers + coordinating conjunction before the third element.

```
deflated = mean(S_voc over item3) < max(mean(S_voc item1), mean(S_voc item2))
```

**The applause lands on the third item** — it is the completion point that cues the audience. A list where items 1 and 2 outrank item 3 prosodically is a device built and then thrown away. This is the "1, 2, 3!" instinct made computable.

### V12 · Contrast pair emphasis

**Grade:** A.

Detect antithesis (negation + parallel structure, "not X but Y", "we could Z — instead we W"). Check the **second** element carries the higher `S_voc`, and that a boundary pause precedes it.

### V13 · Missing completion pause

**Grade:** B.

```
gap = onset(next_speech) − offset(device_completion)
flag if gap < 300 ms
```

Bull's mistimed-applause work: the device needs a pause at the completion point or the audience doesn't get its cue. Speaking straight through your own punchline is the most common way a well-built device fails.

---

## A.4 · Slide–speech divergence

Their "not even mentioning what's on the slide."

### V14 · Semantic alignment per slide window

**Scope:** SNIPPET. **Grade:** A (principle) / C (measurement).

```
align_n = cos(embed(utterances during slide n), embed(slide n content))
```

**Caveat to write into any comment generated from this:** the best published automatic lecture-slide alignment reaches 54.7% against a 45.4% chance baseline. This is a hard, unsolved problem. Set the certainty threshold high and route conservatively.

### V15 · Lexical overlap — inverse target

```
overlap_n = ngram_overlap(speech_n, slide_text_n)
```

**Target: LOW.** Keyword-level on-screen text g = 0.99; near-verbatim g = 0.21. High V14 with low V15 is the goal. High on both is reading the slides — the single most documented wrong thing.

### V16 · Alignment lag

```
lag = argmax_τ crosscorr(align_series, slide_change_series, τ)
```
Non-zero lag means speaking about slide *n* while slide *n−1* is displayed. Temporal contiguity is d = 1.22–1.31 — one of the largest effects in the multimedia literature and completely invisible to the speaker.

### V17 · Orphans

- **Orphan slide:** displayed ≥ X seconds with `align < threshold` throughout — shown but never spoken to.
- **Orphan claim:** a high-salience assertion with no semantically related slide on screen.

---

## A.5 · Information structure

### V18 · Bridging-inference load

**Scope:** SNIPPET. **Grade:** A.

Per sentence, does presupposed material have an explicit antecedent within the prior N sentences? Each violation costs the listener ~130–180 ms (Haviland & Clark: 835 ms direct antecedent vs 1,016 ms bridging; replicated at 137 ms and 65–74 ms).

Report as **cumulative inference debt per minute**, not per sentence — one bridge is fine, six in a row is where the audience quietly falls off.

### V19 · Given-information emphasis

**Cross-modal. Grade:** B.

```
flag where is_given(t) = true AND S_voc(t) > +1.5σ
```
Stressing what the audience already knows. Reads as condescending or padded, and steals emphasis budget from the new material in the same sentence.

---

## A.6 · Structural seams

### V20 · Unsignposted topic shift

**Scope:** TALK. **Engine:** FEEDBACK. **Grade:** A.

Detect topic boundaries via semantic shift over a sliding window (TextTiling-style). Then check each boundary for **all three** of:

1. a macro-marker ("the second point is…", "so what does that mean for…") — *not* a micro-filler ("well", "now", "so")
2. a boundary pause above threshold
3. a prosodic reset (f0 baseline return)

```
unsignposted = boundary with 0 or 1 of the three present
```

Chaudron & Richards: macro-markers facilitated recall of lecture content, micro-markers did not. **A topic change with no signpost and no pause is a place the audience is lost and doesn't know it yet** — and neither does the speaker.

### V21 · Segment duration distribution

Mean and variance of inter-boundary intervals. Very long segments = no segmentation (Mayer d = 0.67). Very short and uniform = choppy. Report the distribution, not a target number — there is no evidence-based optimum.

---

## A.7 · Promises made and kept

### V22 · Unrefuted counterargument

**Grade:** A.

Detect concessive framing ("of course", "admittedly", "some would argue", "it's true that") and check for a rebuttal marker within a window.

```
flag if concession with no rebuttal in the following W sentences
```

Allen (k = 19, N = 5,624): refutational two-sided r = +.076, **non-refutational two-sided r = −.060** — raising an objection and not answering it is worse than never raising it. A detectable, fixable, evidence-backed defect.

### V23 · Unresolved open loop

**Grade:** B.

Track posed questions and explicit forward references ("I'll come back to this", "more on that shortly"). Match against later resolution by semantic similarity.

```
unresolved = loops with no resolution before the close
```

Kang et al.: curiosity predicted recall of the *answers* 1–2 weeks later. An unresolved loop is a promise broken — it spends the attention and never pays it back.

Also compute **loop latency** (open → resolve). Very short = not a gap, just a rhetorical tic.

---

## A.8 · Cross-modal patterns — the hidden ones

Neither channel reveals these alone. This is where the two engines earn their keep.

| ID | Pattern | Computation | Reads as | Grade |
|---|---|---|---|---|
| **X1** | **Confidence–content inversion** | hedge density high where `S_verb` is high | Least certain exactly where the claim matters most. Very common in technical speakers, and the single most credibility-costly thing on this list. | B |
| **X2** | **Emphasis–certainty conflict** | `S_voc` > +1.5σ AND hedge markers within the same span | "This is DEFINITELY… I think… maybe." Mixed signal; reads as performed rather than meant. | B |
| **X3** | **Load at the seams** | within-clause pause rate spikes at V20 boundaries | The speaker doesn't know their own transitions. Within-clause pauses index lexical retrieval failure; boundary pauses index planning. The *type* is the tell. | B |
| **X4** | **Rehearsed-opening collapse** | `var(S_voc)` in first 60 s ≫ `var(S_voc)` in body | Memorised open, unrehearsed body. Predicts where coaching effort should go. | C |
| **X5** | **Slide-reading signature** | V15 high AND `var(S_voc)` low AND pause variance low | Confirms with prosody what lexical overlap only suspects. Three weak signals, one confident finding. | B |
| **X6** | **Recovery signature** | after a disfluency cluster, time for `S_voc` range to return to baseline | Professionals recover within seconds; novices stay flattened for the rest of the segment. Within-speaker contrast — the same design that made the interpreter finding legible. | B |
| **X7** | **Jargon without slowdown** | jargon term (V-A3 density) introduced with no rate reduction, no pause, no gloss | The speaker doesn't know it's jargon. A direct, observable audience-modelling failure — and jargon impaired processing fluency at η² = .11 *even with definitions supplied*. | B |
| **X8** | **Question asked as statement** | rhetorical question with falling terminal contour and no following pause | The audience never registers a question was asked, so the curiosity gap never opens. The device is spent for nothing. | B |

**X1, X5 and X7 are the ones I'd build first.** Each fuses signals that are individually too weak to act on and jointly diagnostic — which is the whole argument for a multi-task recognizer over N independent detectors.

---

## A.9 · Routing

Per SPEC.md §2, engine assignment follows the *kind of claim*, not the modality:

| Family | Engine | Why |
|---|---|---|
| V1–V5 emphasis alignment | **FEEDBACK** | The transcript shows it. A coach can point at the word. Checkable. |
| V6–V10 arc and peak | **FEEDBACK** | Checkable against the envelope — but grade C, phrase as observation. |
| V11–V13 rhetorical devices | **FEEDBACK** | Definitionally checkable. Highest-confidence family here. |
| V14–V17 slide divergence | **FEEDBACK** | Checkable against the deck. |
| V18–V23 structure and promises | **FEEDBACK** | All checkable against the transcript. |
| X1–X8 cross-modal | **Split** — see below | |

Cross-modal items split by what the claim rests on:

- **FEEDBACK** if the finding survives without a perceptual judgment: X1, X5, X7, X8 (hedge placement, slide reading, jargon handling, contour on a question are all inspectable).
- **ALBUM** if the finding *is* a perceptual event: X2, X3, X4, X6 — these assert something sounded a certain way, which per §3.1 requires witnesses, not acoustics.

> **All four ALBUM-routed items are deferred.** v1.0's Album Engine carries **confidence only** (SPEC.md §1.2). Each of X2, X3, X4, X6 would need its own operational definition, panel question, label lane and panel capacity — the `NOTICE` carve-out in Appendix C.8. Adding one is a scope decision, not a detector.
>
> X2 and X3 additionally depend on the hedge extractor and filler-rate extraction respectively, neither of which exists (SPEC.md §1.3).

**Everything above is a candidate generator.** None of these outputs is a claim until it has passed either a coach edit or a panel rating. Do not surface a raw detector output to a user.

---

## A.10 · Build order

Scored by (evidence grade × diagnostic value ÷ implementation cost):

| Tier | Items | Rationale |
|---|---|---|
| **1** | ~~V11, V12, V13,~~ **V22** | A-graded, cheap, unambiguous. **Corrected — see the dependency defect below.** Only V22 is genuinely dependency-free. |
| **2** | V1, V2, V3, V5 | The alignment core. V5 (orphaned salience) is the payoff. Needs an LM for surprisal and the prosodic curve, both of which you need anyway. |
| **3** | V20, V18, X7, X1 | Structural seams and audience modelling. Higher value than the arc family and better evidenced. |
| **4** | V14–V17, V6–V10, remaining X | Slide alignment is genuinely hard (54.7% vs 45.4% chance) and the arc family is grade C. Neither should gate the release. |

**Do not build V6–V10 before V1–V5.** Arc shape is the weakest-evidenced family in this appendix and the most likely to produce confident nonsense; the alignment core is the strongest and feeds it.

### The Tier 1 dependency defect

Tier 1 as originally written is not buildable first:

- **V11** (deflated list) computes `mean(S_voc over item3) < max(...)` — it needs `S_voc`, which is **V2, in Tier 2**
- **V12** (contrast pair) checks that the second element carries the higher `S_voc` — same dependency
- **V13** (missing completion pause) needs to know where a device *completes*, which requires V11/V12 to have detected one

So three of Tier 1's four items depend on Tier 2 or on each other. **Only V22 (unrefuted counterargument) is genuinely dependency-free** — concessive-marker detection plus a rebuttal-window check, pure text pattern matching over the transcript, A-graded (Allen, k = 19, N = 5,624), and it detects a defect that is measurably *worse than never raising the objection*.

**V22 is therefore the correct first Feedback finding beyond SPEC.md §1.2's five**, and is named as such in SPEC.md §15.2. V11–V13 move to Tier 2, behind V2.

---

## A.11 · Do not compute

| Item | Reason |
|---|---|
| An "overall emphasis score" | Collapses V4 and V5 into one number, and they need opposite remedies — one is *stop stressing that*, the other is *start stressing this*. |
| Absolute emphasis thresholds | Everything is speaker-relative (§5.1). A loud speaker is not an emphatic one. |
| Arc-shape classification into the six named shapes | Reagan's shapes are descriptive over novels with a download proxy. Reporting "your talk is an Icarus" is a category error dressed as an insight. Report reversal presence and peak position; nothing further. |
| Emphasis alignment on a snippet | `r_align` is TALK-scope. Scored on a snippet it is noise with a decimal point. §4 must raise. |
| Any of this during LIVE mode | §11. Mechanical attention under pressure is how choking happens (r = .59–.64). |
