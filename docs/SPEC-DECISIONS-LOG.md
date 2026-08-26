# Decisions log — settled in review, not yet folded into SPEC.md

**Last updated:** 2026-08-14.

**Purpose:** everything agreed after SPEC.md v3 was committed. This file exists so a long
review session survives itself. Entries here are **binding** and get folded into the numbered
sections on the next spec pass. Where this file and SPEC.md v3 disagree, **this file is newer.**

---

## A · Architecture — the model changed shape

**A1 · One trigger mechanism, N feedback types, one manager.** The Album/Feedback split by
"claim type" is superseded. Every feedback type works identically: measured vocal/verbal cues →
compared against a benchmark → fires when the mismatch crosses. **The Album is a feedback type
with three extra properties**, not a different kind of engine: the fragment is saved for peer
review, the intervention carries playback, and once verified it gains comment + coach video.

**A2 · Three artifacts per feedback, not one.**

| | Artifact | Reversible? | Who corrects |
|---|---|---|---|
| 1 | **MUTATION** — what is done to the text (bold, highlight, colour, cut, replace) | **Irreversible.** Applied in real time; it creates the next version | Nobody, in the moment. The coach improves *future* mutations |
| 2 | **COMMENT** — the short justification | yes | **The coach — this is where DPO sits** |
| 3 | **PROPOSAL** — the concrete suggested text | accept/reject by user | The coach; a rewritten proposal is as much a DPO pair as a rewritten comment |

This is the versioning system. Iteration by iteration the mutations husk negative patterns out
of the text and it converges on what the user meant to say. **Which is why a mutation cannot be
a default or a guess — a wrong one moves the text away from that and the user cannot tell.**

**A3 · The span IS the intervention.** A wrong span costs recall on the part that mattered
(cued material is recalled at the expense of non-cued). Every mutation declares: anchor → extent
→ min/max → preconditions. **If a span rule cannot resolve: do not fire, log it uncovered.**
That gap is the data-collection signal. Never approximate a span.

**A4 · GPT-4o has exactly three jobs.** Verbalizer (score object → comment), proposer (the
suggested text), extractor (cues a lookup can't give — LCM, device detection). It must **never**
decide whether to intervene, which intervention, the span, or score anything.

**A5 · `NOTICE`'s affordance is `RATE_AND_REVEAL`, not `PLAY_SPAN`.** star → modal → blind
question → submit → reveal → if verified, comment + coach video. The rating step *is* the
predict-then-reveal gate, so the corpus and the therapeutic effect come from one interaction.

---

## B · The manager engine — four dials, all set now

| Dial | Value | Why |
|---|---|---|
| **Objective** | maximise measured change, take N → N+1 | acceptance is a **constraint**, never the objective — optimise on being liked and you learn to generate well-received feedback that changes nothing |
| **Dismissal ceiling** | TBD | pauses a type without letting acceptance become the goal |
| **ε_explore** | ~10–20% | surface rank 2–3, log the counterfactual. Rank 1 always winning teaches nothing |
| **γ_control** | ~10–15%, **per-dimension** | a share of (user, dimension) pairs get **nothing**. Users improve by recording more, feedback or not — without this you credit yourself with the practice effect |
| **Intervention randomisation** | 20% | the only route to causal attribution. Confounded data cannot be un-confounded |
| **Lag weighting** | TBD | acceptance arrives in seconds, change a take later; at equal weight the fast signal dominates by volume |

**Dual baseline.** Two distances per cue: `d_self` (vs own baseline) and `d_science` (vs the
research target). **Appendix B's states are the gate** — NOVICE/APPRENTICE fire on `d_self`,
GRADUATE fires on `d_science`, FRAGILE on neither (they can't self-monitor, so a standard they
can't perceive produces a plateau).

**γ_control is also what makes the album experiment interpretable.** Uncontrolled, the first run
measures practice and calls it the album.

---

## C · The album — flow and quorum

**C1 · Uncapped, two levels, both recency-first.** Per project (arc) and a pool across projects;
the 5 most recent shown at the top of each. **Display rule, not retention** — nothing ages out.
Consequence: "cleared quorum" and "is in the album" are the same predicate, so `_W_B` fires once
and does not decay.

**C2 · The flow.**
```
ideal-text overlay → modal → blind question → submit
  → "Registered — waiting for your coach."     ← NO machine read shown
the game lives ONLY in this modal
      ↓ user leaves the ideal text
chat → bubble appears at ≥3 VERIFIED confident moments → links to the album page
      ↓
album page → toggle → any snippet registered by the system and/or verified by the coach but
             MISSING the user's own label can be labelled inline (same instrument, no modal)
```

**C3 · The machine read is never shown.** Earlier design showed it with a pending-coach
disclosure; superseded — display only **"Registered — waiting for the coach."**

**C4 · Quorum.** Machine **proposes** (candidate generator, §3.1 — it is not a peer). Coach,
owner and peers **agree blindly**. ~~The machine's vote is asymmetric: it can help a moment in,
never keep one out.~~ Coach + peer override where the machine rejected → **log those rows
separately, they are the blind-spot corpus.**
**Amended 2026-08-11 (§J):** the machine has **no vote**, asymmetric or otherwise, and the
**owner is not one of the agreeing parties** — a self-report is calibration signal, not a peer
judgment. Quorum is **two humans, neither of them the speaker.**

**C5 · Why blindness matters, and it is not mainly statistical.** "Three people who couldn't see
each other's answers all heard this as strong" is a different object from "our algorithm liked
this." That difference *is* the album's value proposition.

**C6 · A false positive in the album is a fake mastery experience.** Bandura's mechanism requires
actual mastery. Precision is not an accuracy stat here — it is the mechanism.

---

## D · The lanes and the coach's two roles

**D1 · The coach is a PEER for confidence labels** (equal weight, no privileged vote on a
percept) and a **TRUTH SOURCE for comments** (`_W_C` privileged; comment rewrites are the DPO
lane). Two roles, never merged.

**D2 · The blind rule is about independence, not authority.** Any rater whose labels feed the
corpus must stay uncontaminated. If all raters see the machine's answer they drift toward it and
the panel's agreement becomes agreement-with-the-machine.

**D3 · Cold start / bootstrap engine — coach labels external audio.** What it buys:
1. breaks the cold-start circle (no detector → no clip selection → no labels)
2. **the cheap source of recall** — labels on clips the detector did *not* flag
3. the only sample not confounded with the product
4. **speaker diversity — I5's speaker-independent splits are impossible without it.** With 1–2
   users you cannot hold out a speaker you don't have
5. coach-clone at the *recognition* layer, the way comment corrections do it for the writer

**Comments: the coach must see the draft** (that's the mechanism). **Labels: still rate blind.**
The sequential gate means this is not a trade-off — rate blind, commit, then see everything.

**D4 · External-audio peer lane — unblocks the panel without consent work.** Users labelling
*external* voices gives multiple raters per clip, hence inter-rater agreement, with no
cross-user consent gate and no self-recognition bias.

**D5 · Ordering rule (locked).** Own voices first, external second — matches Bandura's ordering
of efficacy sources (mastery before vicarious). Framing to the user: *"you're now defining your
preferred charismatic voice, and it helps us personalise your learning."*

**D6 · Preferred-speaker form: collect the name, defer the audio.** The preference signal is
cheap. YouTube ingestion is a separate decision — the *recording* is copyrighted even though the
voice isn't, pseudonymised ≠ anonymous under GDPR, and studio audio isn't acoustically
comparable to a phone mic.

**D7 · Sex must be manually enterable on the coach page** for external audio, which has no user
profile and would otherwise land as inferred/unknown.

---

## E · Bias — what each mechanism actually catches

| Mechanism | Catches |
|---|---|
| Multi-rater agreement (the game) | **idiosyncratic** bias — one rater deviating from the rest |
| The Jiang & Pell anchor | **shared** bias — everyone agreeing and everyone wrong |

Both are needed; they catch different things.

**E1 · The sex-conditional weights correct the MACHINE, never a human rater.** Panel labels carry
whatever prior the rater walked in with. Since D.5 step 3 re-fits cue weights against those
labels, **the re-fit is capable of dissolving the correction.**

**E2 · The one-way valve (founder spec) — locked.** Directional/monotonicity constraints on
protected feature weights during re-fit; solver may move them favourably or not at all, never
toward the population bias. Graceful fallback retains `W_current` on non-convergence. CI test
generates a deliberately biased mock corpus and asserts the weights sit exactly at the floor.
Two corrections: use `L-BFGS-B` coefficient bounds (GBM `monotone_constraints` constrain
feature→output, a different guarantee), and **HNR is dropped from the protected list** — it is
not computed, and a constraint on a missing feature protects nothing.

**E3 · Track the yes-rate by speaker sex across raters** as a standing metric, extending §5.2's
per-group precision/recall to the labels themselves. It is the only thing that would notice the
bias before a re-fit bakes it in.

---

## F · Weights — what is science and what is ours

**Directions come from the literature. Weights are ours.** `voice_confidence.py` says so in its
own docstring: *"direction from the paper; weights are OURS and provisional."*

- **From Jiang & Pell:** which 7 cues, each cue's direction, Table 3 separation magnitudes, the
  sex reversal on cue 1.
- **Ours:** the 7 weights, the tanh dead zone, the ±0.35 bands, the decision to build a composite.

No paper publishes a weighted confidence composite — J&P measured cues independently and never
built a predictor.

**Same applies to the two VERBAL composites, and only those.** `SIS` (sentence weakness) and
`S_verb` (V1, `w = [0.3, 0.25, 0.25, 0.1, 0.1]`) are hand-weighted and version-stamped. The
single-cue verbal dimensions — D10, A2, D7, D1, A6 — are individual measurements with **no
weights to worry about.**

**SIS has a defect:** it was specified on low concreteness + high abstraction, which Appendix D
says are the same axis (*"trades against D1 — do not fire both"*). Rebuild on concreteness +
hedging + dependency distance.

---

## G · Build order (revised — the curves changed it)

1. **Four day-one absolutes** — D7a (collective pronoun, T2), B6 (refutation, cheap + A-graded),
   E5a/E5b (speech rate, `wpm` already computed). These fire immediately with no corpus.
2. **`S_verb` + `S_voc` + V5.** The curves are computed from **one recording** — no corpus, no
   other users, no cold start. V5 (orphaned salience — the key point delivered flat) is the
   highest-value detector in Appendix A, and the curves unlock four cross-modal patterns
   including X5, the "what to say *and* how to say it" case.
3. **The corpus-relative set** — D10, A2, D7b, D1, A6. **Extractors live from day one** so the
   pile accumulates; triggers wake as each corpus clears its floor. Building them *is* how the
   cold start ends.

**Cross-modal is deferred by dependency, not priority.** Seven of X1–X8 need `S_voc` or an
unbuilt verbal extractor; X8 is closest (needs question detection + `f0_mid_end_delta`, which
exists). Half of them route to ALBUM, which means an operational definition, panel question,
label lane and panel capacity apiece.

**Segmentation: skip.** Latent profiles need users in the hundreds. Log the inputs now
(per-user dimension aggregates, calibration, intervention response) so it isn't zero later.

---

## H · Also settled

- **Breakthroughs: removed entirely.** They fit neither engine.
- **Potentiometer (`acoustic_read`): removed entirely** — the blind checks replaced its purpose.
- **`moment_direction`: survives, re-pointed and renamed** — coach label becomes the confidence
  ternary, the fallback becomes `voice_confidence`'s band. It is now **the Album trigger**, not
  a star helper.
- **`BreakthroughsOverlay` + `/explore/arc/<id>/breakthroughs`: deleted outright.**
- **Coach video: survives.**
- **`EMPHASIZE` goes dark** until a cue exists whose remedy is "land this harder."
- **Bandwidth feedback** moves to speaker-relative deviation on `voice_confidence`.
- **Legacy direction labels: nuke them.** No business or predictive value for the retired
  construct. The raw audio is the IP, not the labels.
- **There are no users yet**, so live-loop risk is theoretical for this wave.

---

## I · Open

1. **What is "the window"?** Every rate says *per 1,000 words* / *in the window* and nothing
   defines it. D7a needs ≥200 words; a piece is ~35. **The biggest hole in the table.**
2. **Whose corpus** for CORPUS_REL — pooled across users, or the user's own history? Pooled
   ranks users against each other, which AC-9 fences. Per-user makes it SPEAKER_REL renamed.
3. Can two findings mark the same span?
4. Do mutations survive a version edit?
5. What is a "take" for max-marks-per-take?
6. ~~**`PANEL_LANES` bug** — `services/state_ratings.py` includes `game_owner`; §9.1 excludes the
   owner from agreement. Should be `("coach", "game_peer")`.~~ **CLOSED** — `PANEL_LANES` is
   `("coach", "game_peer")`, and §J·2 makes the exclusion a stamped column rather than a lane
   inference, so a self-report on the *coach* lane is caught too.

---

## J · The label ledger — quorum, self-report and routing (founder 2026-08-11)

Four rules for the voice-game labelling pipeline. The one thing they protect: the ground-truth
corpus must not contain **circular logic** — no number in it may trace back to a prediction made
by the thing it will be used to evaluate. Implemented in `services/label_quorum.py`,
`migrations/add_label_quorum_ledger.sql` (columns + the `snippet_label_quorum` view).

**J1 · The machine is a ROUTER, not a rater.** It selects **which** clip gets rated. Its
prediction **does not count as a vote** — not as a full vote, not as the asymmetric half-vote
§9.1 gave it. **Quorum is strictly 2 humans.** The proposal is stored in its own column
(`confidence_labels.machine_value`) **beside** the human label, never blended into it, stamped
server-side (a client-supplied proposal would mean the rater's screen carried it — I1).

*Why storage and not just exclusion:* "which prediction did this human disagree with" is
unanswerable after the fact without it, and that disagreement is the whole of J3's active
learning. Excluding the machine from the vote and keeping its proposal are the same decision.

**J2 · The owner is not a peer.** Rating your own clip is a **self-report**: flagged
(`self_report`), excluded from the 2-peer quorum ground truth, kept for **rater calibration
only**. The speaker knows what they intended — the one judgment that is not independent of the
thing judged. Rating **another user's clip or a YouTube clip** makes them an ordinary valid 2nd
peer and the answer counts in full. The voice game **serves the user's own recordings first**
*(2026-08-14: extended into the full three-class queue order — own voice → consented app users
→ YouTube corpus — one law in `game_engine._source_class`).*

*Why a column and not `lane='game_owner'`:* lane records the **surface**, not the **ownership**.
A coach rating a session they own writes `lane='coach'` and is still a self-report.

**J3 · The singleton is weak supervision.** One rating is **never** gold and **never** used for
evaluation — it is calibration signal. **Active-learning priority:** when the lone rating
*disagrees with the machine's proposal*, that clip is the most informative unrated thing in the
corpus (either a model miss or a rater miss, and one more peer says which) — it routes
**immediately** for a 2nd peer.

**J4 · IDK is a RESPONSE, not a null.** Counted like any other answer:
- **1 definite + 1 IDK** = not a quorum → **route to a 3rd rater**.
- **2 IDKs** = **settled**, marked **"perceptually ambiguous"** in the DB. This is a
  high-value ground-truth state: it trains the detector to **output uncertainty rather than
  faking confidence** where humans are genuinely uncertain (I10 — "keep disagreement", low
  agreement is a finding).

**J5 · One rule generates all four cases** (`label_quorum.resolve`, mirrored in the view):
count every eligible response with IDK included; a snippet is **settled** when one response is
**strictly modal with ≥2 votes** — modal IDK settles as *perceptually ambiguous*, any other
modal settles as *quorum*, one response is a *singleton*, and anything else *needs a third*.

**J6 · Two flagged gaps — gap 1 now CLOSED by founder ruling.**
1. ~~**What "IDK" maps to.**~~ **CLOSED — founder ruling 2026-08-14:** *"IDK strictly means
   'ambiguous to judge' (it is a valid perceptual rating of the audio, not a technical 'I can't
   hear the clip' failure)."* So **`neutral` IS the IDK** — the ternary's third value, the arc
   game's "yes / no / idk" — and it **counts**: two of them settle as `perceptually_ambiguous`.
   **`unrateable` is the technical abstention** — a failure of the artifact, not a reading of
   the voice — and is **no response at all**: never counted, never settling anything (the same
   treatment the twice-labelled game gate always gave it). Implemented in
   `label_quorum.response_of` (`IDK_VALUES = ("neutral",)`, `NON_RESPONSE_FLAGS =
   ("unrateable",)`) and mirrored in the `snippet_label_quorum` view. A capture-time abstention
   *reason* is therefore unnecessary — the two shapes now mean two different things by
   construction.
2. **Two conflicting definites (yes + no).** Not specified. Treated the same as J4's case B —
   two humans who disagree have not reached a quorum → 3rd rater, rather than booking a
   coin-flip as ground truth.

**J7 · What this does NOT build.** The **cross-user / YouTube peer serving queue** J2 implies.
Today every session in an arc belongs to the arc owner, so the game is 100% self-report and the
own-first ordering is a no-op that becomes load-bearing the day a round can carry someone else's
clip. `routing_priority` / `rating_queue` are the ordering that queue will read; the queue
itself, its consent surface and its FE are a separate build.

---

## K · Confidence evidence, evaluation and rollout — current contract (founder 2026-08-25)

This section supersedes J wherever the older binary/neutral instrument or IDK settlement rule
conflicts with it. Historical rows keep their question version and remain interpretable; they are
not rewritten into the new meaning.

**K1 · Five distinct answers, one visual hierarchy.** The current instrument is
`conf-q-v2`: `yes`, `in_between`, and `no` are perceptual judgments; `not_sure` is rater
uncertainty; `audio_unclear` is a technical failure. The UI gives the first three equal primary
weight and renders the last two as secondary utilities. None is coerced into another.

**K2 · Audio first, answer first.** Blind raters hear the audio without transcript, machine
prediction, score, explanation, or contextual recommendation. The transcript may be released
only after the rating is committed. Model selection provenance remains server-side.

**K3 · Strict language eligibility.** A rater must have the clip language in their verified
proficient-language profile. Unknown/mismatched language fails closed; it is never relaxed to
fill a queue.

**K4 · Two-human perceptual quorum.** Exactly matching `yes`, `in_between`, or `no` answers
from two independent eligible humans settle ground truth. A disagreement or `not_sure` routes a
third. Three perceptual/uncertain answers without a matching perceptual pair become `UNRESOLVED`
and enter neither training nor evaluation.

**K5 · Technical failures are separate.** One `audio_unclear` routes the clip to a different
eligible rater (`AUDIO_RETRY`). Two independent `audio_unclear` reports quarantine the artifact
(`AUDIO_QUARANTINED`). Neither is a confidence label.

**K6 · Coach and peer may form one panel.** An authenticated blind language-matched coach and
an authenticated blind language-matched peer are equally valid independent panel members. The
owner remains a self-report and never counts toward quorum. The machine remains a router and
never votes.

**K7 · No same-rater retries masquerading as independence.** After one technical failure, only
a fresh eligible rater may answer. A rater may update an ordinary perceptual answer before the
item closes, but cannot supply two independent votes.

**K8 · Lane follows the verified act, not clip source.** A panel-grade blind coach answer is
`coach` whether the audio came from a rehearsal or imported corpus. `bootstrap` is reserved for
seeded/historical rows whose blindness, identity, or language conditions cannot be verified.

**K9 · Mixed queue selection, with auditable inclusion probability.** The blind queue combines
model-boundary active learning, balanced predicted regions, and genuine random exploration.
Each selected clip stores the policy version, selection reason, and sampling probability. These
never appear before the judgment. The random slice is the unbiased window; model-selected clips
alone cannot estimate production performance.

**K10 · Speaker-disjoint dataset releases.** Every clip from one speaker belongs to exactly one
of train, validation, or test. The grouping key is an immutable speaker/owner identity, with a
conservatively normalized imported-speaker label as the final allowed fallback; project,
session, filename, and audio are never identity guesses. Unknown speakers fail closed. A
versioned split manifest freezes test speakers; extensions may add new speakers only to train or
validation. Language, device, source, sex (when declared), and acoustic-region balance are
reported, never used to leak speakers across partitions.

**K11 · Pre-registered multi-metric release gate.** Before test results are opened, a sealed
plan names the model version, frozen dataset release, declared baseline, sample floors,
macro-F1 threshold, per-class recall floors, calibration ceiling, and supported slice gates.
Sparse slices report `insufficient_evidence`, never “passed.” A release fails on any global
failure or adequately sampled slice regression. Thresholds have no code defaults and cannot be
chosen after reading the frozen test result.

**K12 · Controlled rollout; no self-promotion.** A model has only three states: `off`,
`shadow`, and `limited`. Shadow predictions are internal and have no product effect. Limited
mode requires the exact passing evaluation report and may nominate only a high-probability
`yes` for a deterministic versioned cohort. The nomination must still pass Manager arbitration;
it cannot style text, create feedback, change a coach verdict, or admit a clip to the Voice
Album. Uncertain outputs abstain. A kill switch restores the deterministic route immediately.
There is no full-rollout flag and no automatic online retraining/promotion; every new model
version needs a new sealed evaluation and an explicit rollout decision.
