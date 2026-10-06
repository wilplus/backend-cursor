# Decisions log — settled in review, not yet folded into SPEC.md

**Last updated:** 2026-09-25.

**Purpose:** everything agreed after SPEC.md v3 was committed. This file exists so a long
review session survives itself. Entries here are **binding** and get folded into the numbered
sections on the next spec pass. Where this file and SPEC.md v3 disagree, **this file is newer.**

## 2026-09-22 · Article 50(2) and the plain-text clipboard — SETTLED

**Founder decision, 2026-09-22: do not go further than the obligation
requires. The `text/plain` clipboard flavour carries no marker line.**

This closes the open item recorded in
`legal/phase1-2026.1/03-article-50-assessment-v1.0` §3, where the written
assessment and `docs/AI-CONTENT-MARKING-PROPOSAL.md` §3 disagreed and the
implementation had taken one side without the disagreement being resolved.

**What was decided.** The rich-text (`text/html`) flavour keeps its marking.
The plain-text flavour ships unmarked, as it does today. No visible trailing
line, and — unchanged and never in question — no zero-width encoding.

**On what basis.** §3 assesses Article 50(2) as **MET as of 2026-09-19**, and
rests that on a boundary: the obligation is on the provider to mark what the
AI system produces, and a user copying text out is the user's own act. §3's own
list of what then goes unmarked is "the `text/plain` clipboard flavour, a
screenshot, and retyping" — one category, of which only the first could ever
be marked at all. A rule that followed generated text through a screenshot
would bind no provider of generated text anywhere.

**What this does NOT settle**, and §3 is explicit that it cannot: *"counsel
confirms whether html-only satisfies 50(2) for the clipboard at all."* That
question is open under every option and is not the founder's to close. If
counsel rejects the boundary argument, the trailing line is where this lands,
and this entry gets a superseding one below it rather than an edit.

**Not folded into the signed document.** `03` was signed at 21:02:08 UTC on
2026-09-22 with the item recorded as open. Editing its markdown now would
break the match with the signed PDF — the defect that superseded two earlier
signature rounds. The decision lives here and in the proposal's status line. A
`v1.1` of `03` carrying it is a separate, unhurried call.

**Supersedes** the recommendation in `AI-CONTENT-MARKING-PROPOSAL.md` §3
("option 1 for `text/plain`, plus the HTML flavour"). That document's
reasoning stands on the record and is not withdrawn; the product does not
follow it.

**C2PA** (proposal §4) remains the strategic answer and is unaffected. Today's
choice is a holding position until a signing identity makes it proportionate.

## 2026-08-29 · PLF-1 onboarding and processing flow

The product/legal onboarding, recording-eligibility, AI-transparency,
termination, deletion, and audio-lineage decision is locked in
[`PRODUCT-LEGAL-FLOW-PLF-1.md`](./PRODUCT-LEGAL-FLOW-PLF-1.md).

PLF-1 supersedes earlier conversational assumptions about per-recording
sole-speaker confirmation, full-date-of-birth collection, per-recording
country checks, and waiting for training before feedback. It does not activate
or authorize implementation, deployment, datasets, training, or promotion.

### PLF-1.1 amendment

[`PRODUCT-LEGAL-FLOW-PLF-1.1.md`](./PRODUCT-LEGAL-FLOW-PLF-1.1.md) supersedes
PLF-1. Required service processing and optional pooled model improvement now
have independent authorization states and affirmative actions. A user may
withdraw pooled-improvement authorization while continuing recording and
coaching. Dataset eligibility is recomputed at release time and is never
inherited from an acquisition snapshot or policy flag.

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
learning. Excluding the machine from the vote and keeping its proposal are the same decision. *Amended 2026-10-06 (founder, Navigation Panel QG1 A; ledger CA02; decisions log N51): J1 still holds for the label ledger and for the sound confidence read — the machine stays a router, quorum stays two humans, and `label_quorum.resolve` keeps `machine_votes: 0` (rule 1 of `services/label_quorum.py`). Willfidence (SPEC §17, `willfidence-v1`) is a separate, internal measure; its S term averages the coach, peer and machine votes for that measure alone — a carve-out for the measure, not a vote in the ledger.*

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
**immediately** for a 2nd peer. *Amended 2026-10-06 (founder, Navigation Panel QG1 A; ledger CA06; decisions log N51): J3 still holds for the label ledger and for the sound confidence read — a singleton is never gold and never evaluation, and only a settled clip is gold or evaluation data (rule 3 of `services/label_quorum.py`). Willfidence (SPEC §17, `willfidence-v1`) is a separate, internal measure computed from stored answers; it is not a label, not gold and not an evaluation set. This note changes nothing about training labels.*

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

---

## L · Phase-1 processing and retired-signal cutover (founder 2026-08-29)

This section supersedes earlier operational text wherever it suggests active
challenge/threat inference, sex-dependent weights, pitch-based sex inference,
or hidden corpus writes.

**L1 · Universal delivery calculation.** `power_score` keeps its internal
blended ranking role, but has no challenge/threat input. Confidence uses
`voice-confidence-universal-v3`: one cue contract for every speaker. The
product neither asks for speaker sex for processing nor infers it from f0.
Historical versions are incomparable and cannot be relabeled as v3.

**L2 · One processing authority.** Required Phase-1 recording/coaching uses one
server-owned policy, acquisition-principal, immutable receipt/snapshot and
provider-permit boundary. Passive viewing never creates acceptance. Guest
claim preserves the original acquisition principal. Phase-2 learning cannot
borrow this authority.

**L3 · Exact acquisition evidence.** Accepted intake atomically links the Take,
recording, exact storage provider/bucket/key, exact-byte SHA-256, authorization
snapshot, durable job and outbox event. Uploaded-but-unreferenced objects enter
an exact-coordinate orphan cleanup queue.

**L4 · Phase-2 remains dark.** Corpus imports, hidden coach-video learning
writes, MLC-2 bundled-consent routes, datasets, training, evaluation,
promotion, personalized exercise recommendation and exercise adequacy are not
operational Phase-1 purposes. Registry presence is not processing authority.

**L5 · Deletion fails closed.** A request blocks future processing immediately.
Completion cannot be claimed until canonical, product, storage, provider,
coach, cache, dataset and model lineage have approved resolvers and verified
terminal evidence. Unknown or mixed-purpose dependencies produce
`review_required`; they are never silently skipped.

**L6 · Activation remains separate.** Migration 0310 and local implementation
do not activate the policy. Exact Product/legal artifacts, retention/deletion
readiness, staging proof and explicit production authorization are still
required. The destructive historical cleanup migration remains outside the
manifest until separately authorized.

---

## M · Coach review is core to the service (founder 2026-09-23)

**The ruling, verbatim.**

> Coach review is core to the product. A user who refuses to allow a human to
> listen to their recordings cannot use WillpowerLab. This reverses the
> assumption in doc 01 §3 and §6, which placed `coach_review` on consent and
> held it out of v1 because it was treated as optional. Consequence: coach
> review moves to Art 6(1)(b) contract basis, the Terms must describe it, and
> the Art 9 element stays separate. Put to counsel 2026-09-23.
>
> — Artur Willoński, founder and controller

**M1 · This supersedes doc 01 §3 row 8 and §6.** Document 01 was signed on
2026-09-19, so those sections are not edited — they stand as the position held
on that date, and a v1.1 carries the new one. `coach_review` becomes
Art 6(1)(b) contract, `required_for_core_service TRUE`. The Article 7(4)
objection that governed the old structure does not reach it: 7(4) is about
consent, and this is not consent.

**M2 · "Agree or leave" is the intended offer and is lawful for a contract.**
It is not lawful for consent, which is why the basis is the load-bearing part
of the ruling rather than a formality.

**M3 · What the ruling does NOT decide, and needs a second ruling of the same
kind.** `resolve_mlc3_dual_purpose_receipt_v2` gates the MLC-3 general-user
service on the receipt naming BOTH `coach_review` and
`personalized_exercise_recommendation`. The ruling settles the first. The
second is untouched: doc 01 §3 row 9 already places practice on 6(1)(b)
contract — the BASIS was never in question for it — but §6 held it out of v1,
and §6's reason (an optional purpose leaves no receipt evidence) is moot for
anything marked required. So the open question is narrow: **is practice
capture and comparison part of the service, or optional?** Until that is
answered, the MLC-3 gate still cannot resolve.

**M4 · The Terms currently describe a different product.**
`legal/phase1-2026.1/copy/terms-2.0.txt` lists "no coach reviews" for the Free
and Practice plans. Read beside M1 that is a contradiction, and it is the piece
counsel will weigh. The reconciliation put to the founder: separate *a human
may listen* (every plan, part of the service) from *you receive N coach
reviews* (a tiered deliverable). Not yet confirmed; the Terms are not rewritten
until it is.

**M5 · Article 9 stays separate and cannot be contract.** One consent element
therefore remains in the flow. If refusing it also means leaving, Art 7(4)
applies to that element alone. Doc 01 §3 already offered counsel the
alternative position — that Article 9 is not engaged at all — and that question
is now more load-bearing, not less.

**M6 · The optional-consent writer keeps its purpose.** Migration 0356's
`accept_phase1_processing_authorization_v2` was built for purposes a person can
decline. After this ruling that is no longer `coach_review`; it is pooled model
improvement, which must stay declinable and can never ride on a contract. It is
not retired.

## N · Training consent, the training corpus and project delete (founder 2026-09-25)

Locked by the founder on 2026-09-25. Design:
`docs/SPEC-training-corpus-and-project-purge.md`.

**N1 · C1 — training returns only through re-acceptance.** Training may come
back later only through a new policy version that every user re-accepts.

**N2 · C2 — the MLC-2 tables hold the training yes; bundled-era yeses count
for nothing.**
- Only a fresh yes counts: given under the new policy version, as its own
  act, separate from everything else.
- Anything recorded under `mlc2-bundled-consent-v1` is never a training yes and
  is never migrated into one.
- The tables stay; `record_mlc2_consent_grant_v1` and
  `record_mlc2_consent_withdrawal_v1` do not, because both are hard-wired to
  the two bundled purposes. New versioned functions record and withdraw
  `pooled_model_improvement` alone.

**N3 · C3 — copies survive a project delete only under an active training
yes.**
- They are purged on withdrawal and on account erasure.
- Project delete must first exist as a project-scoped purge. Today the purge
  is principal-wide only, and the row-delete route was reverted (#649).

**N4 · C4 — #651 merged as it was.** DPIA §2.4 records that training is not
processed since `phase1-2026-09-23`, and that counsel has not cleared the
bundled consent.

**N5 · Also settled.**
- Voice is not biometric data here, on counsel's advice, so a training grant
  carries no Article 9 basis.
- No backfill.
- The honest delete copy is agreed in principle; its exact text is held for
  sign-off at the phase where training goes live.

**N6 · Spec questions settled (founder 2026-09-25).**
- **Q1:** the corpus copies audio segments around Confident Voice items,
  transcript spans and coach labels.
- **Q2:** copies are kept until the training yes is withdrawn or the account is
  deleted, with no fixed maximum.
- **Q3:** after withdrawal there is no retraining; future use stops.
- **Q5:** a project-deletion purge waits for operator confirmation. There is no
  automatic execution.
**N7 · Q4 = A — the MLC-2 grant is the only training yes (founder
2026-09-25).**
- Accepting the policy writes the Phase-1 receipt, which never records a
  training tick; `pooled_learning_eligible` stays false.
- A separate training toggle writes the MLC-2 training grant, which requires
  a receipt for the policy version that introduced training (enforces C1).
- **Amends M6.** The optional-consent writer keeps its job for the policy's
  other optional purposes (`personalized_exercise_recommendation`,
  `individual_learning_profile`) and no longer covers pooled model
  improvement.

**N8 · P1 and cleanup decisions (founder 2026-09-25, answered on the decision
board).**
- **P1 starts now**, shipped as PRs for review.
- **Operator target:** an operator confirms a project deletion within 7 days
  (legal ceiling one month).
- **Cancel:** a user can cancel a pending deletion until an operator confirms
  it.
- **Queue:** the operator queue lives in the existing admin panel.
- **Copy approved as written:**
  - Delete "<project name>"?
  - Every take in this project and its ideal text will be permanently
    deleted. This can't be undone. We'll finish within 7 days, and until then
    the project is locked.
  - Request deletion
  - Deletion pending
  - Cancel deletion
- **Damaged take links:** repaired by hand with
  `scripts/sql/repair_delete_cleared_take_links.sql`, previewing first.
- **Trainings-page deletes fail cleanly:** done in #653.
- **Counsel brief:** sent.

**N9 · A purged project row is a tombstone (founder 2026-09-25).**
- **Found by running it:** `tests/test_take_purge_postgres.py` purges an
  account with one recorded take through the real orchestrator. The take was
  deleted, then the project delete was refused: every accepted recording
  attempt is retained as evidence and points at its project ON DELETE
  RESTRICT. So no erasure could finish for anyone who had recorded a take.
- **Decision:** keep the row, wipe its content. The registry files `projects`
  as `tombstone` under the deletion-evidence rule; migration 0368 blanks
  `display_name`, `setup` and `presentation_ref` and stamps `tombstoned_at`,
  only for projects in the request's frozen graph.
- **Still true:** production has no active retention rule yet, so a real run
  stops at `review_required` until the retention schedule is seeded.

**N10 · P5 wording signed; counsel's answers (founder 2026-09-26).**
- **Founder sign-off on the four wordings**, as drafted in the P5 packet §3
  ("You've got my sign off on the wordings"):
  - *Training switch:* **Help improve WillpowerLab** — "Keep separate copies
    of short moments from my recordings (the audio, its words and my coach's
    rating) to train WillpowerLab. I can turn this off at any time, and my
    copies are then deleted." Its own screen, off by default, never on
    sign-up, never a condition of the service.
  - *Turning it off:* **Turn off training?** — "Your training copies will be
    deleted. Anything already used to train stays in that training, but it
    won't be used again."
  - *Project delete, switch on:* "Your project will be deleted. Recordings you
    shared for training stay until you withdraw that permission."
  - *The new policy version:* approved in principle; counsel drafts the text,
    the founder approves the final text before it is published.
- **Counsel's answers to the P5 packet §2, relayed by the founder:**
  1. The separate switch is valid consent (Art. 6(1)(a), 4(11), 7(4)): yes.
  2. No Article 9 basis on a training grant: confirmed.
  3. Voice is not treated as biometric; copies may outlive a project delete
     while the switch is on: confirmed.
  4. Retention "until the switch is turned off or the account is deleted",
     no fixed maximum: confirmed.
  5. After withdrawal: no retraining, stop future use. Models already trained
     are kept as intellectual property; they are to use only anonymised data
     and hold no personal information.
  6. Bundled-era yeses count for nothing and are never carried over: yes.
  7. New Privacy Policy text, a "Training copies" retention-schedule row and
     the DPIA update: agreed as the paperwork to produce.
  8. Processors and transfers for a future training run: confirmed as a
     required disclosure (the named processors are still to be supplied).
  9. Consent records (the yes and the no) are kept after an account deletion
     as long as they are useful for training the model.
- **Still needed before P5 can go live:** counsel's drafted policy text
  (item 7), the named training processors and transfer mechanism (item 8),
  and the signed retention schedule that seeds the `training_corpus` and
  consent-evidence rules.

**N11 · The eight open training questions (founder 2026-09-26, answered on the
decision page).**
1. **Consent records after an account deletion:** kept "as long as useful for
   training", as counsel said. No automatic end; a person decides. Engineering
   recommended "while a model trained on the person's data is in use" and was
   overruled. Counsel is asked to check the wording
   (`legal/phase1-2026.1/11-…` §3).
2. **Model anonymity:** rely on counsel's statement; no technical check is
   built before a trained model is kept. Recorded as against engineering's
   recommendation.
3. **Who trains:** not decided. **Training stays off until it is.**
4. **Transfers:** decided together with who trains.
5. **Privacy Policy text:** engineering drafts, counsel reviews, the founder
   approves. Draft: `legal/phase1-2026.1/10-training-policy-changes-DRAFT.md`.
6. **Retention schedule:** engineering prepares v1.1 with the training-copies
   and consent-record rows, counsel checks, the founder signs. Draft:
   `legal/phase1-2026.1/11-retention-schedule-v1.1-training-DRAFT.md`.
7. **Delete one project (P1):** finish now.
8. **The switched-off P5 pieces:** build now, everything off.

**N12 · Four more answers (founder 2026-09-26, answered on the "finish line"
page).**
1. **A take's permanent record on deletion: keep an empty receipt.** When a
   project or an account is erased, the append-only take lineage
   (`recording_attempts`, `takes`, `processing_transition_events`, the
   canonical feedback rows) keeps only identifiers and timestamps. Every word,
   every piece of feedback and all audio is erased. This is the N9 tombstone
   rule applied to the take lineage. It is what lets a deletion finish for
   anyone who has recorded; today every real one stops at `review_required`.
2. **Who trains: OpenAI.** Training copies go to OpenAI in the United States
   under the European Commission's standard contractual clauses. Filled into
   `legal/phase1-2026.1/10-training-policy-changes-DRAFT.md` for counsel.
   Training itself stays off until P5.
3. **The Data & consent intro, approved wording:** "Your recordings are used to
   run your own coaching. They are used to train models only if you turn on
   Help improve WillpowerLab." It is shown only while the switch is offered;
   until then the current wording stays, because it is still true.
4. **The dead commit codes in `legal/phase1-2026.1/SIGNED-ARTIFACTS.md`:**
   delete them ("Simply delete them"). `4e92203`, `8ddaab2` and `81369c0`
   were removed and the sentences kept readable; the signed PDFs and their
   hashes are unchanged.

**N13 · Two answers (founder 2026-09-26).**
1. **Users see Delete once the signed retention schedule is loaded.**
   `PROJECT_DELETE_ENABLED` (frontend) turns on only after retention schedule
   v1.0 is seeded in production. Until then a confirmed deletion stops at
   `review_required`, and the copy's "We'll finish within 7 days" could not
   be kept.
2. **Retention schedule v1.0 §3b: yes, same as consent.** `deletion_evidence`
   and `transparency_evidence` follow `accountability_need_ends`, the rule
   already signed for `authorization_evidence`. Neither holds a person's words
   or voice. This closes §3b; doc 06 itself is signed and is not edited.
3. **Load retention v1.0 now; upload the signed PDF after** ("Not yet, turn
   on anyway"). Migration 0381 registers the schedule by the coordinates in
   `SIGNED-ARTIFACTS.md` row 06 and seeds its four rules. Until the founder
   uploads the signed file to `phase1-2026.1/legal/retention-schedule-v1.0.pdf`,
   that record names a file storage does not hold. **Open: the upload.**

**N14 · Archive on the project list, Delete in Data & consent (founder
2026-09-26).** "In place of a real delete that for now we can hide":
1. The ⋯ on each row of the project list (the choose-topic screen) offers
   **Archive**: the project leaves the list; nothing is deleted.
2. **Delete a project** moves to Data & consent (hamburger menu): it opens the
   list of projects, and a project is chosen and deleted there, never straight
   from the choose-topic screen.
3. **Why Delete stays switched off for users for now:** a real deletion still
   stops at `review_required`, because several append-only tables that every
   take with feedback writes (`take_feedback_exposure`,
   `take_feedback_self_report`, `ideal_text_part_revision`,
   `phase1_processing_job_events`) are marked `external_review` in the purge
   registry and have no decided disposition. The copy promises "We'll finish
   within 7 days"; until those are decided it could not be kept.
4. **Getting a project back: in Data & consent.** Its project list marks an
   archived project "Archived" with an **Unarchive** button; the choose-topic
   screen stays clean.
5. **The four append-only records stay as they are** ("No, keep them as they
   are"): no empty-receipt wipe for `take_feedback_exposure`,
   `take_feedback_self_report`, `ideal_text_part_revision` or
   `phase1_processing_job_events`. So a real deletion keeps stopping for
   review, and **Delete stays switched off for users**
   (`PROJECT_DELETE_ENABLED = false`). Archive is the way to tidy the list.
6. **Words approved as written:** "Archive", "Archived", "Unarchive",
   "Delete a project", "Your projects", "Couldn't archive. Try again." The
   delete confirmation keeps the signed N8 wording.

**N15 · Door 1 opened; Privacy 3.2 and Terms 3.2 approved (founder
2026-10-01).** In chat, in this order: "You have my sign off" on counsel's
switch sentence and the four lines above it (recorded in
`legal/phase1-2026.1/13-training-consent-wording-SIGNED-2026-10-01.md`);
then "I just approve it here right now" on Privacy 3.2 and Terms 3.2 as
drafted from counsel's five fixes (`10-…`, `12-…`), including the six-year
consent-record period that counsel has not yet confirmed; then "Yes, open
door one."
1. **`MLC2_TRAINING_SWITCH_ENABLED` is True** by the reviewed change carrying
   that sentence. The route answers; the Settings card stays hidden until a
   training policy row exists, and the database refuses a yes from anyone who
   has not accepted the policy version that introduced training (C1). The
   order of the real gates is therefore unchanged: Privacy 3.2 published and
   re-accepted → the policy row registered → the card appears.
2. **The approved text is `copy/privacy-3.2.txt` and `copy/terms-3.2.txt`**,
   effective 1 October 2026, the day the founder ran the publish script
   (a first run with the placeholder still in the text registered nothing) (the 2026-09-24 lesson: the effective date in registered copy
   must be the activation day). The AI notice and the agreement screen are
   unchanged from 3.1. The publish script is
   `scripts/phase1_policy_publish_training_3_2.sql`, version id
   `phase1-2026-10-01`; the five processing purposes are unchanged, because
   the training yes is recorded in the MLC-2 consent ledger, not as a Phase-1
   purpose (`pooled_model_improvement` stays phase2 in the registry and the
   publish RPC refuses it).
3. **Still counsel's:** the six-year number. If counsel replaces it, the copy
   changes before publishing (free) or in a 3.3 everyone re-accepts (not).
4. **The wording PDF** is rendered from `13-…` for the founder's qualified
   signature (PAdES, as for 01 and 06); its signed hash goes into
   `SIGNED-ARTIFACTS.md` row 13 and the registration SQL in
   `docs/LEARNING-DOORS.md`.
5. **PUBLISHED 2026-10-01 09:00:43 UTC.** The founder ran the four pieces of
   `scripts/phase1_policy_publish_training_3_2.sql` in the Supabase SQL
   editor: STEP 0 resolved all five purposes operational; STEP 1 registered
   `phase1-2026-10-01` (status approved, policy_id `dbd20044-099d-453e-9feb-9d5e01f3da45…`);
   STEP 2 activated it (cutoff 2026-10-01T09:00:43Z), retiring
   `phase1-2026-09-23`; STEP 6 read privacy_has_4a = 1, terms_has_licence = 1,
   placeholder_left = false. Every speaker is now asked to accept 3.2.
6. **THE TRAINING POLICY ROW EXISTS, 2026-10-01 09:08:46 UTC.** The founder
   ran `configure_mlc2_training_consent_policy_v1` with the signed sentence,
   its fingerprint, the signed PDF's hash (SIGNED-ARTIFACTS row 13) and
   `phase1-2026-10-01`: `training-only-v1`, grant_scope training_only,
   active. Door 1 is now open on every side: the constant (this PR), the
   policy version (item 5) and the row. The Settings card shows for every
   speaker who has accepted 3.2, off, with the four lines above the switch.

**N16 · Door 2 opened for exercise_script (founder 2026-10-01).** "open door
2 for surface exercise_script", said in chat after door 1 was open on every
side (N15). The reviewed change carrying it: `MLC2_PAIR_RELEASES_ENABLED =
True` and `PAIR_RELEASE_SURFACES = {"exercise_script"}`.
1. **The pair door is its own constant.** `MLC2_DATASET_RELEASES_ENABLED`
   gates the retired DPO export lane (`scripts/export_openai_preference_jsonl.py`,
   audit J1-2) and four tests pin it dark; a pair release and a DPO dataset
   release are different lanes, so the sentence opens the pair door only.
2. **What leaves, and when:** every Monday's weekly job writes one signed
   JSONL file of the exercise_script pairs that are releasable (the
   speaker's training yes, re-read that week) to `willab-pair-releases`,
   marks them left, and lists the release on the research screen. The other
   two surfaces report "no founder sentence" until theirs.
3. **Config first:** the bucket variable is set; `PAIR_RELEASE_SIGNING_KEY`
   (and the R2 token's scope for the new bucket) must be on the backend web
   service before the first Monday, else the job reports "no signing key"
   and nothing leaves, which is the designed failure.

**N17 · P2-19 done on the founder's word, the ML-5 wait waived (founder
2026-10-01).** "do P2-19 now", said in chat after door 2 opened (N16). Lock L2
and contract 65 held the removal of the arc-level delivery until the ledger
had shown a week of walk pairs (build plan ML-5); the founder waived the wait
and the removal landed the same day, both repos.
1. **What answers 410 now:** the per-snippet note and surface toggle, the
   re-cut, the per-take Save, the wrap-up read, the slide-mapping
   correction, the arc-level publish and the internal publish door. Their
   tables (`coach_snippet_drafts`, `coach_review_revisions`,
   `coach_review_delivery_outbox`, `snippet_slide_corrections`,
   `recording_feelings`) stay as history and take no new writes.
2. **What is gone:** the publish service, the publish-delivery worker job and
   its sweeper, the publish-results email, and on the frontend the
   take-review overlay, the per-snippet card, the Delivery overlay, the
   wrap-up page, the slide-mapping control, the legacy roster that opened
   them and the `/chat?review=` deep link. The confidence label chips stay
   as a component: the walk's Judge screen and the speaker's Feedback sheet
   use them; the old review's second instrument is gone with the card.
3. **The Voice Album's coach leg:** it was gated on the publish ("blind
   until publish"). On the walk a judgement is answered blind and is final
   when written (35g-5), so the judgement write now reconciles the exact
   clip; no other gate replaces the publish. The album still has no read
   surface, so nothing the speaker sees changes.
4. **What still reads the old data:** the speaker's "Your coach" falls back
   to a revision published before this day when no Take word is shared; the
   slide corrections already recorded still feed the Ideal Text's slide
   bucketing; `results_published_at` stops advancing for new Takes, which
   the speaker never saw as such.


**N18 · Door 2 opened for praise_line and clearer_version (founder 2026-10-01,
C4).** "open door 2 for surface praise_line" and "open door 2 for surface
clearer_version", said in chat the same day door 2 opened for exercise_script
(N16). The reviewed change carrying them adds both to
`Config.PAIR_RELEASE_SURFACES`; nothing else moves: door 3 and door 4 stay
closed (`MLC2_TRAINING_ENABLED`, `MLC2_PROMOTION_ENABLED` False), the retired
DPO lane stays dark. It rests on counsel's signed door-1 answer of 2026-10-01,
which named all three existing surfaces. The two coach-word surfaces of Phase 7
(`coach_moment_line`, `coach_take_word`) are not opened: the founder's "open
now" for them rested on an AI draft, not a lawyer's answer, and they wait for a
qualified lawyer's written answer to question 2 and the founder's sentence
after it.

**N19 · Phases 1 and 2 of the after-practice paths built dark (founder
2026-10-01, F1, F2; "go until you finish the whole implementation").** F2's
exercise fallback ladder (`EXERCISE_FALLBACK_LADDER_ENABLED`, contract 35g-1)
and F1's judgement after feedback (`JUDGEMENT_AFTER_FEEDBACK_ENABLED`,
migration 0408, contract 24e-1) are in the code, off. Fallbacks and rewrite
practices are excluded from every outcome measure. Opens and skips are
recorded under either flow, so the coach-load report (requests per opened
moment, by kind, before and after the switch) has its "before". The flip of
each switch is a reviewed change after the founder's yes; the speaker's
screens follow the designer session's build of the flow. **Amended 2026-10-06 (founder, Navigation Panel QA15 B; ledger A042a; decisions log N51):** the before/after comparison is dropped. The coach-load report shows "after" only — requests per opened moment, by kind. No open or skip was recorded while the switch was off, so there is no "before" to compare.

**N20 · The coach panel's learning additions built dark (founder
2026-10-01, F8, C5-a, F6, C5-b, task 4; "go until you finish the whole
implementation").** Migration 0411 and one constant per lane:
`COACH_EXERCISE_PREFERENCE_ENABLED` (1b, contract 35g-7),
`COACH_WORD_PAIRS_ENABLED` (7, 35g-8), `ERROR_PRESENCE_AUDIT_ENABLED` with
`ERROR_PRESENCE_AUDIT_VERBAL_ENABLED` and `DETECTOR_TRAINING_AUTHORISED` (6a
to 6d, 35g-9), `COACH_BLOCK_PICK_ENABLED` (8, 35g-10), and
`COACH_TAKE_BUBBLES_ENABLED` (0c, reserved). The coach's exposure record and
the blind stamp on ratings (35g-11) are not behind a constant: they only ever
subtract, and the first rating a coach gives on a moment is blind as before.
Door 2 stays shut for the two coach-word surfaces. Every flip is a reviewed
change after the founder's yes; the 6a privacy line and the 6d voice consent
precede theirs.

**N21 · Phase 0c built dark (founder 2026-10-01, A2, A3).** A student's new
Take as a bubble in the coach's Lounge chat (`COACH_TAKE_BUBBLES_ENABLED`,
contract 35g-12): derived at read from the coach's own queue, never stored,
opening the walk on that Take; the real name rides only as 0b allows. Three
proposed frontend strings wait for sign-off with the flip.

**N22 · The founder's flips of 2026-10-02 ("go with all of them in that
order").** On, in this order, one reviewed PR each: `COACH_TAKE_BUBBLES_ENABLED`
(0c), `COACH_EXERCISE_PREFERENCE_ENABLED` (1b), `COACH_BLOCK_PICK_ENABLED` (8),
`COACH_WORD_PAIRS_ENABLED` (7), then `JUDGEMENT_AFTER_FEEDBACK_ENABLED` (F1),
`EXERCISE_FALLBACK_LADDER_ENABLED` (F2) and `PRAISE_AFTER_PRACTICE_ENABLED` (F5)
together. The strings proposed on 2026-10-01 were signed off the same day. Off,
awaiting counsel: `ERROR_PRESENCE_AUDIT_ENABLED` and its verbal switch,
`DETECTOR_TRAINING_AUTHORISED`, `PEER_LANE_ENABLED`, `DELAYED_MEASURE_ENABLED`;
door 2 stays shut for the two coach-word surfaces. The speaker's after-practice
screens remain the designer session's to build; until then F1, F2 and F5 act
through the existing screens only (the fallback rung's caption on the exercise
card; the open-time request and the praise sentence travel in payloads no
screen renders yet).

**N23 · The founder's eight determinations of 2026-10-02 (own answers; not
reviewed by outside counsel).** Recorded one per answer under
`legal/phase1-2026.1/14-founder-determinations-2026-10-02/`. Gate 6a: the blind
check runs on legitimate interest once the Privacy and Terms lines of
`15-…-DRAFT.md` are published and re-accepted, with the speaker's Personalised
practice choice as the easy off switch read at sampling time (Q1), and the
coach's answer deleted with the recording (Q2). Phases 4 and 5: a clip of a
voice reaches another user only behind its own per-recording switch, off by
default, and switching it off pulls the clip from both pools at once (Q3, now
true of the delayed measure's pair as well); the switch is written into both
Terms and Privacy in the next policy version everyone re-accepts first (Q4,
`PEER_SHARE_POLICY_VERSION` gates the route until then); a listener's answer is
the speaker's data and the listener's own (Q5). Gate 6d: the mistake-spotter
describes how a delivery sounds, not how the speaker feels (Q7), so the
employer and school fact is moot while that stands, with the condition that it
decides prohibition if Q7 ever moves (Q6); document 02 v1.1 carries both. Door
2: the coach-word surfaces need the speaker's yes like the other three (Q8,
changed from B to A the same day to keep counsel's 2026-10-01 answer), so door
2 stays shut for them. Nothing of this merges without the founder's review,
and no gate flips on it until its wording is published.

**N24 · The founder's sign-off of 2026-10-02 ("I sign it all"; own
determinations, not reviewed by outside counsel).** In chat, after the eight
determinations (N23): the founder signed the Privacy and Terms lines of
`legal/phase1-2026.1/15-coach-blind-check-privacy-line-and-balancing-test-SIGNED-2026-10-02.md`
§1 and `legal/phase1-2026.1/16-share-switch-wording-SIGNED-2026-10-02.md` §1,
document 02 v1.1, the delayed-measure definition
(`docs/MEASURE-exercise-human-delayed-v1.md`), and said counsel has answered
everything put to it; what needs a real signature is rendered for him.
1. **The approved text is `legal/phase1-2026.1/copy/privacy-3.3.txt` and
   `legal/phase1-2026.1/copy/terms-3.3.txt`**: the 3.2 bytes plus the signed
   lines, placed as the two records say, and nothing else except the version
   line and a version note at the top of each text that describes both
   additions (engineering's words; the founder confirmed them the same day,
   "Yes"). The effective date is the day the publish runs (the 2026-09-24
   lesson): the founder named 2 October 2026, and both texts and the publish
   script `scripts/phase1_policy_publish_3_3.sql` (version id
   `phase1-2026-10-02`) carry it. The AI notice and the agreement screen
   are unchanged; the five purposes are unchanged and read back from the
   registry. Neither addition is a Phase-1 purpose: the blind check rides
   legitimate interest with the Personalised practice choice as its off
   switch, the lending yes is the per-recording share switch.
2. **Document 02 v1.1 is signed by the controller** (approved_at 2026-10-02,
   signature date 2 October 2026), rendered by `scripts/render_doc_pdf.py` for
   the PAdES signature, upload to its `object_key` and hash
   (`legal/phase1-2026.1/SIGNED-ARTIFACTS.md`, pending rows). Its condition is
   engaged (N23): counsel's confirmation is the next action.
3. **Retention schedule v1.2**
   (`legal/phase1-2026.1/18-retention-schedule-v1.2-blind-check-and-lending-DRAFT.md`):
   v1.0 unchanged, v1.1's two training rows (six years stands as the
   founder's figure) and the three rows of 15 §3 and 16 §3, rendered for the
   same signature; `scripts/phase1_retention_rules_v1_2.sql` registers the
   signed PDF and seeds the five rows, run by hand after the upload.
4. **The measure definition is signed**; its C1 to C3 are the founder's Q3 to
   Q5. `DELAYED_MEASURE_ENABLED` still waits on the published policy, the
   seeded rows and `PEER_LANE_ENABLED`.
5. **What flips, and in what order, each one reviewed PR after the founder's
   review:** 3.3 active and re-accepted → `PEER_SHARE_POLICY_VERSION =
   'phase1-2026-10-02'` → rows seeded → `ERROR_PRESENCE_AUDIT_ENABLED` (and
   the verbal lane), `PEER_LANE_ENABLED`, `DELAYED_MEASURE_ENABLED`;
   `DETECTOR_TRAINING_AUTHORISED` after 02 v1.1 is uploaded and its hash
   recorded. Door 2 for the coach-word surfaces stays shut (N23, Q8). Nothing
   of this merges without the founder's review.
6. **No counsel answer is on file.** The same day the founder pasted a
   memorandum headed "SPECIMEN — DRAFTING EXERCISE. NOT LEGAL ADVICE", by an
   author who states they are not an admitted lawyer and that it must not be
   filed in the pack or cited as counsel's opinion. It is not filed and not
   cited; every record keeps "not reviewed by outside counsel". Two points
   from it are already met by the pack's own reasoning (document 02 §7.1
   assumes the AI Act's Article 3(34) condition is met and decides on
   condition (i); record 15 §2 is the contemporaneous balancing test with the
   off switch read as the Article 21 right). One is an engineering follow-up
   outside this entry: an access response to a listener must not disclose the
   speaker, nor the speaker's the listener (Article 15(4)), to be checked in
   the data-export path before the peer lane flips.
7. **Both PDFs signed 2026-10-02 15:53:48 UTC** (PAdES), received by the
   session the same day, each the unsigned render plus the signature and
   nothing else; hashes in `legal/phase1-2026.1/SIGNED-ARTIFACTS.md` and in
   the two registration scripts. The upload to each `object_key` is the
   founder's.

**N25 · The flips of 2026-10-02 ("You have my go on each of the flips, so
just go"; founder).** On the merged sign-off (N24, #861) the founder ordered
the flips ahead of the publish and the seeding, so each is gated in code on
the speaker's own re-acceptance rather than on the day:
1. **`PEER_SHARE_POLICY_VERSION = "phase1-2026-10-02"`.** The share switch
   exists only for a speaker whose current authorization is on 3.3 or
   later; before the publish runs nobody is, and the route answers
   `TERMS_REACCEPT_REQUIRED`.
2. **`BLIND_CHECK_POLICY_VERSION = "phase1-2026-10-02"`** (new) and
   **`ERROR_PRESENCE_AUDIT_ENABLED`, `ERROR_PRESENCE_AUDIT_VERBAL_ENABLED`
   True.** A clip is sampled only from a speaker on 3.3 or later
   (`services/error_presence_audit.py`, `_on_notice_version`, the share
   read's twin) who still has Personalised practice on (Q1-C). The balancing
   test (15 §2) therefore never applies to a speaker who has not read the
   line; the record's "published and re-accepted first" holds per speaker.
3. **`PEER_LANE_ENABLED`, `DELAYED_MEASURE_ENABLED` True.** Both ride the
   share switch (Q3-A), which rides 1. The founder signed the measure
   definition (N24) and answered C1 to C3 himself (N23).
4. **The retention rows (18 §2) are seeded after the founder uploads the
   signed v1.2 and gives its hash** (`scripts/phase1_retention_rules_v1_2.sql`);
   the founder's order puts the flips first. The rows are the signed
   period's proof, not a disposition the purge consults (18 §2), and the
   period itself is in the 3.3 text every sampled speaker has accepted.
5. **`DETECTOR_TRAINING_AUTHORISED` follows in its own change** once 02 v1.1
   is uploaded and registered by its hash
   (`scripts/phase1_register_power_score_v1_1.sql`).

**N26 · `DETECTOR_TRAINING_AUTHORISED` on (founder 2026-10-02, "You have
my go on each of the flips").** The last of the five flips. What authorises
it: document 02 v1.1, the founder's own determination that the speaking-error
detectors describe how a delivery sounds (Q7, N23), signed 2026-10-02 (N24),
rendered for the PAdES signature and registered by its hash once uploaded
(`scripts/phase1_register_power_score_v1_1.sql`); and Privacy 3.3 §4, whose
line says the blind-check answer "is used only to check and correct the
software that chooses your feedback" (15 §1). The learned detector's only
input is those answers, each from a speaker on 3.3 (N25 item 2); no audio and
no transcript is trained on, and no training on voice is opened by this (door
3's voice consent, C1, is untouched). What the flip does today: `fit` no
longer refuses on authorisation; the learned detector is still built, not
trained (`NotImplementedError`), and the tuned thresholds keep running in
shadow behind the promotion bar (35g-9). Registration of 02 v1.1 by its hash
is the founder's upload; the flip precedes it on his order, as N25's do.

**N27 · The ring says who the canonical promotion is for (production,
2026-10-03).** Since the flip (#814, 2026-09-30) every spoken Take's
promotion went to `promote_recording_attempt_with_mlc2_confidence_v1`, which
needs a speaker binding and a bundled grant that only the founder-consent
route creates; for every other speaker the RPC refused ("confidence producer
requires a resolved speaker"), the promotion rolled back with it and the
speaker had no Take at all, three attempts and a failed job. The ring row
`confidence_learning_writes` (0394) was always the chain's "who" (ring 5 and
a current pooled-model-improvement consent, the set readiness read before
the flip); the writer consulted only the state. Now `promote_attempt` asks
the ring for the attempt's owner and goes canonical only for a speaker it
names; everyone else gets the plain promotion, as before the flip. And when
the canonical RPC refuses an eligible speaker, the plain promotion runs
instead, logged at error level: the Take is F1 and outlives the learning
write, which is F2; Q1's rule (never a canonical promotion without the
consent it needs) holds because the Take is then not canonical, and the
producer never attaches later (the RPC's own "pre-cutover Take" refusal).
An unknown owner or an unreadable ring reads as not eligible.

**N28 · "Turn on the learning?" before every Take (founder 2026-10-03).**
The founder's words: "a simple question, turn on the learning? Yes as a CTA
and stacked below the skip button, for each user that has it OFF; if you
have it ON it doesn't show; if you have it OFF it shows each time you are
starting a take; the next take: right before the screen to start the
recording, in the same design always." The frontend asks it as the first
screen of every Lab entry while the training switch is off (before the
feelings check-in on a new project, before the "Start recording" screen on
the next Take), in the consent gate's layout. The yes IS the signed training
consent (13, 2026-10-01): the four counsel lines and the switch's sentence
render above the answer and the yes is sent against that sentence's
fingerprint through the same route as the account card, so C1 and the
own-act rule hold unchanged. Skip records nothing. Raised and overruled:
once-and-remember (the ring announcement of 0394) was proposed because a
question repeated after every refusal weighs on "freely given"; the founder,
as controller, chose "each time", and this entry is the record of that
choice. The screen never gates the live loop: a closed switch, a switch
already on, a guest, a slow or failed read all pass straight through.

**N29 · The F1 Repair Plan: the founder's answers (founder 2026-10-03).**
After the lock audit (https://claude.ai/artifact/DwAgAoxxszUSd3WV5EJfMk)
showed the F1 loop works only in part for a speaker who is not the founder,
the founder settled eight questions before the plan
(https://claude.ai/artifact/9vuDyMBxjo9ipKisHz9Ds4):
1. **V3 reaches every speaker.** The F1 Feedback read stops requiring a row
   in `mlc3_service_principal_allowlist` (the retired MLC-3 loop's guest
   list, which held only the founder); the pending-deletion check stays.
   Config first: `MLC3_SERVICE_ENABLED` is confirmed on the web service
   before that migration merges. (Plan Phase 2.)
2. **A Take rewrites whole Slides**, as built since Q4 A. Contract 8 now says
   Slide, not Paragraph; a Paragraph not said again on a spoken Slide is
   replaced with the Slide, and its text stays in history.
3. **A Take that cannot be lined up follows the Take**: a deck recording
   with no slide taps belongs to the Slide on screen when recording started;
   a document whose Slides cannot be proven is rewritten whole from that
   Take. (Plan Phase 3; contract 8 amended.)
4. **24e-1 is built now** — this is the founder's "build it": the Feedback
   sheet shows the machine's feedback first and asks the judgement after,
   using only strings the design and the locks already contain;
   `JUDGEMENT_AFTER_FEEDBACK_ENABLED` stays on meanwhile. (Plan Phase 6.)
5. **Wiring-only fixes may touch the design-locked screens** (handlers,
   hiding Practise when Personalised practice is off, reading the V3
   failure status). Any new or changed string or element goes to the
   founder first.
6. **F1 first; idle switches off; the rest later.** Off from today, each
   until what it needs exists: `PEER_LANE_ENABLED` and
   `DELAYED_MEASURE_ENABLED` (no screen renders the share switch or Lend
   your ear; the measure wrote pairs nobody could vote on),
   `EXERCISE_FALLBACK_LADDER_ENABLED` (no rungs, no caption on screen),
   `COACH_BLOCK_PICK_ENABLED` (it samples shadow frames written only for
   the founder's own Takes) and `DETECTOR_TRAINING_AUTHORISED` (the fit does not exist, and
   document 02 v1.1 §9 keeps the gate off until counsel confirms). This
   reverses the flips of N22 (ladder, block pick), N25 (peer lane,
   measure) and N26 (detector training) for these five only; no row is
   deleted. Kept on: `JUDGEMENT_AFTER_FEEDBACK_ENABLED` (its screen is
   Phase 6), `PRAISE_AFTER_PRACTICE_ENABLED` (it writes nothing unless a
   coach acts), doors 1 and 2, and the coach preference, word pairs, blind
   audit and Take bubbles, which render for coaches. The Voice Album, the
   coach side, legal and retention, the commercial model and the ML doors
   wait for a second plan.
7. **Proof is a speaker who is not the founder**: the founder records with a
   non-founder test account after each deploy, and every fix carries a test
   against the real schema or the real screen.
8. **This session runs each phase** once the founder accepts its prompt,
   merges when green, and audits before writing the next prompt.


**N30 · A guest sees the whole page; sign-up stands in front of practise
(founder 2026-10-04, "Accept phase 0.6").** Recording as a brand-new guest
on a phone, the founder got plain text: "it makes no sense. You need to show
the full feedback ... when they click on the text, the bookmark should open,
the feedback should open. And then when they want to practice, then show you
need to sign up. That should be the order." F1 Repair Plan Phase 0.6:
1. **The guest reads its own page.** The Ideal Text page's reads (the core,
   enrichment, recording roots, the deck, setup, a paragraph's history, the
   owner's own answers) accept a verified guest owner token as well as an
   account (`routes/v2/guest_owner.py`). A guest's actor is its owner
   principal -- the actor the publisher already used for a guest Take -- and
   a caller matches only Takes whose account, else owner principal, is theirs.
2. **Sign-up carries the Take (0413).** `claim_guest_owner`'s adopt path (a
   brand-new account) never gave the guest's Takes the account's `user_id`,
   so the account got "not found" on its own project. Fixed, already-adopted
   guests repaired, and the guest's paragraphs move with it so Paragraph
   identity survives sign-up (L1).
3. **Practise, Take 2, coach review and Lounge stay account-only.** Writes a
   guest would make on the page (answering a moment, helper words, edits)
   stay account-only in this phase; the page asks to sign up at those steps.
   Opening them to guests rides Phase 2, where V3 starts serving guests --
   until then a guest Take has no Feedback items to answer.
4. **Guest identities are rate-limited** (`RATE_LIMIT_GUEST_IDENTITY`,
   default 10/min, 60/h, per IP) on minting and on guest project creation.
5. **0414 (Phase 0.5b):** a claimed guest that only accepted the Terms and
   acquired nothing never displaces an account that holds its own
   acceptance.

**N31 · A revisited slide is still one slide (founder 2026-10-04, "A: join
their slide").** Recording against the default deck the founder went Slide 1
-> 2 -> 1 -> 2 -> 3; the document's paragraphs came out on slides 2, 1, 1,
2, 2, 2, 2, 3, 3, and the page (which will not guess a slide order it cannot
prove) showed the whole text as one unlinked "Your talk" block. Words said
on a slide on a return visit now join that slide, after what was already
said on it; the Ideal Text is in slide order and each slide holds everything
said on it in that Take, in spoken order. Pieces are still cut per contiguous
visit, so every audio span stays exact. A talk with no slide information
stays exactly as spoken. `services/transcript_document.py`
`_one_run_per_slide`.

**N32 · Phase 2: V3 for every speaker, failing visibly (founder 2026-10-04,
"I accept phase two").**
1. **The allowlist is off (0415).** `require_mlc3_service_principal_v1`
   consults `mlc3_service_principal_allowlist` only while
   `ring_settings.v3_requires_allowlist` is true (default false) -- the
   switch back without a deploy. The pending-deletion check always holds.
2. **No stand-in.** A typed V3 failure, an exception inside V3, or no V3
   answer while MLC3_SERVICE_ENABLED is on serves NO rows and reports
   `feedback_status: failed`; an empty V3 result is V3's honest answer and
   serves no rows. Only MLC3_SERVICE_ENABLED off (a deliberate switch) keeps
   the legacy answer (`services/ideal_text_changes.v3_outcome`).
3. **The page says so.** Retried once, then "We couldn't prepare your
   feedback this time. Your text is saved." with "Try again" (founder
   sign-off 2026-10-04).
4. **Coverage per Take is written down**: one `feedback_v3_coverage` log
   line per served Take against its 70/80/100% floor (24c).
5. **A guest's first save asks to sign up** (founder 2026-10-04, "Ask to
   sign up"): reading the Feedback is free; answering a moment, picking
   helper words or practising opens the sign-up dialog. Guest saves that
   follow the Take into the account are not built (six database checks and
   append-only evidence would need a claim-time exception); revisit only on
   the founder's word.
6. **A guest Take is baked for its reader** (the bake's actor is the
   account, else the Take's owner principal).

**N33 · Phase 3: Take 2 follows the Take (founder 2026-10-04, "Accept phase
three.").**
1. **No taps is not no slide.** A recording with a deck but no slide taps
   was spoken on the first slide; its words are slide 0, not "unknown"
   (`services/slide_word_split._contiguous_slide_runs`).
2. **An unprovable document follows the Take whole.** When the old document
   cannot be merged by slide (no slide provenance, or the merge cannot be
   proven), the latest Take's own words become the whole text; the previous
   version stays in the versions table. It used to stay exactly as it was,
   which is a best-of by omission (L1, contract 8 as amended, N29 answer 3).
   One `take_rebuild_followed_whole_take` warning per such Take
   (`services/take_rebuild.follow_the_take`).
3. **Every Take rewrite is a Paragraph revision (0416, contract 16).** Each
   Paragraph whose words a Take changed, or that it created, appends a
   `take_rewrite` revision carrying the Take session and the review
   version, so the Paragraph's History reads Take N from its own record. A
   Paragraph on a slide the Take did not speak gets none.
4. **The lock is the Paragraph row's.** The v2 core read took `locked` from
   the newest revision being a `lock`; a Take rewrite keeps the lock but
   appends a newer revision, so a locked Paragraph would have read unlocked
   after Take 2. 0416 reads `ideal_text_part.locked_at`, as every bundle
   read already did.

**N34 · Phase 4 (first half): practice that saves, starts and is offered
honestly (founder 2026-10-04, "Accept phase four.").**
1. **Attempt 4 and attempt 10 save (0417).** 0279's inline
   `CHECK (attempt_index BETWEEN 1 AND 3)` on
   `confident_voice_practice_attempt` outlived the route's own cap (D2,
   2026-09-30): the fourth attempt was refused by the database. It is
   replaced by `CHECK (attempt_index >= 1)`.
2. **A refused save leaves no recording.** The route uploads before it
   records; `record_practice_attempt` now deletes the uploaded object
   (verified by its bytes) on every refusal or exception. The orphan sweep
   never saw this path's objects, despite the comments that said it would.
3. **Every moment can be practised.** The practice cannot start without the
   moment's evidence coordinates, and only moments with an attached
   exercise were grounded, so practise on a praise, rewrite or plain card
   recorded and went nowhere. Every Confident Voice moment with a clip is
   now grounded (`_ground_every_moment`); coordinates only. Practice on a
   praise card passes on the speaker's own Yes or In-between, as every
   practice does (`practice_adoption.outcome`).
4. **Practise follows the choice (frontend, wiring only).** With
   Personalised practice off, the paragraph sheet offers no Practise and no
   "Accept and practise" (its one button promises the practise); its
   footer is Next. A plain "Accept" for these speakers would be new copy
   and waits on the founder.
5. **The attempt label counts on.** The Feedback sheet's recording screen
   read "Attempt 3" from the third attempt on (a clamp on a remaining count
   that stops at zero); it now numbers the next after those saved.

**N35 · Phase 1 (the window of three) and Phase 4 B (an accepted rewrite is a
Paragraph version), founder 2026-10-04 ("Accept phase four"; "keep going
with all the next phases ... and merge along the way").**
1. **The window finds the machine's read.** The score map was keyed by the
   bundle candidate's uuid and looked up by the served row's id (its
   candidate key), so every lookup missed and the window filled in text
   order. It is keyed by (family, candidate key) and by the uuid
   (`window_scores`, `window_score`).
2. **Never three of one colour, at any count.** The three-or-fewer shortcut
   and the unscored fallback both skipped the two-per-colour rule; both are
   gone (`feedback_window.choose_open_moments`).
3. **Slide-saved words count as saved.** A locked paragraph whose helper
   words live on its Slide row (from practice or an earlier Take) leaves the
   window like one with its own words (`saved_paragraphs`).
4. **An accepted rewrite writes its Paragraph (P1-1, 29b, clause 16).** After
   the owner's `apply_suggestion` on a V3 rewrite, the server takes the
   quote and the proposed words from the V3 freeze that served the item
   (the selected membership item names the Paragraph; its candidate holds
   the words), replaces the quote in that Paragraph and writes the result
   through `compare_and_set_user_ideal_edit_v1`, which appends the
   `owner_part_text_updated` revision and stores the owner edit; the next
   Take supersedes it (Q5 A, clause 9). The decision-ledger star is no
   longer sent for these items. Refused, with the reason in `text_update`
   and no word changed: a Paragraph with helper words or a lock
   (`protected`), a quote no longer in the Paragraph or Paragraphs that do
   not join to the text (`stale`), an item the freeze never served
   (`not_found`), any writer failure (`failed`). The writer needs the
   speaker's MLC-3 enrollment, which follows the Personalised-practice
   choice -- as every text edit already does.

**N36 · Phase 5: helper words hold together (founder 2026-10-04, "keep
going with all the next phases ... and merge along the way").**
1. **The four-word cap holds on the server** (B3): the paragraph route, the
   earlier-Take route and the practice route refuse more than four words with
   their existing INVALID_ROOT_PHRASE answer (`within_cap`). Words saved
   before the cap are read as they are.
2. **A lock replaces only its own paragraph's earlier words** (Q14 A,
   narrowed): a pick locked in a later Take replaces what THAT paragraph had
   from earlier Takes; a sibling paragraph's words on the same Slide stay
   until it is locked anew (contract 14). The recording roots cover a
   legacy paragraph root by its paragraph, not its Slide.
3. **The Album refresh fails closed**: inserts still land, removals wait for
   a refresh whose every read completed.
4. **Frontend** (wiring only): Presentation Mode and export read the page's
   helper words (Slide-saved words included); a deleted set stays in
   History; the Lab's text screen gets Delete-unlock, earlier-Take words and
   judged updates; "Record Take 2" there asks "Turn on the learning?" (N28).
5. **Open for the founder: the old "undecided" lock gate.** The lock route
   refuses (409 UNDECIDED) while any served row on the paragraph is open --
   a V3 rewrite or praise note included -- and the page treats that refusal
   as final, so helper words can save while their lock does not. Pinned by
   `tests/test_the_undecided_lock_gate.py`; left as it stands until the
   founder decides whether it goes.

**N37 · Phase 6 (judgement after feedback, 24e-1) and Phase 7 (landing after
a Take, J1 J2 J4 J5), frontend, founder 2026-10-04 ("keep going with all the
next phases ... and merge along the way").**
1. **The sheet opens on the feedback** (24e-1): a waiting moment opens in the
   paragraph's own sheet on the card the machine's read chooses -- the
   praise on a confident moment (Next then asks the judgement), the exercise
   matched to the clip, else the rewrite, else the moment, on one that needed
   work (Practise, or Skip, which settles the moment unanswered through the
   `skipped` event; a rewrite the speaker can accept keeps 29b's "Accept and
   practise" with "Keep my words"). Practise opens the card shown. The open is reported once (`opened`, with what was on
   screen), which raises the coach request under the machine's kind (0408).
   The card is chosen on the page from the served items by the same matrix as
   `decide_at_open`, so it never waits on the network; the open's
   `follow_up` is recorded, not read. Only strings the design and the locks
   already hold. `FEEDBACK_FIRST` is the page's one switch back.
2. **A Yes shows the praise only** (24f): a Yes on a moment read weak no
   longer falls through to the rewrite.
3. **No made-up answer**: a practice started before any judgement sends no
   `original_user_answer`, instead of a "no" the speaker never gave.
4. **Landing after a Take** (J1, J4): the text lands with "Review feedback"
   and the next Take both visible, "See next steps" as the quiet link; the
   walk's end card offers the next Take as its one button with "Back to the
   text" as its link. The button reads "Record Take 2" after Take 1 and
   counts on after that, with its existing labels. J2: the Lounge no longer
   opens the text by itself when a Take settles. J5: the journey bubble no
   longer offers Presentation Mode (the ⋯ menu stays its only door).
5. **Open for the founder**: the J2 Lounge card that reads "working on your
   text" and turns into "Review feedback" is not built -- the founder asked,
   2026-08, for the working-on-your-text block to be deleted (flowCopy), so
   bringing it back is the founder's call.

**N38 · Close-out audit fixes (F1 Repair Plan Phase 8, 2026-10-04).** Two
independent checkers re-read Phases 1-7 against the code; what they found
and this session confirmed is fixed here.
1. **The Album never empties on a failed read.** The readers behind the
   refresh returned empty on failure, so the Phase 5 guard never tripped
   and one failed read could remove every entry. The refresh now reads
   strictly (`strict=True` on the six readers it uses); any failure keeps
   every entry.
2. **No V2 stand-in on an early V3 failure** (24h, N32). The session read,
   the document and the binding ran outside V3's guard, so a raise there
   left V2's rows serving. They are V3 failing the Take now: no rows, the
   failure reported. V2's rows failing their own span check no longer
   silence V3 either.
3. **An accepted rewrite** (N35.4): a repeated answer finds the words in
   place and changes nothing, even when the new words hold the quote; a
   quote found more than once is refused rather than guessed (the freeze
   carries no span); helper words saved on the Slide row protect their
   Paragraph; the writer's refusals are read by their exact codes; the
   Paragraphs are joined as every other writer joins them.
4. **Words of a Paragraph the Slide no longer has** (N36.2): a lock retires
   the earlier-Take rows of Paragraphs no longer on the Slide, which no lock
   or unlock could reach.
5. **Frontend** (Phase 6): Practise opens the card shown (a library exercise
   opened the rewrite or the old sheet before any judgement); the button
   before a judgement reads Next, not Done.

**N39 · The founder's answers to the close-out questions (2026-10-05).**
1. **Practice off hides Accept too** ("ok"): with Personalised practice off,
   neither Practise nor "Accept and practise" shows. No plain "Accept" string.
2. **The "undecided" lock gate is retired** ("i guess yes"). The lock route no
   longer refuses (409 UNDECIDED) while feedback on the paragraph is open, and
   no longer rebuilds the Feedback block to ask. Nothing is decided on the
   speaker's behalf: an open row stays open, and a rewrite on a locked
   paragraph is refused at Accept (N35.4, PROTECTED). `undecided` stays the
   page-colour rule.
3. **No "working on your text" Lounge card** ("no"): journey decision 2's card
   is not built; the Lounge keeps not opening the text by itself (N37.4).
4. **Accept on a paragraph with helper words**: explained to the founder,
   awaiting the answer; the refusal stands meanwhile.
5. **A moment the machine could not read, with a rewrite**, opens on Accept and
   practise / Keep my words with no Skip ("acceptable").

**N40 · Accept on a Paragraph with helper words or a lock (founder
2026-10-05: "it is possible that helper words are attached to the words
that are not visible - but exist only in the history; that should be the
logic of it"; "yes, relax the guard and build it").** Supersedes the
refusal of N35.4 and N39.4 for protected Paragraphs.
1. **The words go in, the lock and the helper words stay.** Accepting a
   rewrite on a locked Paragraph, or one with helper words, writes the new
   words as a Paragraph version ("Correction accepted"). Helper words picked
   in the text move to the Slide row, locked, and the in-text span is
   cleared: they show as the Paragraph's helper words with nothing marked in
   the text, pointing at the version they came from, which stays in
   History -- the same rule as words picked from an earlier Take. They stay
   until the speaker picks new ones (contract 14).
2. **One door in the writer (0418).** `compare_and_set_user_ideal_edit_v1`
   still refuses every change to a protected Paragraph, except a text change
   -- never a move or a removal -- to the one Paragraph that
   `accept_rewrite_into_part_v1` names for that transaction. The patch edits
   that single line in place and refuses loudly if it is not found.
3. **Nothing is lost on a failure.** If the helper words cannot be carried
   to the Slide row (no Slide proof), nothing is written and Accept answers
   `protected` as before.


**N41 · A guest's Take gets its Feedback (founder live test, 2026-10-05:
"there are still no feedbacks available in the ideal text").**
1. **The claim knows a guest's Take (0419).** `claim_ideal_text_feedback_set_v1`
   compared `v2_sessions.user_id` with the caller; a guest's Take has none, so
   every guest claim raised 'feedback set provenance mismatch'. It now
   compares `COALESCE(user_id, owner_principal_id)` -- the rule
   `session_actor_id` already applies on the guest read route. A signed-in
   Take compares as before.
2. **Never silent again.** A refused claim no longer throws the whole Feedback
   block away: the page gets `feedback_status: failed`
   (`feedback_set_claim_failed`) and shows its notice and Try again. A block
   that falls over for any other reason says so too (`changes_failed`).


**N42 · Second plan, Phase 1 (founder "go", 2026-10-05, after the "Nine
Choices, Drawn" page).**
1. **A coach's draft takes the speaker's permit.** The three coach drafts (a
   request answer, the Take word, a moment line) send the speaker's
   transcript to the provider from /v2/coach/, outside the core gate.
   `speaker_provider_route` binds each to the SPEAKER's current authority:
   it resolves the Take's owner, requires current authorization and opens
   the protected scope that every provider call inside reads its permit
   from. A speaker without authority gets no draft; the coach writes by
   hand. Inert while the gate is off.
2. **Switches with nothing behind them go off (as N29).**
   `PRAISE_AFTER_PRACTICE_ENABLED` is off: no screen renders the sentence,
   the encouragement, Bold voices or the coach readings.
3. **Best Presentation leaves the surface (L1).** Its Lounge card is never
   fired again: every arc with three Takes gets the transcript card, and no
   Best Presentation is composed to decide it. Rows already written stay;
   the frontend hides them, and its doors open the Ideal Text.
4. **The pace panel's pair jar only grows.** It counts every releasable
   pair ever written, not the pairs still waiting for export, which every
   weekly export emptied.


**N43 · Financial records are kept five years (founder 2026-10-05, "It
should be kept for 5 years").**
1. **The answer to retention schedule v1.0 §3.** `financial_evidence`
   (`token_ledger`, `llm_usage`) is retained five years from the end of the
   financial year in which a record was made: option 2, a bounded period, at
   the period v1.0 §3 names for accounting records in Poland. The same day
   purchases became one-time packages (N44), so the token ledger records
   each sale.
2. **It reaches the database the way every rule does.** Retention schedule
   v1.3 (`legal/phase1-2026.1/19-…`) carries the one row; the founder signs
   its PDF, and `scripts/phase1_retention_rules_v1_3.sql` registers it and
   seeds `financial-evidence-v1`, refusing while the signed hash is a
   placeholder. Not a migration.
3. **What it unblocks, and what it does not.** With the rule active, an
   account erasure is no longer stopped by these two tables. Nothing yet
   deletes them when the five years end (the scheduled clean-up is its own
   decision), and an account holding rows the registry marks
   `external_review` (an arc purchase, a coach AI conversation, Life Panel
   consent) still stops for an operator, as before.


**N44 · Packages, bought once (founder 2026-10-05, "Packages").**
1. **The buy button opens a one-time Checkout.** `/v2/tokens/checkout`
   opens a Stripe Checkout in `payment` mode at the published price
   (`services.token_prices.TIERS`, written inline), never a subscription.
   Until today it opened a monthly subscription while the purchase screen
   said "one-time purchase" (contract §8 items 48-50 were right; the code
   was wrong).
2. **A paid package is granted once, from the session Stripe re-reads.**
   The webhook grants only a session that is paid, in USD, for exactly the
   package's price; its tokens go into `bonus_balance` and its coach reviews
   into `coach_review_credits` (0420), both never reset, idempotent on the
   Checkout Session id.
3. **Nothing renews.** `PERIOD_RESET_ENABLED` is off: the period no longer
   rolls, so the free grant lands once, at seeding, and `period_ends_at` is
   null. The coach allowance is the tier's own plus every review bought,
   against a counter that no longer resets.
4. **Held for the founder.** Terms 3.3 §2 still describes monthly plans; a
   3.4 §2 proposal (and one Privacy line) awaits sign-off and counsel. The
   line Stripe shows ("Practice · 150,000 tokens") follows the purchase
   screen's chip. Existing subscriptions, if any, keep their webhook path;
   none can be started.


**N45 · The second plan's open questions answered (founder 2026-10-05,
"3a yes b 30 days / 4 yes as recommended / 5 yes / 6 yes / 7 agreed / 8 no /
9 B").**
1. **Q5 · The Album's Machine Yes is the clip's own read.** The machine leg
   is `judgement_follow_up.clip_machine_read` on that exact clip: the read
   that colours the bar green and chooses the follow-up. It was the legacy
   star lane's EMPHASIZE row (`MOMENT_SUGGESTIONS_ENABLED`, off by default),
   so nothing could enter. A clip that cannot be read is neither Yes nor No:
   it adds nothing and removes nothing (fails closed, as N38).
2. **Q9 · Naming a pattern on the moment is retired (B).** The route
   `/coach/sessions/<sid>/snippets/<snip>/named-errors`, its two service
   functions and the `named_errors` field on the coach's Read are removed;
   no screen ever called them. `coach_moment_error_events` and its rows
   stay as history; the practice-attached path still writes there.
3. **Q8 · "You are here" is not built.** Lock-in spec §4 is marked retired.
4. **Q7 · The coach's words to the speaker go to the designer session.**
   `coach_answer` stays on the speaker's item, unrendered, until the design
   places it on the Feedback sheet (design lock).
5. **Q6 · The coach's practice judgement comes back** on the coach's screen
   (frontend; the backend route never left). **Q3, Q4 · leaving and
   retention:** a "Delete my account" button (its words to the founder for
   sign-off), unclaimed guest recordings cleaned after 30 days, and a
   retention cleaner (audio 12 months after last use, logs 90 days) that
   reports what it would delete before its first real run, which waits for
   the founder's word.


**N46 · "Last use" of a recording (founder 2026-10-05, "12 months without
the activity is the last used").** Nothing records when a recording was last
opened or played, so last use is the later of when the recording was made
and the last change to any project of its owner (a claimed guest's
recordings count under the account that claimed them). Audio goes when that
is more than 12 months ago. `scripts/retention_report.sql` already counts by
this rule; the real deletion run still waits for the founder's word on the
report's numbers (N45).


**N47 · Retention schedule v1.3 registered; the retention report reads zero
(founder 2026-10-05).**
1. **Registered.** The founder signed v1.3 (PAdES, 13:42:28 UTC; sha256
   `59a25f94…3cfb4` in SIGNED-ARTIFACTS.md) and ran
   `scripts/phase1_retention_rules_v1_3.sql`; its verify query returned one
   row: `financial-evidence-v1`, `financial_evidence`,
   `financial_year_end_plus_5_years`, active, on `retention_schedule` 1.3.
   An account erasure now completes: purchase and usage records are kept
   under this rule and everything else goes.
2. **The report reads zero.** `scripts/retention_report.sql` in production
   returned 0 for every line: no unclaimed guest older than 30 days and none
   of their audio, no audio unused for 12 months (N46), and no row older than
   90 days in any of the five log tables. The real deletion run (N45) has
   nothing to delete today; it is still not built and still waits for the
   founder's word.


**N48 · Closing the Gap: the founder's thirty answers and the Wave 1 "go"
(founder 2026-10-05, "Q1 A / Q2 B / Q3 A / ... / Q14 A / ... / Q18 B / ... /
Q30 A", on the page https://claude.ai/artifact/29WuaVG6EmaVeuo3DGcgTG).** The
plan covers all 305 lines the lock audit of 5 October left open, in twelve
workstreams and five waves. Wave 1 starts now; each later wave starts with its
answers below.
1. **Wave 1, with one correction ("keep it as it is today").** Step 3 is
   dropped: on a later Take a saved paragraph's sheet keeps showing no player.
   The helper-words lock's "playback in both" (B8-2, D6) is amended
   accordingly. Wave 1 is: the page opens the card the follow-up matrix
   names; the window's third slot never goes to an uncoloured moment while a
   coloured one exists; detector praise and machine rewrites reach V3 with
   their evidence and the fallbacks step in only when nothing servable
   exists; History shows an accepted correction as its own row; the coach's
   Take-word video is transcribed under a permit; Practise follows the
   sensitive-information choice; re-record asks "Turn on the learning?"; two
   tests against the real database and screen.
2. **The paragraph and the page.** Q1 A: the coach's queue holds only moments
   the speaker was shown or answered. Q2 B: no structure lane now; contract
   27 says verbal and formulation now, structure later. Q3 A: after "Keep my
   words" the same rewrite is not offered again on that Paragraph until its
   words change (PARTS §12.3, read by V3). Q4 A: "Rehearse all"
   (PARTS §7), replacing the deck inside a project (contract 4) and the
   unbaked served text (PARTS §12.2) are retired. Q5 A: the Manager's
   helper-word proposal for an uncovered Slide stays off; clause 20 says so.
   Q6 A: after Delete the paragraph rejoins the walk at once on its earlier
   answer.
3. **Words on the locked screens.** Q7 A: the helper-words lock is amended to
   29b on rewrite cards ("Accept and practise" / "Keep my words"). Q8 A: "Done"
   becomes "Next"; "Record again" becomes "Record Take N"; "Yes — Confident" /
   "No — Not confident" become "Yes" / "No"; the header caption becomes "AI-
   generated text · Take N"; "Small rewrite" becomes "Clearer version";
   "Choose different words" becomes "Edit"; the Take 1 note shows in the
   paragraph sheet's picker; "Keep practising" becomes "Practise again". Q9 A:
   "Delete helper words", "Tap words from any Take", "Confident" / "Not
   confident", "Accept and practise", "Keep my words" and "Say it this way ·
   accepted" are signed into the lock. Q10 A: "Your coach is working on your
   exercise." shows only while a coach is active. Q11 A: a coach's word
   belongs to its Take and Step 0 opens whenever an unseen word exists. Q12 A:
   the contract and lock texts are amended to the later decisions (24f, 47,
   the design-lock L3 note). Q13 A: after a check for live subscriptions, the
   subscription and credit-pack paths, the arc checkout and the Best
   Presentation builder are removed and the deck fallback replaced.
4. **Leaving and legal.** Q14 A: account deletion completes by itself after
   a 7-day cancel window; a person acts only on rows no rule decides. Q15 A:
   retention schedule v1.4 is drafted for the founder's signature (product
   records deleted with the account or project; job evidence kept 12 months)
   and counsel reads it. Q16 A: the scheduled clean-up (guests 30 days, audio
   and voice measurements 12 months after last use, logs 90 days) is built
   with a dry run; its first real run waits for the founder's word. Q17 A:
   speakers may delete one project, after Q14; its words go to the founder
   first. Q18 B: no "report a recording" control; the Terms carry the rule.
   Q19 A: after a deletion request the app shows a one-line ended state, its
   words to the founder first. Q20 A: the Terms stand (others with their
   agreement) and the lock is amended. Q21 A: country is asked once and
   prefilled; location reassessment is dropped unless counsel wants it.
   Q22 A: document 03 is corrected to say what the screens label, and counsel
   is asked whether the sheets need their own label. Q23 A: document 02's
   condition goes to counsel this week as the first question.
   *As built (migration 0422): Q14 A and Q17 A supersede the operator's
   confirmation in N6 Q5 and N8 (SPEC-training-corpus §6.4 amended). A
   request blocks at once and deletes nothing for 7 days; after that it is
   purged by the scheduled run, which executes only with
   `PHASE1_PURGE_EXECUTION_ENABLED`. Until retention schedule v1.4 decides
   the four append-only feedback and job tables, a purge that meets their
   rows still stops for a person (N14.3), so project Delete stays off.*
   *As built (Q15 A, Q22 A, Q23 A): retention schedule v1.4
   (`legal/phase1-2026.1/20-retention-schedule-v1.4-product-records-and-job-evidence-DRAFT.md`)
   and document 03 v1.1 (`03-article-50-assessment-v1.1-DRAFT.md`) were
   signed 2026-10-05 20:05 UTC (D1 A, D2 A on the Wave 3 sign-off page,
   N50; hashes in `SIGNED-ARTIFACTS.md`), and the counsel brief is written
   (`21-counsel-questions-2026-10.md`, document 02's condition first).
   Registration waits for the upload and, for v1.4, for 0424 (the purge
   change that acts on its two rules) and 0425 (the grant that lets the
   purge delete three job tables' rows) to be deployed.*
5. **Coach and learning.** Q24 A: coaches' Yes answers in the blind error
   audit are what promote a shadow cue. Q25 A: a "Library" link in the coach
   menu. Q26 A: the Students screens stay off. Q27 A: the confidence-learning
   chain is connected: one consent authority (the training yes) and the coach
   walk's blind labels as its judgements; training stays closed.
6. **Designer session and content.** Q28 A: the designer draws, in order,
   coach words to the speaker, praise after practice, the share switch with
   Lend your ear and the delayed measure, then Bold voices. Q29 A: the nine
   praise lines and three rewrite moves are drafted by the session for the
   founder's signature. Q30 A: the exercise fallback ladder stays off until
   three general exercises are filmed.


**N49 · The legacy commerce check reads zero; the old paths are removed
(founder 2026-10-05: ran `scripts/legacy_commerce_check.sql`, "stripe is
clear", "merge it when green").** N48.3 Q13 A made the removal wait for this.
1. **The numbers.** No live, past-due, cancelling or other subscription row;
   no subscription renewal or tier change in 35 or 90 days; no account on a
   paid tier; no credit-pack purchase in 90 days (7 ever, all older); no arc
   checkout through Stripe ever. In the Stripe dashboard the founder found
   nothing live ("stripe is clear").
2. **Removed:** subscriptions (tier checkout, portal, webhook branches,
   `plan` on the balance), credit packs, the per-project arc checkout, the
   Best Presentation builder and pencil-edit route, the best-of assembly
   branch, and their frontend clients. The portal answers 410; the webhook
   still acknowledges any stray subscription or arc event with 200 and logs
   it. Token packages are untouched. No table or column is dropped: the
   seven credit-pack grants and every financial row stay as records.
3. **Left for a later founder decision (contract 55):** the legacy credits
   hook, arc redeem/unlock, the retired tier keys, and the one remaining read
   of the Best Presentation cache.
4. **After merge (ops):** the retired Railway variables
   (`STRIPE_CHECKOUT_PRICE_CREDITS_JSON`, `STRIPE_PRICE_TIER_JSON`,
   `STRIPE_AUDIT_PRICE_ID`, `AUDIT_CHECKOUT_*_URL`) are read by nothing and
   may be unset.

**N50 · Wave 3 sign-off: nineteen answers and two signatures (founder
2026-10-05, on the page https://claude.ai/artifact/EE7tWDgonShyveozGwDgKW:
"W1 A / W2 A / W3 A / W4 A / W5 A / S1 A / D1 A / D2 A / P1 A / P2 A / P3 A /
P4 A / P5 A / P6 A / P7 A / C1 A / C2 A / C3 A / C4 B").**
1. **Words signed (W1–W4 A).** The leaving screen: "Your account will be
   deleted on <date>." and "Nothing new is processed for this account.",
   with the signed "Your account is being deleted. We'll finish within one
   month." and "Data & consent" placed on it. Cancelling: "Cancel
   deletion", "Your account will not be deleted.", "Couldn't cancel. Try
   again.", "It can no longer be cancelled." The account confirm while
   cancelling is on: "Everything you recorded and wrote here will be
   permanently deleted after 7 days. Until then you can cancel. From now on
   nothing new is processed." The project window: "The deletion happens 7
   days from now and can't be undone after that. Until then the project is
   locked, and you can cancel." and "Will be deleted on <date>".
2. **W5 A.** N10's project sentence is retired: it is untrue since training
   is text only and a project delete removes the training copies made from
   its takes. For a person with training on, the project and the account
   confirms end with the signed "A model already trained stays." (training
   wording, 2026-10-01).
3. **S1 A.** The leaving screen and cancelling switch on now; project Delete
   stays off until v1.4 is registered and P1 is built.
4. **D1 A, D2 A.** Retention schedule v1.4 and document 03 v1.1 signed
   2026-10-05 20:05 UTC (SIGNED-ARTIFACTS.md).
5. **v1.4 §5 adopted, to be carried by v1.5 (P1–P7 A).** P1: the nine
   function-only live records are deleted with the account or the project
   through a governed database function, applied by hand once. P2: a free
   founding pass is a product record; an arc row paid in credits is a
   financial record (five years). P3: `ml_consent_snapshots` is consent
   evidence (six years). P4: a reference video goes with the account unless
   it is library content, when only the speaker's link goes. P5: in the
   retired corpora a person's own rows go with the account, each table by
   its own reviewed, previewed clean-up. P6: learning lineage and the
   switched-off paths go with the account through P1's function. P7: the
   clean-up deletes `token_ledger` and `llm_usage` rows once their five
   years end, counting first; its first real run waits for the founder's
   word.
6. **The clean-up (C1–C4).** The eight voice-measurement stores as built
   (C1 A); Voice Album clips go with the audio (C2 A); processing-job rows
   that deletion evidence points at are kept (C3 A); `dev_bugs` is the
   founder's own bug list, not a log, and stays out of the clean-up (C4 B).
   *As built (0426, `migrations/financial_records_go_after_five_years.sql`):
   C4 B: `retention_log_relations_v1` is re-issued without `dev_bugs`, so the
   report, a dry run and a live run never count it or touch it. P7: rule 4
   of the clean-up counts, and behind `RETENTION_CLEANER_LIVE` (still False)
   deletes, each `token_ledger` and `llm_usage` row once five years have
   passed since the end of the financial year it was made in, read as the
   calendar year in Warsaw time (a row made in 2026 is due from 1 January
   2032), for every account, open or deleted; a row whose account has an
   unfinished account-wide purge waits for it. The service role gets
   SELECT (id, created_at) and DELETE on the two tables, nothing more.
   Nothing reads an old row for a balance, a receipt or Stripe; a per-arc
   action re-opened on an arc whose charge row has gone is charged again,
   once, while token pricing is on.*
7. **The founder's check** (Supabase, read-only, the same evening):
   migrations 0422 and 0423 are in production; no account deletion has been
   asked for.

**N51 · The founder's answers of 6 October 2026 (Navigation Panel; two
exports, 07:59 and 13:10 UTC).** The answers are verbatim, with the
founder's notes, in `docs/audit/PANEL-ANSWERS-2026-10-06.md` and
`docs/audit/PANEL-ANSWERS-2026-10-06-b.md`, and the rows they decide are in
`docs/audit/LEDGER.md`, all three on branch `claude/audit-ledger`. Each answer
is listed here by its panel ID with the ledger rows it decides (in brackets;
"—" where the answer sets process or a build-plan item and no ledger row
carries it).
1. **The morning five (first export).** R1 A undo it, revert #907 [N01].
   R2 A merge #908 and #616 first [N04a, N05, B1.1]. R3 A fix the
   shadow-frame writer now [N20, B1.1]. R4 A delete
   mlc2-confidence-readiness after a check [N17], superseded by R4a A keep
   the alarm and find the cause [N17]. R5 A land the B6 patch [A002, A006].
2. **How the work runs (W, M, H).** W1 A the ledger is the list, W2 A most
   serious problem first, W3 A a fresh session per row (note on outside
   agents and model choice, verbatim in the export), W4 A questions only
   come to the panel, W5 A a Done screen in the panel with the app's real
   screens [X7]. M1 and M2 not answered; M2a B keep copy-paste for a while.
   M3 A a different model writes the test, M3a A one model writes tests and
   the other checks, M3b A the fixer flags and never edits the test, M4 A
   task files copied by hand (note verbatim in the export), M5 A other
   models write fixes for small rows, M6 A one fresh outside read now
   [N22]. H1–H7 A build X1, X2, X3, X4 a/b/c, X5 [X1–X5, B2.2]; H8 A
   screens, database changes and every tenth other PR [X6]; H9–H12 A build
   X7, X8, X9, X10 [X7–X10].
3. **The V4 page (V).** V1 A every speaker [B1.1]. V2 A from all moments
   [B1.2]. V3 A round up [B1.2]. V4 A stretch evenly [B1.3, B1.6, BEXIT,
   BG01]. V5 B stricter filler scale [B1.3]. V6 A spread stays empty [B1.3].
   V7 A phone clock [B1.4]. V8 A any single blind coach answer [B1.4b]. V9 A
   In-between counts half [B1.4b]. V10 B a paragraph ID that survives
   rewording [B1.5] (note: a slide has more than one paragraph; follow-up
   V10a open). V11 B only a clear rise [B1.5]. V12 A all the paragraph's
   moments [B1.5]. V13 A Claude drafts the importance list, the founder
   approves [B1.6, BO1]. V14 A cut-off from dark-run data [B1.6, BO2]. V15 A
   fallback per block [B1.6, B2.1]; V15a A falling back too often fails the
   exit gate (4 of 5 blocks) [B1.6, BEXIT]. V16 explain it more simply;
   V16a A V4 picks moment and kind, the exercise picker picks the video
   [B1.6]. V17 A In-between counts half [B1.7]. V18 A "None needs it" by
   both is agreement [CA07]. V19 A "Is the new version surer? Yes / No /
   Can't tell" [B1.9]. V20 A speaker's words vs a machine version [B1.9].
   V21 A simple rule with a minimum [BEXIT]. V22 B show V4 to a few speakers
   [BEXIT]; V22a B skip the dark run, a few speakers now, then everyone,
   note "Cause there are no users" [BEXIT]; V22b not answered. V23 A leave
   Keep/Swap on [N23]. V24 A weekly, as lock C6 says [N24]. L1 A still at
   most 3 orange bars [B2.2]. L2 A the practice attempt that reached the
   bar [B2.2].
4. **The gap and clash questions (QG).** QG1 A one paperwork PR now [BG04,
   CA02, CA03, CA06, N25]. QG2 explain more simply [CA04] (follow-up QG2a
   open). QG3 A rewrite "V3 is the served policy" as decided [CA01, N29].
   QG4 B the golden set is the founder's picks alone, lock L6 [CA07, B1.8].
   QG5 A Claude drafts, founder signs [BG05, CA10]. QG6 A add a small dark
   check [BG10]. QG7 A no past-data estimate [BG01, BEXIT]. QG8 A add Take
   and speaker willfidence to 1.3 [BG03]. QG9 A coach re-picks 1 in 10 in
   1.8 [BG02, B1.8]. QG10 A D3 covers the sound question only [CA05].
   QG11 A write Phase 2 changes when each step starts [CA08, CA11]. QG12
   explain more simply [BG09] (follow-up QG12a open). QG13 A Album machine
   Yes stays today's sound read [BG06]. QG14 A both doors [CA12].
5. **The audit rows (QA, QB).** QA1 A answers can change [A018a]. QA2 not
   answered [A055b]. QA3 A praise gets its own switch [A045, A053b]. QA4 A
   follow lock B3 [A004a, A004b]. QA5 A keep Next only [A055a, A056c]. QA6
   A light the coach dot from today's answers, with the founder's design
   note [A014a]. QA7 B no dot on answered paragraphs [A014b]. QA8 B show old
   long phrases whole [A005]. QA9 A Practise again after Takes 1 and 2
   [A019a]. QA10 A show "done before" [A057]. QA11 and QA12 not answered
   [A050a, A060]. QA13 B wait for the designer session [A063b]. QA14 A
   reword the two audit questions [A072b, A092]. QA15 B drop the comparison
   [A042a]. QA16 B keep pre-6 Oct pairs out [A098b]. QA17 A accept
   #606/#607/#613/#615 [A021]. QA18 A stand-ins are fine [A003b]. QA19
   explain more simply [A003c]. QA20 A show coach-work numbers on the pace
   panel [A042b]. QA21 B leave old practice rows out of History [A058].
   QA22 A accept [A074a]. QA23 A accept [A018b]. QA24 A mark DONE-1
   replaced [A052a]. QB1 B others keep recording, with the founder's note on
   settling the architecture first [A192]. QB2 explain more simply [A163].
   QB3 A switch the training_corpus rule off until training starts [A126a].
   QB4 A remove the copy job [A123b, A124, N09]. QB5 A marking is enough
   [A217b]. QB6 A sound reads only [B1.6]. QB7 A any feedback, praise too,
   with the founder's note [B1.8]. QB8 A the reached bar splits above/below
   [B1.9]. QB12 A six years like consent proof [A214a]. QB13 A keep the
   walk as is [A230]. QB14 A fold gate 5 into the outside read [A118].
   QB15 A Claude drafts the DPIA, counsel reviews [A139]. QB16 A linking is
   enough [A180b]. QB17 explain more simply, with the founder's note that it
   is now willfidence, not confidence [A114]. QB18 A same project as today,
   with the founder's note [A151c]. QB19 B add the disagreement exercise to
   the designer's list [A151b, A169c]. QB20 A remove the two old routes
   [A187a, A187b]. QB21 A reword Privacy 4b [A225b]. QB22 B every Take
   [B2.3].
6. **The product rows (P).** P1 not answered [A025, A050a]. P2 A nothing
   goes to the coach [A175b]. P5 A remove the Replace PDF offer [A157].
   P9–P20 B none of the twelve praise and rewrite lines signed as written
   [A053a, A068a]. P21 A it is the signed after-practice list. P23 A accept
   [A185a]. P24 A keep the standard sentence. P25 B hide the two wrong
   lines. P26 explain more simply [A169a]. P28 B keep the machine read
   hidden from the coach [A151a]. P31 A answer by kind is enough [A181].
   P33 B wait for the re-landed v1.5 PDF [N21]. P34 A calendar year,
   Warsaw. P35 B exempt, remember "already paid" [N21]. P36 A the answer
   goes with the item [N21]. P37 A the job goes with the bundle [N21]. P38 A
   add paid project records now [N21]. P39 A remove the bundle's exercise
   panel [A093a]. P43 A confirm. P44 not answered. P46 A sign the jar
   fallback reason line. P50 A keep one name. P51 B and P52 B the founder
   writes the words [A077a, A077b]. P53 A a pair trains once [A107]. P54 not
   answered. P55 A counts are enough [A238b]. P57 A leave it [N04b].
7. **Paperwork landed with this entry (QG1 A, "one paperwork PR now").**
   SPEC D8, §7.2, D19, §9.1 and the lexical-dilution rule carry dated notes
   that the old rule still holds for the sound confidence read and that
   willfidence is a separate, internal measure; SPEC §17 gains the
   founder-signed written definition `willfidence-v1`, the WORDS qualities
   open under O3 (QG1 A; BG04, CA02, CA03, CA06, N25). J1 and J3 above carry
   the same note (CA02, CA06). SPEC D3 says it governs the sound confidence
   question only (QG10 A; CA05). "V3 is the served policy" is rewritten in
   the backend CLAUDE.md, `docs/willab_decision_filter.md`, contract 24, 24h
   and the clause 47 note: V3 is served today; V4, when built, replaces it
   for every speaker by the founder's switch (V22a B); a block V4 is very
   unsure of gets V3's pick, logged, never silent (V15a); the filter copy's
   stale V2 "exactly three items" text is brought up to date (QG3 A; CA01,
   N29). Coach-panel lock L6 notes that the golden set stays the founder's
   picks alone and coach picks are compared with them, which narrows the V4
   page's M9 and V18 (QG4 B; CA07). Contract 35g-2: no coach request for a
   clip the machine could not read (P2 A; A175b). Contract 34: the coach
   does not see the machine's read after submitting; the comparison happens
   off-screen, for analysis only (P28 B; A151a). Contract 36: the coach's
   answer by kind is the review history for rewrite and praise items (P31 A;
   A181). Contract 35j: the record is linked to the speaker's action and the
   coach's judgement (QB16 A; A180b). N19 above: the before/after comparison
   is dropped (QA15 B; A042a). Helper-words lock B3: phrases saved before
   the four-word limit show whole in Recording Mode (QA8 B; A005), and B3's
   tap-by-tap model stands with the 26 September two-tap rule retired
   (QA4 A; A004a, A004b). The frontend CLAUDE.md's filter copy is brought to
   the same text in its own PR.
8. **Not in this entry.** QG2 and SPEC D7 (still being decided, QG2a);
   DONE-1 and DONE-5 (the build plan is not in this repository); Privacy 4b
   and the DPIA (legal drafts, QB21 A and QB15 A); the retention schedule
   (re-lands with v1.5, P33 B); the Phase 2 texts (QG11 A: written when
   each step starts).
9. **The third export, 13:38 UTC** (verbatim in
   `docs/audit/PANEL-ANSWERS-2026-10-06-b.md`, "Third export"). V10b A a
   paragraph is placed by its place on the slide, the slide as backup.
   V22c B V4 alone: no V3 running silently beside it for comparison; the
   founder accepted that V4 cannot then be compared with V3 on the same
   Takes. This does not touch V15a above: a block V4 is very unsure of still
   gets V3's pick, logged. QG2a A yes, with a fair comparison (its SPEC D7
   text follows in its own change). QB2a B the speaker's own words to say
   again. QB7a B the mix follows what was heard. P9a A Claude redrafts the
   twelve praise and rewrite lines, short and in simple words with no slang;
   they wait on the founder's signature, one panel screen each (S1 to S12).
   QG12a A the one answer can flag a disagreement. P26a and QB17a: P26 was
   explained more simply (P26b, open); QB17a A leave it. P51a: the note
   arrived empty, so the line is asked again (P51b, open). P52a B keep the
   old label. P44a A keep clip picking as built. QN1 B rename confidence to
   willfidence (sound) everywhere, code too, with the founder's note
   "willfidence is words and sound; the sound is the sound of the
   willfidence"; how far into the database the rename goes is asked on
   QN1a (open). QA19a A a server test is enough. QB18a A the welcome shows
   as soon as the first moment enters. P54 A keep it by hand. These answers
   change no clause in this entry's paperwork; the work they call for is in
   the ledger.

**N52 · The Feedback walk is locked, communities will work, and the words
the founder wrote in the prototype are signed (founder, 6 October 2026, in
chat over prototype rounds 1 to 4).** The prototype is
<https://claude.ai/artifact/C2CTBmU1bfSSDQgJUHTKkE> (version 10); its
written record is `docs/FOUNDER-LOCK-feedback-walk-2026-10-06.md`, which
wins over older design locks where they disagree.
1. **The walk, its look and its motion are locked** ("the design we have
   now is good! it should be unified everywhere across the app"; "please
   lock in also the small interactions, the smoothing, how the screens
   change"). The panel closes R2b A (the speaker's words hidden beside
   the player, shown only on the clearer version), PR3 A (all praise
   first), R4d A (round 4 accepted) and R4e (the app's messages carry a
   grey profile picture like the coach's: "make it grey as it was").
2. **The order of the walk.** The coach's note for the Take, then all the
   praise (helper words right after each), then the practising (clearer
   version, exercise), then "Judgement time!", the judgements and
   sharing. Helper words before judging ("it makes no sense that helper
   words are after the judge them"). This amends helper-words lock B2
   and the judgement-first order of 24e-1; contract 24e and 29a are
   amended when the walk is built.
3. **The practise loop.** No self-judgement after a practise ("don't ask
   me right away does my last take sound confident to me, you need to
   check it yourself"): the machine compares each try with the moment.
   Praise ends the loop; otherwise the encouragement line and another
   try, until praise or Skip. Never a number on screen (AC-9). Whether
   the loop has a limit is CM3 (open).
4. **Communities will work** (founder, 6 October: "the community will be
   working"; first locked in round 4: "please lock it, it is very
   important feature!!!"). After every finished review the speaker is
   asked whether to share that Take; several choices may be ticked:
   the general community, only my community (with a pass code), or a
   community of their own (a name and a pass code); "None" stands alone.
   A shared Take is judged by the community chosen; with "None" only the
   coach judges it. When judging, the speaker hears their community's
   Takes first, then their own mixed with training clips. Consent is per
   Take, and taking it back removes the Take from every community queue.
   Community answers are peer ratings, a provenance of their own (L3),
   never coach labels, owner routing or training labels by themselves.
   Still open: CM1 (whose training clips may be played to others) and
   CM2 (now asked as: when the sharing goes live, given that the sharing
   screen's words need counsel's approval first).
5. **Words signed by the founder in this round** (written by the founder
   in chat; verbatim, punctuation as shown in the prototype):
   - "It was better, and I have yet another practice for you to try!"
     (the encouragement after a try that is not yet better; "keep this
     one", it never rotates).
   - "Judgement time!" · "If you are honest when judging others, it will
     help you find your confident voice and calm the inner critic 😌" ·
     "More about self-modeling theory" (grey link to a Journal post, not
     to the PDF: "don't use the PDF anywhere") · "I am going to judge them
     honestly" · "Skip".
   - "Here is a slightly more polished option:" · "Do you accept and want
     to practise it?" (the clearer version, with the changed words crossed
     out and the new words in orange).
   - "Practise" on the exercise video's button.
   - "After all, it's about speaking publicly!" · "Do you agree to share
     this take with others?"
   Every other word on the walk's screens is already in the signed copy
   (`CHUNK_SHEET_COPY`, N48.3 Q8 and Q9).
6. **Not yet signed.** The line bank B01 to B14 (praise and rewrite
   messages, three phrasings each, rotated, never the same twice in a
   row; one panel screen each); the community options' words (the
   founder's own, held for counsel because they ask for consent, and so
   never rotated); the Journal post on self-modeling (Dowrick, WIREs
   Cognitive Science, 2012), to be written and signed.

**N53 · The founder's answers of 6 October 2026, fourth export (19:28
UTC; Navigation Panel).** Verbatim, with the notes, in
`docs/audit/PANEL-ANSWERS-2026-10-06-c.md`; the ledger rows carry DECIDED
notes (A053a, A068a, A060, A077a, A169a).
1. **The line bank.** B11, B13 and B14 are signed as drafted. For B01,
   B05 to B10 and B12 the founder wrote a line of their own; in chat:
   "The examples I gave for a sign-off are just single examples. If you
   could create three more similar ones, similar vibe, I could sign off
   them too." Each goes back to the panel as the founder's line (speech-to-
   text tidied only, the change named on the screen) plus three more
   (B01b to B12b). B06's "all the delivery" is shown as "this part",
   because the line is about one moment, and B09's strong line is flagged
   against the rule that weak evidence uses gentle words; the founder
   decides both on the screen. B02 to B04 are not answered. Nothing from
   the bank ships until it is signed (N52.6).
2. **Communities.** CM1 A: only the voices of people who agreed to share
   reach others; the training clips mixed into judging are the licensed
   corpus (0410, F4), never a speaker's training-corpus clip. CM2 B: build
   now and switch on at once, against Claude's pick, with the risk stated
   on the screen ("people's voices reach others under words counsel has
   not checked, in the EU"); sharing switches on with the sharing screen,
   under the founder's own words for it, without waiting for counsel. The
   consent stays per Take and revocable, and is stamped with the version
   of the words the speaker saw. CM3 A with the note "Up to 3": asked again
   (CM3a).
3. **The walk's screens.** NX1 A: this session builds the walk's screens
   and their motion from the locked prototype, nothing added, each screen
   shown in the panel's Done list with pictures before it goes live. This
   amends the frontend design lock's "a designer's session builds these
   screens" for the walk. NX2 B: one grey picture for the coach and the app;
   no photos. NX3 A: "It was better, and I have yet another practice for you
   to try!" only when something moved between tries; the line for a try
   where nothing moved goes to signature (NX3a).
4. **Everything else.** D4: skipped for now; it waits for a live prototype
   of the coach panel (A060 parked). JP1 A: the Journal post on
   self-modeling is signed as drafted. P51b A: the errors page reads
   "Coaches heard it on {n} of {bar} checked moments." (A077a). P26b A:
   the coach is asked to listen again in their usual work list; the words
   say neither why nor what the speaker answered, so the coach stays blind
   (P26c, to sign) (A169a). QN1a A: docs and code are renamed to
   willfidence (sound); database names stay.

**N54 · The line bank is signed, and the walk's open questions (founder,
6 October 2026, fifth export, 20:03 UTC).** Verbatim in
`docs/audit/PANEL-ANSWERS-2026-10-06-d.md`; every signed line is in
`docs/SIGNED-line-bank-2026-10-06.md`, which is the only source the code
may read them from.
1. **The line bank.** On the founder's request ("for each you should
   create 4"), four new lines per screen went to the panel beside the
   founder's own. All fourteen screens are now signed: B01b with the
   founder's later line ("This sounded more confident than on Take {n}"),
   B05b with the founder's wording for two of its lines, the rest as
   drafted; B11, B13 and B14 gain four lines each. B10's last line and
   B14's fifth are noted as the founder's favourites. The line after a try
   where nothing moved is signed (NX3a, four lines); the founder's
   "It was better, …" shows only when something moved (NX3 A). The coach's
   listen-again words are signed (P26c, three lines, blind by wording).
2. **The practise loop has a limit: up to three tries** (CM3a A). After the
   third try that is not praise the app thanks the speaker and moves on to
   "Judgement time!"; Skip still works at any time. Its lines are on the
   panel to sign (CM3b). This amends lock D2 (no attempt cap) for the walk.
3. **The walk's open questions.** WQ1 A: Skip on "Judgement time!" finishes
   the walk; the moments' bars clear and nothing asks again (a paragraph
   can still be opened and judged later). WQ2 B: "Your coach is working on
   your exercise." is not shown in the walk; the moment waits silently
   (amends N48.3 Q10 for the walk). WQ3 A: with personalised practice off,
   a clearer version offers one word to accept it (to sign, WQ3b) and
   "Keep my words", no practise. The founder's note "But it should not be
   turned off ever" is asked back (WQ3a): the switch is a consent choice
   that the law requires to stay withdrawable, so removing it means making
   practise part of the service, a Privacy and Terms change. WQ4 A: the
   answer toast is the answer with a tick. WQ5 A and WQ6 A: the sharing
   screen's choices and its four messages are signed (CM2 B: they go live
   with the screen).

**N55 · Practise becomes part of the service (founder, 6 October 2026,
sixth export, 20:11 UTC).** WQ3a B, against Claude's pick: personalised
practice stops being a consent choice the speaker can switch off and
becomes part of what people sign up for. Today it is the consent choice
`personalised_practice`, withdrawable at any time; a consent cannot be
made permanent, so the change is a change of legal basis: Claude drafts
the Privacy Policy and Terms change, counsel reviews it, and only then
does the switch leave Settings and the code stop asking
(`consent_choice_required("personalised_practice")`). Until then nothing
changes in the app. CM3b A: the four lines after the third try that is
not praise are signed (`docs/SIGNED-line-bank-2026-10-06.md`). WQ3b A
arrived without a letter; asked again: WQ3c A, the button says "Accept"
(seventh export, 20:14 UTC).
