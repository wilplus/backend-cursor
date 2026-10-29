# Decisions log

> **Label: In force** · one of the rules, read in N95's order. Every doc and its label: [`README.md`](../README.md) (N106).

**What this is:** the founder's dated decisions, newest last. It is the first of the rules (N95):
where any other doc or the code disagrees with an entry, the entry wins, and the rules pages it
names are changed to match. An entry is not rewritten; a later entry says what it replaces.
SPEC.md is Reference and is no longer where entries get folded (N95, N106).

**Known gaps in the numbering** (docs audit, 2026-10-26): N78 and N91 are cited (N77 and N103 cite
N78; N122 and the walk's page cite N91) but were never written as entries. N70 appears
twice (N70 and N70.1). N92 comes before N90, and N168 before N166. N127 and N144 both name
migration 0491; the manifest gives 0491 to N144's WhatsApp number on bookings.

**Known overlaps between entries** (docs audit, 2026-10-26): N130 says the pace practice
"never grades" and is never red; N142, later, sets the pace scale red in the last 0.08 at each
end (no number, so Never 1 holds). The rules pages follow N142: the walk's page, §1 T, and
SPEC.md §17 `pace-scale-v1`.

**From 2026-10-20, the Feedback walk and the chat have one page** (frontend
[`docs/flows/feedback-walk-and-chat.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/feedback-walk-and-chat.md), <https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/feedback-walk-and-chat.md>), where their rules are
edited in place. A decision about that flow keeps its N-number here as two lines
and a link to the page; the full text lives once, there.

## 2026-09-22 · Article 50(2) and the plain-text clipboard — SETTLED

**Founder decision, 2026-09-22: do not go further than the obligation
requires. The `text/plain` clipboard flavour carries no marker line.**

This closes the open item recorded in
`legal/phase1-2026.1/03-article-50-assessment-v1.0` §3, where the written
assessment and [`docs/AI-CONTENT-MARKING-PROPOSAL.md`](AI-CONTENT-MARKING-PROPOSAL.md) §3 disagreed and the
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

**Supersedes** the recommendation in [`AI-CONTENT-MARKING-PROPOSAL.md`](AI-CONTENT-MARKING-PROPOSAL.md) §3
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

*J4 to J6 are replaced by K below (founder 2026-08-25): "Not sure" never settles, and only two matching Yes, In-between or No answers settle a clip. What this did to v1 `neutral` rows is open in [`docs/LEARNING-AND-QUORUM.md`](LEARNING-AND-QUORUM.md) §3 C1.*

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
[`docs/SPEC-training-corpus-and-project-purge.md`](SPEC-training-corpus-and-project-purge.md).

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
   approves. Draft: [`legal/phase1-2026.1/10-training-policy-changes-DRAFT.md`](../legal/phase1-2026.1/10-training-policy-changes-DRAFT.md).
6. **Retention schedule:** engineering prepares v1.1 with the training-copies
   and consent-record rows, counsel checks, the founder signs. Draft:
   [`legal/phase1-2026.1/11-retention-schedule-v1.1-training-DRAFT.md`](../legal/phase1-2026.1/11-retention-schedule-v1.1-training-DRAFT.md).
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
   [`legal/phase1-2026.1/10-training-policy-changes-DRAFT.md`](../legal/phase1-2026.1/10-training-policy-changes-DRAFT.md) for counsel.
   Training itself stays off until P5.
3. **The Data & consent intro, approved wording:** "Your recordings are used to
   run your own coaching. They are used to train models only if you turn on
   Help improve WillpowerLab." It is shown only while the switch is offered;
   until then the current wording stays, because it is still true.
4. **The dead commit codes in [`legal/phase1-2026.1/SIGNED-ARTIFACTS.md`](../legal/phase1-2026.1/SIGNED-ARTIFACTS.md):**
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
   [`SIGNED-ARTIFACTS.md`](../legal/phase1-2026.1/SIGNED-ARTIFACTS.md) row 06 and seeds its four rules. Until the founder
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
[`legal/phase1-2026.1/13-training-consent-wording-SIGNED-2026-10-01.md`](../legal/phase1-2026.1/13-training-consent-wording-SIGNED-2026-10-01.md));
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
   [`SIGNED-ARTIFACTS.md`](../legal/phase1-2026.1/SIGNED-ARTIFACTS.md) row 13 and the registration SQL in
   [`docs/LEARNING-DOORS.md`](LEARNING-DOORS.md).
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
[`legal/phase1-2026.1/15-coach-blind-check-privacy-line-and-balancing-test-SIGNED-2026-10-02.md`](../legal/phase1-2026.1/15-coach-blind-check-privacy-line-and-balancing-test-SIGNED-2026-10-02.md)
§1 and [`legal/phase1-2026.1/16-share-switch-wording-SIGNED-2026-10-02.md`](../legal/phase1-2026.1/16-share-switch-wording-SIGNED-2026-10-02.md) §1,
document 02 v1.1, the delayed-measure definition
([`docs/MEASURE-exercise-human-delayed-v1.md`](MEASURE-exercise-human-delayed-v1.md)), and said counsel has answered
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
   ([`legal/phase1-2026.1/SIGNED-ARTIFACTS.md`](../legal/phase1-2026.1/SIGNED-ARTIFACTS.md), pending rows). Its condition is
   engaged (N23): counsel's confirmation is the next action.
3. **Retention schedule v1.2**
   ([`legal/phase1-2026.1/18-retention-schedule-v1.2-blind-check-and-lending-DRAFT.md`](../legal/phase1-2026.1/18-retention-schedule-v1.2-blind-check-and-lending-DRAFT.md)):
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
   nothing else; hashes in [`legal/phase1-2026.1/SIGNED-ARTIFACTS.md`](../legal/phase1-2026.1/SIGNED-ARTIFACTS.md) and in
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
   ([`legal/phase1-2026.1/20-retention-schedule-v1.4-product-records-and-job-evidence-DRAFT.md`](../legal/phase1-2026.1/20-retention-schedule-v1.4-product-records-and-job-evidence-DRAFT.md))
   and document 03 v1.1 ([`03-article-50-assessment-v1.1-DRAFT.md`](../legal/phase1-2026.1/03-article-50-assessment-v1.1-DRAFT.md)) were
   signed 2026-10-05 20:05 UTC (D1 A, D2 A on the Wave 3 sign-off page,
   N50; hashes in [`SIGNED-ARTIFACTS.md`](../legal/phase1-2026.1/SIGNED-ARTIFACTS.md)), and the counsel brief is written
   ([`21-counsel-questions-2026-10.md`](../legal/phase1-2026.1/21-counsel-questions-2026-10.md), document 02's condition first).
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
founder's notes, in [`docs/audit/PANEL-ANSWERS-2026-10-06.md`](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/audit/PANEL-ANSWERS-2026-10-06.md) and
[`docs/audit/PANEL-ANSWERS-2026-10-06-b.md`](audit/PANEL-ANSWERS-2026-10-06-b.md), and the rows they decide are in
[`docs/audit/LEDGER.md`](audit/LEDGER.md), all three on branch `claude/audit-ledger`. Each answer
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
   the backend CLAUDE.md, [`docs/willab_decision_filter.md`](willab_decision_filter.md), contract 24, 24h
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
   [`docs/audit/PANEL-ANSWERS-2026-10-06-b.md`](audit/PANEL-ANSWERS-2026-10-06-b.md), "Third export"). V10b A a
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
written record is [`docs/FOUNDER-LOCK-feedback-walk-2026-10-06.md`](FOUNDER-LOCK-feedback-walk-2026-10-06.md), which
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
[`docs/audit/PANEL-ANSWERS-2026-10-06-c.md`](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/audit/PANEL-ANSWERS-2026-10-06-c.md); the ledger rows carry DECIDED
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
[`docs/audit/PANEL-ANSWERS-2026-10-06-d.md`](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/audit/PANEL-ANSWERS-2026-10-06-d.md); every signed line is in
[`docs/SIGNED-line-bank-2026-10-06.md`](SIGNED-line-bank-2026-10-06.md), which is the only source the code
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
not praise are signed ([`docs/SIGNED-line-bank-2026-10-06.md`](SIGNED-line-bank-2026-10-06.md)). WQ3b A
arrived without a letter; asked again: WQ3c A, the button says "Accept"
(seventh export, 20:14 UTC).

**N56 · The coach panel redrawn; the training corpus switched on
(founder, 6 October 2026, chat 20:37 to 21:44 UTC and the panel export of
21:46 UTC).** The founder corrected the coach panel screen by screen on a
clickable prototype of today's panel and then on its redesign; the layout
is agreed ("rest looks ok") and locked in
[`docs/FOUNDER-LOCK-coach-panel-redesign-2026-10-06.md`](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/FOUNDER-LOCK-coach-panel-redesign-2026-10-06.md).

1. **One action per screen; diagnosis before cure** (chat). An error
   moment asks "What kind of error is it?" (what the machine heard marked;
   "Something else" names a new error; "I don't hear an error" makes a
   note) before "Choose exercise", which offers only exercises for that
   error. The coach's words are shown where the speaker will see them,
   editable with a pencil. The queue lists speakers; the Lounge pins
   Speakers and Training corpus. Choice cards shade by position.
2. **CP2 A: the new words are signed** as listed in the lock.
3. **CP3 A: the exercise library and the speaking errors page move to the
   founder's admin area**, next to the pace panel; they leave the coach's
   app.
4. **CO1 A: the training corpus is switched on and built properly.** This
   is the separate authorization CLAUDE.md requires for the Phase-2
   corpus path, scoped to: the coach-only import of audio the founder has
   the rights to; the same confident-moment spotting a Take gets (V3
   blocks of about 75 words, the machine's pick per block, stored and
   never shown so coaches judge blind); a split of the corpus labels by
   speaker ("Whose voice this is"; an import without a speaker name is a
   speaker of its own), 80% to learn from and 20% held out for testing,
   decided by a fixed hash and never re-shuffled; tests over the whole
   path. **Nothing trains on the labels** until the founder says so: the
   dataset, training, evaluation and promotion paths stay off.
5. **The speaker side: a paragraph without a bookmark does not open on
   tap** (chat, 20:37 UTC), amending B7.
6. **JP2 A: the Journal post was never saved** in the editor; Claude checks
   the editor's save and sends shorter steps.


**N57 · The coach panel's design is locked (founder, chat, 7 October
2026).** "Generally you can lock the design of the coach panel, it's
done; lock it just like you locked the ideal text design." The coach panel
prototype (<https://claude.ai/artifact/TEBvGMehRF6wXCvJTEYTUA>, copy in
`docs/design/coach-panel-redesign-2026-10-06.html`) is now the design every
coach screen is built to, exactly as the Ideal Text Final Screens are for
the speaker's: no layout, flow or wording change and no added element
without the founder. The frontend's CLAUDE.md carries the rule
("Design lock — the coach panel"); [`docs/FOUNDER-LOCK-coach-panel-redesign-2026-10-06.md`](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/FOUNDER-LOCK-coach-panel-redesign-2026-10-06.md)
stays the written record. The panel's training-corpus questions CO2 and
CO3 are open and do not change the screens.

**N58 · Corpus imports are processed under one founder basis, and an
importer's judgement counts (founder, Navigation Panel export, 7 October
2026, 08:14 UTC).**
1. **CO2: no per-import licence record; one corpus processing basis.** The
   founder's note is the answer, verbatim: "no need for license check pls;
   we have it legally recorded and we don't need license to prove it! this
   version is agreed with the counsel and it is my executive decision". An
   executive decision, agreed with counsel. A training-corpus import
   (`source='training_import'`, created by a coach through
   `POST /v2/coach/training-imports` while `Config.TRAINING_IMPORT_ENABLED`)
   may be analysed (Whisper and the rest) under
   `PLF1_PROCESSING_AUTHORIZATION_MODE=enforce` on the strength of ONE
   durable basis the founder recorded (`corpus_processing_bases`, decision
   N58, 2026-10-07, "legal basis recorded by the founder, agreed with
   counsel"; migration 0435), never a user's consent and never the
   importing coach's own acceptance. It sits inside the canonical
   authorization path: the same provider adapter and permit scope, with
   its own database permit writer (`issue_corpus_provider_permit_v1`) and
   ledger beside the Phase-1 one; every permit names the basis (id and
   N58) and the session. A permit is refused when the switch is off, the
   session is not a training import, the import route did not register it,
   the session has an owner or a project, its recording was acquired
   through the Phase-1 intake, or no basis is in force. No ordinary Take,
   guest Take or user recording can ever be authorized by the corpus basis
   (the B-2 hole closed by 0355 stays closed), and the other way round the
   Phase-1 permit writer now refuses a corpus import under any principal,
   the importing coach's included (its one added check; the rest of 0355
   is unchanged, as is the resolver). Phase 2 stays closed: dataset release,
   training, evaluation and promotion are untouched; nothing trains.
2. **CO3 A: a coach's blind judgement on a clip they imported counts like
   any other coach's.** An import's `user_id` is the corpus row's owner,
   the importing coach by default, never the voice on the clip, so their
   label is not a self-report and counts toward quorum
   (`label_quorum.rating_is_self_report`). "A coach still can't judge their
   own voice anywhere": a coach or user rating their own Take is still a
   self-report, unchanged.

**N59 · The recording screens' design is locked (founder, chat, 7 October
2026).** "Lock the recording screens." The recording screen prototype
(<https://claude.ai/artifact/9CFAAP2Ue7pvRdLvdesn9h>, version 6, copy in
`docs/design/recording-screens-2026-10-07.html`) is now the design the
speaker's recording screens are built to, exactly as the Ideal Text Final
Screens and the coach panel are for theirs: the first recording's learning
screen ("Scroll down to start"; on a desktop "Click down to start"), "Take
N · Slide n of m" in the top bar, only the slide and its helper words
moving under a still frame, calmer gestures that land softly, the keyboard
without a click, and never a reload from a scroll to the top. The words new
with it are locked with the screens. The frontend's CLAUDE.md carries the
rule ("Design lock — the recording screens");
[`docs/FOUNDER-LOCK-recording-screens-2026-10-07.md`](FOUNDER-LOCK-recording-screens-2026-10-07.md) is the written record.
It wins over the Ideal Text lock's line on Recording Mode for these screens.

**N60 · The consent screens' design is locked (founder, chat, 7 October
2026).** "The consent screens are great; but right now they are not
scrollable like that in the real app; so lock it like that." The consent
screens prototype (<https://claude.ai/artifact/TuMKSE2BH364ZQ1Eq4UMdd>,
version 2, copy in `docs/design/consent-screens-2026-10-07.html`) is now the
design the first-time agreement, the Data & consent page and the "Turn on
the learning?" question are built to. Every step scrolls from its true top;
a document's title and buttons stay still while its text scrolls. One word
change, signed in the same message: "Two things to confirm" becomes "Three
things to confirm". The frontend's CLAUDE.md carries the rule ("Design lock
— the consent screens"); [`docs/FOUNDER-LOCK-consent-screens-2026-10-07.md`](FOUNDER-LOCK-consent-screens-2026-10-07.md)
is the written record.
Amended the same day (ST1 A): the Data & consent page follows the settings
page prototype (<https://claude.ai/artifact/4jDJsvBAquMUgaGkJgHR76>, copy in
`docs/design/settings-page-2026-10-07.html`): a Support card with
contact@willpowerlab.com, Back from Privacy and Terms returns to it, the menu
loses Support and Community and marks the current page. "Support" and "Back"
are signed.

**N61 · A training yes counts the acceptance the account is processed under
(founder's bug report, chat, 7 October 2026).** "Couldn't save that. Try
again." on Help improve WillpowerLab, every time. The yes is recorded under
the account, but its receipt check (0373 C1, 0412) read the account only,
while the account's processing is authorised by the principal
resolve_phase1_acquisition_principal_v1 returns: a guest claimed into the
account at sign-in, after the current Terms were accepted as a first-time
visitor. Migration 0436 lets C1 accept a receipt held by the account or by
that resolved principal; nothing else changes, and no one else's acceptance
can count. Ships after a GPT check (HO-14).

**N62 · The build plan's questions are answered, and Wave 1 starts
(founder, Navigation Panel, 7 October 2026, 16:36 UTC).** The audit of
every agreed design against `main` ([`docs/audit/build/BUILD-PLAN-2026-10-07.md`](audit/build/BUILD-PLAN-2026-10-07.md))
asked 15 questions; the founder answered 11, all with Claude's pick, and
gave Wave 1 its green light (GO-W1 A: "I start now, merge each PR when it's
green, and post every finished piece in Done").

- **Q-B1 A.** The machine may use its private willfidence read (sound times
  words) to rank which moment gets feedback, inside the machine only; no
  number ever reaches a screen (AC-9). Before V4 ranks with it, Claude writes
  a one-line operational definition of each of the four word signals and the
  list of moment roles for the founder's signature (CONSTRUCT). This settles
  the clash with SPEC §17's "never a ranking term" for this internal use.
- **Q-B2 A.** With several slides the Feedback walk spans the whole Take: all
  praise from every slide, then all the practising, then one "Judgement
  time!" for every moment. The top bar names each moment's slide.
- **Q-B4 A.** Every word a locked prototype shows is signed with its design.
  Where a signed list differs, the list wins ("Choose a file"); signed words
  with no place are not used. "Journal" shows above the post in the walk, and
  "Getting your mic ready" becomes visible text.
- **Q-B6 A.** Skip on "Judgement time!" clears the bars and still asks to
  share, then the end card (amends WQ1 A). Sharing names the current
  Privacy/Terms, and each share records the words the speaker saw. A
  "Sharing" row in the ⋯ menu reopens the same screen; "None" takes the
  share back. "None" needs the founder's signature before it ships.
- **Q-B7 A.** An error a coach names in one field is stored as "named by a
  coach" until the founder writes its definition and question in admin. The
  exercise reaches the speaker now and waits in the library. The coach's
  list shows every active error plus coach-named ones. Naming is a signal for
  the founder only; readiness for a detector still comes from blind "Do you
  hear it?" answers.
- **Q-B8 A.** V4's two blind coach questions ("Pick the moment for feedback",
  "Which sounds surer") go under "Also waiting · blind" on the coach panel,
  in its look; "listen again" arrives as a normal moment in that speaker's
  queue with its signed line. A clickable prototype goes to the founder to
  sign first (amends the coach panel lock once signed).
- **Q-B11 A.** At most 3 other voices per walk, community first, then
  training clips, on the same judgement screen without the slide bar. Lend
  your ear's engine serves them under the per-Take consent only. The Album
  share switch and Bold voices are retired.
- **Q-B12 A.** When a coach changes an answer the speaker already has, the
  new answer replaces the card; the old one stays in history for audit.
- **Q-B13 A.** A clearer version never goes to the exercise library; its kind
  only labels the coach's work, and the screen shows "Share with {p}" alone.
  A note goes straight to "Ready for {p}" (closes D4).
- **Q-B15 A.** The twelve smaller choices apply as listed in the plan: the
  picker notes ("These words show while you record your next take"; "These
  replace your Take N words. Those stay in Earlier Takes." with the real
  Take number), the library video when a coach has none, B10–B12 not shown
  for now, the "done before" mark dropped (amends QA10 A), the Lounge's Take
  3 message loses its last sentence, corpus hide/delete/restore move to
  admin, "Do you hear it?" stays on, single-project delete stays off,
  "What's changed since you agreed" stays as signed, "No projects yet." for
  an empty list, a refused "Turn on" keeps today's words with the reason
  logged, and the Personalised practice tick goes only after counsel clears
  N55 and the founder signs the changed prototype. "No projects yet." and
  the Take N note are signed by this answer.

Still open: Q-B3, Q-B5, Q-B9, Q-B10 and Q-B14, which go to the founder with
a clickable side-by-side prototype.

**N63 · The last five build-plan questions are answered, and Wave 3 is
unblocked (founder, Navigation Panel, 7 October 2026, 20:09 UTC).** The
founder answered the five questions N62 left open, each with Claude's pick,
after the side-by-side prototype
(<https://claude.ai/artifact/PnCmGJaKDper6SgTiw3rpY>). All 15 of the build
plan's questions are now answered.

- **Q-B3 A.** When the walk goes live, tapping a paragraph with an open
  moment opens the walk at that moment. An answered or saved paragraph opens
  "This paragraph" or "Helper words saved", redrawn in the walk's look and
  keeping History and Edit. Neither screen is retired (unblocks D-FW-14,
  D-IT-6).
- **Q-B5 A.** Tap-by-tap picking keeps one connected phrase: each tap adds a
  word next to the others, up to four (B3), saved and shown in italics
  exactly as today. Both pickers follow this one rule; the server's single
  phrase and the single italic run stay as they are (unblocks D-IT-5,
  D-IT-11, D-FW-14).
- **Q-B9 A.** The walk's orange rule (orange marks only new words and the
  Lounge's "new" tag) applies inside the walk only. Outside it the bars, the
  helper-word headlines (page, Presentation Mode, export, Recording Mode) and
  the coach panel's "Something else" stay orange (unblocks D-IT-10, D-OP-3).
- **Q-B10 A.** After the walk the text page keeps the 30 Sep bars: only open
  moments, green or orange by the machine's read (B7). The bottom is
  "● Record Take N" with a "Review feedback" link under it, as the walk
  prototype draws; "See next steps" is removed (unblocks D-IT-8).
- **Q-B14 A.** The five small look choices apply as listed: (1) the app's one
  small grey close X everywhere; (2) Presentation Mode dark, as in its
  frame, with no slide dots; (3) a soft 0.4-second fade into and out of the
  white Recording Mode screens; (4) the coach panel on a computer uses the
  same phone-width screens, centred; (5) the Support card shows
  contact@willpowerlab.com as plain text with a copy button and no mail
  link. Each screen is shown to the founder in the panel's Done list before
  it goes live (unblocks D-RC-6, D-RC-7, D-IT-9, D-FW-21, D-CP-23, D-CS-7,
  D-OP-3).

Nothing is left open. Wave 3 (the Feedback walk behind its switch) can start
once Wave 1 closes; Wave 2 still owes the founder three signatures first
(the four word-signal definitions and moment roles, Q-B1; the V4 coach-sheets
prototype, Q-B8; the "None" word, Q-B6).

**N64 · The contract and the locks catch up with the walk, the coach
panel and N63 (build plan D-OP-3, D-CP-1, D-RC-6; 7 October 2026).** No
new decision: the answers already given are written where the code reads
its rules from.
- Contract 24e, 24e-1 and 29a carry dated amendments for the Feedback
  walk (N52.2, N54.2, N55 CM3b A): inside the walk helper words follow a
  praise or a practise the machine reads as praise, the judgements come
  under "Judgement time!", and the machine checks each try, up to three.
  Outside the walk and until its switch they are served as written.
- Helper-words lock B2 and D2 carry the same dated notes.
- Contract 35g-2a carries the coach panel's amendments (N56, N57; Q-B7 A,
  Q-B12 A, Q-B13 A): naming on the moment returns as a signal only, a coach
  may change an answer with every earlier answer kept, and a clearer
  version never goes to the library.
- The walk lock's "orange only" line applies inside the walk (Q-B9 A); its
  Recording Mode fade is a soft 0.4 s fade into the white screens
  (Q-B14 A); its "Still open" list now names what was settled and leaves
  only "None" (S-B6).
- The recording lock records the one close button and the fade (Q-B14 A).
  N59 named the prototype's version 6; the lock is version 7, as the
  frontend's CLAUDE.md and the lock file already say.
- [`docs/COACH-PANEL-BUILD-PLAN-P2-P7.md`](COACH-PANEL-BUILD-PLAN-P2-P7.md) maps the coach panel rebuild to
  steps, screens and endpoints.

**N65 · Wave 2's signatures are given, and V4 may measure every
speaker (founder, Navigation Panel, 7 October 2026, 21:04 UTC).** The
founder signed the five Wave 2 items, each with Claude's pick, and
confirmed again the five N63 answers (Q-B3, Q-B5, Q-B9, Q-B10, Q-B14 A).
- **S-B1 A.** The four word signals inside V4's private read
  (willfidence-v1) are signed as written. Each runs on one moment of about
  75 words, gives a value from 0 to 1 and never reaches a screen (AC-9):
  - *Filler*: how free the moment is of filler words. The share of its
    words that are unambiguous fillers (um, uh, erm, basically, literally),
    turned into 0 to 1 on the stricter scale (V5 B), so a few fillers
    already lower it. "So", "like" and "right" never count.
  - *Hedging*: how directly the speaker commits to what they say. The
    share of its words that are unambiguous hedges that lower certainty
    (sort of, I think, maybe, probably, perhaps), turned into 0 to 1 the
    same way. Modal words like "might" or "could" never count.
  - *Slide fit*: whether the moment says what its slide is about. 1 if it
    fully makes at least one of the slide's points, 0.5 if it partly does,
    0 if it makes none, by the point-by-point check the app already runs.
  - *Holding together*: whether the moment's sentences follow on from each
    other as one line of thought. 1 yes, 0.5 partly, 0 no, read by one
    fixed, versioned instruction in the same single call per Take that
    tags the moment's role. New: nothing measures it today.
  The fifth, naturalness, comes to the founder separately.
- **S-B1b A.** The moment roles and their weights are stored as version 1:
  Opening 1.0 (the first moment, where the speaker wins attention); Main
  point 1.0 (states what the slide is there to say); Close 1.0 (the last
  moment, or the one that asks the audience to act); Evidence 0.7 (a
  number, story or example that backs a point); Transition 0.4 (moves from
  one point or slide to the next); Aside 0.2 (a side remark, housekeeping
  or a repeat). One call per Take tags each moment with exactly one role.
  A later change is version 2; older picks keep the version they used. The
  weights stay inside the machine.
- **S-B6 A.** "None" is signed for the sharing screen and the ⋯ menu's
  Sharing screen.
- **S-B8 A.** V4's two blind coach sheets are signed as the prototype
  shows them (<https://claude.ai/artifact/4keT4hRL73HGNeNVGH2VEt>), built
  behind the coach panel switch (D-ML-13, D-ML-14) and off until V4 is
  measuring.
- **S-V1 A.** V4's pick log is recorded for every speaker's Takes, not only
  the founder's: once GPT-0441 passes and 0441 merges, the dark-frame gate
  (`take_feedback_policy_v3.dark_enabled`) widens to every speaker in its
  own change with its own test, and V4 starts measuring. The frame stays
  internal (serves_user_feedback false, dataset_eligible false), is purged
  with the Take (`take_feedback_policy_v3_shadow_frames` in the purge
  registry) and never reaches a payload (AC-9). Config first:
  `TAKE_FEEDBACK_POLICY_V3_MODE=dark` on every service that runs the Take
  pipeline (V4 row B1.1b).

**N66 · The founder signs three held items (founder, chat, 8 October
2026: "I sign off on it all!").**
1. **The training corpus admin page's words are signed.** Every word on the
   frontend's `/admin/corpus` page ("Hide", "Restore", "Nothing imported
   yet." and the rest) is signed copy. Nothing may keep that page hidden
   for want of signed words; it stays behind the coach panel switch
   (`NEXT_PUBLIC_COACH_PANEL_V2`), which is on in production.
2. **Practise becomes part of the service: the founder signs the Privacy
   and Terms change in place of counsel (N55, WQ3a B).** Counsel's review
   of the wording was not obtained; the founder's signature stands in for
   it, and the record says so. No draft existed when this was signed, so
   Claude writes it, shows the founder the final text in chat, and it is
   published as the next policy version through the existing hand-run
   publish path only after he has read it. Activating that version is
   what asks every speaker to accept it again; until then nothing changes
   in the app. **Text signed** (chat, 8 October 2026): Privacy 3.4 and
   Terms 3.4 as shown, drafted from 3.3 with only the practice passages
   changed. Practice moves to Art 6(1)(b) and is no longer a separate
   choice; skipping any exercise stays free. The coach's blind accuracy
   check, whose only off switch was Personalised practice, now ends on a
   written objection to contact@willpowerlab.com. Terms 3.4 does not carry
   the unsigned packages rewrite of §2 (N44.4). Before publishing, the
   acceptance tick and the Settings card for practice must go (a changed
   consent prototype for the founder to sign), because the database
   refuses a tick for a purpose the policy makes required.
   **Published** (founder, Supabase SQL editor, 8 October 2026, 14:22
   UTC): `phase1-2026-10-08` (Privacy 3.4, Terms 3.4, effective 8 October
   2026) registered and activated by `scripts/phase1_policy_publish_3_4.sql`
   after migration 0454 (`practice_is_part_of_the_service.sql`, #956) was
   live. The verify step read all four signed passages and no placeholder.
   Every speaker is asked to accept 3.4; the acceptance screen and Data &
   consent follow the policy (frontend #660). A written objection to the
   blind check is recorded with `scripts/record_blind_check_objection.sql`.
   0454 had an independent review (GPT and Grok first pass; Grok re-check:
   no real blocker).
3. **The retention cleaner's first real deletion run (W3-B2).** First the
   dry run's counts, per table, are shown to the founder in chat; only
   after his second word ("go") does `RETENTION_CLEANER_LIVE` become True,
   in its own reviewed change, and the first live run's results are
   confirmed back to him. Deletion cannot be undone, so nothing is deleted
   before that second word.

**N67 · Sharing goes live in the Feedback walk (founder, 8 October 2026;
build plan D-FW-20).** The founder, in the build chat: "I want the sharing
built and switched on"; "you have my OK". CM2 had held the sharing screen's
consent words for counsel; CM2 B (N53.2) let sharing switch on with the
screen under the founder's own signed words (N54, WQ5 A, WQ6 A; "None"
S-B6 A, N65). This is the founder's decision: **counsel's review of the
sharing words was not obtained**, and the founder takes the risk stated on
the panel (people's voices reach others under words counsel has not
checked, in the EU).
- The walk asks to share after the judgements, and after Skip on
  "Judgement time!" (Q-B6 A), then shows the end card. The screen is the
  locked prototype's step 11 with the signed words of version
  `sharing-screen-2026-10-06`, which every share records
  (`take_shares.share_words_version`, 0443). "None" takes the share back.
  A share names the current Privacy/Terms (`COMMUNITY_SHARE_POLICY_VERSION`,
  phase1-2026-10-02; 409 TERMS_REACCEPT_REQUIRED before it).
- `COMMUNITIES_ENABLED` turns on. Community answers stay peer ratings, kept
  apart from the coach's, the speaker's own and the machine's (L3); nothing
  about anyone's voice reaches a screen as a number (AC-9).
- Not in this step: the "Sharing" row in the ⋯ menu (Q-B6 A), its own task.

**N68 · The 3.5 pack is signed: every learning pipe under the training yes
(founder, chat, 8 October 2026).** The founder, word for word: "I sign the
3.5 pack of 8 October 2026 as drafted: Privacy 3.5, Terms 3.5, the training
switch wording v2 with its eight lines, the retention rows, document 02
v1.2, and the DPIA and ROPA addenda, with D1 to D4 as drafted, knowing
counsel has not seen them." **Counsel's review was not obtained**; the
founder signs in its place and the record says so on every file.
- **Signed, as drafted** ([`legal/phase1-2026.1/SIGN-3.5-2026-10-08.md`](../legal/phase1-2026.1/SIGN-3.5-2026-10-08.md)):
  `copy/privacy-3.5.txt` and `copy/terms-3.5.txt` (exact bytes; effective
  date line "8 October 2026"), `22-…-SIGNED-2026-10-08.md` with D1 (the
  corpus copy copies no audio; the code's audio branch goes first), D2
  (passages from before the yes may be used), D3 (a training-only-v1 yes
  counts as off until given again) and D4 (the corpus import rests on Art
  6(1)(f)), `23-…-v2-SIGNED-2026-10-08.md` (the switch sentence, sha256
  `69d3e702…521083c`, and its eight lines), `24-…-SIGNED-2026-10-08.md`,
  document 02 v1.2 (the note, and its full text
  [`02-power-score-classification-v1.2-SIGNED-2026-10-08.md`](../legal/phase1-2026.1/02-power-score-classification-v1.2-SIGNED-2026-10-08.md)), and the DPIA
  and ROPA addenda (`docs/legal/*-ADDENDUM-2026-10-08-all-learning-SIGNED.md`).
- **Rendered for the PAdES signature** by `scripts/render_doc_pdf.py`: 23
  and 02 v1.2; their unsigned hashes are in [`SIGNED-ARTIFACTS.md`](../legal/phase1-2026.1/SIGNED-ARTIFACTS.md). The
  retention version that carries 24's rows is not yet assembled: v1.5 is
  reserved for N50 P1–P7 (reverted by #909, to re-land).
- **Signing published nothing and opened nothing.** Every lane still waits
  for its own switch PR after its E-item holds (22, §4).
- **Publication is blocked on one missing function.** v1 must be retired at
  the instant v2 starts (D3; `configure_mlc2_training_consent_policy_v1`
  refuses v2 while v1 is open, `ANOTHER_TRAINING_POLICY_IS_ACTIVE`), but
  `ml_consent_policies` is append-only (`reject_mlc2_immutable_mutation`,
  `migrations/add_mlc2_foundation.sql`) and no reviewed function retires a
  training policy, so 23's `UPDATE … SET retired_at` is refused in the SQL
  editor. A migration adding that function, reviewed, comes before the 3.5
  publish; Privacy 3.5 is not published before it, since its §4a "a yes
  given before 3.5 counts as off" is true only once v1 is retired.
- **The eight lines on the locked consent screen.** The sentence signs the
  words of all eight; the layout change to the locked prototype (four lines
  shown) is confirmed by the founder under the consent-screen lock before
  the frontend PR merges.

**N69 · Counsel answers the 3.5 pack's four open questions (founder, chat,
8 October 2026).** Relayed by the founder: (1) the training data is not
special-category data, so no Art 9 basis is needed and the database's
`article_9_treatment = 'not_applicable'` stands (Privacy 3.5's Art 9(2)(a)
mention is surplus, tidied at the next version); (2) a model fine-tuned on
speakers' text is anonymous, so it stays after a withdrawal; (3) the
regurgitation test checking only withdrawn speakers' text is enough, and the
memorisation rate does not gate door 4; (4) D4 confirmed: the corpus import
rests on Art 6(1)(f). No code changes. Counsel also confirmed question 7 (the
consent record kept six years after withdrawal or erasure) and question 1
(document 02's condition, including the learned detector, v1.2). Nothing
from the 3.5 pack's open list remains.
Recorded in `legal/phase1-2026.1/22-…-SIGNED-2026-10-08.md` §5. The
founder also gave the OpenAI data processing agreement's date: signed 18
September 2026 (recorded on [`SIGN-3.5-2026-10-08.md`](../legal/phase1-2026.1/SIGN-3.5-2026-10-08.md); a filed copy is still
to be recorded).

**N70 · The recording screens move by buttons, not scrolling (founder,
chat, 12 October 2026).** "We are resigning from the scrolling — it was not
practical." The founder approved, through three rounds of the clickable
prototype (<https://claude.ai/artifact/4zD6Tjw4MWjooqWq6z4FAL>, version 4,
copy in `docs/design/recording-screens-2026-10-12.html`), and said "that's
what i want; please lock it". It amends N59: two buttons under the strip,
**Back** and **Next slide**, in the coach panel's pair style; on the last
slide **Next slide** becomes a red **Finish take**, and the strip loses its
own Finish take, so a Take finishes only from the last slide (confirmed);
no slide dots; the slides move sideways (Next: in from the right; Back: in
from the left); a swipe or scroll never changes the slide; the Take 1
learning screen (**Scroll down to start**, **Click down to start**) is
deleted, so every Take opens on **Getting your mic ready**. "Back" and
"Next slide" are signed. [`docs/FOUNDER-LOCK-recording-screens-2026-10-07.md`](FOUNDER-LOCK-recording-screens-2026-10-07.md)
carries the amended lock; the frontend's [`docs/LOCKS.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/LOCKS.md) points to the new
prototype.

**N70.1 · The arrow keys on the recording screen (founder, chat, 12 October
2026).** "Let the left and right arrow keys move between slides on the
recording screen, without the keys stealing presses from buttons." ← and →
change the slide like Back and Next slide; a focused button keeps its own
Space and Enter. Asked what → and Space do on the last slide, the founder
chose "Nothing, small bounce": keys never end a Take, only the red Finish
take does. Prototype <https://claude.ai/artifact/LU1XgQyqY2nPSvDAmsRJFo>
(version 2), copy in `docs/design/recording-screens-2026-10-12-keys.html`.

**N71 · The AI version of your voice in practice (founder, chat, 12 October
2026).** In the voice Exercise only, the app plays the speaker's own sentence
in an AI version of their voice (ElevenLabs Instant Voice Clone, Eleven v4),
said a little better: pace, pause or stress, chosen by a new per-problem
severity (0–1, ≥ 0.4) against the speaker's baseline. The clip takes the
library video's place when no video fits exactly (D-rule: exact fit and the
same problem), and follows a try that is not yet better, at most 3 per
exercise. It is made only in that lane, once per exercise (D4), checked
before it is shown, words included (D7), never played by itself, and shows
audio only, labelled "AI version of your voice". The voice is made once from
Take 1 (A4; a noisy Take 1 waits for Take 2, D8). It is agreed by using the
app, in the Terms, on from the start (D3a, D3b, the founder's choice over a
separate tick); counsel reviews last, and until then it is on for the
founder's account only. Data & consent gets one card to delete it and turn
it back on. Words L1–L13 signed. Prototypes
<https://claude.ai/artifact/G8Am3fR3f3SzAdTkwyUGKZ> (v8) and
<https://claude.ai/artifact/1AUfoqBtZThxVbQKz1BTih> (v2); plan
<https://claude.ai/artifact/RYMPxAqSyHinRStymsGwFr>. Lock:
[`docs/FOUNDER-LOCK-ai-voice-practice-2026-10-12.md`](FOUNDER-LOCK-ai-voice-practice-2026-10-12.md).

**N72 · The 3.6 pack is signed: the new features described, training widened
to what speakers write to Will, the United States for California residents
(founder, chat, 15 October 2026).** The founder, word for word: "I sign the 3.6 pack of 15 October 2026 as drafted: Privacy 3.6, Terms 3.6, AI notice 3.2 and the training switch wording v3 with its nine lines, with D1 to D8 as drafted, and the United States (California only) added to the countries, knowing counsel has not seen them."
**Counsel's review was not obtained.**
- **Signed, as drafted:** [`legal/phase1-2026.1/25-privacy-terms-3.6-new-features-SIGNED-2026-10-15.md`](../legal/phase1-2026.1/25-privacy-terms-3.6-new-features-SIGNED-2026-10-15.md)
  (Privacy 3.6, Terms 3.6, AI notice 3.2; D1–D8) and
  [`26-training-consent-wording-v3-SIGNED-2026-10-15.md`](../legal/phase1-2026.1/26-training-consent-wording-v3-SIGNED-2026-10-15.md) (training-only-v3,
  nine lines). Training stays opt-in (founder, 14 October: "Keep opt-in,
  widen it"); `allowed_countries` gains `us`, California only (D8).
- **Signing published nothing.** 3.6 is published only after E1–E12 (25, §4),
  the PAdES signature of 26's PDF and the publish script.
- **The consent screens, same day.** The founder approved the frontend change
  under the consent-screen lock: "I approve the WIL-7, WIL-8 and WIL-9
  changes to the locked consent screens as built on 15 October 2026: the
  optional Help improve WillpowerLab tick as the third thing to confirm, Back
  on the confirm step, and the United States listed below Poland as "United
  States (California)"."
- **Two corrections, confirmed the same day** (25 §8): Meta's US transfers
  rest on the EU-US Data Privacy Framework (WhatsApp Business Data Transfer
  Addendum, 16 February 2024), and a coach's video answers are kept while
  the account is open, outside training. The founder: "I confirm both
  Privacy 3.6 corrections: the transfer lines in section 6 and the coach
  videos in section 7."

**N73 · The consent screens, shortened (founder, chat, 15 October 2026).**
Approved on the clickable prototype (<https://claude.ai/artifact/YCM8rQKkkwA2HKb4UYajeo>): "this looks perfect".
- **Training:** "Can we make the product so much better for you?" / "We'd
  train our feedback on your practice. Read more" / "Yes, make it so much
  better." on every screen that asks; Read more opens Privacy §4a. Training
  wording v4 (`legal/phase1-2026.1/27-…`) supersedes v3, never registered.
  "Your practice" is defined in Terms 3.6 §8 (founder: "it should be defined
  in the terms").
- **Sensitive information:** "I agree that WillpowerLab may process my
  recordings." Required ticks carry *, the training tick does not; no
  "Optional" label.
- **Removed at the founder's request:** the withdrawal line and footnote,
  "Never your voice", Back on the confirm step (WIL-9 keeps Back on the
  documents and the country step).
- **Documents:** open in their own window on a computer; "Done reading"
  becomes "Continue".
- **Risks recorded for counsel** (27, "Risks the founder accepted"; 25 §9):
  no withdrawal notice where consent is given (Art 7(3)); the sensitive tick
  no longer names sensitive information (Art 9(2)(a)); scope carried by a
  defined term.
- **Will's conversation is not training data** (founder, same day: "the
  conversational chat is all private"). Taken out of Privacy 3.6 §4a and §7
  and the Terms 3.6 §8 definition and licence; the 3.6 texts say it is never
  used for training.
- **Will's conversation is private** (founder, same day: "not more than any
  other LLM out there"). The marking of feedback messages and the admin
  route `GET /v2/admin/speaker-feedback` are removed; Privacy 3.6 §4 says
  nobody reads the conversation except for safety, the law, or the
  speaker's own request.
- **Approved** (founder, same day): "I approve training wording V4 and the
  privacy in terms 3.6 changes of 15 October." ElevenLabs has not answered
  the controller request; the founder proceeds without it (25 §10).
  `legal/phase1-2026.1/PUBLISH-3.6-2026-10-15.sql` is ready, dry-run on a
  disposable database; it waits for the signed PDF of 27.
- **Published** (founder, 15 October 2026, 08:42 UTC): `PUBLISH-3.6-2026-10-15.sql`
  run in Supabase after the founder's own 25 v2 training copies were erased
  (the supersede refuses while a predecessor yes has copies). 3.6 and
  training-only-v4 are in force.

**N74 · Privacy 3.7: Will reads the whole talk (founder, chat, 15 October
2026).** The founder, word for word: "approve all", on the two replacements
in Privacy §4 "Talking to Will" and the §7 OpenAI line. Told that 3.6 was
already published and cannot change in place, the founder: "yes, go ahead as
3.7".
**Counsel's review was not obtained.**
- **Why:** Will answers "what do I say on slide 4?" and "does my talk match my
  title?" from the whole talk, slide by slide; and since backend #1069 Will
  reads the Lounge thread (the summary after a Take, the walk's steps, the
  coach's word).
- **What:** [`legal/phase1-2026.1/28-privacy-3.7-will-context-APPROVED-2026-10-15.md`](../legal/phase1-2026.1/28-privacy-3.7-will-context-APPROVED-2026-10-15.md);
  `copy/privacy-3.7.txt` is 3.6 with the founder's two passages verbatim and
  the version lines. Terms 3.6, AI notice 3.2 and training-only-v4 unchanged.
- **Publishing** is the founder's step: `legal/phase1-2026.1/PUBLISH-3.7-2026-10-15.sql`,
  dry-run on a disposable database. Speakers then accept 3.7 in one tap (the
  update prompt). The code that gives Will the whole talk goes live only
  after.
- **Risk the founder accepted:** OpenAI now receives each slide's points and
  the full Ideal Text for chat answers, and counsel hasn't seen this.
- **Published** (founder, 15 October 2026, 12:49 UTC): `PUBLISH-3.7-2026-10-15.sql`
  run in Supabase. `phase1-2026-10-15-3.7` is in force with the approved
  bytes and the United States; training-only-v4 stays the one wording in
  force. The code that gives Will the whole talk may now go live.

**N75 · The AI clip practises fillers; the transcript stays clean (founder,
Linear and chat, 18 October 2026).** From the Linear issue "Evaluate
retaining filler words in transcripts" and the founder's four answers in the
Claude Code session: the transcript keeps removing hesitations silently (the
fence of 2026-07-20); the speaker learns about their fillers only in the
AI clip, as a fourth exercise next to pace, pause and stress; the test that it
improves awareness is fewer fillers in the next try, measured internally and
read in the admin Take view, never shown; an uploaded Take has no voice and
gets nothing. One signed sentence, L18, under the player ("you have my OK to
the previous one"). Lock: [`FOUNDER-LOCK-ai-voice-practice-2026-10-12.md`](FOUNDER-LOCK-ai-voice-practice-2026-10-12.md),
"Decided after the lock (2026-10-18, fillers)". Migration 0475.

**N76 · Words first, then voice (founder, chat, 18 October 2026).** The
practise moment opens on the Clearer version only when its words need help and
the rewrite passes the gate; otherwise the voice Exercise with the AI clip ("ok,
push to prod" on <https://claude.ai/artifact/Ut2SqvHCoJ1hvH8dp17yQe>). The rule:
flow page C4 and H3; [`FOUNDER-LOCK-ai-voice-practice-2026-10-12.md`](FOUNDER-LOCK-ai-voice-practice-2026-10-12.md). No migration.

**N77 · A coach's word for a Take shows on its own Take only (founder,
Claude Code session, 18 October 2026).** Asked who gets a coach's recorded
message, the founder chose every recommended answer on the plain-words map
(<https://claude.ai/artifact/QU5ENGdftkJXFppAQYFhyj>). The part in force
here: the coach's word for a Take shows on that Take only, and a later Take
starts without it (supersedes N48.3 Q11 A's earlier-Take fallback). A word
left on an earlier Take after a newer one exists reaches the speaker through
its Lounge bubble ("Later · from your coach"), the WhatsApp and the email.
Their links name the word's Take (`take=<session_id>`, founder 2026-10-21)
and open that Take's coach-only walk with the word; a link without it opens
as before. Contract 35g-6 carries the dated amendment; `services/coach_message_read.py`
serves the Take on screen only. Landed on main with N95. The rest of N77, a
coach's video belonging to the speaker it was made for (and N78 after it),
arrives with #1127 and migration 0480 and is not in force until that merges.
No migration.

**N79 · What we keep of what a coach says, and what may leave (founder, chat,
19 October 2026).** The goal is a coach "text brain" trained on what coaches
say, the situation and the error type; first we fix what is captured. Four
answers, each the recommended option:
- **The doors close to direct messages.** `coach_take_word` and
  `coach_moment_line` leave doors 2, 3 and 4 until names and specifics are
  scrubbed, the one privacy update is published and the versioned coach
  agreement exists. They are still recorded for every speaker; only a
  training yes would make one releasable. ("Close them for now.") Nothing
  had left by then: every Take-word pair was refused by 0402's one_home
  CHECK, and nothing in the app calls the moment-line drafter.
- **The latest version teaches.** When a coach edits a Take word, every
  version is kept in its history and training reads the newest one.
- **Coach videos are transcribed only for speakers with the training yes.**
  The words have no use but training; a catch-up picks up anyone who says yes
  later. Copies kept inside the database (the situation, the drafts) are kept
  for everyone and deleted with the Take.
- **A coach's words stay with the speaker.** When a coach leaves, their
  words, transcripts and the error type they picked on each answer stay with
  the speaker's Take and go when it goes; the error type is copied onto each
  answer so it survives. The coach agreement says so.
Built as one small pull request per fix, each branched from main: the door
hold, the Take-word video ref, the Take-word pair's home, Take-word history,
every draft with its exact prompt, exercise transcription from the audio,
answer-video transcripts, and the situation frozen on each answer.

**N80 · When a coach changes their word for a Take (founder, chat, 19 October
2026).** One "Later · from your coach" bubble per Take word; a taken-back video
never plays again; watched anywhere is watched; on the coach panel the saved
video with "Record again" and the new word "Remove the video" (the two-phone
prototype <https://claude.ai/artifact/APk56PLZt6o6Cx9qUMKkuk>). The rules: flow
page D5; [`FOUNDER-LOCK-coach-panel-redesign-2026-10-06.md`](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/FOUNDER-LOCK-coach-panel-redesign-2026-10-06.md) ("Decided after the
lock (2026-10-19, the saved video, N80)"). No migration.

**N81 · The lens is one chat (founder, chat, 20 October 2026; WIL-89).** The
walk is one chat that grows by taps: nothing swaps, the step's buttons are a dock,
a choice lands as the speaker's bubble, every practise is one thread ("can you
build it that way?" on <https://claude.ai/artifact/P5fHFguyCgjhMGPsmH7UaD>). The
rules: flow page B5–B7, B12, C7. Frontend only; no migration.

**N82 · Will asks one question after a Take, and the practise moment cheers
first (founder, chat, 20 October 2026).** The voice Exercise opens with L4, the
AI clip and L3; Will asks one question in the Lounge, as the Take's one ask, only
when something is off or missing, with tap answers from what Will knows; every
answer is kept for Will ("signed, build it" on
<https://claude.ai/artifact/HSRfvDZLDRQizmGJDxMUJz>). The rules and the signed
words: flow page C6, E2–E4, K. No migration.

**N83 · The founder edits Will's questions on the coach panel (founder, chat,
20 October 2026).** One row under the blind lists, "Will · only you" →
"Will's questions"; the words are checked before they are kept; migration 0488
`will_question_bank`, GET/PUT `/v2/admin/will-questions` ("OK" on
<https://claude.ai/artifact/WLZ1KY6dX1RBLXiNU73F9N>, the review waived). The
rules and the new words: [`FOUNDER-LOCK-coach-panel-redesign-2026-10-06.md`](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/FOUNDER-LOCK-coach-panel-redesign-2026-10-06.md)
("Decided after the lock (2026-10-20, Will's questions, N83)"); flow page E5.

**N84 · A Good job only when clearly better, and the AI voice on time
(founder, chat, 20 October 2026).** A Good job on the voice alone needs the
lock's +0.05 margin (`after_practice.GOOD_JOB_MARGIN`); the voice copy starts
as the spoken Take is stored, beside its processing, and the walk shows the
clip whenever it lands. Two of N82's open items. The rules: flow page C7 and
H2. No migration.

**N85 · The walk spots words that undermine the speaker (founder, chat, 20
October 2026).** One undermining word (apologising, asking permission,
self-doubt, playing the idea down; closed lists in `services/undermining.py`)
makes the words need help; a rule writes the clearer version with them left
out, never a word added; it opens with B10's first line and B13's "Try saying
it like this:" (the signed prototype
<https://claude.ai/artifact/HSRfvDZLDRQizmGJDxMUJz>). The rules and the
words: flow page C5, H3, K. No migration.

**N86 · The flow page's first review (founder, 20 October 2026, on the
decision-tree page and in chat).** Nine rules read right; the rest, decided:
the walk opens the moment processing finishes, nothing in between; the score
decides each of the two shown moments, praise at or above the floor and a
correction below it, both corrected when both are weak and both praised when
both are strong (in place of the fixed roles of 2026-10-14); the highest
moment's bubble opens with the new signed line "This was your most confident
moment." ("… so far." when it is corrected); Will may say his signed
questions with light variation, the tap answers never; counsel approved L12
and L13; self-judgement waits for about 50 clips with both answers, then the
founder sees the numbers; the coach panel's audience-and-goal lines get a
prototype. The rules: flow page A2, C2, C4, C5, E2, H1, K, §2, §3. The
builds are §2 lines. No migration.

**N87 · The coach sees who the talk is for and what they should do (founder,
chat, 20 October 2026).** Under the speaker's goal on their screen, in the
same small text, the speaker's own words from the newest Take that said them
("Who it's for: …", "What they should do: …", the signed group names of N83);
nothing when they have not said. The founder approved the prototype
<https://claude.ai/artifact/UiZzNZs5623NkforaeR4PM> ("make it all the same
small text", "please execute all of that"). The coach panel's rules move to
one page, frontend [`docs/flows/coach-panel.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/coach-panel.md), as the walk's did (N86); its
lock file is history. The rules: that page, C3 and J. No migration.

**N88 · The walk opens the moment processing ends (founder, the app, 20
October 2026).** After checking the app: the marks are baked in the
processing run right after the Take is ready, the processing bubble waits
for them, the Clearer version is served on its moment, and the speaker-side
practice gates read the speaker's own page. The rules: the walk's page, A1,
A2, C3, C4, D4, D5 (frontend [`docs/flows/feedback-walk-and-chat.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/feedback-walk-and-chat.md), §6
N88; backend #1209, frontend #896). No migration.

**N89 · One mechanism opens the walk; the chain after the Take (founder, the
app, 20 October 2026).** Every door opens the whole Take's walk at its step;
after the summary (no next step, no record button) the asks come one at a
time, each with Will's lead-in, then "Look, practice makes perfect. If you're
ready, let's go with the next take. 💪" and "Record Take N". The rules: the
walk's page, B10, C1, D3, D4, D5, E1, F4, F5, K (frontend
[`docs/flows/feedback-walk-and-chat.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/feedback-walk-and-chat.md), §6 N89; backend #1210, frontend
#897). No migration.

**N92 · The coach's answer and video reach the speaker's page as they
stand (founder, the app, 21 October 2026: "the video was sent too with the
coach feedback and didn't pass through").** The speaker's feedback rows are
served from a stored bake that only the speaker's own writes retire, so the
coach's answer, and the signed link of their video, stayed as baked. Now the
bake re-reads the coach's answer on every read, one read per Take, the video
signed afresh, and a coach's share asks for one rebake. The rules: the walk's
page, C1, D5 (frontend [`docs/flows/feedback-walk-and-chat.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/feedback-walk-and-chat.md), §6 N92). No
migration.

**N90 · The walk's doors checked in the app; the coach's bubble at the
bottom (founder, the app, 21 October 2026).** A step already answered past
opens the walk on that step with the parts before and after it to scroll;
the "Later · from your coach" bubble is written the moment the coach
shares, review ended or not; a try not heard says so; "Edit the helper
words". The rules: the walk's page, B10, C3, C7, D5, E1, K (frontend
[`docs/flows/feedback-walk-and-chat.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/feedback-walk-and-chat.md), §6 N90). No migration.

**N93 · The AI clip that came out flat gets one more try (founder, the
Claude Code chat, 21 October 2026).** The stress clip of 20 October failed
its check (0.02 dB of contrast; the two that passed had about 2.4) and,
made only once, never came: a clip that fails its check is now made once
more with a new seed, never a third time, and a try after a clip that was
never made is not scored. The rules: the walk's page, C6, H2 (frontend
[`docs/flows/feedback-walk-and-chat.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/feedback-walk-and-chat.md), §6 N93). No migration.

**N94 · After the walk, a short cheeky summary, a bridge, then Will's
question; at most two asks (founder, the Claude Code chat, 21 October
2026).** The summary is one or two short sentences, only a cheeky sum-up of
the Take: no greeting, no question (the app had asked about the talk's
content inside it). In the chat a bridge line comes before Will's question
("Ok, now let's dive into the content for a bit." / "Alright, let's dive
into the content for a moment."); at most two asks a Take, the home screen,
WhatsApp and then "Did this help?" waiting for a later Take; after the
chat's safety reply the asks wait until the speaker writes again; a fourth
Take's fallback is no longer called the third; the 48 reading lines are
signed into [`docs/SIGNED-line-bank-2026-10-06.md`](SIGNED-line-bank-2026-10-06.md). The rules: the walk's
page, C2, C5, C7, D, E1, F3–F5, G1, K (frontend
[`docs/flows/feedback-walk-and-chat.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/feedback-walk-and-chat.md), §6 N94). No migration.

**N95 · One source of truth: backend main's docs (founder, chat, 21 October
2026).** What is in force is what is written and merged on this backend
repo's `main`, read in this order: this log, then
[`docs/CANONICAL_PRODUCT_CONTRACT.md`](CANONICAL_PRODUCT_CONTRACT.md), then [`docs/LOCKS.md`](LOCKS.md) and the
`FOUNDER-LOCK-*.md` files with their prototypes. Nothing said only in chat,
a PR description, an open branch or the frontend's own docs is in force; each
founder decision made in chat comes here at once in its own small docs PR,
never bundled with code waiting for review; where main's code disagrees with
these docs, the docs win and the code is a bug. The rule: [`CLAUDE.md`](../CLAUDE.md), "One
source of truth". The frontend's flow pages
[`docs/flows/feedback-walk-and-chat.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/feedback-walk-and-chat.md) and [`docs/flows/coach-panel.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/coach-panel.md) also
count for their flows, because the frontend design-lock guard requires them
to change together with the code. With it, N77's part about the coach's word
showing on its own Take lands on main (contract 35g-6,
`services/coach_message_read.py`), with the coach's links naming the word's
Take. No migration.

**N96 · Import audio takes several files at once, inside the upload limit
(founder, the Claude Code chat, 21 October 2026: "please make it possible to
upload more than 1 file in the trianing coprus if it doesnt exceed the limit
of the upload"; "ok" to the words below).** On the coach panel's training
corpus each picked file becomes its own import under the same set-up, one at
a time in name order (one file per request, as before), filed as "{topic} ·
{file name}" when there are several. It stays inside `whisper_limit` (20 a
minute, 200 an hour per coach): more than 200 files is refused at the
choice, a per-minute refusal is waited out, an hourly one stops the batch.
New words: "{n} files", "{name} · {i} of {n}", "Up to 200 files at a time".
The rules: frontend [`docs/flows/coach-panel.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/coach-panel.md), H2. No backend change, no
migration.

**N97 · The speaker/coach disagreement signal (founder, the WIL-32 decision
page in the Claude Code chat, 21 October 2026).** A clip where the speaker
and the lone coach answer differently goes to the front of the line for a
second blind listener, as a machine disagreement does. It is built only once
speakers answer about their own clips again, and judging your own moments
stays out of the walk. Other speakers' clips stay one per practice try:
other speakers first, licensed clips for the places left (this replaces the
mix of 19 October, 3 every walk). The rules:
[`docs/DESIGN-WIL-70-disagreement-signal-2026-10-18.md`](DESIGN-WIL-70-disagreement-signal-2026-10-18.md) §6 and frontend
[`docs/flows/feedback-walk-and-chat.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/feedback-walk-and-chat.md), C8 and §3. No code change, no
migration.

**WIL-93 · The coach's links, tapped signed out, go to log in and back
(founder, the Claude Code chat, 21 October 2026: "please go with the fix.
You have my okay").** Tapped where the speaker is not signed in, the
WhatsApp and email links to the coach's feedback go to log in and come back
to the same link, never to the guest's "Done" screen; a project the device
holds as a guest's own work stays on the guest's screens. No new words. The
rules: the walk's page, C1 (frontend [`docs/flows/feedback-walk-and-chat.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/feedback-walk-and-chat.md),
§6 WIL-93; frontend #911). No backend change, no migration.
**N98 · The founder's roadmap page (founder, the Claude Code chat, 21 October
2026: "can you build it into the CEO panel as a separate tab in the hamburger
menu and make it updated at all times? … I just want it to be my overview and
where things stand not the decision or ticking tool").** The admin menu gets
Overview → Roadmap (`/admin/roadmap`, founder only). It shows the 1.1, 1.2 and
2.0 plan with each item's state read from the two GitHub repositories (done,
in review, draft, in progress, not started) and the PRs merged lately. An
overview only: no decisions, no ticks, nothing typed by hand; a state comes
only from GitHub, and "done" only when every PR that finishes the item is
merged. The plan lives in `config/roadmap.json`; a PR that starts or finishes
an item adds its number there. Read without a token (both repositories are
public), cached five minutes; the page reads again every two minutes while on
screen. No migration, no environment variable.

**WIL-93, follow-up · The coach's link with nothing of the coach's goes
back to the chat; in another account it says so (founder, the Claude Code
chat, 21 October 2026: "if you can not direct me to the walk directly at
least just open the lounge and the bubble with orange dot will be there";
"ok" to the words).** A coach's door with nothing of the coach's to show
goes back to the chat, where the coach's bubble is, never to the Ideal Text.
Opened in an account the project is not in, the page says "This link is for
another account." with "Log in with that account", which signs out and comes
back to the link, instead of waiting on "Building your Ideal Text". The
rules: the walk's page, C1, K (frontend [`docs/flows/feedback-walk-and-chat.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/feedback-walk-and-chat.md),
§6 WIL-93; frontend #917). No backend change, no migration.

**N99 · Judging the training corpus goes on from one recording to the next
(founder, the Claude Code chat, 21 October 2026: "make the training corpus
switch from the recording to recording without needing to click the table
of the next one it goes recording one by one; and done are moved to the
bottom; and please make sure it is smooth that it loads fast").** After an
import's last moment the next import in the list with moments waiting opens
by itself, and the list when none is left; in the list the done imports sit
at the bottom. An answer moves on at once while its save runs behind it; a
refused save brings the coach back to that moment. The coach's queue read
and the label save are to answer fast (they took 6.7 s and 9 s). The rules:
frontend [`docs/flows/coach-panel.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/coach-panel.md), H3. No new words, no migration.

**WIL-93, second follow-up · The coach's link opens the coach's feedback,
read or not (founder, the Claude Code chat, 21 October 2026: "ok do it" to
the proposal).** The WhatsApp and email links always open the coach's
feedback for their Take, even once it has been seen: the coach's word and
every moment the coach answered on that Take, as they were given (the
speaker's own answers kept, nothing to redo), then Continue back to the
chat. Read or unread changes only the bubble's dot, never what the link
opens; no "already viewed" notice. When the page holds nothing of the
coach's (a link naming an earlier Take whose coach left only moment
answers), the chat opens scrolled to the coach's bubble, which pulses once;
a tap on it opens that Take's feedback as before. No new words. The rules:
the walk's page, C1 (frontend [`docs/flows/feedback-walk-and-chat.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/feedback-walk-and-chat.md)).
No backend change, no migration.

**N100 · The training corpus list loads in steps as the coach scrolls
(founder, the Claude Code chat, 21 October 2026: "no it can go in steps,
just make it faster; you can make the pages or a scrolling and you wait for
it to load (that is preferred)").** The list opens with its newest imports
and, at the bottom, loads the next step while the app's one loader shows;
judging one import after another (N99) reads the next step when the steps
loaded hold no import left to judge. The list is no longer cut at its
newest 200 imports. The rules: frontend [`docs/flows/coach-panel.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/coach-panel.md), H4. No
new words, no migration.

**N101 · The training corpus is judged mixed: across imports, speakers and
the machine's reads (founder, the Claude Code chat, 21 October 2026: "make
sure that for the display of the recordings for the judgement, they do not
come from the same speaker; the fragments are really mixed, with different
willfidence scores like really neutral, high, and low").** Judging draws its
clips in rounds across every open import the coach may hear, from each
import's frozen cohort: never one speaker twice in a row while another is
left, and up to the same number of clips from each band of the machine's
read (high, neutral, low), so all three are there. The band decides only
which clips come in, never where they stand: the order is a seeded shuffle
of the clips, so nothing on screen hints at the machine's read (BLIND
COACH). Opening an import starts the round with one of its clips; the next
round follows when one is done, and the list when none is left. This
replaces N99's one import after another. The rules: frontend
[`docs/flows/coach-panel.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/coach-panel.md), H3. No new words, no migration.

**N102 · Learning sources and the label quorum have one page (founder, the
Claude Code chat, 21 October 2026: "unify the .md files about the learning
sources and quorum in general").** [`docs/LEARNING-AND-QUORUM.md`](LEARNING-AND-QUORUM.md) gathers what
the app learns from and how an answer becomes a label, with a plain-words
summary, the rules as they stand (each naming its source), what is in flight
and what is open. It outranks nothing: the order of N95 stands, and the page is
fixed where it differs. The older pages open with a note pointing to it. The
twenty-four disagreements it found wait for the founder in its §3. No rule
changes, no code, no migration.

**N103 · Three approved versions of an exercise video per mistake before the
app stops asking coaches (founder, the Claude Code chat, 21 October 2026).**
The app keeps asking coaches for exercise videos for a mistake until it has
at least three versions of it, so a speaker is not shown the same lesson
again and again. Only versions the founder approved for other speakers count
(N78's approval; a video made for one speaker stays that speaker's and does
not count). Below three, a speaker whose moment shows the mistake still gets
an existing version at once (never waits), and the moment also goes to the
coach's queue to record another version; at three or more the app stops
asking for that mistake. Choosing among the exact fits: a shuffle that skips
any version this speaker has already seen and rests a version after their
"Good job", keeping the 80/20 learning slot. Builds on N77/N78, which arrive
with wilplus/backend-cursor#1127; not in force until it is built and merged.
No new words; the coach-panel line that asks for another version needs the
founder's wording when it is built.
**N104 · "What happened" on the coach panel gets one more line, Willfidence;
the person's admin page loses the Confident Voice practice tile (founder,
the Claude Code chat, 21 October 2026: "I would like to have it removed
from here, at least the confidence level, and rather have it here ... after
the judgement ... just add there one row: Willfidence ——— percentage").**
After the coach's own blind answer, "What happened" shows a last line,
**Willfidence**, with the moment's willfidence as a whole percent (S × W,
the read the Take's moments are picked by; flow page H1). A clip with no
sound read shows no line, not the middle of the scale. This is for the coach
only: a speaker never sees it (Never 1), and the coach sees it only behind
the blind gate (BLIND COACH). It is the one number in the coach's read;
AC-9's "never a number on screen" still holds for speakers. The new word is
"Willfidence", signed here. The person's admin page (WIL-73) no longer shows
the Confident Voice practice progress tile. The rules: frontend
[`docs/flows/coach-panel.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/coach-panel.md), E1. No migration; the person's admin read no
longer carries `practice`.


**N105 · The person's Takes table gets a Willfidence column (founder, the
Claude Code chat, 21 October 2026: "add the willfidence column here (in the
ceo panel but only here)").** On the founder's person page, "Takes and
acoustic data" shows each Take's willfidence in whole percent: the mean of
its pieces' willfidence (N104), counting only pieces with a sound read, and
"—" when none has one. It is on that table only (and its CSV); no speaker
sees it. The word is the one signed in N104. No migration.

**N106 · The docs are sorted: one master doc and four labels (founder, the
"Sorting the docs" decision page in the Claude Code chat, 21 October 2026,
eleven answers, then "Yes ship it").** The master doc is the backend's root
[`README.md`](https://github.com/wilplus/frontend-cursor/blob/main/README.md). It lists every doc worth reading, as clickable links, in N95's
order. The frontend's [`README.md`](https://github.com/wilplus/frontend-cursor/blob/main/README.md) points to it and lists the frontend's own
pages. Every doc carries one label: **In force** (the rules), **Reference** (how
something works today), **History** (kept as written, because the rules still
cite it), or **Archive** (nothing needs it). Each doc says its label in one line
at the top, except where its bytes must not change: the legal pack, the signed
texts, and files that code or tests read. The MLC-2 and MLC-3 files become
History behind one entry, except the parts still in force. The prompts written
for coding agents and the session handoffs are archived. So are the files
unchanged since before July, except the legal records and anything the rules
still cite. The frontend's copies of backend docs become one-line pointers,
except [`CLAUDE.md`](../CLAUDE.md) and [`AGENTS.md`](../AGENTS.md). Archived files are labelled now and moved
later. The mentions in the In force docs become clickable links now. The
founder checks every file's proposed label on a page, and corrections follow
in their own PR. Map: the docs map of 21 October 2026 (step 1). No rule
changes, no code, no migration.

**N107 · The docs converge (founder, the Claude Code chat, 21 October 2026,
"do it all", to four steps proposed in the same chat).** (1) The docs labelled
Archive under N106 leave `main`; git keeps every one, and the master doc links
to the last commit that had them. (2) History collapses: the MLC-2 and MLC-3
chain becomes one summary page, the audits keep their latest and what the rules
cite, and the other History docs stay only while a rule or code names them.
Where the rules cite a deleted doc, the mention becomes a permanent link to it in
git history. (3) Every locked screen gets one rules page in the frontend's
`docs/flows/`, in the shape of the walk's page: the recording screens, the
consent screens, the Ideal Text with its helper words, and the AI voice in
practice. Each folds in its founder lock, signed words verbatim, and the lock
file becomes history, as the walk's and the coach panel's did. The contract
keeps its numbered clauses, because code and tests cite them by number. (4) A
new doc is not started: the area page or the master doc is edited, and handoffs
and prompts for coding agents go in pull request descriptions. A new doc needs
the founder's OK and a line in the master doc. No rule about the product
changes, no code, no migration.

**N108 · The voice decides the confident moment; a correction with nothing
to offer is skipped (founder, the Claude Code chat, 21 October 2026, on a
screenshot of "Say this one like your confident moment." under a moment that
"was a confident moment ... even more confident than the first one"; "Voice
decides", "Skip that moment").** The shown moments are ranked by their voice,
the sound read S, and the strongest voice is "your most confident moment". A
shown moment whose voice reaches the floor is praised, unless its words need
help (the rewrite gate), which gets the Clearer version; the voice Exercise
is only for a moment whose voice is under the floor. Until now S × W decided
both (N86), so weaker words could put a stronger voice under the floor and
then ask it to change its voice. Willfidence stays S × W everywhere else
(N104, N105, the practise's margin). A voice correction with no AI clip and
no exercise is skipped, in place of "said again, never dropped" (N88): the
walk moves on and the moment still reaches the coach. A clip with no sound
read keeps the rule of 2026-10-17. The rules: flow page C2, C4, H1
(frontend [`docs/flows/feedback-walk-and-chat.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/feedback-walk-and-chat.md)). No migration.

**N109 · The confident moment's line fits what follows (founder, the Claude Code chat, 21 October 2026: "it was a solid confident moment we have recognised, here is an example to make it even better"; "vary around the line I suggested … no abruptions").** When the walk goes on to make the Take's most confident moment better, one line names it solid and confident and leads into what follows (a clearer version, an example, or saying it again), three phrasings each around the founder's line, in place of "so far"; Line A is never said on that moment. The rules: flow page C2 and K (frontend [`docs/flows/feedback-walk-and-chat.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/feedback-walk-and-chat.md), FE #929). No migration.

**N110 · The waiting screen stays until the walk is there, and starts at 1%
(founder, the Claude Code chat, 21 October 2026, with a screenshot of the walk
opening on its typing dots: "It starts on the screen and then automatically
closes and opens the lounge it is abrupt make it stay"; "when it says it's done
it opens the walk automatically but then it still loads the walk - so it is not
done!"; "when the processing starts it should show at least 1% from the very
first second so that user knows it has at least started").** After Finish take
the waiting screen stays on screen: when the server holds the Take, the Lounge
takes the wait over and shows the same screen at once, full screen, in place of
the chat; its ✕ shows the chat, where "Processing your recording" waits as
before. When the Take's text is stored and the walk opens by itself, the
waiting screen stays over it until the walk's first step is on screen (or, with
nothing to walk, the text), also when the speaker had gone to the chat, so
"done" never opens onto the walk still loading. The bar shows at least 1% from
the first second, in place of "…" before the first report; a processing
percentage is allowed (Never 1, founder 2026-10-19). No new words. The rules:
the walk's page, A1, A2 (frontend
[`docs/flows/feedback-walk-and-chat.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/feedback-walk-and-chat.md), §6 N110); the recording
screens' page, the flow, 5 (frontend
[`docs/flows/recording-screens.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/recording-screens.md), §6 N110). No migration.

**N111 · The open questions of 21 October (founder, the decision page "Docs
and Learning Decisions" of the Claude Code chat, 21 October 2026: 29 yes-or-no
answers, then "Yes, ship it").** The questions left open by N106 and N107, and
§3 of [`LEARNING-AND-QUORUM.md`](LEARNING-AND-QUORUM.md). Two answers are held
and asked again (A11 and A14, at the end), because the question put to the
founder missed a fact. Each answer below is built in its own pull request.

- **The docs.** The labels stand as set (N106). The policy update prompt
  (<https://claude.ai/artifact/GPRRXaivyrZE2UjrRZY93K>, version 2) and every
  Lounge ask, unified (<https://claude.ai/artifact/CzVL6JWK85tZDVpU9JRtgY>,
  version 2), join the consent screens' rules; the code already follows both.
  The docs that only code comments name leave `main`: 65 of the 82 kept on
  21 October because code named them, each comment now pointing to the doc's
  last version. The other 17 stay, because a migration (never edited once it
  has run), a script, a prompt the app reads, a golden eval file or a sheet
  still waiting for the founder's signature needs them. The four rules
  pages of N107 are rewritten in the present tense part by part, when their
  screen next changes. WIL-32 goes to Done and WIL-70 closes once Linear is
  connected to the chat.
- **The docs don't pile up again.** Every part of the code has one home doc,
  named in a table in the master doc ("Home docs for the code"; the
  frontend's table is in its own `README.md`). A row may say "No page" when
  the code and its comments describe that part. The checks refuse a pull
  request with code that no row covers, and a new `.md` file unless its line
  in the master doc says `Founder-Approved:`. The rules pages also guard the
  locked-screen files they missed (`scripts/flow-pages.txt` in the frontend),
  except the Lounge's thread files, which the walk's page leaves unguarded on
  purpose.
- **Learning and the label quorum** (§3 A of the learning page):
  - A1 · The Voice Album: contract 32 decides. A clip is admitted by a
    Machine Yes, a User Yes and a Coach Yes on the same recording. C1 and C4
    are out of date where they make the Album a two-person quorum.
  - A2 · Once a coach's answer is saved, the coach panel shows what the
    machine heard (coach panel D2, E1). On that point this replaces contract
    34's amendment of 6 October (N51). Before the answer the coach sees
    nothing (CLAUDE.md, Never 2).
  - A3 · Detector training is on: the founder's "turn it all ON" of 8 October
    covered it (`config.py`, `DETECTOR_TRAINING_AUTHORISED`). Contract 35g-9
    and N29.6 are out of date on that point.
  - A4 · The blind lines are off (coach panel B3, contract 35g-10). Production
    is checked, and the notes of `error_presence_audit.py`,
    `coach_block_pick.py` and `v4_coach_sheets.py` are corrected.
  - A5 · "Half praised and half low" leaves walk rule I1. The order is N86's,
    N101's and N97's.
  - A6 · willfidence-v2's "200 labels" means 200 settled clips.
  - A7 · A coach's answer on an import of their own talk is a self-report and
    never counts (N58). The code is corrected.
  - A8 · The "Turn on the learning?" question before every Take is gone, by
    the consent screens' lock as amended on 18 October. N28's question is
    retired.
  - A9 · The ledger's "a second listener right away" (J3) orders only a
    Take's confidence queue. The coach panel's queue, the corpus rounds
    (N101) and other speakers' clips (N97) keep their own order.
  - A10 · The copies kept for training are text only (N68, D1). N6 Q1 and
    N10 are out of date on that point.
  - A12 · A speaker's answer about their own practice never trains any model
    (contract 30, walk I2; the founder, 19 October: "never trains any
    model"). MLC3 §8 is out of date on that point.
  - A13 · Willfidence is the voice-confidence read of one sentence (walk H1).
    SPEC §17 is out of date on that point.
  - A15 · The exercise measures of WIL-29 count, with the founder's chat
    answers of 18 October as the code states them: "build option 1";
    "founder only" (one person's list of their exercises is the founder's,
    never a speaker's or a coach's screen); "next time is the next Take of
    the same project" (a practice gets at most one "held" result, decided
    when the next Take of the same project is ready); and, the founder's
    default, a paragraph rewritten, split or cut is "unknown", never "held".
    The concept is
    [`CONCEPT-per-user-exercise-effectiveness-2026-10-18.md`](CONCEPT-per-user-exercise-effectiveness-2026-10-18.md).
- **Code that disagrees with the rules** (§3 B): each of the seven is fixed in
  its own pull request, and confirmed in the code first. The first changes
  the view `snippet_label_quorum`, so it is a migration and gets its outside
  review before it merges.
- **History** (§3 C): clips settled by two `neutral` answers under J4 to J6,
  before K of 25 August, stay settled (K: old rows keep their meaning). The
  code is corrected. That `neutral` means three things in three places is
  written on the learning page, and that is enough.
- **Held, asked again.** A11 (does training rest on Article 9 explicit
  consent?): the question said the legal pack is counsel's text and N69 is
  not, but N69 is counsel's answer as the founder relayed it, and the 3.5
  pack was signed without counsel. A14 (were Privacy and Terms 3.5
  published?): the question missed that migration 0458 cleared the blocker
  N68 names, that `config.py` records the publication on the evening of 8
  October, and that doors 3 and 4 have been open for three surfaces since.
  Until the founder answers again, nothing changes for either.

The rules pages: the consent screens, the walk (I1, I3) and the coach panel,
and the locked-screen files they now guard (frontend #932). No migration in
this entry.

**N112 · A moment whose words hedge gets its clearer version (founder, the
Claude Code chat, 21 October 2026: "There was no single rewrite in the take";
then "Rule leaves out hedges").** A shown moment whose words needed help for
their hedges had no rewrite to offer: the AI writes one only for a clip it
read as unconfident, rude or off the slide, and the rules only for
undermining words, a broken sentence or a repeat, so a strong voice was
praised instead. The rule of N85 now also writes the clearer version for a
sentence that hedges: its softening hedges ("I think", "maybe", "kind of")
left out, nothing added; a hedge's words that are not a hedge where they
stand ("I think about it", "this kind of problem") stay. It opens with C5's
"Here is a slightly more polished option:", so no new words on screen. The
rules: flow page C4, C5, H3 (frontend [`docs/flows/feedback-walk-and-chat.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/feedback-walk-and-chat.md)). No migration.

**N113 · A confident voice whose words are reworded still gets its helper
words (founder, the Claude Code chat, 22 October 2026: "in the walk the
helpers for the moments were not there"; "we landed on the right place but
the helpers were missing"; then, asked where they go, "After the
rewording").** Since N108 a shown moment whose voice reaches the floor is
praised only when its words need no help, and since N112 a sentence that
hedges always has its clearer version, so most strong voices were walked as
corrections, and helper words came only after a praise: a Take could end with
none. Now a shown moment whose voice reaches the floor and whose words get
the Clearer version keeps the Clearer version and its practise, then "Choose
your helper words" on its paragraph, as after a praise. The server says which
moments these are with a flag, never the score. A voice under the floor is
unchanged: no helper words. No new words on screen. The rules: flow page C3,
C5, H1 (frontend [`docs/flows/feedback-walk-and-chat.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/feedback-walk-and-chat.md)). No migration.

**N114 · While the servers are down, every page says so (founder, the Claude
Code chat, 22 October 2026, during Railway's security incident: "show a
banner on the top of the site like a one like supabase does; with servers are
temporarily down, will be back soon!").** A slim amber bar at the top of
every page reads "Servers are temporarily down, will be back soon!", in the
founder's own words. The full-screen screens (recording, Ideal Text, the
walk, consent) stay above it, so no locked screen changes. It is temporary:
it comes off when the servers are back. Frontend
[#938](https://github.com/wilplus/frontend-cursor/pull/938). Same day, with
Railway's deploys still paused, the founder changed the words ("please change
it to: there is a high upstream traffic - please visit us tomorrow!"): the bar
now reads "There is a high upstream traffic - please visit us tomorrow!".
Frontend [#939](https://github.com/wilplus/frontend-cursor/pull/939). The same
afternoon, with the rotated keys deployed, the founder took the bar off ("take
off the label cause all got deployed now!"). No migration.

**N115 · No backfill for the Takes without a dark frame, and 0489 merged
without the outside review (founder, the Claude Code chat, 22 October 2026:
"no back fill bro"; then "no outside review").** From #1207 (N86, 20 October,
~19:20 CEST) until 0489 ([#1262](https://github.com/wilplus/backend-cursor/pull/1262), `the_shadow_writer_accepts_frame_v7.sql`)
the database refused every Take's dark frame, so those Takes have no frame,
no random draw, no paragraph map and no willfidence read. They are not
backfilled: a Take gets its frame when its Ideal Text is built again (opened
as the speaker's current Take, or baked again), and the others stay without
one, so no tagging call is made for them. 0489 merged on green checks without
the GPT or Grok review CLAUDE.md asks of a new migration; the waiver was for
0489. No migration in this entry.

**N116 · The screen stays on while a Take records (founder, the Claude Code
chat, 23 October 2026, after a Take recorded on the phone reached the server
empty: "this time the screen was getting locked automatically cause I spent
more time on the same slide without clicking … we should keep the screen up
when the recording is ON").** While the mic records a Take, the app holds the
browser's screen wake lock, so the phone cannot lock itself and cut the mic
off. It asks again when the page comes back into view and lets go when the
Take ends. Nothing on screen changes and no words are added; a browser without
a wake lock records as before. The same fix keeps the audio in one-second
pieces as it is spoken, so a lock the app cannot prevent (the side button)
loses only what came after it, and an empty recording is never sent: the
speaker is asked to record again. Frontend
[#942](https://github.com/wilplus/frontend-cursor/pull/942). No migration.

**N117 · Both repos stay public (founder, the Claude Code chat, 23 October
2026: "ok, let's keep it public I think we don't overshare there").**
`wilplus/backend-cursor` and `wilplus/frontend-cursor` are public on GitHub:
anyone can read the README, every doc, the legal pack and the history without
logging in. Asked whether to make them private (which would limit some
things), the founder chose to keep them public. Checked the same day, in the
files and the whole history of both repos (2,033 and 2,066 commits), for key
and token patterns: no real key was found. The only key-shaped strings are
Supabase's published demo key (the fake the CI uses) and test fixtures that
check keys are scrubbed. Not checked: personal data, and whether each file of
the legal pack is meant to be public. No migration in this entry.

**N118 · Every Take shows its two best moments, one per paragraph (founder,
the Claude Code chat, 23 October 2026: "it should be minimum 2; best two;
highest willfidence moments of the take; even if there is low willfidence in
general you choose two best"; "it doesnt have to be separate slide"; "don't
show two moments on the same paragraph"; "if you extend the length of the
paragraph you can actually spot more confident moment you can extend the
paragraph"; then, asked, "Move the boundary", "S×W picks, voice names top",
"Keep the skip", "Split into two").** The Take shows the two moments with the
highest willfidence (S × W), however low, at most one per ~75-word block and
no longer one per slide, so both can be on one long slide; clips with enough
words still rank first. Of the two, the stronger voice is "your most confident
moment", and each is still praised or corrected by its own voice (N108). When
the two best clips share a block, the boundary between them moves so each
gets a block of its own (40 to 120 words, never across a slide, never cutting
a clip; a typed partition exception, contract 24a), and a Take of one block is
split in two the same way when each clip has 5 words or more. A Take shows
fewer than two only when it has fewer than two clips that can be played. A
correction with nothing to offer is still skipped (N108). No new words on
screen. The rules: flow page C2, H1 (frontend [`docs/flows/feedback-walk-and-chat.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/feedback-walk-and-chat.md), frontend [#944](https://github.com/wilplus/frontend-cursor/pull/944)). Its core built 2026-10-23 (the flow page's §6 names the pull requests); the boundary move and the one-block split built 2026-10-24 (N128). No migration.

**N119 · Three moments to judge every walk: high, middle and low, three
speakers, and the imported corpus may be played to speakers (founder, the
Claude Code chat, 23 October 2026: "I am choosing that my audience is only me,
but still I should be getting the judgements to do from the training corpus";
"3 clips (high, middle, low willfidence) from 3 different speakers ... ok,
let's plan that"; then, asked, "Yes, the basis covers it", "First in their
level", "Show fewer").** Found: the walk's training clips were read only from
the licensed corpus table (`corpus_clips`, 0410), which nothing fills, so with
no community clips the queue was empty and the step was left out without a
word; the clips the coaches judge are the imported training corpus, a
different store. Now every walk asks for three moments, one the machine reads
high, one in the middle and one low, each from a different speaker, never the
speaker's own or one already judged, in a blind order, fixed per Take; a
community clip takes its level's place first and the training corpus fills
the rest. The training corpus is the imported clips the coaches judge, played
to speakers anonymously, audio only, under the corpus basis (CO2, N58), and
the licensed corpus; this amends CM1 A ("the training clips mixed into judging
are the licensed corpus") and replaces N97's one moment per try. With fewer
than three different speakers it shows fewer, never one speaker twice; an
empty queue is logged. A speaker's answer on a training clip is never a label
(L3). No new words on screen. The rules: flow page C8, G4 (frontend [`docs/flows/feedback-walk-and-chat.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/feedback-walk-and-chat.md), frontend [#945](https://github.com/wilplus/frontend-cursor/pull/945)). Built 2026-10-24 (the flow page's §6 names the pull requests), with one migration, `migrations/a_speaker_may_judge_an_imported_clip.sql` (speakers' answers on imported clips, `import_clip_answers`).

**N120 · The walk speaks like a coach: a hello with the name, the praise as
one sentence, the AI clip in one short bubble (founder, the Claude Code chat,
23 October 2026: "could we make it more flexible and human like more
appealing and inviting for the user?"; "as a coach I would use here more
friendly language and make it shorter focused on one only thing without the
general assessment, like one word for the general"; "say it stronger; or lean
on this sentence"; "also add the name at the start: Hi Artur, good to see you
back! It seems like this was your most confident moment, cause it was nice and
steady, no question mark at the end, you simply fired it!"; then every line
below signed, "Signed as drafted").** The walk opens once with "Hi {name},
good to see you back!" ("Hi {name}, great to meet you!" on Take 1; without a
name, the same lines without it), the first name from the account. A praised
moment is one sentence built from signed pieces: "It seems like this was your
most confident moment, cause it was {level}, {cue}, {closer}" on the highest,
"This one was {level}, {cue}, {closer}" on the other; the level (W1–W10) and
the clip's strongest confident voice cue still choose the pieces (a cue is
left out when none stands out), the closer rotates. The AI clip comes in one
short bubble: a one-word opener ("Nice." / "Close." / "Good."), one tip for
the problem the clip fixes ending ", like this:", the clip, then "Your turn.",
or "Try again." after a try not yet better; it replaces L4 "That was good.
But…", L3, L5 and L14–L18, and the clip keeps its label (L1). The Take's most
confident moment keeps its own line when it is corrected (N109). Every word,
verbatim: frontend flow page C0, C2, C5, C6, C7 and K, and the AI voice page's
amendment of 23 October (frontend [`docs/flows/feedback-walk-and-chat.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/feedback-walk-and-chat.md), [`docs/flows/ai-voice-practice.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/ai-voice-practice.md), frontend [#946](https://github.com/wilplus/frontend-cursor/pull/946)). Built 2026-10-23 with N122 (the one-sentence praise dropped first); the AI clip's lines are signed into `docs/SIGNED-line-bank-2026-10-06.md`. No migration.

**N121 · The rewrite gate reads the words on screen (founder, the Claude Code
chat, 23 October 2026: "But for the help where do you source the fillers? From
the corrected transcript? There won't be any fillers cause they are already
corrected bro"; then, asked, "Yes, add it to N118").** Both halves of the
rewrite gate (`services/rewrite_gate.py`) read the words the speaker sees, the
Ideal Text's own words after the silent smoothing: hesitations ("um", "uh")
that never reach the screen no longer make the words need help, and a rewrite
is a real fix only against the shown words. Until now gate 1 counted fillers
on the clip's raw transcript and gate 2 measured the lift against the worse of
the raw and the shown words, so a moment could go to a rewrite for ums the
speaker never saw and almost any rewrite passed. Hesitations reach the speaker
only through the AI clip's fillers tip (N120). Built 2026-10-23 with N118's core. The rule: flow
page H3 (frontend [#946](https://github.com/wilplus/frontend-cursor/pull/946)). No migration.

**N122 · Confident moments are practised, the praise stays short, new bubbles
land at the bottom (founder, the Claude Code chat and the review page
<https://claude.ai/artifact/R8xUjSkVfHS2vyPJw5vqYr>, 23 October 2026: "do we
practice the confident moments? I think yes we should!"; "the 3 dots loading
should be at the bottom"; "i like this old version more it is shorter!"; then
"ok this is good" on the page's six choices).** A praised moment is practised
too: after its praise, the AI clip's short bubble (N120) with the clip of its
own sentence a little stronger, up to three tries, a Good job ends it, then its
helper words; with no clip there is no practise and the praise stands on its
own. This amends the walk's "two praises and no practise" (N108) and the AI
voice lock's "Never with praise" and "Praise still never gets a clip"; up to
two more clips a Take, inside the same limits. The praise keeps its three
lines ("This was your most confident moment.", the level line, the cue line);
N120's one-sentence praise is dropped before it was built. Every new bubble,
and the typing dots before it, land at the bottom, right above the buttons, and
the thread follows them, as in the Lounge (replacing 20 October's "the newest
step comes to the top"; a door still brings its step to the top, N91). With
N118, a shown block's moment is its highest-willfidence clip that can be
served, a frozen choice kept. With N120, the first name comes from the
account (`GET /v2/user/profile` `first_name`), and the AI clip names its
`problem` and `phrase` while the app picks the signed tip. No new words on
screen. The rules: flow page B5, C2, H1, K and the AI voice page's amendment
(frontend [#947](https://github.com/wilplus/frontend-cursor/pull/947)). Built
2026-10-23 with N120 (the clip in a shown block with N118's core); the flow
pages' §6 name the pull requests. No migration.

**N123 · The asks and the walk's lines are said fresh, from their signed
meaning (founder, the Claude Code chat, 23 October 2026: "please do not make
the asks fixed all the time, please make them fairly smart like there should
be some flexibility"; asked which, "both").** Each ask after the Take (E1, E2,
the CEO panel's included) and each of the walk's own lines (the AI clip's
opener, tip and closer, the Clearer version's opener and question, Line A, the
not-yet and move-on lines, Line B and "Does this sound confident to you?")
keeps its signed line as its anchor; Will says it fresh for this speaker and
this Take (their name, their talk, how the Take went, what was said before),
one or two short sentences, never the same wording twice in a row. A check
keeps it only when it still means the signed line, carries no number or score,
keeps the speaker's own words and quoted phrase, and stays short; otherwise
the signed line shows. The founder signs the meaning and these guardrails once,
which is rule 4's OK for the wordings that pass them. The walk's lines are
written once per Take while it is processed, under its processing
authorization, so the lens and the chat agree and nothing waits. Never varied:
buttons and tap answers, the praise lines (N122), consent and sharing words,
the legal lines, the AI clip's label, "We couldn't hear that clearly. Try
again.", the safety reply. This widens N86's light touch on Will's question.
The rules: flow page K, E1, E2 and the AI voice page's amendment (frontend
[`docs/flows/feedback-walk-and-chat.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/feedback-walk-and-chat.md)). Not built yet. No migration expected.

**N124 · The rewrite rules find what speech really does (founder, the Claude
Code chat, 23 October 2026: "Let's do 1-4").** Found the same day: the frames
since 20 October showed the Clearer version on 2 of 69 shown moments, and on
the founder's own Take 4 the four rules (N85 undermining, N112 hedges, the
broken sentence, the repeated phrase) wrote nothing, while a coach would have
reworded three sentences. Four more signals, each written by a rule that only
takes words out: a restart (a phrase begun and begun again at once in the same
sentence keeps its last attempt); an approval tag at the end of a sentence
(", okay?", ", right?", ", you know?", ", yeah?" go and the sentence ends on a
full stop); a playing-down "just" ("is just a job", "if you could just", "I
just wanted to"; never "just now", "just in time", "just before", "just as");
a weak opener ("So,", "And so,", "So yeah,", "Well," at a sentence's start;
never "so that", "so far"). A restart, an approval tag or a playing-down
"just" makes the words need help on its own, as an undermining word does; the
tag and the "just" open with B10's line like undermining words. Weak openers
count with the fillers (3 or more per 100 words). One rewrite per sentence
carries every rule, and removing any of them is a real fix. A deliberate repeat
across sentences is never touched. No new words on screen. First in the build
queue, before N118. The rule: flow page H3 (frontend [`docs/flows/feedback-walk-and-chat.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/feedback-walk-and-chat.md)). Built 2026-10-23; the flow page's §6 names the pull request. No migration.

**N125 · The six questions before development, settled (founder, the Claude
Code chat, 23 October 2026: "For the 6 questions use your recommendations",
on the development plan <https://claude.ai/artifact/F1cP9grzdTLj3r83zoUmVm>).**
1. N118 is built in two parts: the core first (the pick by willfidence from
any slide, the stronger voice named most confident, a shown block's best
clip), the boundary move and the one-block split last. 2. The walk builds'
commits end with "Founder-Approved: Claude Code chat 2026-10-23, N120 N122
N123". 3. N123's fresh lines are written by the small model Will already uses
for his light touch (gpt-4o-mini), one call per Take for the walk's lines and
one per ask. 4. N124 is measured before it is tuned: the share of shown
moments with a Clearer version is read from the frames after the next ten
Takes (3% before; 15 to 35% expected for most speakers). 5. A full stop
between sentences is allowed where the speaker paused (N126). 6. Whether the
blocks re-cut by N118's second part may change their ids is decided when that
part comes. Every build still starts on the founder's go, one at a time, test
first, as the plan sets out. No migration in this entry.

**N126 · A full stop between sentences, where the speaker paused (founder,
the Claude Code chat, 23 October 2026, the recommendation of N125's question
5 taken).** On the founder's Take 4 the Ideal Text ran sentences together
where a piece ended without its full stop ("Startup is just a job It's a
job…", "we need vitality We need emotions…"). The smoothing fence of
2026-07-20 (`services/transcript_smoothing.py`) allowed one closing mark, at
the end of the document only. Now, where a piece ends with no closing mark,
the next piece begins with a capital, and the recording has a clear pause at
that seam, one full stop goes in silently; nothing else changes, and every
other change stays visible and approvable as the fence says. The rule:
frontend [`docs/flows/ideal-text.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/ideal-text.md) §2. Not built yet. No migration.

**N127 · session_sniper_metrics is dropped; user_sniper_profile stays
(founder, the Claude Code chat, 24 October 2026, an exception to "never drop
anything").** The retired Sniper dartboard's per-session table held 143 rows
(2026-03-05 to 2026-06-02), nothing writes or reads it, and no foreign key
points at it. It is dropped and leaves the retention schedule
(`retention_measurement_stores_v1`); `user_sniper_profile` is kept. Migration
0491, applied by hand after an outside review, then recorded:
[wilplus/backend-cursor#1281](https://github.com/wilplus/backend-cursor/pull/1281).

**N128 · N118's second part goes ahead, and re-cut blocks get new ids
(founder, the Claude Code chat, 24 October 2026: "Finish the 4th", then,
asked which, "Build 6, N118 extras", the answer that also gives the OK that
re-cut paragraphs get new ids; answers N125's sixth question).** When a
Take's two best clips fall in one block, the cut between them moves so each
gets a block of its own, and a Take of one block is split in two the same
way, as N118 says; the blocks this makes are new blocks with new ids, so
nothing that points at a block id is carried over to them. A Take whose
blocks are already frozen keeps them. The rule: contract 24a. No migration.

**N129 · A diagnosis and a treatment plan decide what each walk practises
(founder, the Claude Code chat, 24 October 2026: "we need to build a
modification that allows for a diagnosis and then a clear action plan for a
user depending on their deadline and then a gamified progress bar after each
take"; "before there is a need for a diagnosis few questions and voice
measurement of those like when is your presentation, why do you believe your
presentation is important ... it will relay on the voice messages from the
user right after they do the first onboarding and before they start the
practise with the slides"; "The walk stays the same this is the practise
itself. Now we need a flow that will define what goes into that walk so it
serves the purples [purpose] and solves the problem identified during the diagnosis";
then, asked, "The plan's progress", "Words + plan, machine first", "The
deadline sets it").** The direction: after onboarding and before the first
practice with slides, the speaker answers a few questions by voice message
(when the presentation is, why it matters), and their voice is measured; the
app names in words, with the speaker's own clip, the one to three things it
heard, and the plan that treats them; a coach later hears the voice messages
blind and may change the plan, never seeing the machine's guess first (Never
2). The plan's interventions, as the founder lists them: the Clearer version
for filler and repeated words; the AI version of the voice for mannerisms or
a flat voice; a coach-recorded exercise for an error of the speaker's own
that fits neither; the sniper exercise for pace that runs too fast and too
few or wrongly long pauses; judging others from the speaker's team;
recording for a bigger audience ("the crowd"); a 15-minute live coach call
every Friday or every second Friday by need; and 15 minutes of exercises in
the app three times a week, for example for two months. The deadline sets
the schedule by rule from the presentation date and the diagnosis; the
speaker may move the days. After each Take a progress bar fills with what
the speaker did (Takes, exercises, calls, the days to the presentation),
never with a measure of the voice, so Never-rule 1 stands. The walk itself
does not change: the plan decides which interventions go into it. Not
specified in full and not built: the flow is drawn as a prototype first, and
each part that meets an existing rule gets its own decision before it is
built (the consent lock's no screen before a Take, N121's hesitations kept
out of the Clearer version, contract §8 item 50 and N44's no subscriptions
for calls on a rhythm, and the retired sniper exercise, N127). No migration
in this entry.

**N130 · The Pace Circle, a live rhythm practice screen (founder, the Claude
Code chat and the "Pace Circle" brief, 24 October 2026, every recommendation
taken).** A separate practice screen, never between a Take and the Ideal
Text: one soft mid-screen circle and one puffy orange ball that guides and
never grades. Speed moves the ball left and right; how often the speaker
pauses moves it up (fewer) and down (more); the circle's rim, never the
ball, shows the pause happening now: green, then amber, then a deep amber,
never red. Measured live in the browser from the voice's loudness, with no
transcript and no provider call: syllables per second over the last ~5 s,
share of time silent over the last ~45 s, a slow, floaty ball. The centre
starts at research values and moves gradually to the speaker's own (about
half-way after 10 minutes of speech, at most 80% their own), learned from
every practice session but never leaving a healthy research band. No words
on screen while speaking beyond start and stop; listen only, nothing
recorded or stored, in the first version; the speaker practises a paragraph
of their own Ideal Text; phone and desktop; loudness left out. Before it
ships, pace and pause each get a one-line written definition. Brief:
<https://claude.ai/artifact/VJ2uSugQWmbAsmReyxuufz>. Not built yet. No
migration.

**N131 · The diagnosis and the plan, made as simple as they can be (founder,
the Claude Code chat, 24 October 2026: "please simplify it as much as you can
make it super stupid simple when it comes to design and mechanics, but do not
compromise the logic behind it"; then, asked, "Yes, tap the date", "Yes, one
minute", "Yes, one at a time", "Yes, a Take is a practice").** N129 made
simple: two questions in the Lounge, the presentation's date by a tap and one
voice message of about a minute ("Why does it matter, and what is it about?"),
which carries the reason, the topic and the voice sample the diagnosis
measures. The plan names one thing to fix first, in words with the speaker's
own clip; the other things heard follow one a week, each named when its week
starts. One practice is one Take with its walk, about 15 minutes; "3 times a
week" is three Takes, and the progress bar fills one part per Take. Drawn on
the prototype <https://claude.ai/artifact/R3FVcoDNasDY9JcR82VmDF>. Not built
yet. No migration in this entry.

**N132 · A treatment picker, and nobody is fixed (founder, the Claude Code
chat, 24 October 2026: "we need to make the matching algorithm maybe sort of
like a picker for the treatment. So first we do the diagnosis and then the
treatment. A treatment defines how the lock looks like, how the walk looks
like. And the deadline defines how the journey, user journey will look like.
So the picker is something that picks the moments, right? It is right now
like that. But now we need the treatment picker. So a new function that shows
how the treatment is adjusted to the needs of the user and what interventions
are being used"; "drop that we will fix your pace. We're not gonna fix
anything. We're just gonna help you reach another level of excellence. We're
not fixing you, you're not broken, you're just fine").** The moment picker
keeps choosing which moments a walk shows (N118). A new treatment picker
takes the diagnosis and chooses the treatment: what each walk does with its
moments and which interventions it uses, adjusted to the speaker as their
Takes go on; the deadline chooses the journey (N129, N131). No word on screen
says the speaker will be fixed or that something is wrong with them: the plan
names the next level of excellence they are working towards. The picker's
table is drafted on the prototype
<https://claude.ai/artifact/R3FVcoDNasDY9JcR82VmDF>; its open questions are
asked in the chat. Not built yet. No migration in this entry.

**N133 · The Pace Circle's three reads are defined (founder, the Claude Code
chat, 24 October 2026).** Speed, how much of the time the speaker pauses,
and the pause happening now each get a one-line operational definition, as
the construct rule requires before N130 ships: `pace-speed-v1`,
`pace-pause-share-v1` and `pace-pause-length-v1`, in
[`docs/SPEC.md`](SPEC.md) §17. Three, not two, because the screen measures
two different things about pauses. Speed leaves pauses out, so its starting
centre is the rate syllables are said while talking (about 5 a second in
English), not the brief's 4. Not built yet. No migration.

**N134 · The treatment picker's twelve decisions (founder, the decision page
<https://claude.ai/artifact/6my4BFJMsresHfmmCY18g2>, 24 October 2026, every
recommendation taken, sent from the page).** For N129, N131 and N132:
1. The treatment decides how the walk looks ("lock" read as "look").
2. A walk shows the Take's best moment and the moment where this week's
level shows most; when no moment shows the level (the speaker already does
it well), it shows the two best, as N118 does today. This amends N118's "the
two best moments" for a speaker with a plan.
3. The next level starts when the current one is reached on two Takes in a
row, or when its time runs out; the speaker then sees the next level, with
no words about their voice (Never 1 stays).
4. A level that has not moved after three Takes switches to the next
intervention in its row, and the coach sees it in their queue.
5. The level names stand: "Say it once, and it lands", "Let your key line
land", "Pauses that hold the room", "A voice that moves", "Make it yours".
6. The two questions are asked in the Lounge after consent, with "Not now,
just record"; nothing stands before a Take (the consent lock stays).
7. The Pace Circle (N130, N133) is the plan's practice for pace and pauses:
two minutes before the Take in a pace or pause week.
8. "Um" and "uh" do not count for the filler-words level: N121 stays, and
the AI voice's fillers tip covers them.
9. Mannerisms are voice habits (a rising ending, a croaky or breathy voice),
practised with the AI version of the voice.
10. Recording for the crowd waits for a later version.
11. Each Friday call is booked and paid on its own, as today (contract §8
item 50, N44, unchanged).
12. The founder is the coach on the calls, for now.
Drawn on the prototype <https://claude.ai/artifact/R3FVcoDNasDY9JcR82VmDF>.
Not built yet. No migration in this entry.

**N135 · No date means two months, said in words; one recorder (founder, the
Claude Code chat, 24 October 2026: "if there is no date yet, we assume that the
practice will take around 2 months, and we say it. So let's assume a 2 months
horizon for whatever your goal is. Put it in the nice words, please. And for
the mic, please use the mic or the recording interface that we use for the
feedback walk practice. The same. I want it unified, please").** For N131's
two questions:
1. A speaker who answers "No date yet" gets a two-month plan, whatever the
goal: three practices a week and a call every second Friday, as the treatment
picker's journey table drew for no date. The app says so in words; the
wording is drawn on the prototype
<https://claude.ai/artifact/ApK5fCkbc55aVN4iYQLdcn> for the founder's OK
(Never 4).
2. The voice message in the Lounge is recorded with the walk practise's own
recorder: the Take's recording strip (dot, clock, bar), Skip and the red Stop
(`RecordingStrip`, `RecorderFooter` in the frontend), and the message lands in
the chat as the speaker's orange voice bubble. No separate microphone button.
Not built yet. No migration.

**N136 · Every speaker is diagnosed and gets a plan; "Not now, just record"
goes (founder, the Claude Code chat, 24 October 2026: "delete does not now
just record, because we want practice. When you go to a doctor, you don't
say, oh, just check me. You ask for a treatment plan. So the same is here.
You come in and it doesn't matter if you just want to test it or not. We're
going to diagnose you and we're going to give you a treatment plan. So you can
either click your date or you can click skip the date and you're going to be
given the date. And we will tell you that in the bubble").** Amends N134 item
6 and N135:
1. The two questions are asked in the Lounge after consent and before the
first Take, and they cannot be skipped: "Not now, just record" is dropped.
This overrides N134 item 6's "nothing stands before a Take" for the first
Take, and CLAUDE.md's Never 3 ("coaches and exercises are never in the way")
for it; the founder decides whether that line is reworded.
2. Only the date can be skipped. A speaker who skips it is given a date two
months away (N135: eight weeks, three practices a week, a call every second
Friday), and Will says that date in the bubble. The words are drawn on the
prototype <https://claude.ai/artifact/ApK5fCkbc55aVN4iYQLdcn> for the
founder's OK (Never 4).
3. The voice message is recorded with the walk practise's recorder (N135)
without its Skip: the strip and the red Stop.
Not built yet. No migration.

**N137 · The two questions' words (founder, the Claude Code chat, 24 October
2026: "Ask when is your deadline, not when is your presentation. Then for the
second question, say, I assume you came here to practice for some important
event in your life. Please tell me, why does it matter and what is it
about?").** The first question reads "When is your deadline?". The second
reads "I assume you came here to practise for some important event in your
life. Please tell me, why does it matter and what is it about?" ("practise",
the verb, as the app spells it). These words are signed (Never 4); they
replace "When is your presentation?" and "Why does it matter, and what is it
about? Tell me in about a minute." on the prototype
<https://claude.ai/artifact/ApK5fCkbc55aVN4iYQLdcn>. Not built yet. No
migration.

**N138 · After the voice message, Will says what it heard and asks follow-up
questions about the goal (founder, the Claude Code chat, 24 October 2026:
"give it a little bit more context after the recording. Say something like,
okay, now I can hear you speaking about your goal and important life even. I
can already see what are your fundamental vocal cues and verbal habits. Let me
draft a plan. And then ask a couple of questions. So you can hear that person
more. You can understand where they're coming from. ... I think these
questions should not be fixed. There should be a follow-up on the goal of
theirs. And should calculate, for example, did they fit in the time? It should
calculate certain parameters. Please list out those parameters and the
questions you would ask").** For N131 and N137:
1. When the voice message is sent, Will says in a bubble that it heard the
speaker talk about their goal and can already hear their vocal cues and verbal
habits, and that it will draft the plan; the wording waits for the founder's
OK (Never 4).
2. Then Will asks a couple of follow-up questions, answered by voice with the
same recorder (N135). They are not fixed: each follows up on the speaker's own
goal and is chosen by what the diagnosis still lacks.
3. The diagnosis computes a set of parameters from the message and the answers
(for example, whether the speaker fit in the time). The list of parameters and
the question bank were proposed in the chat on the same day and wait for the
founder's picks.
Not built yet. No migration.

**N139 · At most three follow-up questions (founder, the Claude Code chat, 24
October 2026: "Please choose maximum three follow-up questions. And show me
this whole thing on the clickable prototype and make it as simple and easy to
use as possible").** N138's follow-up questions are at most three, chosen by
what the diagnosis still lacks. The prototype draws the bank as proposed in the
chat: the key-line question every time, then the first missing of audience,
talk length and slides, experience, success, worry and opening; the founder may
still change the bank and its order. They come one after another in the Lounge
chat, each answered with the same "Record your answer" button. Drawn on the prototype
<https://claude.ai/artifact/ApK5fCkbc55aVN4iYQLdcn>. Not built yet. No
migration.

**N140 · Changing the plan, coming back, and the prototype's open points
(founder, the decision page <https://claude.ai/artifact/CbvkxMeHXfnjRwQdkRDjH8>,
25 October 2026, every recommendation taken, sent from the page).** For N131
to N139:
1. The speaker changes their deadline from "Change your plan" on the plan
card; the plan recalculates (practices a week, calls, weeks and the bar).
2. The speaker picks any three practice days; with two weeks or less to go,
it is every day.
3. The level comes from the diagnosis: the speaker cannot change it and asks
the coach ("Ask your coach"). The coach changes it in the coach panel or talks
it over on the next call; a coach's change always wins (N134).
4. A new event gets the questions again and a new plan, started from a fourth
row in the plan sheet, "I have a new event". One plan runs at a time: the new
one replaces the old, which stays in the history.
5. On a practice day Will says so as the Lounge opens: "Hi Artur, good to see
you back! Today is practice 2 of 9: Let your key line land."
6. Practice days may have a reminder: opt-in and off by default, offered once
as a switch on the plan card, sent as a web push like the Life Panel's, saying
"Today's practice is ready: Let your key line land." It never counts missed
days, never says "come back" and never fires twice in a day. This widens the
Life Panel's exception to "no nudges" (founder 2026-07-30) by this one opt-in
reminder and nothing more.
7. CLAUDE.md's Never 3 is reworded narrowly, in both repos: the plan's
questions come once, before the first Take (N136).
8. The Pace Circle starts before Take 2, because Take 1 has no Ideal Text yet.
9. After the key line, the follow-up questions come in this order: audience,
talk length and slides, worry, experience, success, opening (amends N139's
drawn order).
10. "Did they fit in the time" is measured on every Take, against the length
set in the set-up.
11. The progress bar shows on the walk's end sheet and on the plan card. This
changes the locked end sheet, approved here.
12. A practise that slowed down gets its own signed lines, said in turn: "You
gave it room, and it landed." · "Slower, and every word counted." · "That pace
lets them keep up with you."
13. The answer button for no deadline stays "No date yet".
14. The other new words on the prototype
<https://claude.ai/artifact/ApK5fCkbc55aVN4iYQLdcn> (version 6) are approved
as drawn (Never 4).
Not built yet. No migration in this entry.

**N141 · The reminder's switch, and the topic from the voice message
(founder, the Claude Code chat, 25 October 2026: "OK" and "yes", to the two
questions left after N140).**
1. The practice-day reminder's switch on the plan card reads "Remind me on
practice days" (N140 item 6); the words are signed.
2. The set-up's first question, "What is the topic?", is filled in from the
voice message (N131), and the speaker can still change it. The set-up
(`RecordingSetup.tsx`) is not on the locked-screens lists, so this is an
ordinary change.
Drawn on the prototype <https://claude.ai/artifact/ApK5fCkbc55aVN4iYQLdcn>.
Not built yet. No migration.

**N142 · The pace scale is settled (founder, the Claude Code chat, 24-25
October 2026, after live tuning on the founder's bench: "that works good,
settle it").** The Pace Circle (N130) became a horizontal scale from 0 to 1
with one dot, moved only by what is known at once, every 10 ms
(`pace-scale-v1`, [`docs/SPEC.md`](SPEC.md) §17). The founder's bench at
`/admin/pace-circle` (frontend `src/app/admin/pace-circle/paceSignal.ts`)
runs these settled values:

- *Voice:* 14 dB over the room for 70 ms and 62% voice-like (pitch); the
  room is the quietest moment of the last 3 s.
- *Rising, while a voice sounds* (seconds of voice): 0 to 0.3 in 0.24 s;
  0.3 to 0.5 in 0.32 s; 0.5 to 0.6 in 3.5 s; 0.6 to 0.65 in 2.8 s; 0.65 to
  0.75 in 4.4 s; 0.75 to 1 in 11.3 s. After 22 s without a pause every
  brake is lifted and it runs into the red.
- *Holding:* a gap under 250 ms between words holds the dot, except above
  0.75, where any gap brings it down.
- *Falling, while silent* (seconds of pause): 1 to 0.75 in 0.5 s; 0.75 to
  0.6 in 0.8 s; 0.6 to 0.5 in 1 s; 0.5 to 0.4 in 2 s; 0.4 to 0.37 in 0.3 s;
  0.37 to 0 in 9.3 s.
- *Colour by place:* green from about 0.28 to 0.72, orange towards the ends,
  red in the last 0.08 at each end.

It replaces the bench's earlier reads (N133, N134 were never built for
speakers). Founder's bench only; the speaker's screen is not built and will
show no number. No migration.

**N143 · A link without a price can set its own meeting length (founder, the
Claude Code chat, 25 October 2026: "I want to do the link without the price,
but also the time set, specifically for that link, which is going to be like
15 minutes by default, but I can change it").**
1. On /admin/booking, "Make a link without a price" has a length beside it:
15 minutes unless the founder changes it (15 to 240).
2. The length is part of the signed link. The booking page, the open times and
the booking itself use it instead of the page's length, and times shorter than
30 minutes start on the quarter hour. Editing the length in the URL gives the
normal page. Links made before this keep working, at the page's length.
3. It is for new people on the corporate plan: they open the link, sign up on
the way in (as every booking link already asks), pick a time for the kick-off
session at their earliest convenience, and pay nothing.
Built with this entry. No migration.

**N144 · A booking can carry a WhatsApp number: the confirmation and a
reminder 1 hour before go there (founder, the Claude Code chat, 25 October
2026: "Can you make it possible to confirm the date / sign up using what's app
and have the remainder 1h earlier sent to them", then, to three questions: the
number on the booking form, every booking with a number, "Use these words").**
1. Sign-up stays as it is (email or Google). The booking form's last step asks
for a WhatsApp number, optionally: "WhatsApp number (optional)", and under it
"We'll confirm your time here and remind you 1 hour before." The field shows
the Lounge's example number (+44 7700 900123), and a number without its
country code gets the Lounge's words for it.
2. Every booking that leaves a number gets, on WhatsApp, the confirmation:
"You're booked with Artur Willoński: {date and time}. Join on Google Meet:
{link}", and 1 hour before: "Your session with Artur Willoński starts in 1
hour, at {time}. Join on Google Meet: {link}". Times are in the person's own
time zone. The emails and the calendar invite stay as they are.
3. The number is kept on the booking, for these two messages only; it is not
the Lounge's number for the coach's feedback. Closing the account deletes it
with the booking, or wipes it from a paid lesson's accounting record.
4. Both messages are Meta templates the founder submits (category Utility)
with the words above, {{1}} for the date and time and {{2}} for the link.
Until Meta approves them, a message reaches only a person who wrote to the
number in the last 24 hours.
Open: Privacy 3.6 names WhatsApp for the coach's message; whether it needs a
line for the booking's two messages is the founder's call.
Migration 0491 (two columns on bookings). A Railway cron service runs every 5
minutes.

**N145 · The diagnosis's first version (founder, the Claude Code chat, 26
October 2026: "2. Yes. 3. Okay. 4. Okay.", to decisions 2 to 4 of the build
plan <https://claude.ai/artifact/5wuXkBNDctRcbxYs9V7R8A>).** For N129 to N141:
1. The diagnosis may use the readings still in their silent shadow stage
(filler words, hedges, restarts, a flat voice, a quiet voice); the founder
checks each new plan for the first weeks. Nothing else is promoted: those
readings still route nothing outside the plan.
2. The follow-up questions are signed templates, filled in by the AI with the
speaker's own words (their event, their audience, their date); the plain
template is the fallback when the AI fails. Never 4 holds.
3. The first version picks levels only from what is measured today. "A voice
that moves" uses pitch range until rising endings and a croaky or breathy
voice are measured.
Not built yet. No migration.

**N146 · The questions are for onboarding only; the plan's docs extend three
pages (founder, the Claude Code chat, 26 October 2026: "not all the questions
that is only for the onboading!" and "yes", to decisions 1 and 5 of the build
plan <https://claude.ai/artifact/5wuXkBNDctRcbxYs9V7R8A>).**
1. The two questions and the follow-ups (N131, N137 to N139) are the
onboarding: a new speaker answers them before the first Take. A speaker who
already has Takes does not go through them; what such a speaker gets instead
is asked in the same chat and logged when answered.
2. No new doc for the plan: it becomes a section of the frontend's
`docs/flows/feedback-walk-and-chat.md`, which already holds the Lounge chat;
`docs/flows/consent-screens.md` gets one line (Agree and continue opens the
questions) and `docs/flows/recording-screens.md` one line (the topic arrives
filled in, N141).
Not built yet. No migration.

**N147 · A speaker who already has Takes gets one question (founder, the
Claude Code chat, 26 October 2026: "A", to the choice left open in N146).**
Before their next Take, a speaker who already has Takes is asked only "When is
your deadline?" in the Lounge (a date, or "No date yet", N135), and their plan
is built from the Takes they have recorded: no voice message and no follow-up
questions. The rest of the plan (N131 to N146) applies to them as to a new
speaker. Not built yet; the founder holds the build (26 October: "not yet").
No migration.

**N148 · Stress and readiness, from 1 to 10 (founder, the Claude Code chat, 26
October 2026: "When the deadline comes, we can ask them to rate their stress
from 1 to 10 and how ready they feel from 1 to 10. And after first practice,
we can also ask them, no, before the practice, we can also ask them how ready
they are and from 1 to 10").**
1. Before the first practice, the speaker rates how ready they feel, from 1 to
10.
2. When the deadline comes, the speaker rates their stress and how ready they
feel, each from 1 to 10.
These are the speaker's own answers, not scores the app gives. How they are
used and whether they are ever shown back (Never 1), where the questions sit,
and what follows the deadline's ratings are asked in the same chat and logged
when answered. Not built yet. No migration.

**N149 · Stress before the first Take, feelings before every other, and the
summary call (founder, the Claude Code chat, 26 October 2026: "replace the
emotional assessment with the stress rating before the first take and then
keep the 4 or 5 emotions before every take and don't do the stress assessment
until the last lesson ... When the project is finished, there usually should
be to choose the call with the coach, like a summary call. Choose a date for
the summary call and a button to go to the booking page, 15 minutes one. And
to all the rest, yes").** For N148:
1. Before the first Take, the stress rating (1 to 10) takes the place of the
feelings check ("How do you feel?"). It is asked with the readiness rating at
the end of the onboarding questions, right before the plan card.
2. From Take 2 on, the feelings check (its four answers) comes before every
Take. Today it is asked once, before Take 1; this widens it. Before the feelings
check leaves Take 1, everything it feeds is listed and kept (CLAUDE.md,
"Replacing a feature").
3. Stress is asked again only at the deadline, with readiness (N148).
4. The ratings are never shown back to the speaker as numbers; the founder and
the coach see them, and Will speaks of them only in words (Never 1).
5. The deadline's ratings come the first time the speaker opens the app on or
after the deadline day. Then Will asks "How did it go?" (a voice message),
offers the summary call (a 15-minute call with the coach: the speaker chooses
a date on the booking page, booked and paid on its own as today, N44), and
asks what's next: "I have a new event" (the questions again, a new plan) or
"Keep practising" (a new two-month plan from their Takes, no questions).
6. A new project asks "Is this for 14 November?" (the plan's deadline): yes
keeps the plan, no starts "When is your deadline?" and the questions for a new
plan. New slides or a rewrite for the same event keep the plan as it is.
Drawn on the prototype <https://claude.ai/artifact/ApK5fCkbc55aVN4iYQLdcn>.
Not built yet. No migration.

**N150 · Will's replies in the intake read what the speaker said (founder,
the Claude Code chat, 26 October 2026, on the prototype's bubbles "Thank you.
Now I can hear you talking about your goal and why it matters...": "Please make
sure these bubbles are actually smart, so they read from the context from what
the user said").** For N138, N139 and N145:
1. Will's reply to the voice message names the speaker's own event, date and
why it matters, in their words (for example, "Thank you. On 14 November you'll
ask the board for two more hires, and your team's funding for next year rides
on it."), then says "I can already hear your main vocal cues and verbal
habits." and "Let me draft your plan. A few more questions first."
2. Each follow-up may open by naming what the speaker just said, and its
template fits their event: a part that cannot apply is left out (a toast gets
no slides question) and a worry they already named is asked about in their
words.
3. The AI writes these within fixed rules: the speaker's own words and facts
only, no judgement of how they spoke, no numbers, no promises, nothing about
fixing them (N132); when the AI fails, the plain signed template is said.
Drawn on the prototype <https://claude.ai/artifact/ApK5fCkbc55aVN4iYQLdcn>.
Not built yet. No migration.

**N151 · Stress and readiness on a plan's first and last practice; "How do
you feel?" on every practice between (founder, the Claude Code chat, 26
October 2026: "on the first take of the lesson, so like for the first time
user, give them the scale from 1 to 10, but on the next takes, when they
practice already, they should not be seeing anything like that, just the how
do you feel, the usual how do you feel. But on the first and the last practice
day or practice at all, there should be the stress and the other one,
assessment, and then how do you feel, screen should be removed"; then "Last
practice replaces it" and "Every plan", the two recommended answers).** For
N148 and N149, changing N149 items 3 and 5:
1. "How do you feel?" (Nervous, Excited, Calm, Not sure) is today's screen and
stays as it is. Today it shows once per new project, before Take 1.
2. A plan's first practice and its last practice get the stress and readiness
ratings (1 to 10) and no "How do you feel?". On the first practice the ratings
come at the end of the onboarding questions, before the plan card (N149 item
1).
3. The last practice is the speaker's first Take on or after the plan's last
practice day, before the deadline. The ratings come before that Take, in place
of "How do you feel?".
4. Every practice in between gets only "How do you feel?" (N149 item 2), never
the ratings.
5. After the deadline the ratings are not asked again: Will asks "How did it
go?", offers the summary call and asks what's next (N149 item 5, without its
ratings).
6. Every plan works this way: a new event or "Keep practising" starts a new
plan whose first and last practice get the ratings. With "Keep practising",
which has no questions, the first ratings come before its first Take.
Drawn on the prototype <https://claude.ai/artifact/ApK5fCkbc55aVN4iYQLdcn>.
Not built yet. No migration.

**N152 · How an exercise is chosen, in one place (founder, the Claude Code
chat, 26 October 2026: "Can you sort it out so it makes sense, it's in one
place?").** The matching rule was spread over contract clauses 35b, 35c,
35g-1 and 35g-4, and four of its parts were written nowhere but the code.
Contract 35g-1 now holds the whole rule, in order: the pool, the gate, fit,
confidence level, the order (eight tie-breaks), the learned order, the 80/20
draw, one exercise per Take, and what happens when nothing fits. 35b, 35c and
35g-4 keep their detail and point to it. The four parts written in as the code
already runs them: an exercise needs its video, and its journal post published
where one is attached; one that suits no confidence level the product can place
is left out; among ties, the one suited closest to how confident the clip
sounded, then the higher editorial priority, then the exercise id. Nothing the
app does changes. The README's home doc for `services/confident_voice_practice.py`
is now the contract; `docs/MLC3-EXERCISE-ADEQUACY-DESIGN.md` stays the home of
how an exercise's outcome is measured. No migration.

**N153 · The plan card says which line and why; the practice-day reminder is
asked on WhatsApp before the first Take (founder, the Claude Code chat, 26
October 2026, on the plan card's "Here's the line that's ready for more room:":
"What is this line? Why you chose this one? Can you make it more clear, the
whole design of it, of this plan? And if you click remind me on practice days,
it should open the WhatsApp icon. And type your number. So before the start
your first recording, there should be this remind me on your practice days
bubble. The same one we have later on ... It should be the same. ... And you
can keep the change your plan").** For N132, N134, N138, N140 item 6 and N141:
1. The plan card says what the level works on and why: the speaker's key line
in their own words (their answer to the key-line question, N138), their own
recording of it, and one line on why this line, from what the diagnosis
heard. Then how they will practise. "Change your plan" stays.
2. The practice-day reminder leaves the card's switch (N140 item 6, N141, a
web push) and goes to WhatsApp. Right after the plan card, before "Start your
first recording", Will asks for it in a bubble: the same ask as today's
WhatsApp ask for the coach's feedback (`WillabWhatsAppPrompt`), the number in
the grey card, with the WhatsApp icon, then Not now | Save. "Start your first
recording" follows either answer.
3. One number serves both: the practice-day reminder and "The feedback from
your coach is in!". A number saved here means the later WhatsApp ask (from
Take 2) never comes.
4. Before it is built: Privacy 3.7 names WhatsApp only for the coach's
feedback, so a new policy version must name the reminder; Meta must approve
the reminder's message template; and the grey card's title, which today
promises the coach's message only, must name both.
The new words wait for the founder's OK (Never 4). Drawn on the prototype
<https://claude.ai/artifact/ApK5fCkbc55aVN4iYQLdcn>. Not built yet. No
migration.

**N154 · The words of N153 are approved (founder, the Claude Code chat, 26
October 2026: "You have my okay for the wording. Yeah, it has to change, like
the privacy policy, Meta, the gray card's title").** For N153, word for word
(Never 4):
1. The plan card: "How you said it" (under the speaker's recording of their
key line); "Why this line:" followed by one sentence from what the diagnosis
heard, for the board pitch "It's the sentence you want the board to remember,
and you said it a little faster than the rest. Give it more room, and it
lands."; "How you'll practise".
2. The reminder ask: "Want a WhatsApp on your practice days? Add your number."
3. The grey card's title, for both WhatsApp asks: "We'll only use it to remind
you on practice days and to tell you when your coach texted you".
4. After Save: "Saved ✓ We'll message you on WhatsApp at {number} on your
practice days and when your coach's feedback is in."
The privacy policy's new version and Meta's template for the reminder are
still needed before the reminder is built (N153 item 4). No migration.

**N155 · No practice-day reminder for now (founder, the Claude Code chat, 26
October 2026, asked whether the WhatsApp reminder of N153 is worth building at
this stage: "There's no WhatsApp reminder for now").** For N140 item 6, N141,
N153 and N154:
1. The practice-day reminder is not built for now, on WhatsApp or as a web
push. The plan card goes straight to "Start your first recording"; the card
keeps no reminder switch.
2. N153 item 1 (the clearer plan card) and "Change your plan" stand.
3. When the reminder comes, it is the WhatsApp ask under the plan card (N153
items 2 and 3) with the approved words of N154, after the new privacy version
and Meta's template (N153 item 4). Until then the WhatsApp number is asked
only as today, from Take 2, for the coach's feedback.
No migration.

**N156 · Transcripts on a person's admin page, and the CSV (founder, the
Claude Code chat, 26 October 2026: "Go with the training-yes gate, and build
the transcript column"; Linear WIL-110).**
1. Each Take row on the person's admin page (`/admin/users/<id>`, the Takes
table) shows one line of what was said. The full text is not in that list.
2. The page's Export CSV carries each Take's full transcript only for a
speaker who holds the training yes now. For anyone else the column is blank.
Only the founder can ask for it; it fails closed on any doubt; Takes of a
project the speaker erased or archived are left out; each release is logged
(who, whose, how many). The file's name carries no user id.
3. Why. Privacy 3.7 section 4 lets the person who runs WillpowerLab see
transcripts, but names no export of them, and a file on a laptop is out of
the deletion promise's reach. Naming the export in a new policy version that
everyone re-accepts is the other road; it is not taken.
4. Open for the founder: `scripts/corpus_base_rates.py` reads every
transcript with no consent filter (its output is rates only); and WIL-110's
"store them so the dev team can reach them" is wider than "the person who
runs WillpowerLab" in section 4.
Built in the frontend's `TakesExplorer.tsx` and the backend's
`services/admin_takes.py`. No migration.

**N157 · The ratings one at a time in the footer; a simpler plan; the two
calls with the coach offered before the first Take (founder, the Claude Code
chat, 26 October 2026: "The scale is shown instead of the type here. One at a
time ... Then the plan should be less crowded. Make it really simplistic. In
the bullet points ... just call it plan ... you have two meetings to schedule
with the coach, the kickoff meeting and the summary meeting ... instead of a
type here form, you just have a calendar, just like for the deadline, and you
set the date and the time ... you have one out of two booked, and you have in
your calendar already the deadline marked ... you can already do the summary
meeting, but you don't have to ... You can just click next. And then it says
you're all set. Start your first recording. Instead of the type here,
form").** For N148, N149, N151, N153 and N154:
1. Stress and readiness come one at a time: the question in the thread, its 1
to 10 scale in the footer in place of "Type here". The pick is not written
back into the thread (N149 item 4). The same at the last practice (N151).
2. The plan card is simpler: the level, its line in the speaker's own words
with their recording ("How you said it"), the reason behind "Why this line?",
then "Plan" in bullet points: the practice days, the Pace Circle, the kickoff
call and the summary call, each with its time once booked. "Your coach will
listen too, and may change it." leaves the card; "Change your plan" stays.
3. Under the card, the footer books the two calls with the coach: a calendar
like the deadline's, with the deadline marked, then a time, then "Book and
pay". The kickoff call first, before the deadline; then the summary call,
after it. The footer counts "1 of 2 booked".
4. Then Will says "You're all set." and "Start your first recording" takes
the footer's place.
5. A summary call booked here is shown at the deadline instead of being
offered again (N149 item 5).
6. The founder's answers to three questions in the chat the same morning (the
recommended answer on the first and the third): either call can wait
("Next"), so no coach stands in the way of the first Take (Never 3), and a
kickoff not booked is offered again after Take 1; booking is paid as the
booking page is paid today ("Book and pay"), and free with a link without a
price (N143); the plan's calls are these two, and the weekly call (N134 item
11) goes.
The new words wait for the founder's OK (Never 4). Drawn on the prototype
<https://claude.ai/artifact/ApK5fCkbc55aVN4iYQLdcn>. Not built yet. No
migration.

**N158 · The Sunday note, locked as a lens (founder, the Claude Code chat, 26
October 2026: "great!! lock it!", on <https://claude.ai/artifact/Bt2YEZLKhu9fLTA1deWTvo>).**
1. Only when asked, only from the week's # notes (the talk goal and the
principles held are context; Takes and the chat never reach it); Old | New
is gone. In the Lounge, "We spotted a pattern!" and the one-sentence case,
with Not now | Investigate in place of the message box; Investigate opens the
lens: the bug, the principle held, the reflection, then the new principle
with Accept or Edit. Rules and words: frontend
[`docs/flows/feedback-walk-and-chat.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/feedback-walk-and-chat.md) §1 L and K.
Not built yet; the backend half is on branch `claude/gracious-faraday-x8tin9`. No migration.

**N159 · The tempo step: one home (founder, the Claude Code chat, 26 October 2026).**
The pace scale (N130, N133, N142) and the tempo step it will drive live in one place: frontend [`docs/flows/feedback-walk-and-chat.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/feedback-walk-and-chat.md) §2 "Tempo", with its prototype in §5. Not built; no migration.

**N160 · The plan has its own flow page (founder, the Claude Code chat, 26
October 2026, shown that the plan lived only in 24 entries of this log, N129
to N157, and asked where its page should go: "Okay", to its own flow page).**
Changes N146 item 2, which made it a section of the walk's page. The plan's
rules as they stand live in the frontend's
[`docs/flows/the-plan.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/the-plan.md),
started from those entries and the same shape as the other flow pages; a
change to the plan is a line there and an entry here. The walk's page, the
consent screens' and the recording screens' each point to it with one line
(N146). The pace practice keeps its home on the walk's page (the tempo step);
where it sits is open on the plan's page. Frontend PR #967. Docs only. No
migration.

**N161 · The rating answered in the chat; the kickoff call before the plan
(founder, the Claude Code chat, 26 October 2026: "the stress assessment should
be displayed as the answer to the chat in both cases. Explain that before I
show you your plan, choose a date for a 15-minute call with a coach. This is
your kickoff event ... And do not write book and pay. Just leave book. And then
ask, do they want also to schedule the summary meeting? ... just display the
calendar again and leave skip or book now. And then display, we're all set,
and then display the plan. And try to use at most two types of font in the
plan and maximum three sizes of font. And below the plan, in the place where
the type the text is, leave only the CTA for the practice").** For N149, N151
and N157:
1. The stress and readiness picks show in the chat as the speaker's own
answer, the number they tapped, on the first and the last practice alike. This
changes N157 item 1 ("not written back"); beyond that answer the number is
never shown again, and Will speaks of it only in words (N149 item 4).
2. The calls come before the plan card: Will says "Before I show you your
plan, pick a time for a 15-minute call with your coach. It's your kickoff
call.", and the footer shows the calendar with the deadline marked, a time and
"Book". Then the summary call is offered, the calendar again with "Skip" or
"Book now", with no yes-or-no question first. "Book and pay" goes; booking
stays paid as today (N157 item 6). Either call can still wait (N157 item 6,
Never 3).
3. Then "You're all set. Here's your plan." and the card. The card uses at
most two typefaces and three sizes; under it, in place of "Type here", only
"Start your first recording".
The rules: frontend
[`docs/flows/the-plan.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/the-plan.md)
D, E and F. The new words wait for the founder's OK (Never 4). Drawn on the
prototype <https://claude.ai/artifact/ApK5fCkbc55aVN4iYQLdcn> (version 17).
Not built yet. No migration.

**N162 · The tempo step lives in the Feedback walk only (founder, the Claude
Code chat, 26 October 2026: "it should be in the walk, not in the CO panel or
anywhere else. It should be in the feedback walk only and displayed as per what
the diagnosis and the treatment plan says").**
1. The pace practice (the pace scale, N142) is a step of the Feedback walk and
nowhere else: not in the coach panel, not in the Lounge, not before the Take.
2. The walk shows it when the diagnosis and the plan say so: in a pace or pause
week, from Take 2 (N134, N140, the plan's item 5).
This settles the plan page's open point "where the pace practice sits" and
changes N134 item 7 and N140 item 8, which put it before the Take, 2 minutes.
The card's line "Before each Take this week: 2 minutes with the Pace Circle"
now needs new words, which wait for the founder's OK (Never 4). The rules:
frontend [`docs/flows/feedback-walk-and-chat.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/feedback-walk-and-chat.md)
§2 "Tempo" and [`docs/flows/the-plan.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/the-plan.md).
Not built yet. Docs only. No migration.

**N163 · The plan card's pace line is signed (founder, the Claude Code chat,
26 October 2026: "You have my okay on the wording", to "This week your walk
has a pace game").** For N162: in a pace or pause week the plan card's bullet
reads "This week your walk has a pace game", in place of "Before each Take
this week: 2 minutes with the Pace Circle" (Never 4). The rules: frontend
[`docs/flows/the-plan.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/the-plan.md)
E2 and K. Drawn on the prototype
<https://claude.ai/artifact/ApK5fCkbc55aVN4iYQLdcn> (version 18). No
migration.

**N164 · The deadline in the plan's list, in orange (founder, the Claude Code
chat, 26 October 2026, on the plan card's bullets: "add the deadline on
orange").** For N157 and N161: under "Plan", between the kickoff call and the
summary call, a bullet reads "Your deadline: {day date month}" (for example
"Your deadline: Sat 14 Nov"), the date in orange as the booked calls' times
are in green. With no date given it is the date two months away (N135). The
words wait for the founder's OK (Never 4). The rules: frontend
[`docs/flows/the-plan.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/the-plan.md)
E2. Drawn on the prototype <https://claude.ai/artifact/ApK5fCkbc55aVN4iYQLdcn>
(version 20). No migration.

**N165 · The booking's WhatsApp reminder goes 10 minutes before (founder, the
Claude Code chat, 26 October 2026, on WIL-106 "Implement booking notifications
& practice reminders": "10 min, replacing 1 hour" and "Keep N155: not now", to
two questions).** For N144 and N155:
1. A booking's WhatsApp reminder goes 10 minutes before, in place of 1 hour
before: "Your session with Artur Willoński starts in 10 minutes. Join on
Google Meet: {link}". Meta's template for it (category Utility) carries these
words, with {{1}} for the link. The calendar invite's alarm moves to 10
minutes before too.
2. The line under the booking form's WhatsApp field reads "We'll confirm your
time here and remind you 10 minutes before." This changes N144 item 1 and the
form's "We'll confirm your time here."
([frontend-cursor#962](https://github.com/wilplus/frontend-cursor/pull/962)).
That line and "no reminder for now" earlier the same day were written as an
N145 that never merged
([backend-cursor#1298](https://github.com/wilplus/backend-cursor/pull/1298));
this entry replaces it.
3. Booking needs a signed-in account (email or Google, N144 item 1), so every
booking has an email and gets the calendar invite by email; the WhatsApp
messages come on top when a number is left. A booking without an email does
not exist, so it needs nothing built.
4. The practice-day reminder stays out for now (N155).
The words are signed (Never 4). Before the code merges, Meta approves the new
template, `WHATSAPP_BOOKING_REMINDER_TEMPLATE` names it on Railway, and the
reminders' cron service runs there every 5 minutes
(`bin/railway-booking-reminders-cron.sh`, with `BOOKING_REMINDER_SECRET` on
it and on the web service). No migration.

**N167 · The practice day: "Record Take N" inside a bubble, the card closed
(founder, the Claude Code chat, 26 October 2026, on the practice day's
screen: "After the plan, I would not want to have the record second take.
I'd like to have a bubble that shows an encouragement message ... with the
button inside", then "You have my OK" to the eight points of the design
audit and their words).** For N140, N157, N161 and N164, on a practice day in
the Lounge:
1. After the plan card, one grey bubble, drawn as the app's closing message
is today (N89), with "● Record Take N" inside, under its words: "Today, one
thing: say your key line a little slower than the rest. You've got this 💪"
(the wedding toast: "take a breath before your key line"; a speaker's own
case: "give your key line a little more room"). The chat has one record
button, in the newest bubble: the previous Take's closing message keeps its
words and gives its button up, and a line written after it (a booking) moves
the bubble below. The last practice and the next plan show the same bubble
with N89's signed closing line. No "Start a new project" under it: the "+"
next to "Type here" opens the projects, as today.
2. On a practice day the card is closed: "This week's level", the level, its
line with the speaker's recording, "Why this line?", the bar. "See your
plan" opens the list and "Change your plan". Will's hello, the card and the
record button fit on the first screen.
3. Progress has one unit. Will says "Today is practice {n} of {total}." with
no level (the card names it), and the card shows the bar. "Week {n} of
{weeks}" goes; "{n} of {total} practices done. Next: {day}." stays only
after the Take, on the walk's end sheet.
4. No "Ready by {date}" heading on any plan card: the deadline is the orange
line in the list (N164), in one date format.
5. A call not booked yet reads "Book", a link that opens the same calendar in
the footer (N161), in place of "(not booked yet)"; then "Booked: {when}."
6. Text colours read on white (4.5:1): the deadline's orange #C2410C, a
booked time's green #1F7A4A, the grey #737373.
7. "How you said it" plays from a small grey button, so the record button is
the strongest action on the screen.
8. Every link (Why this line?, See your plan, Change your plan, Book) has a
fingertip's tap area; the text keeps its size.
Signed (Never 4): "This week's level", "See your plan", "Book" in the list,
the three "Today, one thing" lines and "Today is practice {n} of {total}."
The rules: frontend
[`docs/flows/the-plan.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/the-plan.md)
E and G. Drawn on the prototype <https://claude.ai/artifact/ApK5fCkbc55aVN4iYQLdcn>
(version 24). No migration.

**N168 · "Edit" next to the deadline under the calls' calendar (founder, the
Claude Code chat, 26 October 2026: "what happens if I want to update my
deadline when I realize I want to schedule a kickoff call with the coach?
Can there be a small edit next to your deadline text on the calendar?").**
For N157, N161 and N167: under the calendar that books a call with the coach,
the deadline line reads "Your deadline: {day date month}" (for example "Sat
14 Nov"), with a small "Edit" next to it.
1. "Edit" turns the same calendar into the deadline's: "Your deadline" above
it, the deadline ringed in orange, any day after today; with a call booked,
the deadline stays after the kickoff and before the summary call. "Back"
returns to the call; "Save" keeps the new date.
2. After "Save", Will says in the chat "Done. Your plan now runs to {date}."
(and "Your deadline is close, so you practise every day." when it is two
weeks away or less), as "Change your plan" does (N140). The practice days,
the bar and the plan's list follow the new date, and the calendar goes back
to the call with the new deadline marked. A call picked but not booked that
no longer fits is cleared.
3. It works wherever the calendar opens: before the plan (N161) and from a
call's "Book" in the list (N167).
Signed (Never 4): "Edit" here, and "Your deadline: {date}" under the
calendar. Before this, the deadline moved only from "Change your plan", after
the calls. The rules: frontend
[`docs/flows/the-plan.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/the-plan.md)
F. Drawn on the prototype <https://claude.ai/artifact/ApK5fCkbc55aVN4iYQLdcn>
(version 26). No migration.

**N166 · The tempo step: the defaults and the build order (founder, the
Claude Code chat, 26 October 2026: "go with the defaults").**
1. Which stretch: the one the pace scale reads furthest from the green.
2. Where: in the Feedback walk, right after the practise moment (N162).
3. Up to three tries.
4. A noisy room: the line "🤫 Find a quiet spot first." only; no listening check.
5. Built inside the walk, behind a switch, in this order: the meter moves from
the founder's bench to shared code, and the walk gets a list of interventions
(empty by default, tempo the first); the step's screen, founder-only, on a
stand-in stretch; the stretch, its reading and its topic from the backend's
per-clip pace reads; each try's path, comment and summary kept for Will (the
path only, never the audio); the signed words; then who sees it, a per-speaker
switch until the plan (N147) sets it in a pace or pause week.
The words on the step stay drafts until the founder signs them (Never 4). The
rules: frontend [`docs/flows/feedback-walk-and-chat.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/feedback-walk-and-chat.md)
§2 "Tempo". Docs only. No migration.

**N169 · The practice day in time order, and the plan for reminders
(founder, the Claude Code chat, 26 October 2026: "it shows the messages as if
today is practice 2 out of 9, and then it shows my plan ... the order of the
messages is wrong ... It's misleading", then "all ok" to the six questions on
the page <https://claude.ai/artifact/6AyadMpFL24WeaeRzibwGY>).** For N140,
N149, N154, N155 and N167:
1. The chat shows a day line, small and grey, before the first message of
each day, in the speaker's time zone: "Monday 26 October" (weekday, date,
month).
2. Will's practice-day hello is written once per practice day: the first
time the app opens that day, or when that day's reminder goes once there is
one, whichever is first. Never right after a Take, never on a day off, not
when a Take was already recorded that day. Missed practice days leave no
trace: no catch-up hello, no "you missed"; "practice {n} of {total}" counts
the Takes done plus one. A Take on a day off is a practice (N131).
3. The plan card is posted in the chat only when the plan is made or
changed. On a practice day the chat reads, under the day line: Will's hello
with the level, "Hi Artur, good to see you back! Today is practice {n} of
{total}: {level}." (N140's words), the bar under it, and "See your plan",
which opens the plan in a sheet ("Your plan", "This week's level", the list
with "Book", "Change your plan"); then today's one thing, "Today, one thing:
…", with the key line in the speaker's words, their recording and the one
"● Record Take N" (N167). This replaces N167 items 2 and 3: no card in the
chat on a practice day, and the hello names the level again.
4. A reminder and its chat message say the same words, written at the same
moment; tapping the reminder opens the chat at that day line. Every reminder
is opt-in per channel and off by default; at most one practice reminder a
day, never twice on the same local day, between 8:00 and 21:00 in the
speaker's time zone; it says what is ready, never "come back", never a count
of missed days, never a number about the voice (Never 1); outside the app it
carries the level's name at most, never the key line, transcript or
recording; it stops when the plan ends; it never stands in the way of a Take
(Never 3).
5. The practice-day reminder goes at 9:00 in the speaker's time zone by
default, changed in "Change your plan"; no new question before Take 1.
6. Its first channel is WhatsApp, with N154's words, once a privacy version
names practice reminders and Meta approves the template; web push (built
for the Life Panel) comes second. Until then N155 stands: no practice-day
reminder.
7. On the deadline's morning a short good-luck line, in the chat and on the
chosen channel; the morning after, "How did it go?" with the link outside
the app, beside N149's message in the chat. Their words wait for the
founder's OK (Never 4).
Signed (Never 4): the day line's form. The rules: frontend
[`docs/flows/the-plan.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/the-plan.md)
G and I; the chat's page names the day line. Drawn on the prototype
<https://claude.ai/artifact/ApK5fCkbc55aVN4iYQLdcn> (version 27). No
migration.

**N170 · The Sunday note comes on Sunday by itself and whenever asked, in
any wording, with an honest "nothing", from the last seven days (founder,
the Claude Code chat, 26 October 2026: "yes, log it and update the flow
page", on <https://claude.ai/artifact/M5GWxvbNPRbkEjoL2ivZxB>; then "keep it
sunday", choosing "Sunday by itself, plus when asked").**
For N158 L1: Will understands the ask by its meaning ("do you see a
pattern?", "what keeps tripping me up?", "sunday note"), not three set
phrases; with nothing to find it says so in one line ("Nothing stands out in
your notes from the last seven days yet." / "There are no # notes from the
last seven days yet.") instead of answering as usual; the case reads the
last seven days of # notes, not the calendar week. And on Sunday from 6 pm
in the speaker's time zone, once, Will brings "We spotted a pattern!" by
itself when the last seven days of # notes show one; with none, nothing is
sent, and not when a case was already shown in those seven days. This
replaces N158's "only when asked, nothing on a schedule". Never on another
day by itself; the lens is unchanged. Rules and words: frontend
[`docs/flows/feedback-walk-and-chat.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/feedback-walk-and-chat.md) §1 L1. Not built yet. No migration.

**N171 · Notifications and reminders: the Lounge is the inbox, WhatsApp the
doorbell (founder, the Claude Code chat, 26 October 2026: "all your
recommended", to the six questions after an inventory of every message the
app sends).** Four kinds, one rule each:
- *A notification* is news from someone else (the coach's feedback is in, a
  booking is confirmed). It leaves the app only when the person must know
  (WIL-74 principle 5).
- *A reminder* hands back something the person chose, with a time (a booked
  session; practice days, when they come). Only one they turned on, and it
  keeps N169 item 4's rules on every channel. No message ever asks a
  speaker to come back.
- *A signal* is news inside the app: the Lounge's bubbles and the orange dot.
- *An ask* is Will's, in the chat, at most two a Take (N94).

1. The Lounge is the inbox. Its bubbles and the orange dot stay as they are;
there is no bell, no notification centre, no unread count and no reminder
inside the app.
2. A message outside the app opens one place in it (the coach's links,
WIL-93) and never carries the content (Privacy 3.7).
3. One channel a speaker: with a WhatsApp number, the coach's WhatsApp and
no email; without one, the email. When the WhatsApp cannot be sent, the
email goes instead. The booking's emails and calendar invite stay as they
are (N165 item 3). Contract 35g-6 carries the amendment.
4. One message a coach's sitting: after a coach shares a word or a moment
answer, the message waits until the coach has shared nothing more with that
speaker for 10 minutes, then one goes for all of it, its link naming the
Take of the last share. None goes when the speaker has opened the coach's
feedback in the app meanwhile (the orange dot cleared). Was: one WhatsApp
and one email for every share (founder 2026-10-14: "any message the coach
shares").
5. The WhatsApp ask comes from Take 1, once the Take has gone to the coach:
the first ask of Take 1's chain, still at most twice in all. Within N94's
two asks, "Did this help?" waits on Take 1 rather than WhatsApp. No new
words: Will's lead-in and the ask's signed words, as from Take 2 today.
Was: never on Take 1 (confirmed 2026-10-21).
6. Replies on WhatsApp reach us: "STOP" removes the number, as Remove on
Data & consent does; any other reply is forwarded to the founder by email.
Built before any new WhatsApp reminder. The answer to "STOP" is new words
and waits for the founder's OK (Never 4).

Open: the same morning, in another chat, N169 item 6 gave the practice-day
reminder WhatsApp first and web push second. This chat's answer was the
speaker's own calendar first and WhatsApp second, with no web push for
speakers. The founder decides which stands; until then N169 item 6 does, and
N155 holds the reminder back either way.

Before the build: one new privacy version names the booking's WhatsApp
messages (N144's open point), the replies (item 6) and, when it comes, the
practice-day reminder (N153 item 4); the reply webhook's secrets are set on
Railway before it merges. The rules: frontend
[`docs/flows/feedback-walk-and-chat.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/feedback-walk-and-chat.md)
E1. Not built yet. No migration in this entry.

**N172 · Life goals: asked once after the first # note, one goal per
sitting in a lens, worked back from the horizon to the quarter, kept in the
Life Panel (founder, the Claude Code chat, 26 October 2026: "build the life
goals now", on <https://claude.ai/artifact/HaWehtwfg1jzJvGeGM1c24>, version 7;
the three open points answered the same day: Not now asks once more after
the next note, the goals live in the Life Panel, a space may hold more than
one goal).**
For the Will learning plan's step 3. Founder only (ring 6, `life_goals`).
1. Asked once right after the first # note's "Noted.", with Not now | Start
in place of the message box; Not now asks once more after the next note;
any day when asked in the speaker's own words, and then the lens opens by
itself.
2. One goal per sitting: the space that matters most; three open questions,
said or typed; Will drafts only from their words and quotes them; goal or
want ("What would having it give you?" redrafts the goal); ambitious enough;
what they give up; a horizon, then the steps worked back from it to the
quarter, with the four-week rule.
3. The ladder per goal, with the talk goal and this week's focus under the
goal the talk serves; any step changed by tapping it, a change checks the
step below, every version kept with its date.
4. Later in the build order: the clash between two goals, the quarter
coming back on its last day, and a # note that sounds like a change.
Rules and words: frontend
[`docs/flows/feedback-walk-and-chat.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/feedback-walk-and-chat.md) §1 M. The
founder's "build the life goals now" on the prototype signs its words
(Never 4). Not built yet.

**N173 · The plan's words from the three journeys, signed (founder, the
Claude Code chat, 26 October 2026: "You have my OK on the wording", on the
words marked as not signed in the prototype
<https://claude.ai/artifact/D3ytWWsMbpBrmLQYUEV7Zr>).** For N140, N149,
N151, N157, N161, N167 and N169, signed (Never 4):
1. A practice day's one thing, by level, after N167's key-line lines:
"Today, one thing: a short pause between your ideas. You've got this 💪"
(pauses) · "Today, one thing: say each idea once, without the extras. You've
got this 💪" (filler words) · "Today, one thing: lean on your numbers. You've
got this 💪" (a voice that moves) · "Today, one thing: say it like your best
moment. You've got this 💪" (make it yours).
2. The ratings' questions: "How stressed do you feel about it right now?" ·
"How ready do you feel for it right now?"
3. The calls and the plan: "Booked: {weekday date month}, {time}." ·
"You're all set. Here's your plan."
4. The day after the deadline: "Your deadline was {date}." · "How did it go?
Tell me in a voice message." · "Thank you for telling me." · "Your summary
call" · "What's next?" · "Keep practising".
5. The coach's queue, for a level that hasn't moved in three Takes (N134 item
4): "{name} · {level}" · "Three Takes without moving. Next in the row: your
video."
Not in this OK: the pace game's words (the tempo step has its own drafts on
the walk's page, N166, which the prototype drew simplified) and the deadline
morning's good-luck line (no words yet, N169 item 7). The rules: frontend
[`docs/flows/the-plan.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/the-plan.md)
K. Docs only. No migration.

**N174 · Six answers on the Doorbell Decisions page (founder, the Claude
Code chat, 26 October 2026: "all your recommended", to the six questions on
<https://claude.ai/artifact/8XPLcBbA8xmajs6LKJqLt1>).** For N155, N165, N169
and N171:
1. The practice-day reminder, when it comes (N155 stands until then): the
speaker's own calendar first, then WhatsApp for those who want it; no web
push for speakers. This settles N171's open point and changes N169 item 6.
The calendar is one the phone subscribes to, so it follows "Change your
plan" and the deadline's "Edit" and stops when the plan ends (N169 item 4);
its alarm goes at the reminder's time (9:00 by default, N169 item 5) and its
link opens the chat at that day's line. The phone rings the alarm, so the
day's hello is written when the app first opens that day (N169 item 2). The
calendar offer's words wait for the founder's OK (Never 4).
2. One message when the coach is done (N171 items 3 and 4) is built now.
3. The founder's "Homework" email, today one for every spoken Take sent to
the coach queue, becomes one email a day with the list. The coach queue in
the app still shows every Take at once.
4. backend [#1298](https://github.com/wilplus/backend-cursor/pull/1298), the
N145 that never merged, is closed: N165 replaced it.
5. The answer to "STOP" on WhatsApp is signed (Never 4): "Done. We've
stopped the WhatsApp messages and deleted your number."
6. Signing up with a WhatsApp code, in place of email or Google (talked
through in another chat, 25 and 26 October), is not built now. First count
how many people leave at the sign-up screen; the founder decides on those
numbers.
The rules: frontend
[`docs/flows/the-plan.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/the-plan.md)
G11. No migration in this entry.

**N175 · The plan card's last waiting words, signed (founder, the Claude Code
chat, 26 October 2026: "OK", to "Does your OK cover those too?" about the
words the journeys prototype showed on the plan card without marking them).**
For N153, N157, N161, N164 and N173, signed (Never 4): "Why this line?" ·
"Plan" · "Kickoff call with your coach" · "Summary call with your coach" ·
"Your deadline: {date}" (the orange line in the plan's list, N164). The rules:
frontend
[`docs/flows/the-plan.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/the-plan.md)
K. Docs only. No migration.

**N176 · The plan's remaining waiting words, signed (founder, the Claude Code
chat, 26 October 2026: "Agreed.", then "Yes, sign them all" to the list of
the plan's words still waiting).** For N140, N148, N149, N157 and N161,
signed (Never 4):
1. The follow-up templates: "What worries you most about it?" · "Have you
given a talk like this before? How did it go?" · "What has to happen for you
to call it a success?" · "How will you open? Say your first sentence." · the
plain key line, "If your audience remembers one sentence from you, what is
it? Say it the way you'll say it."
2. The ratings: "Two quick taps before your plan." · "Calm" · "Very
stressed" · "Not ready" · "Fully ready".
3. The calls: "Before I show you your plan, pick a time for a 15-minute call
with your coach. It's your kickoff call." · "{n} of 2 booked" · "Your
deadline" · "Skip" · "Book" · "Book now" · "Would you also like to book your
summary call? It's after your deadline, to look back and plan what's next."
4. The plan's end: "15 minutes with your coach, to look back and plan what's
next." · "Choose a date" · "Not now" · "Here's your next plan." · "Is this
for {date}?"
Still open: the deadline morning's good-luck line, which has no words yet
(N169 item 7); the pace game's words belong to the tempo step (N166). The
rules: frontend
[`docs/flows/the-plan.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/the-plan.md)
K. Docs only. No migration.

**N177 · The practice-day reminder: email or WhatsApp, no calendar (founder,
the Claude Code chat, 26 October 2026: "How do you mean their calendar we
don't have access to it", then "I want two options email or what's app we
don't have a add to calendar option yet").** For N169 item 6 and N174 item 1:
1. When the practice-day reminder comes (N155 stands until then), the
speaker picks one of two: an email or a WhatsApp. No calendar and no web
push. This replaces N174 item 1 (the speaker's own calendar first, then
WhatsApp).
2. Either keeps N169 item 4's rules: opt-in and off by default, at the
reminder's time (9:00 by default, N169 item 5), at most one a day and only
between 8:00 and 21:00 in the speaker's time zone, never "come back", never
a count of missed days. The email carries its own unsubscribe link.
3. The WhatsApp option keeps N154's words. The two-option offer under the
plan card and the email's words wait for the founder's OK (Never 4).
4. A lesson's reminder stays as N165 has it: the calendar invite in the
booking email rings 10 minutes before, and a WhatsApp goes too when a
number was left.
The rules: frontend
[`docs/flows/the-plan.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/the-plan.md)
G11. Not built yet. No migration.

**N178 · Six answers from the docs audit (founder, the Claude Code chat, 26
October 2026: "Answered", choosing the recommended answer to each of the eight
questions on <https://claude.ai/artifact/MGpi9Q23qqeioeXeZEKbU9>).** Two of
the eight were settled the same day in other chats: the Sunday note on Sunday
by itself (N170, which stands), and the practice-day reminder, where this
page's "calendar first" gives way to N177 (email or WhatsApp, no calendar,
which replaced N174 item 1). The other six:
1. Numbers in the plan (Never 1). A count of where the speaker is in the plan
("Practice 2 of 9", "{n} of {total} practices done") may be shown: it is not
about the voice. The speaker's own answers to the two 1 to 10 questions are
never shown back as numbers. This changes N161 item 1 (the orange bubble with
the number they tapped); how the tap is answered in the chat waits for the
founder's words (Never 4). Never 1 in both CLAUDE.md files says so. This entry
also records Never 1's earlier exception, written only in CLAUDE.md until now
(founder, 2026-10-19): a processing-progress percentage and a token price are
not about the speaker and are allowed.
2. Before a Take (Never 3). Before every Take but the first, the only thing
shown is the feelings check, one tap, with a Skip (this adds the Skip to N149
item 2). The plan's intake questions still come once, before the first Take
(N136, N140). The questions later entries put before a Take are asked after
it instead: the deadline question for a speaker who already has Takes (N147),
a new event's questions (N140 item 4), a new project's "Is this for {date}?"
(N149 item 6), and the two ratings before the last practice and before a new
plan's first Take (N151). Never 3 in both CLAUDE.md files says so.
3. The tempo step stays in the Feedback walk, before the Ideal Text (N162),
with a Skip, and the whole walk gets a time limit. This replaces N130's "never
between a Take and the Ideal Text" for the walk's own practice steps. Open:
the limit; the founder sets it.
4. Helper words: up to eight in one pick, as the app has done since 15 October
(`HELPER_WORDS_MAX = 8`). Contract clause 13 and the Ideal Text page change
from six to eight.
5. The plan stays a rules page, not a locked screen, until its first part is
built; then it is locked like the others and its files join the frontend's
`scripts/flow-pages.txt`.
6. The loop comes first. "That loop is the product" stands: when the plan and
the loop compete, the loop wins. The plan chooses what each walk practises
(N129) and never slows the loop. CLAUDE.md's "What we are building" in both
repos and the top of README.md say so. The next three builds were not named.
The rules: both CLAUDE.md files, contract clause 13, and frontend
[`docs/flows/the-plan.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/the-plan.md),
[`docs/flows/feedback-walk-and-chat.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/feedback-walk-and-chat.md)
and [`docs/flows/ideal-text.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/ideal-text.md),
in their own docs pull requests. Docs only. No migration.

**N179 · The tempo step's words are signed (founder, the Claude Code chat, 26
October 2026, shown every line in order: "Signed").** For N166 step 5, the
words of the tempo step as the prototype drew them:
- The top bar: "Tempo".
- Will's opening: "That part went fast. 🏃 Let's try a little game." (a rushed
  stretch) or "That part slowed down, with long pauses. 🐢 Let's try a little
  game." (a slow one); "Tell me more about {topic}, and keep the ball in the
  green." ({topic} the backend's few words, else "that part"); "🤫 Find a
  quiet spot first."
- The buttons: "I'm ready", "Skip", "Stop", "Practise again", "See how it
  went", "Next"; the speaker's own bubble "Try 1", "Try 2", "Try 3".
- After a try: "Better. You let it breathe." · "Still rushed. Take a breath
  after each offer." · "A bit slow. Keep the words moving between the pauses."
- The close: "Dynamic. You paused where it mattered. 🔥" · "Still rushed. Give
  each offer its own breath next Take." · "Slow. Keep the words moving between
  the pauses."
- A blocked microphone: "The microphone is blocked. Allow it for this site in
  the browser's settings, then try again."
The rules and the words: frontend
[`docs/flows/feedback-walk-and-chat.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/feedback-walk-and-chat.md)
§1 K and §2 "Tempo". Who sees the step is unchanged: the founder, and whoever
the rings panel's `tempo_step` row reaches. Docs only. No migration.

**N180 · The app is the proverbial 15 minutes a day, never more (founder, the
Claude Code chat, 26 October 2026: "This feature should not be addictive";
"we really don't want you to spending this app more than 15 minutes a day";
"learn here the base and then go and testing real life and then come for a
quick recap and practice"; "Their own physical one outside of the app";
"przysłowiowe 15 min for the training and leave to live your life outside
the digital world").**
1. The philosophy: the app teaches the base. The speaker practises it out
there, away from the phone and any app, and comes back for a short recap
and practice that keep the base fresh. No feature is built to keep someone
in the app longer: no streaks, no counts of missed days, nothing that pulls
them back for its own sake.
2. Personal details belong in the speaker's own paper notebook, outside the
app. The app keeps only the base (the goal, its steps, the speaker's
practice).
3. "15 minutes" is the proverbial 15 minutes, not a timer the speaker
watches or a limit that locks anything.
4. Where the app says it is drawn on the life goals prototype (version 8):
<https://claude.ai/artifact/HaWehtwfg1jzJvGeGM1c24>.
   - when the lens first opens;
   - when a goal is set;
   - once a day, in the chat, after about 15 minutes in the app, never
     during a Take, the processing or the Feedback walk.
   Its words wait for the founder's OK (Never 4). Not built yet.

**N181 · The Sniper is the walk's pace step, for speakers with a plan or
without one (founder, the Claude Code chat, 26 October 2026: "Sniper should
be a part of the feedback walk as one of the interventions available for
existing users", then, asked, "The pace step, as built" and "When the Take
needs it").** For N127, N129, N162, N166 and N179:
1. "The Sniper", the founder's name for the pace exercise in N129, is the
tempo step: one of the Feedback walk's interventions, right after the
practise moments, up to three tries, with a Skip (N162, N166, N178 item 3),
in the words of N179. The old Strength/Pace dartboard stays retired (N127).
2. A speaker with a plan gets it in a pace or pause week (N162). A speaker
without a plan, as every speaker has today, gets it from Take 2 whenever the
pace scale finds a stretch outside the green (N166 item 1), once in that
walk; with no such stretch, there is no step.
3. It reaches people through the rings panel's `tempo_step` row: the ring is
widened, then turned on for everyone. Until then, the founder and whoever
the ring reaches, as today.
The rules: frontend
[`docs/flows/feedback-walk-and-chat.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/feedback-walk-and-chat.md)
§2 "Tempo". No migration in this entry.

**N182 · The principles are their own feature, ring 6, not the speaking
coach (founder, the Claude Code chat, 26 October 2026: "the principles is a
ring 6 separate feature not a speaking coach but a reflection and cohesion
tool for a deeper grounding and relaxation and identity based motivation to
be a principled man woman", then, asked, "Own page, ring 6").**
1. The principles, the Sunday note that suggests them (N158, N170) and life
goals (N172), with the voice notebook's # notes they read, are one feature: a
reflection and cohesion tool for grounding, calm and identity-based
motivation, to live as a principled man or woman. It is not the speaking
coach.
2. Ring 6: the founder only, through the rings panel's rows
(`voice_notebook`, `life_goals`), until the founder widens them.
3. The Feedback walk, the plan, the coach panel and a Take's feedback and
summary never read or show the principles, the Sunday note or life goals.
4. In the app they stay where they are decided: the Sunday note and life
goals in the Lounge and their lens, the principles in the Life Panel.
5. Their rules move to their own frontend flow page,
[`docs/flows/principles.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/principles.md),
out of the walk's page; L and M keep their letters there, so N158, N170 and
N172 still point at the right rules. No migration.

**N183 · N180's three lines signed; the voice notebook stays for short
notes (founder, the Claude Code chat, 26 October 2026: "You have my okay on
the wording. You can add a small emoji about the notebook, like how to use
it with an exclamation mark and then the explanation"; "You first, then
everyone"; "Keep it for short # notes"; "it is not everyday it is when the
practice time comes", choosing "When the day's practice is done").**
For N180, on <https://claude.ai/artifact/HaWehtwfg1jzJvGeGM1c24> (version 8):
1. When the life goals lens first opens (no goal yet, no draft): "📓 Use
your notebook!", then "Keep the details in your own notebook, the paper
one. Here we keep only the base."
2. When a goal is set, after "Noted. Your … goal is set.": "That's the
base. Now go and live it. Come back for a short recap."
3. Not every day and not on a clock: on a practice day (the plan's, N140),
as soon as that day's practice is done, Will says in the chat "That's your
15 minutes for today." and "Now go and live it, away from the phone." The
practice is the 15 minutes. Nothing is locked; the message box stays. On
other days, nothing. It waits for the plan's practice days to be built; the
founder first, then everyone. This replaces the third place in N180 item 4
("once a day … after about 15 minutes in the app").
4. The voice notebook (Will learning plan step 1) stays as it is, for short
# notes for Will; the long personal writing goes in the paper notebook.
The rules: frontend [`docs/flows/principles.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/principles.md)
§1 M16 (lines 1, 2 and 4) and
[`docs/flows/the-plan.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/the-plan.md) (line 3, with the practice day).

**N184 · A saved WhatsApp number gets one check message, no code (founder,
the Claude Code chat, 26 October 2026: "mmm agreed", to "don't add a code
step. It's friction at exactly the moment someone is saying yes. Instead,
make the first message the check").** For N171 items 3 and 6:
1. No verification code for a WhatsApp number, at sign-up or when it is
saved. The number stays format-checked only (country code, 8 to 15 digits).
2. When a speaker saves a number (the Lounge's ask, a number typed in the
chat, Data & consent), one WhatsApp goes to it at once: the messages will
come here, and reply STOP if this isn't you. A STOP removes the number
(N171 item 6), so a mistyped number reaches a stranger once at most.
3. Its words, proposed: "You'll get your WillpowerLab messages here. Reply
STOP if this isn't you." They wait for the founder's OK (Never 4); the
message is a Meta template, category Utility.
4. A booking's number already gets its confirmation at once (N144); that
message is its check.
5. Built with N171 item 6 (replies reach us), after the new privacy version
and Meta's template. Not decided here: a confirmation email at sign-up.
The rules: frontend
[`docs/flows/feedback-walk-and-chat.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/feedback-walk-and-chat.md)
§2, N171's line. No migration.

**N185 · The clash between two goals: asked before the new goal is set, kept
as a step on both ladders (founder, the Claude Code chat, 26 October 2026:
"build the clash between two goals next", then choosing a row "WHEN THEY
CLASH").**
For N172 M12:
1. When a new goal is about to be set and another goal is kept, Will checks
once whether the new goal's give-up pulls against the other goal, or the
other's give-up against the new one, from their words only. If so, before
the ladder, one bubble names both in their words, then "When they clash,
which wins?" ({emoji} {space} · {emoji} {space} · ⚖️ I decide each time;
when both goals share a space, each is named by its first words), then
"Noted. On both ladders: when they clash, …".
2. Asked once per pair of goals.
3. Both ladders show a new step, WHEN THEY CLASH, with "{emoji} {space}
wins" or "You decide each time".
4. It changes by tapping like any step; the earlier answer is kept with its
date.
The rules: frontend [`docs/flows/principles.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/principles.md) §1 M12.

**N186 · The quarter comes back the first time the Lounge opens on its last
day (founder, the Claude Code chat, 26 October 2026: "build the quarter
coming back next", then choosing "the first time you open it").**
For N172 M13:
1. No clock and nothing pushed. On a goal's quarter's last day, the first
time the speaker opens the Lounge, "The quarter ends today." and "{emoji}
{step}. Did it move?" with Not now | Start are waiting there.
2. If the Lounge is not opened that day, they come the next time it is,
with "The quarter ended on {date}." in place of "The quarter ends today."
3. Once per goal and quarter. The rest of M13 stands as written: the lens,
"Did it move?", "What got in the way?", their own # notes when some match,
the next quarter's step, the ladder, "Noted.".
The rules: frontend [`docs/flows/principles.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/principles.md) §1 M13.

**N187 · The founder's time is priced at $30 for 15 minutes; no automatic
renewal (founder, the Claude Code chat, 26 October 2026: "my 15min is 30$",
"no auto renewal"; before that, "it takes me 10 minutes to review each manual
item" and "I don't record all the exercise videos sometimes when there is an
error that doesn't match the library of errors and interventions or
exercises, than i add a new one, but generally the idea is that I don't").**
1. The founder's time with a speaker is priced at $30 for 15 minutes, $2 a
minute: a 15-minute call is $30, and a 10-minute manual item (a written coach
review, a custom message) is $20. The app's machine work keeps flat token
prices (fence §6.2); the founder's minutes are priced at this rate, not as a
multiple of what the machine costs.
2. A new exercise video for the library and labelling for the training
corpus are library work, not something a speaker buys: they are not priced
per speaker.
3. No automatic renewal: purchases stay one-time packages (contract §8 items
48 to 50, N44). Linear WIL-97 ("Automatic subscription renewal") is not
built.
4. Not decided here: the packages and their prices under item 1 (a two-month
plan with its two calls, a review and a custom message), what happens to a
Take sent to the coach when no review is left, and the AI voice's limits per
speaker. Until they are, the token prices and the packages are unchanged.
No rules page. No migration.

**N188 · The plan package, a review not included, and the AI voice's limits
per speaker (founder, the decision page
<https://claude.ai/artifact/NqCyUjhU16pHTYguJxbYZo>, 26 October 2026, every
recommendation taken, sent from the page; and "plan = starter; voice slots =
1 out of 10").**
For N187:
1. A two-month plan package is sold once at $99: 150,000 tokens, the
kickoff and summary calls (15 minutes each, N157), one written coach review
and one custom message. It never renews (contract §8). It goes on sale once
the Terms describe it: Terms 3.6 still say a paid plan "renews each month".
2. The Starter, Plus and Pro token packages stay as they are; the plan is
sold beside them.
3. A Take that reaches the coach when the speaker has no review left: the
coach's queue marks it "not included" and the coach decides whether to write
the review. The speaker is never blocked, and the Take still reaches the
coach.
4. The AI voice: at most 3 new clips a day and 20 a month for each speaker
(it was 10 a day, with no monthly limit). Over a limit the walk shows the
video or nothing, and the Take is never held (Never 3). No new voice is made
while the plan's voice slots are full, counted from the voices the app has
made: Starter has 10, with 1 in use on 26 October. The month's credit stop
stays as it is.
5. An AI voice clip has no token price of its own: the Take's price covers
it (over the last 30 days a Take cost about $0.007 in OpenAI and a clip about
$0.014, against 1,000 tokens, $0.064 to $0.08).
The rules: frontend
[`docs/flows/ai-voice-practice.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/ai-voice-practice.md)
§1, the limits (item 4). Items 1 to 3 and 5 have no rules page. No migration
in this entry.

**N189 · Messages, simpler and quieter (founder, the Claude Code chat, 26
October 2026: "all your recommended", to the six changes of a notifications
audit).** For N94, N144, N165, N171 and N184:
1. No messages at night: a coach-feedback WhatsApp or email that falls due
between 21:00 and 8:00 in the speaker's time zone waits until 8:00. With no
time zone known for the speaker, it goes as today.
2. Before a lesson, one ping at a time: the calendar invite's alarm goes
back to 1 hour before; the WhatsApp stays at 10 minutes, with the join link.
This changes N165 item 1's alarm.
3. One booking confirmation: the email with the calendar invite. The
WhatsApp "You're booked" (N144 item 2) goes, so WhatsApp rings only 10
minutes before. The line under the booking form's WhatsApp field needs new
words; proposed: "We'll remind you here 10 minutes before." They wait for
the founder's OK (Never 4).
4. One ask after each Take, not two: the first that waits, in E1's order
(the CEO panel's ask, WhatsApp, the home screen, Will's question, "Did this
help?" when the Take looks off); the others wait for a later Take. So Take 1
brings the WhatsApp ask and Take 2 the home screen. This replaces N94's "at
most two asks a Take".
5. No check message when a number is saved: the app already shows the
number back ("Saved ✓ … at {number}"), and STOP to any message removes it
(N171 item 6). This replaces N184 items 2 to 4.
6. One "Messages" place for the speaker, on Data & consent: WhatsApp on or
off with the number, email on or off, practice reminders on or off with
their time. It changes a locked consent screen, so its design and words wait
for the founder's OK.
Built in this order: 5 and 4 (rules), then 2 and 3, then 1, then 6.
The rules: frontend
[`docs/flows/feedback-walk-and-chat.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/feedback-walk-and-chat.md)
C1, E1 and §2, and
[`docs/flows/consent-screens.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/consent-screens.md)
§2. No migration.

**N190 · Email and password on Data & consent (WIL-95) (founder, the Claude
Code chat, 26 October 2026: "approved, implement it", on the clickable
prototype <https://claude.ai/artifact/5tNVcdnq9PjkTyHHm9hzfT>, version 1;
copy in `docs/design/settings-email-password-2026-10-26.html`).**
1. Data & consent gets a card, **Email and password**, between Your projects
and Support: the email with Change, the password with Change.
2. Change email asks for the new email and the current password, then sends
a link to the new address and a notice to the old one. The email changes
when the link is opened. Only the new address confirms, because people
lose old work addresses; the notice tells the old one to write to
contact@willpowerlab.com if it wasn't them.
3. Change password asks for the current password and the new one twice.
The change signs the person out on their other devices and sends a notice.
**Forgot password?** under it sends a reset link to the account's email; the
link opens the live Set new password screen, which signs out everywhere, as
it does today.
4. An account that signs in with Google or LinkedIn and has no password:
the email form has no password field, and the password row reads "You sign
in with Google." with **Set a password**, which sends a link to the same
screen.
5. Every request, change and wrong password is a row in a backend security
log (`account_security_events`, migration 0493): what happened, the old and
new email where one changed, the time, the IP address and the device; never
a password. The speaker never sees it. It is deleted with the account.
6. The words are the prototype's, the ones with dashed outlines on the card
and in the five emails, approved with it. Not in the prototype and so not
signed: what an expired or already used link says. Until the founder words
it, the card shows the page's signed "Couldn’t save that. Try again."
7. The `/change-password` page, which nothing linked to, goes; the card
replaces it. The login page's Forgot password? is unchanged.
The rules: frontend [`docs/flows/consent-screens.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/consent-screens.md)
§1, "Amended 2026-10-26".

**N191 · A note that sounds like a change to this quarter: Will asks once,
under the note, with the new words only from the note (founder, the Claude
Code chat, 26 October 2026: "build the note that sounds like a change next
show it to me on the clickable prototype").**
For N172 M14, as the prototype shows it (version 9, scene 5):
1. After a # note's "Noted.", when the note sounds like a change to one
goal's quarter step, Will asks once: "Change {emoji} this quarter to
“…”?" and "Now: …. From your note: “…”", with Not now | Change. The new
words and the quote are found word for word in the note; when they are
not, or the note is no change, nothing is asked.
2. Change: "Noted. {emoji} This quarter is now “…”. “…” stays in its
history." and the ladder, the step dated and its earlier words kept. Not
now: "Noted." and nothing changes. The same note is never asked about
again, and a step never changes by itself.
3. Only the quarter step, as M14 is written: asked, the founder answered
"this quarter only is fine".
The rules: frontend [`docs/flows/principles.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/principles.md) §1 M14.

**N192 · The chat shows a Take's walk as one bubble, "Feedback walk"; an
edit says "Edited" in place (founder, the Claude Code chat, 26 October 2026:
"please show it in the chat as feedback walk; there should be just the ideal
text after the take and the feedback walk above it; and whenever smth from
the feedback walk is getting edited it should show on the feedback walk as
edited like on the whatsapp; but it should not go at the bttom like a new
message cause it is not!"; then "go with all three recommendations" and "go
with A", on the prototype <https://claude.ai/artifact/Xb51mpaFDguFdBuL8Gjv18>).**
1. In the Lounge a Take is its recording, one "Feedback walk" bubble with the
Take's date and a small arrow, and its Ideal Text card under it once the walk
is done. Everything else the walk says stays in the walk; opening a walk
posts nothing in the chat. Every step is still stored as before
(`lounge_messages`, kind `walk_step`), so Will, the summary and the coach's
queue read the same rows. This overrides "whatever happens in the walk is
shown in the chat" (the founder's own words).
2. A change to the walk after it was said (the speaker's helper words, the
coach's changed word, the summary a coach's note rewrites) is an edit: it
changes in place and reads "Edited", in the walk and on the Take's Feedback
walk. Nothing lands at the bottom.
3. The closing summary lives in the walk only. The coach's word that was there
when the walk ran stays in the walk; a word sent later lands at the bottom
under "Later · from your coach"; a changed word is Edited in place (was:
moved to the bottom, N80). The sharing choice is one line under the Take's
recording (was: three bubbles).
4. An outlined bubble has a full stroke and no tail.
The Ideal Text card alone with a black line on every paragraph that has
feedback, and one card with a Feedback walk row, were drawn and not chosen.
Signed (Never 4): "Feedback walk", "Edited". The rules: frontend
[`docs/flows/feedback-walk-and-chat.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/feedback-walk-and-chat.md)
B3, B10, B12, B13, C1, C3, D4, D5, G1 and K (frontend
[#1001](https://github.com/wilplus/frontend-cursor/pull/1001)). Not built
yet. Built in the frontend, with two small backend changes for item 3: a
coach's changed word is written at its earlier bubble's place in the thread,
marked edited (`services/take_summary.py` `coach_update_message`; today the
new version lands at the bottom and the read hides the old one), and the
coach's word served to the walk says whether it changed since it was first
shared (`services/coach_take_word.py`). No migration.

**N193 · Quiet hours use the country of residence (founder, the Claude Code
chat, 26 October 2026: "Can you assume the time zone based on what the user
said in the consent form, which country they chose?", then "yes, log it").**
For N189 item 1:
1. "No messages at night" (21:00 to 8:00) reads the speaker's time zone from
the country they gave on the acceptance screen (`country_of_residence`), so
nothing new is asked or stored. A country with one time zone uses it; small
islands an hour off (the Canaries, the Azores) are left as they are.
2. For the United States, the quiet window covers the mainland: coach
messages go only between 11:00 and 21:00 New York time (8:00 to 18:00
California).
3. A speaker abroad gets messages on their home country's clock. With no
country on record, messages go as today.
4. A practice-day reminder at a set hour (N177) needs the real time zone:
when it is built, the app saves the phone's time zone with the time the
speaker picks.
The rules: frontend
[`docs/flows/feedback-walk-and-chat.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/feedback-walk-and-chat.md)
§2, the messages line. No migration.

**N194 · The voice note is written as it is said (founder, the Claude Code
chat, 26 October 2026: "approved, build it", to the prototype
<https://claude.ai/artifact/Wfr7i2RYR7ubYHTRqS6cYe>).** For the voice
notebook (Will learning plan step 1; N182, N183):
1. A tap on the mic records at once, and the person's own orange "# " note
appears at the bottom of the thread with a cursor; the words appear in it
as they are said, the newest one or two lighter while they may still change.
The bar under the thread stays as it is: delete, the running time, send
(founder 2026-10-20).
2. On send, the hesitations fade out and the note settles into the cleaned
words: the same transcription and cleaning as today, which stay the kept
text. A small tick under the note means it is kept; then Will's typing dots
and "Noted.".
3. Only delete throws a note away. Closing or leaving the app keeps what was
said and sends it. A note that cannot leave the phone waits there with a
small clock and goes the next time the app is open with a connection; then
the clock turns into the tick.
4. A tap on one's own note opens its words in the message box to fix a word;
send replaces the note's words in the thread and in the notebook. Will does
not answer again.
5. No new words on screen; two labels only screen readers say: "Fix this
note" and "Close".
6. The live words are a preview: the audio goes in short pieces to the same
transcription provider under the processing-authorization path, and is not
kept. No migration.
The rules: frontend [`docs/flows/principles.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/principles.md) §1 B.

**N195 · Why the voice notebook exists, said before its first question
(founder, the Claude Code chat, 26 October 2026: a note before the first
message, "Look public speaking anxiety sometimes comes from the deeper
uncertainty about life; We have designed a way to keep your goals in check";
then "please imagine you are a steve pinker how would you phrase it?" and
"go with the pinker one").** For N182 and the voice notebook (Will's learning
plan, step 1): the first time the person taps the mic, before "Your notes are
private. Only you and Will read them. Keep a voice notebook?", Will says
three grey bubbles, signed (Never 4):
1. "The jitters before a talk are often about more than the talk. Underneath
is a bigger question: where is my life going?"
2. "So we made a place for your answer: your goals, in your own words."
3. "A goal you can recall is a goal you can steer by. Keep yours here, and
when the jitters come back before your next talk, we'll show you what you're
doing it for."
Once only, with the question; ring 6 as the notebook (N182). The rules:
frontend [`docs/flows/principles.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/principles.md)
A5 and K; backend [`docs/WILL-LEARNING-PLAN.md`](docs/WILL-LEARNING-PLAN.md) step 1.
Drawn on <https://claude.ai/artifact/JiF2eoxoaJmnjQYry53LKm> (version 3). Not
built yet. No migration.

**N196 · Data & consent is called "Settings" (founder, the Claude Code chat,
26 October 2026: "in the hamburger change the data & consent to
'settings'", then, asked whether the page's title and the recording
screen's line should match, "yes change it to “Settings”").**
1. The ☰ menu's row that opens `/account/data-consent` reads **Settings**.
It stays orange on light orange while you are on the page (ST1 A).
2. The page's title reads **Settings**, and so does the link to it on the
screen for an account being deleted, which shows the page's title.
3. The recording screen's line after the consent was withdrawn reads
"Recording is off because you withdrew your consent. You can turn it back on
in Settings."
4. Will's map of the app names the page Settings, so the chat sends people
to the name the menu shows.
5. The address stays `/account/data-consent`, and the documents already
accepted keep their words.
The rules: frontend [`docs/flows/consent-screens.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/consent-screens.md)
§1, "Amended 2026-10-26: the page is called Settings".

**N197 · The life goals ladders on the Life Panel's Goals screen, above the
three bets (founder, the Claude Code chat, 26 October 2026: "build the
ladders on the Life Panel screens next", then choosing on the clickable
prototype).**
For N172 M15, as the prototype shows it
(<https://claude.ai/artifact/BeKgTGi1KXvF5ruvMEiA33>, version 1):
1. On the Goals screen, above "Three bets, in order.": "Life goals", one
ladder per set goal, the same steps as the Lounge's ladder, each tap on a
step opening the lens over the panel to change it, as in the Lounge.
2. Under each ladder "Set on {date}" and "History" (then "Hide history"):
every version, newest first, dated; the panel only shows, the lens changes.
3. Under the ladders "＋ Add a goal" opens the lens on "Which matters most
right now?".
4. Before the first goal is set, the screen is as it is today: nothing new.
The words "History", "Hide history", "Set on {date}" and "＋ Add a goal"
are signed with this entry.
The rules: frontend [`docs/flows/principles.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/principles.md) §1 M15.

**N198 · Everything in tokens: three packages, each with a call with your
coach (founder, the prototype
<https://claude.ai/artifact/4WdWu3QDPmgoirUi4uJUUZ>, version 3, 26 October
2026: "accepted, start the build"; before that, in the Claude Code chat, "the
other two also get the video and the coaching session etc. just that it gets
used faster").**
For N187 and N188; it replaces N188 items 1 to 3, and N188 items 4 and 5
stand.
1. One currency. Calls, written reviews and messages with the coach are paid
in tokens, like Takes. Today's balances and every machine price are divided by
100, so nobody loses a Take: a short Take reads 10, the free grant 120. Chat
is 1 token (it would be 1.5).
2. The founder's time in tokens, 200 a minute: a 15-minute call 3,000, a
60-minute lesson 12,000, a written review 2,000, a message 2,000.
3. Every package comes with the same things: calls with the coach, an AI
analysis of every Take, and exercises built around the way the speaker
speaks. A bigger package lasts longer and costs less per token. Starter $39
for 3,900 tokens, about a month with one call; Plus $99 for 11,000, save $11,
about two months with two calls and a review; Pro $149 for 18,000, save $31,
about three months with three calls and two reviews. The savings are against
Starter's 100 tokens for $1. The $12 Starter goes; Plus was $39 and Pro $89.
Anyone who bought keeps what they hold.
4. A call can be booked with tokens, at the booking's own price, a token a
cent, so a price link or a person's own price counts the same way. Without
enough tokens, booking by card stays as it is. Tokens for a call cancelled at
least 12 hours before come back.
5. A review or a message is charged only when the speaker asks for one.
Every Take still reaches the coach; one not asked for is the coach's to
answer or not, free. Where the speaker asks is drawn next, for the founder's
OK, beside the Feedback walk (a locked screen).
6. The review's price rises from 35,000 of today's tokens (about $2.80) to
2,000 ($20): speakers who hold tokens are told before it changes, as the
Terms promise.
7. The words on the cards as the prototype shows them. The new packages go
on sale once Terms 3.7 describe them; until then the build stays switched
off.
No rules page. No migration in this entry.

**N199 · The voice note: the wave first, the words follow (founder, the
Claude Code chat, 26 October 2026: "great!!!", to version 4 of the prototype
<https://claude.ai/artifact/Wfr7i2RYR7ubYHTRqS6cYe>, after the live words
were found to arrive 2 to 4 seconds behind the voice).** Amends N194 item 1
and 2:
1. A tap on the mic shows, in the person's own note, a small wave of their
voice at once, drawn on the phone; no network is waited for.
2. The words replace the wave a phrase at a time, about 2 to 4 seconds
behind the voice; a phrase is lighter until its whole piece has been heard.
The wave not yet written stays at the end of the note.
3. On send, the note stays where it is; the wave not yet written shimmers
while Will's typing dots show, then the last words land, the hesitations
fade, the tick and "Noted.".
Everything else in N194 stands. No new words on screen. No migration.
The rules: frontend [`docs/flows/principles.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/principles.md) §1 B.

**N200 · The booking reminder's words (founder, the Claude Code chat, 26
October 2026: "please rewrite the texts as if you are a steven pinker",
"short and concise though", "recommended", then "the session with your coach
starts... don't use the name and rewrite it as steven pinker pls; but still
acceptable by whatsapp as a tool").** For N165 item 1 and N189:
1. The booking's WhatsApp reminder, 10 minutes before, reads "Your coaching
session starts in 10 minutes. Join here: {link} See you there." It names no
one. This replaces N165's "Your session with Artur Willoński starts in 10
minutes. Join on Google Meet: {link}".
2. Meta's template `booking_reminder` (category Utility, Meta's
"Narzędzia"; English) carries these words, with {{1}} for the link. "See you
there." stays after the link because Meta refuses a template that ends with
a variable.
3. The backend's plain-text reminder (`WHATSAPP_REMINDER` in
`services/booking.py`, sent when no template is named) carries the same
words; the 10-minute code is
[backend-cursor#1321](https://github.com/wilplus/backend-cursor/pull/1321).
The words are signed (Never 4). No rules page. No migration.

**N201 · The password notice says its time in UTC (founder, the Claude Code
chat, 26 October 2026: "keep UTC in the email").**
For N190, the email "Your password was changed": the time is written as
"on 26 October at 16:40 UTC". The prototype had no time zone; the person's
own zone is not known, and a time without one would be wrong for anyone
outside UTC. Already so in `services/email_account_security.py`; nothing
changes. No rules page.

**N202 · The Feedback walk and its Ideal Text card, one pair (founder, the
Claude Code chat, 26 October 2026: "can the ideal text and the feedback walk
be similar width and always together, first the feedback walk and the ideal
text bubble next, but always as two bubble pair", then "yes, go with both
recommendations", on version 6 of the prototype
<https://claude.ai/artifact/Xb51mpaFDguFdBuL8Gjv18>).** Amends N192 item 1:
1. A Take's Feedback walk is as wide as its Ideal Text card (80% of the chat,
at most 384px) from the moment it lands, and the card sits right under it, a
few pixels apart, their left corners drawn in where they meet, as one pair.
2. The card still joins when the walk is done, not before (question 1).
3. The pair stays under the Take's recording: what lands while the walk
waits, such as the speaker writing to Will, stays under the pair, and nothing
moves (question 2).
Both answers as recommended. No new words on screen. No migration. The rules:
frontend [`docs/flows/feedback-walk-and-chat.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/feedback-walk-and-chat.md)
B3 and D4.

**N203 · The plan is built now, one to one with the prototype (founder, the
Claude Code chat, 26 October 2026: "yes, start building the plan; just like
we built it in the prototype; mach that 1 to 1").** This lifts N147's hold
("not yet"). All of the plan's rules (frontend
[`docs/flows/the-plan.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/the-plan.md)
§1, N129 onward) are built as drawn on the prototype
<https://claude.ai/artifact/ApK5fCkbc55aVN4iYQLdcn> (version 27), screen for
screen and word for word. The weeks from the plan to the deadline follow the
three journeys <https://claude.ai/artifact/D3ytWWsMbpBrmLQYUEV7Zr>. Where the
prototype and the rules disagree, the rules page says so in §3, and the
founder is asked before that part is built. It ships behind a switch, the
founder first, then new speakers, then everyone. Not in this build: what the
rules hold back (§1 J: the practice-day reminder) and the words still
waiting (the deadline's good-luck line, the chat's answer to a rating tap).
The build plan: <https://claude.ai/artifact/5wuXkBNDctRcbxYs9V7R8A>. Each of
the build's migrations gets an outside review before it merges. The rules:
frontend [`docs/flows/the-plan.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/the-plan.md)
§2. No migration in this entry.

**N204 · The plan goes on ring 5, built in one night (founder, the Claude
Code chat, 26 October 2026: "go ahead, start build 1 to the end so I can test
it in the morning please build it all; and place it on ring 5"; then, on the
migration, "Review it in the morning").** For N203:
1. The plan is one ring row, `plan`, at ring 5: everyone on ring 5 or 6 gets
it, nobody below. The row comes with the plan's migration.
2. Every build goes in now, the code switched off until the row exists. The
migration's pull request waits for the founder's outside review (GPT or
Grok) in the morning; merging it creates the tables and the row, and the
plan is on for ring 5.
3. The coach's side (Build 9) is drawn for the founder's OK, as the coach
panel is locked, and built after it.
The rules: frontend [`docs/flows/the-plan.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/the-plan.md)
§2. No migration in this entry.

**N205 · The coach answers every Take; nobody asks for it (founder, the
Claude Code chat, 26 October 2026: "There should be no option like this,
because coach writes and records for each take, at least at the beginning
months of the operation of the system, because the system needs to learn how
the coach answers and needs to get smart. So please do not do anything like
write a review or something like that. It will happen either way.").**
For N198:
1. The coach writes and records an answer to every Take, at least in the
system's first months, because the system learns from how the coach answers.
2. So there is no way to ask for a review or a message, and none is built: the
ask N198 item 5 named is dropped, with its prototype
<https://claude.ai/artifact/C3dnYam7DDicPWz142EGCd>.
3. With nothing to ask for, everything in tokens (N198) never charges for the
coach's answer to a Take: it charges for practice and for calls.
4. The price the review carries today stops now, before N198 is switched on:
a Take that reaches the coach is no longer charged its 35,000 tokens (asked
whether it should stop now, "Yes, for the first one, yes").
5. The packages' words stay as the accepted prototype shows them, "a written
review" and "two written reviews" included; anything that does not match the
prototype waits ("I accepted the design you suggested and build it like
this. Anything that does not align with the prototype that you showed to me
should be deferred.").
No rules page. No migration in this entry.

**N206 · The coach's WhatsApp carries no picture (founder, the Claude Code
chat, 26 October 2026: "i removed the image", then "feedback is active").**
For N171 and N174:
1. Meta's `feedback` template, the message that tells a speaker their
coach's feedback is in, has no picture at the top: the founder took the logo
out, and Meta approved the edit. It reads "Your coach has replied to your
latest Take. Open it to see their feedback." with one button, "See the
message", that opens the Take's feedback.
2. The backend sends no picture with it: `WHATSAPP_TEMPLATE_HEADER_IMAGE_URL`
is removed from the worker and the web service on Railway, since Meta
refuses a message whose parts differ from its template. Set it again only
with a template that has a picture header.
No rules page. No migration.

**N207 · The booking form stops asking for a WhatsApp number; the reminder
goes to the account's number; sign-up is counted before WhatsApp sign-up
(founder, the Claude Code chat, 26 October 2026: "can we remove it from the
booking page and add it on the sign up page - or add the sign up with
whatsapp? not through twilio though", then, to three questions, "Remove it,
use account number", "Count drop-off first" and "Change the words").** For
N144, N165, N171, N174 item 6 and N189:
1. The booking form no longer asks for a WhatsApp number: the field and the
line under it go. This replaces N144 item 1, N165 item 2 and N189 item 3's
proposed line; frontend
[#972](https://github.com/wilplus/frontend-cursor/pull/972) is no longer
needed.
2. Booking needs a signed-in account (N165 item 3), so the booking's WhatsApp
reminder (N165: 10 minutes before, with the join link) goes to the number
saved on the account, the one the Lounge's ask and Settings hold. A booking
made before this keeps the number it carries. With no number saved: the
email and the calendar invite only. No "You're booked" WhatsApp goes to the
account's number (N189 item 3). This replaces N144 item 3.
3. The number was given for the coach's messages, so the words that say so
change (signed, Never 4):
   - the Lounge's WhatsApp form: "We will only use it to let you know your
     coach texted you, or that your call starts soon." (was "… texted you");
   - Settings, with a number saved: "We message {number} when your coach's
     feedback is in and 10 minutes before a booked call."
The next privacy version names the booking reminder (N171, "Before the
build"). Until it is published the reminder goes only to a number left on a
booking; `BOOKING_WHATSAPP_TO_ACCOUNT=true` on Railway turns on the
account's number (off by default).
4. Sign-up stays email, Google or LinkedIn, with no number field: Google and
LinkedIn never show the form, and the WhatsApp ask comes after Take 1.
5. Signing up with WhatsApp still waits for the count (N174 item 6). It needs
no Twilio: Supabase's Send SMS hook hands the code to the backend, which
sends it through Meta as it sends the coach's message (a Meta
Authentication template). An account made that way has no email, which the
booking's invite, receipts and password reset need; that is decided then.
6. The count N174 item 6 asks for is built now: how many people reach the
sign-up screen and how many make an account, by way (email, Google,
LinkedIn). The founder's only; no speaker sees it.
The rules: frontend
[`docs/flows/consent-screens.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/consent-screens.md)
(Settings' WhatsApp card) and
[`docs/flows/feedback-walk-and-chat.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/feedback-walk-and-chat.md)
E (the WhatsApp ask's form). No migration in this entry.

**N208 · Terms 3.7 and Privacy 3.8 are signed (founder, the sign-off page
<https://claude.ai/artifact/R65WrnFbUUFr3SEGeZaikA>, then the Claude Code
chat, 27 October 2026: "I sign as drafted, question 1 A, question 2 A").**
For N44, N104, N105, N153, N198, N205 and N207:
1. Terms 3.7 and Privacy 3.8 are signed as drafted (`copy/terms-3.7.txt`,
`copy/privacy-3.8.txt`), to be published as `phase1-2026-10-27-3.8` with AI
notice 3.2 and the 3.1 agreement unchanged. Engineering drafted them from the
code; counsel has not seen them.
2. They say what was decided: free tokens once, then packages bought once,
nothing renews (N44; Terms 3.6 still sold monthly plans); the coach's answer
costs nothing (N205); a lesson can be paid with tokens, and tokens paid for a
lesson cancelled at least 12 hours before come back (N198 item 4); WhatsApp
10 minutes before a booked lesson (N207) and, if the speaker asks for it, on
practice days (N153). They name no price and no token count, so the new
packages can go on sale without another version (N198 item 7).
3. They say what was already live and the texts in force denied or left out:
clips of imported recordings play to speakers (N119); Will's note about each
speaker (WIL-74); the history Will reads; what a speaker tells Will that
reaches the coach (N87, the goal card) or the founder (the weekly note, the
note); the training yes on a card in the Lounge; the words of the coach's
videos, written out for speakers with the training yes (N79).
4. Question 1, A: the Willfidence reading stays as N104 and N105 have it,
and the texts describe it: never shown to the speaker, seen by a coach only
after their own answer and by the founder per Take. Document 02 gets a note,
version 1.3, for counsel's next look.
5. Question 2, A: the plan (N203, N204) is named, with its own yes for the
stress and readiness answers, in the version that opens it below ring 5. Until
then ring 5 holds only people who know it is a test.
6. Publishing is the founder's step, `PUBLISH-3.8-2026-10-27.sql` in
Supabase. After it runs: `BOOKING_WHATSAPP_TO_ACCOUNT=true` on Railway (N207),
and `PRICING_V4_ENABLED=1` once token holders are told (N198).
- **Published** (founder, 27 October 2026, 06:34:33 UTC):
  `PUBLISH-3.8-2026-10-27.sql` run in Supabase. `phase1-2026-10-27-3.8` is in
  force with the signed bytes and the United States; training-only-v4 is
  unchanged and the two people with a training yes keep it. The founder set
  `PRICING_V4_ENABLED=1` on the web service and the worker the same morning,
  shortly before. Nobody had bought a package (`package_purchase` rows: 0), so
  no token holder was owed notice of the new prices.
- **Counsel** (founder, the Claude Code chat, 27 October 2026, told that
  counsel had not seen them: "they ve seen ti and they accept it!!!"): counsel has seen Terms 3.7, Privacy 3.8
  and the document 02 v1.3 note, and accepts them.
No rules page. No migration in this entry.

**N209 · The level's moment in the walk and a level moving on: four calls
(founder, the Claude Code chat, 27 October 2026, "build G7 and G10 next";
then, asked, every recommendation taken: "Level's own check", "One", "Next
thing heard", "Note it, walk unchanged").** For N134 items 2 to 4, N203 and
the plan's G7 and G10:
1. A Take reaches this week's level when the same check that picked the level
no longer fires on that Take, read on the whole Take (the key line no longer
faster than the rest; pauses no longer few and short; filler words no longer
many; the pitch no longer flat). Never shown, as a number or in words
(Never 1). This answers the first of the two calls the plan's rules page
held open since 26 October.
2. One of the walk's two moments goes to the level: the Take's best moment,
then the moment where this week's level shows most; when no moment shows it,
the two best, as today (N134 item 2). This answers the second call.
3. After two Takes in a row reach the level, or when its time runs out, the
next level is the next thing heard: strongest first, the next level whose
check fires on the latest Take, skipping the levels this plan already had;
when none fires, "Make it yours". "Make it yours" stays. A coach's level is
never moved by the machine (C5).
4. Three Takes on a level without moving are noted for the coach's queue.
Until the coach's side is built (N204 item 3), the walk keeps the level's own
practice; the coach's recorded exercise comes with it.
The rules: frontend [`docs/flows/the-plan.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/the-plan.md)
§1 G7 and G10. No migration in this entry.

**N210 · No price after the pricing page (founder, the Claude Code chat, 27
October 2026: "what I would like to have is that the user does not know that
the coach charges them … It's just for us to calculate how much package should
be … once they see the price on the pricing page, they don't see any prices
later on", then, to two options, "go with A").** For N187, N198 and N208:
1. A speaker sees prices on the pricing page (the package cards) and in the
offers that repeat it: the Lounge's out-of-tokens packages and a price the
founder sends them. Nowhere else: the feedback bubble in the Lounge shows no
price, and Will names no price; he points to the pricing page.
2. The coach's time is an internal number, 200 tokens a minute (N198 item 2),
used to size the packages. No screen shows a call or a lesson in tokens: the
wallet's two lines for them go. A call booked at $0 shows no token price.
3. The wallet keeps the balance and, behind "Show more", its list of what
things cost and the recent spending: Terms 3.7 §2 promises "The price of each
thing in tokens is shown in the app before you use it", and a buyer must be
able to find what their tokens pay for. Hiding those too (option B) would need
a new Terms version that every speaker accepts again; it is not taken.
4. If a call is given a price again, how it is shown is decided then.
No rules page. No migration in this entry.

**N211 · The plan's personal answers get their own yes; the feelings check gets
a Skip now (founder, the Claude Code chat, 27 October 2026, to the draft page
<https://claude.ai/artifact/FFTYRbR3cyMAp229Dy4eYx> and its three questions,
each with a suggested answer: "Go with the suggested answers").** For N148,
N149, N151, N178 and N208 item 5:
1. The plan's personal answers are asked only after the speaker says yes to a
question of its own, once, before them: "Yes, ask me" or "Not now". They are
the worry follow-up ("What worries you most about it?"), the stress and
readiness taps, how the speaker feels before a Take, and "How did it go?" at
the plan's end. With "Not now" none is asked and the plan is built from the
rest. The yes can be changed on a card in Data & consent, "Personal answers in
your plan"; turning it off deletes the personal answers given so far.
(Question 1, A.)
2. The feelings check, "How do you feel?", shows only after that yes, with a
Skip every time. (Question 2, A.)
3. The text and the yes ship together, in Privacy 3.9, before the plan reaches
anyone beyond ring 5's testers; the text that goes with them is drafted on the
page above and waits for the founder's signature. Meanwhile the feelings check
gets a Skip wherever it shows, now: until today a new project's check, once
before Take 1, had none unless a plan's first Take was already recorded.
(Question 3, A.)
4. Not decided here: the words of the ask and of the card (new words on locked
screens, Never 4), which wait for the founder's OK on a prototype; where the
yes is asked for a speaker who has no plan; and the final text of Privacy 3.9.
The rules: frontend
[`docs/flows/the-plan.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/the-plan.md)
§1 A and D (the questions "can't be skipped" stops applying to the personal
ones when the yes is built) and
[`docs/flows/recording-screens.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/recording-screens.md).
No migration in this entry; the consent record's migration comes with its
build, and an outside review.
- **Counsel** (founder, the Claude Code chat, 27 October 2026, after being
told that counsel should see the final text before the founder signs:
"counsle agrees"): counsel agrees with the plan's consent as decided above,
its own yes before the personal answers. The final text of Privacy 3.9 goes
back to counsel with the signature page, as for 3.8.
- **The words** (founder, the Claude Code chat, 27 October 2026, to the
prototype <https://claude.ai/artifact/3GtUo7eVdf9SAhZQCDsTR7>: "approved as
drawn"): approved, the new words included. The ask: "A few of my questions
are personal: how stressed and how ready you feel, what worries you, and how
you feel before each Take. I only ask with your yes. Your coach and I use your
answers to shape your plan. You can turn this off in Data & consent." with
"Yes, ask me" and "Not now" (and Read more). The card, "Personal answers in
your plan": "Will asks how stressed and how ready you feel, what worries you,
and how you feel before each Take. Your coach and Will use the answers to
shape your plan." with Turn on / Turn off; its off line, "Off. Turn it on and
Will asks how stressed and how ready you feel, what worries you, and how you
feel before each Take."; its question, "Turn off personal answers?" with "We
stop asking, and delete the personal answers you have given. Your plan
stays."; its outcome, "Off. We deleted your personal answers." The ask comes
once, after the speaker's voice answer about the event, before any personal
question; "Not now" writes no line of Will's. Built switched off
(`PLAN_CONSENT_ENABLED`) until Privacy 3.9 is published, so the ring 5
testers' plan does not change before then.

**N212 · The principles open to ring 5 (founder, the Claude Code chat, 27
October 2026: "open principles to ring 5").** Amends N182 item 2:
1. The principles (the voice notebook's # notes, the Sunday note and life
goals) reach ring 5 and ring 6, through the rings panel's two rows,
`voice_notebook` and `life_goals`, each set to ring 5. Nobody below ring 5.
2. Everything else in N182 stands: their own feature, apart from the
speaking coach; the walk, the plan, the coach panel and a Take's feedback
never read or show them; private, never shown to a coach. Each speaker still
says Yes to the notebook before it records.
3. Ring 5 holds only people who know it is a test (N208 item 5).
The rules: frontend [`docs/flows/principles.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/principles.md)
§1 A. No migration: the founder sets the two rows on the admin's rings page.

**N213 · The coach's side of the plan is built as drawn (founder, the Claude
Code chat, 27 October 2026, to the clickable prototype
<https://claude.ai/artifact/QznwCAgkBHAVAGDMKVUKvE> and the question "Should I
build the coach's side of the plan now, exactly as the clickable prototype
draws it?": "Build it, words OK", then "OK, build the coach's side").** For
N204 item 3, N209 item 4, N211 and N173:
1. A plan reaches the coach's queue on the speaker's card, beside their Takes:
"New plan" when the machine has picked a level no coach has picked yet,
"Asked about their level" after the speaker's "Ask your coach", "Three Takes
without moving" when a level is noted stuck; with the orange dot. On the
speaker's page a "Their plan" card sits above their Takes.
2. A new plan and "Asked about their level" open "Which level comes first?":
the speaker's voice message ("Why it matters") and their key line ("Their key
line"), then the five levels. Blind: nothing about the machine's level is
fetched before the coach picks (Never 2).
3. After the pick, "What happened": You, The machine heard, the Deadline, and
Stress and Ready when the speaker gave them (N211). "Keep yours" keeps the
coach's level, which the machine never moves (C5); "Change my answer" goes
back to the five levels.
4. A level noted stuck opens on the level's name and "Three Takes without
moving. Next in the row: your video." (N173), the panel's own Record, then
"Ready for {p}" and "Share with {p}". The video reaches the speaker as the
coach's word on their latest Take ("Later · from your coach", opening their
walk), the way a coach's word already does (coach panel G2 to G4).
5. The new words are OK'd: "New plan", "Their plan", "Which level comes
first?", "Why it matters", "Their key line", "Keep yours", "Asked about their
level", "Deadline", "Stress", "Ready".
The rules: frontend
[`docs/flows/the-plan.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/the-plan.md)
§1 C5, G10 and H1, and
[`docs/flows/coach-panel.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/coach-panel.md).
No migration in this entry.

**N214 · Sign up and sign in with WhatsApp, built now and on (founder, the
Claude Code chat, 27 October 2026, on the clickable prototype
<https://claude.ai/artifact/Dcf2FCyDs5c4Pb7BJc7oZ7>: "ok, looks good", then,
to four questions, "Build now, switched on", "Ask for email later", "Add it
in Settings first" and "Yes, use them as shown"; then the remaining words,
each "use these words").** For N174 item 6, N184 item 1 and N207 items 4 and
5:
1. The sign-up page gets "Sign up with WhatsApp", first, above LinkedIn,
Google and email. It is built now and goes on once it is built, Supabase is
set up and the new privacy version names it; it no longer waits for the
sign-up count, which keeps running. This replaces N174 item 6 and N207
item 5.
2. The flow, as the prototype draws it: the number, with its country code
(the Lounge's words when it has none); a code by WhatsApp; the code typed
in; the name; then in. The number becomes the account's WhatsApp number, so
the WhatsApp ask after Take 1 does not come (N189). The code proves the
number is theirs: for this way in only, it replaces N184 item 1's "no code".
3. The code: Supabase makes and checks it (6 digits, valid 10 minutes). Its
Send SMS hook hands it to the backend, which sends it through Meta's
WhatsApp API with the Authentication template `login_code` (English, Copy
code; Meta's own words: "{code} is your verification code. For your
security, do not share this code." and "This code expires in 10 minutes.";
the founder submitted it on 27 October 2026). No Twilio.
4. No email at sign-up. The email is asked for only when something needs it:
booking a call (the calendar invite) and buying tokens (the receipt). On the
booking form, an account with no email gets an "Email" field with "We'll
send your calendar invite here." under it; the email is saved to the
account, so receipts and later invites use it too.
5. Sign in with WhatsApp: the login page's "Sign in with WhatsApp" signs in
only a number that is already an account's way in, and never makes a new
account. A number that is not: "No account signs in with this number. Sign
in another way, or sign up with WhatsApp." ("sign up with WhatsApp" links to
the sign-up page). Someone who signed up with email, Google or LinkedIn adds
WhatsApp as a way in from Settings, in the "Email and password" card: off,
"WhatsApp", "Sign in with your WhatsApp number too." and "Add" (then the
number and the code); on, "You can sign in with WhatsApp at {number}." A
WhatsApp account's card says the same, with no email row until it has one.
6. The words, signed (Never 4): "Sign up with WhatsApp", "Your WhatsApp
number", "Send code", "Enter the code we sent you on WhatsApp", "Resend
code", "Use a different number", "That code didn't work. Try again.", "What
should we call you?", "Continue".
Before it goes on: Meta approves `login_code`; the new privacy version names
the phone number as a way to sign in; in Supabase, phone sign-in is on and
the Send SMS hook points at the backend, with its secret on Railway.
No rules page yet: the Settings row lands on frontend
`docs/flows/consent-screens.md` with its build. No migration in this entry.

**N215 · No ask, and no card, for a speaker without a plan (founder, the
Claude Code chat, 27 October 2026, on the draft of a separate ask for them:
"do not add that", then, asked which part, "The whole ask for speakers without
a plan").** For N211 item 4:
1. A speaker who has no plan is not asked for the plan's yes, in the Lounge or
anywhere else, and gets no card in Data & consent for it. The ask drawn for
them on <https://claude.ai/artifact/9ELP4RVTtXjDQJqXRzGGM2> is not built, and
its words are not in force.
2. "How do you feel?" stays as it is today for a speaker without a plan, with
its Skip, until they have a plan (founder, the Claude Code chat, 27 October
2026, to the question what the tap does for them: "Leave it as today until
they have a plan"). When a plan reaches them it is asked behind the plan's own
yes (N211 item 2), and Privacy 3.9's section 4e names the plan's answers only.
3. Still to build before the switch, `PLAN_CONSENT_ENABLED`, goes on: the tap
behind the yes for a speaker who has a plan. The plan's own ask and card are
built and merged, switched off (backend #1416, frontend #1028).
No rules page: nothing is built for item 1 or 2; item 3 lands on frontend `docs/flows/the-plan.md` D4 with its build. No migration in this entry.

**N216 · Privacy 3.9 is one version for the plan and WhatsApp sign-in
(founder, the Claude Code chat, 27 October 2026, asked whether Privacy 3.9
also covers WhatsApp sign-in: "Yes, one 3.9 for both").** For N211 item 3,
N214 and N215:
1. Privacy 3.9 names, in one version: the plan and its personal answers behind
their own yes (section 4e, N211); "How do you feel?" before a Take, for every
speaker, which today's Privacy 3.8 does not name (N215 item 2); and the
WhatsApp number as a way to sign up and sign in, with its code by WhatsApp
(N214).
2. One draft, one signature, one read by counsel, and one update prompt for
speakers. The text is drafted next and waits for the founder's signature.
No rules page: the text lands in `legal/phase1-2026.1/` when it is signed. No
migration in this entry.

**N217 · Terms 3.8 and Privacy 3.9 are signed (founder, the sign-off page
<https://claude.ai/artifact/HbNkdtWhYgKmXy312wL4sC>, then the Claude Code
chat, 27 October 2026: "I sign as drafted, question 1 A, question 2 A").** For N211, N214, N215 and N216:
1. Terms 3.8 and Privacy 3.9 are signed as drafted, word for word in
`legal/phase1-2026.1/30-terms-3.8-privacy-3.9-the-plan-feelings-and-whatsapp-sign-in-SIGNED-2026-10-27.md`. They name the plan, its personal answers behind
their own yes (Privacy section 4e), "How do you feel?" before a take, and
signing up and signing in with the WhatsApp number. Engineering drafted them
from the code; the session building N214 checked the WhatsApp sign-in facts
against its build. Counsel has not seen them.
2. Question 1, A: for a speaker without a plan, answering "How do you feel?"
is their explicit consent for that one answer. The tap's screen gets one line,
"Your coach sees your answer." (new words on a locked screen, OK'd by this
signature).
3. Question 2, A: every "How do you feel?" answer given before 3.9 is deleted
when 3.9 is published.
4. Before it is published: counsel reads it; built: the tap behind the yes
for a speaker who has a plan, the line on the tap's screen, the deletion of
2 and 3 run at publication, the WhatsApp sign-in screens, Meta's approval of
`login_code`; fixed: closing an account leaves its sign-in record (email, and
with WhatsApp the phone number) in Supabase, against Privacy 3.8 sections 7
and 9 and this text, so by N95 the code is the bug. The texts read "Effective
{publication date}"; on the day, only that line changes, they become the
legal pack's copy files, and a PUBLISH-3.9 script is made for the founder to
run.
The rules: frontend
[`docs/flows/recording-screens.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/recording-screens.md)
(the line on the tap's screen) and
[`docs/flows/the-plan.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/the-plan.md)
D4 and D5, each with its build. No migration in this entry.
- **Counsel** (founder, the Claude Code chat, 27 October 2026, after sending
counsel the sign-off page: "counsel agrees"): counsel agrees with Terms 3.8
and Privacy 3.9 as signed, the answers to questions 1 and 2 and the WhatsApp
messages' consent included.
- **Dated** (founder, the Claude Code chat, 28 October 2026, after Meta made
`login_code` active: "28/10/2026"): Terms 3.8 and Privacy 3.9 read "Effective
28 October 2026", the only change to the signed texts; they are
`copy/terms-3.8.txt` and `copy/privacy-3.9.txt`, published by
`PUBLISH-3.9-2026-10-28.sql` (the founder's step), which also deletes the
feelings given before 3.9 (question 2 A).
- **Published** (founder, 28 October 2026, 11:44:20 UTC):
`PUBLISH-3.9-2026-10-28.sql` run in Supabase. `phase1-2026-10-28-3.9` is in
force with the signed bytes and the United States, five purposes, all
required; training-only-v4 is unchanged and the two people with a training
yes keep it; no "How do you feel?" answer from before 3.9 is left
(`feelings_left` 0, `takes_with_a_feeling` 0).
- **On** (founder, the Claude Code chat, 28 October 2026, asked to set
`PLAN_CONSENT_ENABLED=true` on Railway: "or you can add it in the code?"): the
plan's own yes is on in the code, as WhatsApp sign-in is; nothing is set on
Railway, and `PLAN_CONSENT_ENABLED=false` turns it off.

**N218 · A deleted account's sign-in record is emptied in SQL, not soft-deleted
(founder, the Claude Code chat, 27 October 2026, asked which of the two fixes
for N217 item 4 should stay: "This PR replaces #1425").** For N217 item 4 and
N95:
1. When an account deletion is marked done, the person's Supabase sign-in
record keeps its id and nothing else that signs in or names them: email and
phone are NULL, not Supabase's soft-delete hash `sha256(user id + email)`,
which anyone holding the email can check. Password, tokens, sign-in profile
and linked sign-ins are cleared, sessions ended, refresh tokens revoked, and
it is banned. How the account signed up stays, for the sign-up count.
2. This replaces #1425's soft delete through Supabase's admin API (merged
earlier the same day). Backend #1423 (migration 0497) does it in the
transaction that marks the request done; an erasure that fails leaves the
request for the next run. Accounts deleted before it are erased by the
completion run.
3. Not in this decision: Supabase Auth's own audit log, which names the
email, and purges an operator runs by hand (service termination, lawful
deletion).
No rules page: the deletion runbook, `docs/PHASE1-PROCESSING-RUNBOOK.md`,
says how it works. Migration 0497, in #1423.

**N219 · Users: delete people from the list, several at once, and they leave
the list at once (founder, the Claude Code chat, 27 October 2026, after the
clickable prototype <https://claude.ai/artifact/Gbi8PZmdL2hCitQsycvurw>:
"yes, build the delete and hide").** For N95:
1. On the admin Users list each row has ⋮ on its left, with "Select" and
"Delete user". "Select" puts a tick box on every row, with a bar: "N
selected", "Select all shown", "Cancel" and "Delete N users"; one
confirmation deletes them all. Admins have no ⋮ and are never selected.
2. A deletion here is the one "Delete user" on the profile already makes:
the account stops now, the data is deleted after seven days, and it can be
cancelled until then. The person leaves the list at once and waits under a
second tab, "Being deleted", with "Deletion asked", "Data deleted after"
and "Cancel deletion". The first tab is "Active". A finished deletion is in
neither tab.
3. The confirmation reads "Delete <email>?" or "Delete N users?" with the
emails, then "Their account stops now. They leave this list now. Their data
is deleted after <day>. You can cancel until then." After it, "Deleted. Data
goes after <day>." with "Undo".
4. The list shows no counts: "N shown" goes, and "Being deleted" carries no
number ("you don't need to show how many were deleted, how many are active").
No rules page: the admin console has none. No migration.

**N220 · A correction that ends on a Good job offers its helper words
(founder, the Claude Code chat, 27 October 2026, asked why the helper words
were often missing: "if you improved, you can make it your habit words",
"the correction that ends on the good job and above offers helper words",
then, of the three options, "B").** For N113 and the lock of 2026-10-12,
section 2.5:
1. A corrected moment whose practise ends on a Good job (a try the machine
reads as better) offers "Choose your helper words" on its paragraph right
after the Good job, before the walk goes on, as after a praise. Until now
helper words came only from a voice that was confident in the Take itself
(a praise, or N113's Clearer version), and a correction's Good job went on
with none, so a Take whose two shown moments were both under the floor
ended with no helper words.
2. A practise that ends on the third try without a Good job, or is skipped,
offers none, as before. A moment that already has its helper words step (a
praise, N113) gets it once.
3. No new words on screen: the step is C3's, word for word. The server is
unchanged: it already saves helper words on any paragraph.
The rules: frontend flow page C3 and C7
([`docs/flows/feedback-walk-and-chat.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/feedback-walk-and-chat.md)). No migration.

**N221 · Users: the list hides people instead of deleting them (founder,
the Claude Code chat, 27 October 2026, after "Can not delete the selected
users nor a single user": "Just hide them cause they are deleted through
other workflow inside the app", then, of the options, "Gone from the list",
"Yes, use these" and "Drop it").** For N219:
1. On the admin Users list, ⋮ has "Select" and "Hide"; the bar while
choosing reads "N selected", "Select all shown", "Cancel" and "Hide N users"
("Hide user" for one). Hiding asks nothing first: the person leaves the list
at once and "Hidden." shows at the bottom with "Undo". If it fails, "Could
not do that. Try again." shows, as before. Admins have no ⋮, as before.
2. Hiding changes only the list. The account, its sign-in and its data stay
as they are. People are deleted elsewhere: "Delete user" on their profile,
or their own "Delete my account". The list no longer deletes anyone, so
N219 items 2 and 3 (its seven-day deletion and its confirmation) end here.
3. A hidden person leaves the list for good: no tab lists them, and only
the "Undo" right after brings them back. The "Being deleted" tab goes too
(N219 item 2); the list is one list. Someone whose account is being deleted,
or is deleted, still leaves it on their own.
4. Hiding is kept on the account row's own "hidden from lists" flag
(`v2_student_details.is_archived`), so it needs no new table.
No rules page: the admin console has none. No migration.

**N222 · Users: Delete on the list really deletes, and every account takes
the seven-day road (founder, the Claude Code chat, 28 October 2026: "but
those that are hidden should get deleted", then, told that hidden people
are not deleted, "Make Delete really delete"; the 500 that the profile's
"Delete user" gave for an account from May found why deleting failed).** For
N219 and N221:
1. The Users list's ⋮ "Delete user" and the bar's "Delete N users" delete
again, with N219's words: the confirmation, then "Deleted. Data goes after
<day>." with "Undo", which cancels. N221's hiding ends. Its one list stays:
the "Being deleted" tab does not come back. The people hidden under N221 are
back in the list, to be deleted from it.
2. Every account the admin deletes takes the seven-day road (N48.4 Q14 A),
including one that never agreed to processing: it is given an owner
principal first. Such an account's sign-in record used to be deleted outright
at once (founder 2026-10-14), and Supabase refused that for anyone with a
Take, because the records kept as history refuse to be deleted with it. Its
sign-in is emptied by the completion run instead, as everyone's is (N218).
3. A Delete after a cancel is a new deletion: each admin deletion is kept
under a key of its own, so a second Delete no longer returns the cancelled
one.
No rules page: the admin console has none. No migration.

**N223 · Customer requests: a widget on a client's site, answered in the
chat as a Take (founder, the Claude Code chat, 27 October 2026: "we rather
want to do what we do and already think about another feature and about
testing that hypothesis").** A hypothesis to test beside the speaker loop,
not a pivot: a client (the first testers sell shampoo and run head spas)
puts a widget on their website; a customer fills a short form; the request
reaches the client in our chat; the client records a short video answer; the
customer gets it; every answered request is a pair the client owns. The
founder's answers to engineering's sixteen questions:
1. The answerer is a normal WillpowerLab user. The request is a card in
their chat; the answer is recorded on the recording screen and goes through
the Take pipeline, so they get the transcript and the feedback on how they
communicated it. No new role, no new panel.
2. One backend, one database: a `workspaces` table owned by the client's
account, row-level security by workspace, the widget a static file on
Vercel. No service or deployment per client. A workspace is metadata on a
project, never a fork in the loop (the rule `services/domains.py` already
keeps for domains).
3. Inside the app, each request opens one project named by the customer's
ask; the answer is its first Take; a re-record is Take 2, and the Ideal Text
stays what they said in their latest Take (Never 5). The customer gets the
latest shared Take.
4. The AI does nothing visible in the first version. It collects pairs:
request, photo, the final answer and its transcript. No draft, no automatic
answer, so Never 2 is not yet in question; when a draft comes, the
founder decides whether the answerer answers first.
5. The client's IP is their pairs and their uploaded documents, exported as
JSONL. No model is trained in the MVP; a per-client surface in the existing
fine-tune pipeline (`services/model_training.py`) opens later, per client,
by the founder's word.
6. The customer receives the answer by WhatsApp: a link to an answer page
with the video, the transcript, the recommendation in words, and one reply
box. The reply lands back in the client's chat and is the second pair.
7. The form is fixed for the MVP: the need in the customer's words, an
optional photo (hair, scalp), the WhatsApp number, one consent tick. Fields
per client come later, from the pairs.
8. The client is the data controller; WillpowerLab is the processor. Hair
and scalp advice is health data (GDPR Article 9): a data processing
agreement per client, and the consent line in the widget is given in the
client's name. Counsel reads the DPA and the widget's words before the
first client goes live.
9. The photo is stored in a private bucket under the workspace, read by
signed URL only, and deleted by the retention cleaner 30 days after the
answer. The pair keeps the text, not the photo.
10. An unanswered request alarms after 24 hours: one email per overdue
request to the founder and to the client, the same pattern as
`coach_moments_queue.reach_alarm`. The promise: every request reaches
someone.
11. The customer sees the client's name and one accent colour, with a
"powered by WillpowerLab" line. Two settings on the workspace; no custom
domain in the MVP.
12. Free for testers, a flag on the workspace. Later each answered request
costs tokens from the client's token account.
13. The founder creates a workspace in admin (name, colour, WhatsApp
sender) and the admin page shows the script tag; the client pastes it. No
self-serve screen in the MVP.
14. The client sees only their delivery feedback on the answer. The pairs
and the corpus accumulate unseen; the founder reads the counts in admin.
15. Build order, each slice proving one thing: (a) workspace, widget,
request card in the chat, WhatsApp link to a plain answer page; (b) the
answer as a Take with the walk; (c) the reply box and the second pair;
(d) photo retention, the 24-hour alarm, the JSONL export. The build plan
lives in that pull request's description, not in a new file.
16. The widget, the answer page and the request card are new words on
screen; their texts come to the founder for OK before they are built
(Never 4). The request card sits in the chat's footer slot, the one
`person_asks` uses, one at a time, never between a Take and its Ideal Text
(Never 3).
No rules page: a rules page for this flow (frontend
`docs/flows/customer-requests.md`) waits for the founder's `Founder-Approved:`
line; until then this entry is the only text in force. No migration in this
entry.

**N224 · Customer requests: how the client's own model is built (founder, the
Claude Code chat, 27 October 2026, four answers to engineering's questions on
the learning side of N223).** The machine stays the one that exists: pairs per
surface, a fine-tune at 200 pairs, the sealed golden set, the evaluation, the
regurgitation check and promotion by the founder's word
(`services/feedback_pairs.py`, `model_training.py`, `golden_set.py`,
`golden_evaluation.py`, `model_promotion.py`). A client's model is a surface
named for its workspace in that pipeline, never a separate infrastructure.
1. **The answer schema.** Every answer a trichologist (or any client's
answerer) records is also stored in a structured shape read from the
transcript against the client's catalogue and documents: what was observed,
which products, what routine, when to come in, which signs mean a doctor. The
AI extracts it after each Take; the answerer sees nothing new; the founder
reads and corrects it on the admin page, as Will's note is corrected today
(`SpeakerMemory.tsx`). A pair is the request, the schema and the final answer
with its transcript. No new step in the answerer's loop (Never 3).
2. **Never 2 holds for the answerer.** When the AI starts drafting (from
about a hundred pairs), the answerer records first and sees the draft after.
The pair is their own judgement against the machine's, by the rule that
exists: recorded only when a draft was shown and the final differs.
3. **Who opens autonomy.** A client's model answers customers alone only
after its golden evaluation passes, scored on the schema (same products, same
routine, same red flags), never on token overlap alone. The founder opens the
door per workspace, as the promotion doors today; the client turns it on per
request type they trust; a health red flag always goes to a person. The
answerer reviews a sample and every correction is a pair.
4. **Retrieval.** Per workspace, embeddings in Supabase with pgvector: one
table with a workspace column, the embedding call through the
processing-authorization path, exportable as rows. One migration, idempotent,
reviewed outside before merging. The client's export (N223 item 5) gains the
schema and the golden set: JSONL of pairs, the documents, the evaluation set.
The order of build: collect (no AI, the schema extracted and checked), draft
(retrieval, blind), fine-tune at 200 pairs with the schema score, alone with
the gate. A client whose answers are open-ended (a marketing specialist
advising on campaigns) runs the same loop with a weaker schema and far more
pairs: it drafts early and runs alone much later.
No rules page: the flow page for customer requests waits for the founder's
`Founder-Approved:` line (N223); the learning rules land on
[`docs/LEARNING-AND-QUORUM.md`](LEARNING-AND-QUORUM.md) in the same PR as the
first code. No migration in this entry.

**N225 · Customer requests are a sales tool first (founder, the Claude Code
chat, 27 October 2026: "it is the sales tool; that if automatised will
become a support tool (the instant smart answers); before the AI gets smart
it is a sales tool only because it answers asynchronously").** For N223 and
N224:
1. The widget is judged by purchases and bookings, not by answer time. While
a person answers, the wait is hours, so the answer is a recommendation to
buy, never live support.
2. The answer page carries the sale: each recommended product with the
client's "Add to cart" link, and "Book" with a date when the answerer says
"come in". The link carries the client's code, so a purchase is attributable
to the request.
3. A pair keeps its outcome: whether the customer bought or booked, read from
the client's link, in words on the admin page and never shown to a customer
or an answerer as a score. The model learns what worked, not only what was
said.
4. The form is the client's product finder: a photo or a few words, the
WhatsApp number, one tick. Words optional when there is a photo.
5. Support comes with autonomy (N224 item 3): once a client's model answers
alone, the same widget answers at once, and the asynchronous loop stays for
what the model hands to a person. Nothing is built for instant answers
before that door opens.
No rules page: the flow page for customer requests waits for the founder's
`Founder-Approved:` line (N223). No migration in this entry.

**N226 · The answer is a Take: her voice over slides she picks, camera off;
typed answers for follow-ups only (founder, the Claude Code chat, 27 October
2026: "she does not want to show herself, she just wants to record like
slide by slide, or just her voice, or just a text").** For N223 item 1, which
said "a short video answer" and now reads: a Take, the answerer's voice over
slides. Nothing in the loop needs a camera.
1. Before the recording, the answerer taps what they recommend from the
client's catalogue. Each pick is a slide: the customer's request and photo
first, then each product, in the order picked. The recording screen stays the
locked one; the picker is the same kind of tap list as the helper words.
2. The picks fill the answer schema (N224 item 1) before a word is spoken;
the transcript adds the routine and the reasons. One paragraph per slide is
the Ideal Text.
3. The customer hears the voice over the slides, the slides turning as the
answer goes, with the product cards and the booking under it (N225 item 2).
No video is sent or stored unless the answerer adds one, as a coach may.
4. A typed answer is allowed only for a customer's follow-up: typed in the
card, no Take, the pair still recorded, sent the same way. The first answer
to a request is always a Take, because the walk on it is half of what the
client buys.
No rules page: the flow page for customer requests waits for the founder's
`Founder-Approved:` line (N223). No migration in this entry.

**N227 · The nearest salon: the customer's postcode is asked at the booking,
once, and remembered (founder, the Claude Code chat, 27 October 2026: "we
want them to at least enter the zip code during the sign up or later on in
the process, so we can display head spa near them, the closest to them";
then "At the booking only, remembered after").** For N225 item 2:
1. The widget form stays three fields (N225 item 4). The postcode is asked on
the answer page the first time the customer taps to book a visit: a postcode
field, or "Use my location" with the postcode as the fallback. The guest
identity keeps it, so it is asked once.
2. A workspace has its salons: name, street, coordinates, and the days each
answerer is there. The page lists them nearest first by the customer's
postcode, with the distance and the answerer's days; the nearest is
preselected, then the day, then Book, which opens the client's booking page
for that salon with the request's code. The booked card shows the salon, the
street and a directions link.
3. The outcome on the pair (N225 item 3) names the salon. Distance is a fact
about a place, never a number about a person.
4. Geocoding a postcode is a provider call and goes through the
processing-authorization path; a client's salon coordinates are entered once
in admin.
No rules page: the flow page for customer requests waits for the founder's
`Founder-Approved:` line (N223). No migration in this entry; the salons table
comes with the first code.

**N228 · Four ways a customer meets the answer, in order; built now: the web
app with WhatsApp carrying the link (founder, the Claude Code chat, 28
October 2026: "there are like a couple of layers how it can be done. Yeah,
let's lock it like that").** For N223 item 6, N225 and N226. The customer's
side of a request is the same chat (what they asked, the answerer's bubbles,
the one thing to do in the dock, each answer landing as their own bubble);
only where it runs changes. The gradation, from the most to the least:
1. **The client's own app.** The WillpowerLab chat in the client's name,
installed by the customer, the client's own model answering inside it. The
max version; not built now.
2. **The web app**, on the client's subdomain of willpowerlab.com, opened
from a link. No install, no account: the guest identity. **Built now.**
3. **WhatsApp**, the conversation itself in WhatsApp once a model answers
alone (N224 item 3, N225 item 5). Not built now. **Built now:** WhatsApp
carries the link to the web app and verifies the customer's number.
4. **SMS**, the same link where WhatsApp is not the norm or not delivered:
the country code of the number decides, one line on the form switches, a
failed WhatsApp delivery falls back to SMS, never both.
Every message the customer's chat shows keeps a shape WhatsApp can carry
(text, voice, photo, buttons, a list), so moving a client from 2 to 3 is a
change of transport, not of design. The answerer's side never changes: a
request is a Take in the app (N226).
No rules page: the flow page for customer requests waits for the founder's
`Founder-Approved:` line (N223). No migration in this entry.

**N229 · Customer requests get their own flow page, and their prototypes are
kept in the repo as files (founder, the Claude Code chat, 28 October 2026:
"Approve as drafted", to the page; then "what if I stop using claude? this
links are gone! so make them pdfs so any model can access them").** For N223
to N228:
1. The rules for customer requests are one page in the frontend repo,
   `docs/flows/customer-requests.md`, of the same shape as the plan's page:
   the rules as decided (§1), in flight, still open, where it lives, the
   prototypes and one line per change. A later decision about customer
   requests is folded into it, never a new file.
2. Every prototype the page names is kept in this repo, in
   `docs/design/customer-requests-2026-10-28/`: the prototype's own HTML, which
   runs in any browser, and a PDF of every step, so the design survives
   without the tool it was drawn in. A claude.ai link is a convenience beside
   the files, never the only copy. New prototypes for this flow are kept the
   same way.
3. These six entries were decided in the chat on 27 and 28 October 2026 as
   N218 to N223; other entries took those numbers on main the same day, so
   they are written here as N223 to N228, unchanged otherwise.
The rules: frontend
[`docs/flows/customer-requests.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/customer-requests.md).
No migration in this entry.

**N230 · One WhatsApp number for everything, checked once with a code; the
country by its flag (founder, the Claude Code chat, 28 October 2026: "You
have a green light for both. The design is great too. Please implement it.",
on the clickable prototype <https://claude.ai/artifact/W9JkYyK3pkwcurNd4itZwR>,
after "put poland first then US and then alphabetically" and "show not the
UK … but Poland").** For N184 item 1, N207 and N214:
1. One number per account: the number that gets the WhatsApp messages is the
number that signs in with WhatsApp. Wherever a number is first given (the
sign-up, the Lounge's ask after Take 1, Settings), a 6-digit code on
WhatsApp proves it once, in the WhatsApp sign-up's words; after the code it
gets the messages and signs in. This replaces N184 item 1 ("no code") for
every place a number is saved.
2. Why the code: a number saved without it, once it also signs in, could
open someone else's account to whoever holds that phone.
3. The number field, as the prototype draws it: the flag and the code first,
Poland chosen at the start for everyone; one tap opens the list: Poland, then
the United States, then every country A to Z, searched by name ("pol"), code
("+44" or "44") or short name ("uk", "usa"). A full number pasted with + picks
its country; a leading 0 is dropped; spaces appear as you type; Send code
lights up only when the number is long enough for its country.
4. The words, signed (Never 4): "Search country or code", "No country matches
“{text}”." and "That's too long for {country}. Check the country."
5. A number another account already signs in with is refused; until its
words are signed it shows the page's "Couldn’t save that. Try again."
The rules: frontend
[`docs/flows/consent-screens.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/consent-screens.md)
(Settings and the number field) and
[`docs/flows/feedback-walk-and-chat.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/feedback-walk-and-chat.md)
(the Lounge's ask). No migration in this entry.

**N231 · Customer requests: the customer can always answer back; the
treatment is a card with its price; Skip offers the product at home (founder,
the Claude Code chat, 28 October 2026: "make it like a real form there so
that I can answer that I want this or I want that ... after I click skip ...
I cannot reply anymore. So please make it like in Willpower Lab how you would
reply ... for the deep scalp treatment, CTA, so that person can actually
click it. Or afterwards, after they click skip the visit at the salon, that
maybe they want a remote treatment, which is they want to buy a product").**
For N225 item 2, N227 and N228:
1. The customer's chat uses the Lounge's own parts, in the client's colours:
an ask's two equal buttons in the footer, a grey footer card for a field,
tall options for a pick, and the message box (+, Type here, the mic) whenever
nothing is asked. The customer can always write, add a photo or record a
voice message.
2. The recommended treatment is a card in the thread, tappable like the Ideal
Text card, with its length and the client's real price (for Invita, the Deep
Scalp Treatment, 75 minutes, $138 to $148 by spa). Tapping it, or Book in the
footer, starts the booking.
3. Booking ends on a summary (the treatment, the day and time, the spa, its
price) with Change | Confirm; then the message box comes back.
4. Skip is not the end: the answerer offers what she uses in the treatment
for home, as a card, with Not now | Add to cart. Add to cart opens the
client's own checkout with the request's code (N225 item 2). Then the message
box.
5. What the customer writes reaches the answerer's chat in the app as a
follow-up (N226 item 4); the answer comes back in the same thread, later. No
instant answer until a model answers alone (N225 item 5, N228).
The rules: frontend
[`docs/flows/customer-requests.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/customer-requests.md)
§1 E and F. The prototype, kept as N229 says:
`docs/design/customer-requests-2026-10-28/customer/invita-flow.html` and its
PDF. No migration in this entry.

**N232 · The sign-up and sign-in pages lead with the WhatsApp number (founder,
the Claude Code chat, 28 October 2026: "go, build both pages", on the
clickable prototype <https://claude.ai/artifact/AsGCCSUvSDXQ8JiXzVGw8a>, after
"looks perfect", "make all the logos … black and white" and "the sign up with
WhatsApp should have just a … WhatsApp logo").** For N214 items 1 and 5 and
N230:
1. Both pages open on the number: the logo, then the number field (N230),
then one orange button, "Sign up with WhatsApp" or "Sign in with WhatsApp",
with the WhatsApp logo in white on it. No tagline under the logo and no title
over the field; there is no separate WhatsApp button to press first.
2. Under "or", three small buttons of one size: Email, LinkedIn, Google, with
their logos in black and white (light in dark mode). The only colour on the
page is the app's orange.
3. Sign-up: the code, then "What should we call you?" with "Will and your
coach use it." under it, then in; the terms line stays under everything.
Email opens "Sign up with email" (name, email, password, as today).
4. Sign-in: the code, then in, with no name step and no terms line; Email
opens "Sign in with email" (email and password, Forgot password?). A number
with no account gets N214 item 5's line, whose link opens the sign-up page.
"Don't have an account? Sign up" and "Already have an account? Sign in" link
the two pages.
5. The words, signed (Never 4): "Will and your coach use it.", "Sign in with
email", and the three buttons' "Email", "LinkedIn", "Google". The other words
were signed in N214 and N230.
The rules: frontend
[`docs/flows/consent-screens.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/consent-screens.md)
("WhatsApp as a way in"). No migration in this entry.

**N233 · A booking's WhatsApp number is cleared once its reminder has gone
(founder, the Claude Code chat, 28 October 2026: "do the code fixes", to
"clear the WhatsApp number after the reminder", from the docs audit's
finding D2).** For N144 and N207: a booking made before N207 carries the
number it was given (`bookings.guest_whatsapp`), and N207 item 2 replaced
N144 item 3 ("for these two messages only") without saying how long that
number stays. Now the booking's number is cleared as soon as its reminder has
been sent, and on any booking whose start is more than an hour past, reminded
or not. The number saved on the account (the Lounge's ask, Settings) is
untouched. STOP to a WhatsApp message (N171 item 6, N174 item 5, N189 item 5),
which removes the account's number too, is not built yet: it needs Meta's
webhook and its keys on Railway, and is its own build. No rules page. No
migration.

**N234 · Customer requests: the treatment and the product are paid in the
chat, into the client's own Stripe account (founder, the Claude Code chat,
28 October 2026: "what happens if I click the deep scalp treatment? Can I
buy it from here, from the chat? Please design this", then, on the
prototype, "In the chat, into the client's own Stripe account" and "Yes,
the same pay sheet").** For N225 item 2, N231 items 2 to 4, which said the
booking and the cart open the client's own pages:
1. Tapping the treatment card opens a sheet over the chat: what it is, the
answerer's one line on why, what is included (from the client's own page),
the length and the price by spa, and one button, Book · from {price}.
2. The booking's summary asks Change | Pay {price}. Pay opens one sheet: the
line, the total, Apple Pay first, Pay with card under it, and one line on
who is paid. Then the customer's bubble says Paid {price}, and the
answerer's says Booked and paid, with the address, directions, the receipt
and Add to calendar.
3. The product at home is bought the same way: Not now | Buy · {price}, the
same sheet with where to send it, then Paid, on its way, with the receipt.
4. The money goes straight to the client: each client connects its own
Stripe account once in admin (Stripe Connect); WillpowerLab never holds it.
The receipt is the client's. The booking is written into the client's
calendar by us; how, per client, is open.
5. The cancellation policy, shipping and the product's price are the
client's; each client gives them before going live.
The rules: frontend
[`docs/flows/customer-requests.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/customer-requests.md)
§1 E, G and I. The prototype, kept as N229 says:
`docs/design/customer-requests-2026-10-28/customer/invita-flow.html` and its
PDF. No migration in this entry.

**N235 · A number typed in the chat waits for its code too; a number another
account has is refused in words (founder, the Claude Code chat, 28 October
2026, to the questions left after N230: "Yes cause it will be eligible to use
for sign in too" and "Ok").** For N230 items 1 and 5:
1. A WhatsApp number typed in the Lounge's chat under the WhatsApp ask is not
saved at once (founder 2026-10-20) any more. The chat answers "Enter the code
we sent you on WhatsApp" (N214 item 6) and opens the ask's form on its code
step for that number; once the code is typed, the number gets the messages
and signs in, as N230 item 1 says for the form. A number without its country
code still opens the form with it, as before.
2. A number another account already signs in with is refused with "That
number already has an account." (signed, Never 4), in the Lounge's ask and in
Settings' WhatsApp row. This replaces N230 item 5's stand-in.
3. Still open: the words of the WhatsApp card's Remove in Settings, which
stops the messages but leaves the number the account signs in with; the
founder asked for a proposal ("Ok suggest new").
The rules: frontend
[`docs/flows/feedback-walk-and-chat.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/feedback-walk-and-chat.md)
(E1, the WhatsApp ask) and
[`docs/flows/consent-screens.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/consent-screens.md)
(the number field). No migration in this entry.

**N236 · Customer requests: the answerer's side, in her own Lounge; send
first, the walk after; the link stays as sent; an optional first name; the
answerer told on WhatsApp (founder, the Claude Code chat, 28 October 2026,
on the two clickable prototypes: "Her Lounge, as decided", then "Send first,
walk after", "Stays as sent", "Optional first name" and "WhatsApp").** For
N223 items 1 to 3, N226 and the page's §1 B6, C1, D5 and E2:
1. The answerer answers in her own Lounge, as any speaker: the request is
the Lounge's one ask, Answer opens the picker of the client's treatments and
products, and the Take is her voice over the request and her picks, camera
off, on today's recording screen.
2. Send first: once the Take is processed, its Ideal Text card lands in the
thread marked new, and Will asks at once "Send this answer to {name} on
WhatsApp?", Not yet | Send, with a grey card listing what the customer gets
(her voice, the text, each pick with its price). The walk waits on the card
and opens from it, as after any Take. Was (§1 D5): the send ask after the
walk and the Ideal Text.
3. A Take 2 after sending does not change what the customer has: Will asks
again, and only a second Send replaces it. Was (§1 E2): the link always
opens the latest shared Take.
4. The widget's form gets one optional field, the customer's first name,
between the words and the number. The answerer's chat uses it ("Sarah, a
customer of Invita Head Spa, asks for your advice."); without it, "A
customer". Its words wait for the founder's OK with the rest (Never 4).
5. The answerer is told of each request on WhatsApp: one message from
WillpowerLab's number with a link to her Lounge.
6. Still open, on the page's §3: how fast she must answer and what follows
when she does not; many requests at once; the photos (how many, kept how
long, who sees them); who keeps the catalogue and its prices; the price by
spa; the longest answer and whether it uses tokens; fixing a word before
sending; a check by the client before sending; the WhatsApp sender, Meta's
template approval and the US SMS fallback; one inbox for several answerers;
the calendar, Stripe fees, cancellations and shipping (N234); the answerer's
account; the DPA and consent; what the client pays.
The rules: frontend
[`docs/flows/customer-requests.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/customer-requests.md)
§1 B6, C1, D5, E2 and K, §3, §5. The prototype, kept as N229 says:
`docs/design/customer-requests-2026-10-28/ariel/ariel-lounge.html` and
`6-answerer-side-in-her-lounge.pdf`. No migration in this entry.

**N237 · Replying STOP to a WhatsApp message turns the messages off (founder,
the Claude Code chat, 28 October 2026: "Fox 1 and 2 GO!", to building STOP;
the other fix was N235).** For N171 item 6, N174 item 5, N189 item 5, N233
and N235:
1. Meta sends each reply to our WhatsApp number to the backend
(`/v2/whatsapp/webhook`), which reads a reply only when Meta signed it with
the app's secret.
2. A reply that says STOP (any capitals, with or without a full stop) turns
WhatsApp messages off for every account that gets them at that number, as
Remove on the WhatsApp card does: the number leaves the messages, and the
number the account signs in with stays (N235 item 3). A booking that carries
the number forgets it (N233).
3. WhatsApp's answer, sent within the 24 hours WhatsApp allows after the
person's message: "Done. We've stopped the WhatsApp messages and deleted your
number." (signed, N174 item 5). Its "deleted your number" goes with N235 item
3's open words for Remove: for an account that signs in with WhatsApp, the
number stays for signing in.
4. Any other reply is not read yet. N171 item 6 still holds: forwarding
such a reply to the founder by email is to be built.
5. It stays off until two keys are on Railway's web service
(`WHATSAPP_WEBHOOK_VERIFY_TOKEN`, `WHATSAPP_APP_SECRET`) and the webhook is
set in Meta (its address and the "messages" field).
The rules: frontend
[`docs/flows/feedback-walk-and-chat.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/feedback-walk-and-chat.md)
§2, the line for N171. No migration.

**N238 · The sign-up page says nothing of its own about the messages; the
Terms and the Privacy Policy say what the number is for (founder, the Claude
Code chat, 28 October 2026: "Oh, the new sign-up page. Don't use it, don't
change it, because we're gonna just do general things", then "Yes" to "the
general Terms and Privacy explain the messaging").** For N171, N207 item 3,
N214 and N232:
1. The sign-up page stays as N232 draws it. It gets no line of its own on
what the WhatsApp number is for. "We will only use it to let you know your
coach texted you, or that your call starts soon." (N207 item 3) stays on the
Lounge's WhatsApp form only.
2. The Terms of Service and the Privacy Policy say it instead: the WhatsApp
number someone signs up or signs in with is also the number we message, when
the coach's feedback is in (N171) and before a booked call (N207). Their
words are written with the next privacy version, the one N207 item 3 and
N214 already wait for. No words on any screen change.
The rules: frontend
[`docs/flows/consent-screens.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/consent-screens.md)
("the sign-up and sign-in pages open on the number"). No migration.

**N239 · Customer requests at Invita: booking in Fresha, products through
Shopify, Invita's WhatsApp sender, Ariel alone sends, and the words approved
(founder, the Claude Code chat, 28 October 2026, to the questions left on the
two prototypes: "they use fresha but are open to the new booking system", "we
would need to add an integration to their ecommerce", "it is Ariel who checks
the send", "it is Invita sender", "whatever the length of the answer is - is
good", "OK for 11", "12 = OK", then "Fresha's booking" and "Shopify
checkout").** For N231 items 2 to 4, N234 and N236 item 6:
1. Booking stays in the client's own booking system. For Invita, Fresha:
Book opens Fresha's booking for that treatment at the nearest spa, and the
customer pays there. The answerer's days at each spa come from Fresha, so no
new screen for her. Whether Fresha gives the booking back to us, as the
request's outcome, is checked before the build; Invita may move to another
booking system later. Was (N234 items 1, 2 and 4): the booking paid in our
chat into the client's Stripe.
2. Products are bought in the client's own shop. For Invita, Shopify: Buy
puts the product in Invita's Shopify cart and opens its checkout, so stock,
shipping, taxes and refunds stay Invita's. The order comes back to us as the
outcome. Was (N234 item 3): our pay sheet. Stripe Connect is no longer
needed for Invita.
3. The answerer alone decides to send; no one at the client checks first.
4. The WhatsApp messages to Invita's customers come from Invita's own sender.
5. An answer has no longest length.
6. Counsel reads the data processing agreement and the consent wording
before the first real customer, and what the client pays is settled before
going live ("OK for 11").
7. The words on screen in the page's §1 K are approved as the prototypes
draw them ("12 = OK", Never 4).
The rules: frontend
[`docs/flows/customer-requests.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/customer-requests.md)
§1 D, E, I and K, §3. No migration in this entry.

**N240 · Customer requests: what the client's AI learns, three models on one
platform (founder, the Claude Code chat, 28 October 2026: "how we will fine
tune their chat? ... it should be learning from their answers", the image
recognition "for the types of scalp problems and hair problems, say few first
easy ones like dandruff, receding hairline, dry scalp; main one is the linear
regression for the balding patterns", "can we act here as a launchpad for
their own AI", then "Taps on the picker" and "One platform").** For N224:
1. One Take teaches three models: the eyes (the photo to what is seen: dry
scalp, dandruff, oily, irritated, receding hairline, and the hair-loss stage
on its fixed scale, Norwood 1 to 7 or Ludwig I to III, read the way the
confidence model reads its 1 to 5), the plan (what is seen and the
customer's words to the treatment and the product: the answerer's picks), and
the words (the plan to the answer in her voice: her Ideal Text, N224's
pairs). The reward is the outcome (booked, bought, not yet) and a follow-up
photo after three weeks.
2. The answerer says what she sees with taps on the picker screen, above
"What do you recommend?": the condition chips and the stage, about two taps.
A second trichologist labels a sample blind for the frozen test set; two
humans settle a label, as `services/label_quorum.py` does today. Was (N224
item 1): what was observed read from the transcript only.
3. One platform: the client's models are learning surfaces in the
pipeline that exists (labels, quorum, the split by person, here the
customer, the sealed golden set, promotion by the founder, drift), with
each client's data and weights kept apart and exported to the client. New:
training on photos (training is text only today), a vision training
provider through the processing-authorization path, and scoring the stage
on its scale in the golden evaluation.
4. The order of N224 holds: no AI shown first; drafts in the background,
blind, from about a hundred requests; drafts shown after the golden set
passes; alone only per request type, by the founder's door and the client's
switch, a health red flag always to a person.
5. Before any photo trains a model: the customer's own yes to training, its
retention, and counsel on whether naming a condition makes it a medical
device in the US. Until then the eyes stay advisory and are seen only by the
answerer.
6. This is the launchpad: the client's experts answer in their own voice,
WillpowerLab trains them as speakers (the walk) and trains the client's AI
from their answers. The loop of record, Ideal Text and feedback stays first.
The rules: frontend
[`docs/flows/customer-requests.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/customer-requests.md)
§1 D1 and H, §3; the learning rules land on
[`docs/LEARNING-AND-QUORUM.md`](LEARNING-AND-QUORUM.md) with the first code.
No migration in this entry.

**N241 · The principles' three companions: strengths, what is in your
control, and the sales framing (founder, the Claude Code chat, 28 October
2026, to Linear's WIL-112, WIL-113 and WIL-114: "Life Panel, by principles",
"Will drafts, you decide", "When notes show it twice", "Yes, as one note",
"Will links notes to it", "Before a talk", "Plan's date and their notes",
"Never; the speaker retires it", "How Will talks", "When it hears a worry",
"Sort it, end on one action", "I draft, you sign", "Will's framing, no
charts", "From their own notes", "Both, note and week", "Steps replace bugs",
"One thing they control", "Ring 5, own switches", "Clickable prototype
first").** For N182 and N212:
1. Strengths (WIL-112) are kept in the Life Panel beside the principles and
life goals. Will suggests one only when a positive trait shows in # notes on
two different days (the life goals answer "What fits your nature and
strengths?" counts as one note), once, in the Lounge, quoting both notes;
the speaker accepts, edits or says Not now (propose, never commit, as the
Sunday note's principle). Will never invents a strength and never says one
did not show; only the speaker archives one, and it stays in the history.
2. A later # note that shows a kept strength at work: Will says so once and
keeps the note under that strength, so each strength gathers its own
examples from daily life.
3. Before a talk: in the Lounge, the day before a talk date (the plan's
deadline, or a date a # note names), Will brings back one kept strength,
quoting the note it came from. With no date, no reminder. Never on the
recording screens.
4. What is in your control (WIL-113, constants and variables) is how Will
talks, not a screen. When a # note or a chat message worries about
something out of the speaker's hands (the hotel, the audience, the slot),
Will, once per worry, names what is out of their hands, names what is
theirs, and ends on one thing they control now. Will's guide (the Stoic
grounding, the hotel example, the tips) is drafted for the founder as a
Claude Doc and goes into Will's instructions word for word once signed.
5. The sales framing (WIL-114) is Will's framing too, with no charts (Never
1). Will knows someone sells from their own notes (calls, deals, clients, a
lost sale); no setup question. On a sales note, Will asks which step it
stalled at (the opening, discovery, the offer, the follow-up) and names one
change to that step, never the person. On Sunday, when the week's pattern
is a sales one, the Sunday note offers the sale's steps in place of the four
bugs (L4), then the reflection and a principle about the process.
6. What a speaker leaves a chat with Will holding: one thing they control.
7. Each of the three has its own row on the rings page, set to ring 5, the
founder's to widen (as N212). Like the principles (N182): apart from the
speaking coach, private, never shown to a coach.
8. The words on screen are signed on a clickable prototype drawn on the real
Lounge and Life Panel screens before the build (Never 4); the Sunday note's
change to L4 is drawn there too, as the Sunday note is locked (N158).
The rules: frontend
[`docs/flows/principles.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/principles.md)
§1 N, O and P, §2. No migration in this entry.

**N242 · "I have a new event" waits while a Take is processing (founder, the
Claude Code chat, 28 October 2026: "When I click that I have a new event while
processing the recording it doesn't know what to do", then "Hide it while
processing").** For N140 and N178:
1. While a Take is still processing (its analysis or its Ideal Text has not
landed yet), "I have a new event" is not shown: not in Change your plan (H1),
and not beside "Keep practising" under "What's next?" at the plan's end (I2).
It comes back as soon as the Take has landed, the moment "Record Take N" comes
back.
2. Nothing else changes: a tap once the Take has landed starts a new event as
N140 and N178 say, its questions after the next Take. No new words on screen
(Never 4).
The rules: frontend
[`docs/flows/the-plan.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/the-plan.md)
§1 H1 and I2. No migration in this entry.

**N243 · The principles wait while a speaker is onboarded (founder, the
Claude Code chat, 28 October 2026: "I feel that principals are interfering
with the onboarding here", then, asked which onboarding and what the
principles should do then, "Speaker's first steps" and "Wait for first
Take").** Amends N182 and N212, for N129, N136 and N178:
1. While a speaker is onboarded, nothing of the principles shows: not the
voice notebook's mic, not "Keep a voice notebook?", not the life goals ask,
the Sunday note or the quarter's ask; and Will's chat does not answer as the
notebook, the Sunday note or life goals.
2. A new speaker is onboarded from the plan's first question until their
first Take is recorded. A speaker who already has Takes, only while the
plan's questions are asked (the deadline after their next Take, A2; a new
event's questions, A3).
3. Then everything in N182, N212 and N241 stands. Nothing that waited is
lost: an ask that was due comes the next time it may.
4. Only where the plan reaches (its ring row, N204); with no plan, the
principles are as before. No new words on screen.
The rules: frontend
[`docs/flows/principles.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/principles.md)
§1 A6 and [`docs/flows/the-plan.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/the-plan.md)
§1 A5. No migration in this entry.

**N244 · No next Take in the chat from the moment one is recorded until its
walk reaches its summary (founder, the Claude Code chat, 28 October 2026: "I
can see two bubbles interfering, like bubble flows interfering, one for the
new take and one the summary of the take I just took. So maybe disable the
new event while the processing is happening, so that it is only possible
once it's finished", then "Record Take N" and "Walk's summary seen").** For
N89, N167 and N192:
1. Once the next Take is recorded, the last Take's closing message ("Look,
practice makes perfect…") keeps its words and gives "Record Take N" up, and
so does a practice day's one thing (N167). The chat offers no Take while the
new Take processes and while its walk runs; its own closing message, written
with the walk's summary, brings "Record Take N" back. Until now the button
was held only while the Take processed: the moment processing ended it came
back, naming the Take just recorded, beside the new Take's walk.
2. The "+" and the Ideal Text page's own "Record Take N" are as before. No
new words on screen, nothing changes on the server.
The rules: frontend flow page D4
([`docs/flows/feedback-walk-and-chat.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/feedback-walk-and-chat.md))
and [`docs/flows/the-plan.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/the-plan.md)
G6. No migration.

**N245 · The Sniper guides the tries: a try that lands moves on (founder,
the Claude Code chat, 28 October 2026: "it also keeps asking me during the
sniper practice to practice again and again"; "If it was really better, you
let me go to the next step. If it was just slightly better, you're like coach
that sees the potential and you ask, like, give it a try once more"; "you ask
up to three times"; then, asked, "Long and green", "That landed. 🎯" and
"You're close. 💪").** For N166 item 3 and N179, the tempo step (N181):
1. Will decides when the game ends, not the speaker. "See how it went" goes;
the Skip stays at the start and during each try (N178 item 3).
2. A try lands when it runs at least 20 seconds from the first word and the
ball is in the green four fifths of that time. The stretch spent at least a
quarter of its time outside the green (`tempo_stretch.MIN_OUTSIDE`), so a
landed try is always clearly better than the Take. Will says "That landed. 🎯
Really better. Let's move on." and Next goes on with the walk, on any try.
3. A try that came closer (the ball in the green more than half the time, not
enough to land) gets "Better. You let it breathe." and, while a try is left,
"You're close. 💪 Give it one more try.", then Practise again. Otherwise the
try's comment as signed (N179), then Practise again.
4. Up to three tries; after the third without a landing, the closing line
comes by itself (N179). The bar is never shown (Never 1). Both new lines are
signed. Will's note keeps a landed try as better and the game as ended
dynamic.
The rules: frontend
[`docs/flows/feedback-walk-and-chat.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/feedback-walk-and-chat.md)
§1 K and T. No migration.

**N246 · Two confident moments on every Take; the next one in place of a
sentence that already has its helper words; on a plan, the level as well
(founder, the Claude Code chat, 28 October 2026: "the moment that's already
with the helper word, it's not being chosen as the confident moment again
... if there is already a confident moment and helper words, go for the next
confident moment"; "I've seen only one confident moment on this feedback
round ... there should be at least two confident moments, like the highest
confidence moments from the whole recording"; then, asked, "Nothing at all"
was shown in place of the second, "Two best + level" and "Second
stays").** For N118, N128, N134 item 2, N209 item 2 and D8 of the helper
words lock of 2026-09-30:
1. Every Take shows two moments. A short Take showed one: its two best
sentences sat in the same block of about 75 words, and the rule that each
side of a split keeps 40 words stopped the split. When nothing else could be
shown, that block is now split between the two. Contract 24a is amended.
2. When both moments sit on one slide, helper words picked at the first no
longer hide the second: it stays until it is walked. Until now the slide's
paragraph counted as done (D8) and the second moment left the walk.
3. A sentence that already has its slide's helper words, as they stood when
the Take was recorded, gives its place to the next best moment; it is shown
only when there is nothing else.
4. On a plan, the walk shows the two best moments and this week's level as
well: as a third moment, or on one of the two when the level shows there.
This replaces N134 item 2 and N209 item 2 (the best moment and the level's).
Found on the way: the walk the speaker sees never had the level, only the
hidden copy the server keeps for comparison did. It now has it.
No new words on screen (Never 4). The rules: frontend
[`docs/flows/feedback-walk-and-chat.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/feedback-walk-and-chat.md)
C2, C3 and H1, and
[`docs/flows/the-plan.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/the-plan.md)
§1 G7. No migration in this entry.

**N247 · A reopened Feedback walk shows everything the speaker went through
(founder, the Claude Code chat, 28 October 2026: "It should open the whole
feedback walk with all the things that are there that we went through, the
judgment time, the sniper, whatever intervention was included in the
feedback", then, asked, "Both, read only").** Amends the frontend's C8 ("no
read-only replay", 2026-10-13), for N89, N166 and N192:
1. A Take's walk opened again from its Feedback walk, once it is done, holds
every step as it went, read only: the coach's word, the moments and their
practise, the helper words (still editable on the latest Take, C3), the
tempo step, the judging of other speakers, and the summary at its end.
2. Other speakers: the moments the speaker judged in that walk, each with
the answer they gave, and Next, as the walk reopened shows them since
2026-10-18. Nothing is asked again or sent. With none judged, the step is
left out.
3. The tempo step (the Sniper): as the chat kept it, Will's opening lines,
each "Try N" with its comment, and the closing line or the Skip. No scale, no
microphone, nothing recorded. A Take that had no tempo step has none.
4. No new words on screen (Never 4); nothing changes on the server.
The rules: frontend
[`docs/flows/feedback-walk-and-chat.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/feedback-walk-and-chat.md)
§1 B10, C8 and T. No migration.

**N248 · The calls' calendar opens full screen, and it swipes (founder, the
Claude Code chat, 28 October 2026: "Can you make it a big screen and the
calendar I can swipe through? So it's really minimalistic", then, on the
prototype, "Green light, build it").** For N157, N161 and N168:
1. When Will asks for a call (the kickoff, the summary call, or a call's
"Book" in the plan's list), the calendar opens full screen over the chat
instead of in the footer: "Skip" at the top left, "{n} of 2 booked" at the
top right, the call's name as the title, then the month, the days, "Your
deadline: {date}" with "Edit", and one button at the bottom, "Book" ("Book
now" for the summary call).
2. The month is big and swipes left and right; the arrows stay. Only the days
with an open time are dark. It runs over the months the call can be booked
in.
3. A day picked folds the month into its week, which swipes week to week; the
day's times show under it in four even columns. A tap on the month's name
opens the whole month again.
4. "Book" stays pale until a time is picked. After it, a tick, the calendar
slides away and Will's "Booked: …" is in the chat; the next call's calendar
comes up once Will has asked for it.
5. "Edit" turns the same screen into the deadline's: "Your deadline" as the
title, "Back" at the top left, "Save" at the bottom (N168). Will's "Done. Your
plan now runs to {date}." is written in the chat behind it and read when the
calendar closes.
6. No new words on screen (Never 4): only where they sit changes. Was: the
calendar in the footer under the chat, with "Skip" and "Book" side by side
under it.
The rules: frontend
[`docs/flows/the-plan.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/the-plan.md)
§1 F. Drawn on the prototype <https://claude.ai/artifact/Gfnp8Fg8G2uXcqbCSNycgf>.
No migration.

**N249 · The plan's ask for the yes says "Settings" (founder, the Claude
Code chat, 28 October 2026, asked "Should the personal-questions message say
'Settings' instead of 'Data & consent', to match the menu?": "yes").**
Amends N211's signed words, for N196:
1. Will's ask before the personal questions ends "You can turn this off in
Settings.", the name the ☰ menu and the page have carried since N196. The
rest of the ask, its Read more and its two taps are unchanged.
2. An ask already in a speaker's thread keeps the words it was sent with.
The rules: frontend
[`docs/flows/the-plan.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/the-plan.md)
§1 D5 and K. No migration in this entry.

**N250 · WillpowerLab as a launchpad for its clients' AI: a frontier model
first, the client's data as its asset, one kit per client, and an enterprise
pack (founder, the Claude Code chat, 28 October 2026, after the review of
customer requests from the side of an enterprise AI build: "yes, add section
E and log the decision").** For N224 items 3 and 4 and N240 item 3:
1. A client's AI starts on a frontier model (vision and language) through
the processing-authorization path, with the client's catalogue and documents
as its retrieval and the expert in the loop. A fine-tune comes only when the
golden evaluation shows the frontier model with retrieval stops improving.
The pairs are collected from the first request, as before. Was (N224): a
fine-tune at 200 pairs.
2. What WillpowerLab promises the client is the client's data: the labelled
pairs, the outcomes, the label list, the red flags and the golden set,
exported to the client (N223 item 5). They outlive each model generation;
model weights are added only where a fine-tune was made.
3. One kit, configured per client, with no code written for one client:
the catalogue, the label list, the red flags, the channels, the connectors
(Fresha and Shopify for a spa; a CMS or a CRM for a publisher) and the
brand. The client's onboarding form is the strategic-call sheet.
4. Each client's data and models are kept apart by default. Learning across
clients, anonymised, only where the client's contract says yes.
5. Before the first enterprise client, an enterprise pack: a template DPA
and DPIA, a one-page model card for each client surface, an audit log of
every AI answer (the model version, the inputs, who approved it), a stated
data region, and an "AI-assisted" label where the EU AI Act asks for one.
WillpowerLab holds no SOC 2 or ISO 27001 of its own today
([`docs/VENDOR_DPA_REGISTER.md`](VENDOR_DPA_REGISTER.md) lists only the
vendors'); whether to get one is open.
6. Before a client's AI is scoped, the client answers: the success metric
and today's baseline; the data it already keeps (past consultations, photos,
forms, close-up images from its own equipment); its own way of grading; the
red flags; who owns the photos, the answers and the model, and whether
WillpowerLab may learn from them anonymised; the languages; the volume.
For Invita these are the call sheet's section E.
7. Narrow enterprise cases fit the same shape (a request, an expert's picks
from a catalogue, an outcome): for a media publisher, ad sales answering
advertisers' briefs; expert reader columns only with red flags and the AI
label from the first day. None is built.
8. The record → Ideal Text → feedback loop stays first (CLAUDE.md). A client
that needs code beyond the kit's configuration goes to the founder before
any work starts.
The rules: frontend
[`docs/flows/customer-requests.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/customer-requests.md)
§1 H and I, §3. No migration in this entry.

**N251 · One record button in the chat, the newest Take's, whatever the
project (founder, the Claude Code chat, 28 October 2026, from a decision
page after N244: "the other project's 'Record Take N' goes too while the
new Take processes and its walk runs (any project)", "the other project's
button does not come back. One record button in the chat, the newest
Take's; other projects through the '+'", "Tidy the wording: yes").** For
N244, N89 and N167:
1. N244 held only inside one project: a Take recorded in another project
left that project's closing message with its "Record Take N" beside the new
walk. Now a Take recorded in any project takes the button from every
closing message and practice-day bubble before it, while the new Take
processes and while its walk runs.
2. The button does not come back on them once the new walk reaches its
summary: the chat has one record button, under the newest Take's closing
message (or in a practice day's bubble after it, N167). Another project is
reached through the "+". Was: each project's last closing message kept its
own button, so two projects could show two.
3. The "+" and the Ideal Text page's own "Record Take N" are as before. No
new words on screen, nothing changes on the server.
The rules: frontend flow page D4
([`docs/flows/feedback-walk-and-chat.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/feedback-walk-and-chat.md))
and [`docs/flows/the-plan.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/the-plan.md)
G6. No migration.

**N252 · The launchpad as a business: one request shape, coaching first and
the AI after, templates per trade, a price per answered request (founder, the
Claude Code chat, 28 October 2026, on Claude's suggested answers to eight
questions: "Yes, please log it").** For N223, N224, N225, N240 and N250:
1. **One shape.** Every client's service is the same three parts: the request
(the customer's words and/or photos, an optional first name, the number, the
consent tick), the answer (what the expert sees from the client's label list
and scale, the red flags, her picks from the client's catalogue, her voice
Take) and the outcome (booked, bought, replied or not yet, with its amount,
matched by the request's code). A red flag counts as a pick ("see a doctor").
2. **Per client, data only:** the label list and scale, the red flags, the
catalogue rows (id, name, type, price, link), connectors from a fixed list,
the name and one colour, the languages, words from the signed word set. We
refuse custom fields, custom steps, live chat, an answer with no pick, an
outcome we cannot read from a link, and code for one client (N250 item 8).
Two clients asking the same thing goes into the template for all.
3. **The export is always free.** The client's data is never held back behind
the AI tier; the AI tier sells speed and instant answers.
4. **Coaching first, the AI offered by milestones:** about 100 answered
requests, drafts run unseen; the golden evaluation passes, a 30-day free
trial of drafts is offered; one request type passes, "alone" is offered for
it. The client's owner may read how the machine does, in a monthly note in
words and numbers about the machine; the answerer sees none of it, and no one
sees a score about a person (Never 1).
5. **Templates per trade** (the label list, the red flags, the catalogue's
mapping, the connectors, the signed words, the call sheet, what the golden
evaluation checks, the starting instructions), versioned; a client stays on
its version until it chooses. The contract says: "Improvements to the setup
are ours; your answers, photos and outcomes are yours." Learning across
clients is off by default; a client who opts in gets the shared starting
model and 20% off the AI tier. Never for health photos until counsel answers
N240 item 5.
6. **An answered request** is the first Send. A re-send and typed follow-ups
within 7 days are free; a new request after counts again; an unanswered
request costs nothing.
7. **Prices to test, estimates, reviewed after three clients:** self-serve
$4 an answered request; assisted (health, finance, legal) $8 and a $1,500
setup with the enterprise pack (N250 item 5); two answerer seats with
coaching included, more on today's packages; the AI tier $400 a month with
drafts, then $1 an answer the AI sends alone and $4 one it hands to a person.
Invita stays free as the tester (N223 item 12). If the next three spas all
sign at $4 without pushing back, the fourth is quoted higher.
8. **One currency:** the client pays in tokens, 100 to the dollar (N198), 400
an answered request, from the same wallet; its invoice reads in dollars.
The rules: frontend
[`docs/flows/customer-requests.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/customer-requests.md)
§1 H and I; its lines come in their own frontend PR. No migration in this
entry.

**N253 · "#" is one note, the same as the small mic (founder, the Claude Code
chat, 28 October 2026: "when I tap and want to enter the words in the type
form ... and I start with a hash, there are a series of thoughts, observations
and stuff like that. We don't use it anymore. It's just one text that we
save ... just leave one hash and note ... it's the note, the same that the
small microphone uses. It's an old pattern from the code that needs
fixation.").** For N182 and N194:
1. Typing "#" in the Lounge's message box offers one option, "# note". Tapped,
the box keeps "# " to write on. The old list (#mistake, #observation, #win,
#add, #edit) is gone from the box.
2. Every typed message that starts with "#" is one note in the voice
notebook, kept and answered "Noted.", as a note said with the small mic. A
leading "#note" is read as "#".
3. What stops: from the chat, the Life Panel's tags no longer route
(#mistake to a case, #observation to the strategy check, #win to the wins,
#add to the phrase wall, #edit to today's card); for a notebook user each is
now a note. The Sunday note is how a principle comes from the notes (N158).
The Life Panel's first-run guide still teaches those tags; its new words wait
for the founder.
The rules: frontend
[`docs/flows/principles.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/principles.md)
§1 B8. No migration.

**N254 · One project at a time (founder, the Claude Code chat, 28 and 29
October 2026: "we want the user to have one presentation at a time, so they
cannot be doing more than one presentation. So if they start a new one, it
means, do you want to discard their current progress, something like that,
one at a time. That's the rule", then four answers on a decision page).**
For N14, N244 and N251:
1. A speaker works on one project at a time. "Start a new project" first
asks the question in item 4; Continue archives the current project (N14:
it leaves the "+" list, nothing is deleted, Data & consent brings it back)
and the new one starts. The current project is the one with the newest
Take.
2. Going back to an archived project is allowed: picking it, or "Record
Take N" on its Ideal Text page, asks the same question, archives the
current project and makes the older one current.
3. Speakers who have several projects today keep them as they are; the
project with the newest Take is current, and nothing is archived until they
start a new project or switch.
4. The question's words, signed: "One project at a time" · "“{current}”
will be archived. Its Takes and Ideal Text stay safe, and you can bring it
back from Data & consent." · "Continue" · "Cancel".
5. The next Take of the current project never asks anything (Never 3). A
coach's link and a coach's late word on an archived project still open,
and Will keeps what he learned from it.
6. Updating a project's deck (a project started without one, or a new
version of it) stays in the same project and is designed next, at the
founder's ask the same day; it lands in its own entry.
The rules: frontend
[`docs/flows/recording-screens.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/recording-screens.md)
(the "+" and its question) and
[`docs/flows/ideal-text.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/ideal-text.md)
(its "Record Take N"), with the first code. Unarchive in Data & consent
asks nothing: it puts the project back on the "+" list, where picking it
asks. No migration in this entry.

**N255 · Your why, every day (founder, the Claude Code chat, 29 October 2026:
"what about the reminder daily reminder about my goals? Like raison d'être,
why I'm doing this? My vision. And how I want to treat others.", then "A
short sitting, your words", "Lounge, first open", "one of them everyday -
your why", "Read it, one question", "Why daily, others kept", "After the
first goal is set", "As a goal's step").** For N172 and N182:
1. Three lines of the person's own: their why (why they do this), their
vision (what they see when it works) and how they want to treat others. A
short sitting in the Lounge's lens, as life goals: three open questions,
said with the small mic or typed, each with Skip; Will drafts each line only
from their words, quoting them, and they Accept or Edit. Never invented.
2. Offered once, the next time the Lounge opens after the first life goal's
"That's the base", with Not now | Start in place of the message box (as M1).
A second Not now and it waits for them to ask, in any words.
3. Every day, the first time the Lounge opens that day, the why waits as a
grey bubble in their own words, with one question under it about where it
will show today. No clock, nothing counts the days, nothing waits for an
answer; they answer with a # note or not at all.
4. The vision and how they treat others are kept beside the why in the Life
Panel, open any time; Will reads all three before it chats.
5. Changing one is as a goal's step (M11): the line in the Life Panel or the
› on the daily bubble, "Now: …", a field, Keep the change; dated, the earlier
words kept in its history.
6. Ring 5, its own row on the rings page (as N241 item 7). Private, apart
from the speaking coach, never shown to a coach (N182). Its words are signed
on the prototype first (Never 4).
The rules: frontend
[`docs/flows/principles.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/principles.md)
§1 Q, §2. No migration in this entry.

**N256 · Customer requests: the answerer's Lounge becomes a list of chats,
one chat per customer, and Will's chat for her own Takes and feedback
(founder, the Claude Code chat, 29 October 2026: "Ariel ... she might be
confused getting in one chat messages from different people. So maybe there
should be a tab, a separate chat for the improvements. And there should be a
group chat", then, on the proposal, "Yes, log it").** For N236 items 1 and 2
and the page's §1 C1 and F:
1. An answerer with customer requests opens her Lounge on a list of chats,
as WhatsApp does: Will pinned on top, then one chat per customer, with the
customer's photo as the avatar, the first name and the question, the last
message, the unread count and a status (Waiting for you, Sent, Booked).
Waiting for you comes first; filters All, Waiting, Sent, Done.
2. A customer's chat holds everything about that customer: the request as
the customer's bubble with Not now | Answer in the footer, the picker and the
recording, her answer as her bubble with the Ideal Text card, the send ask in
the footer, the customer's replies, her typed replies and the outcomes
(bought, booked) as lines. What she types there goes to that customer only;
the "To {customer}" chip is gone. A Take recorded in a customer's chat
belongs to that customer, so no answer can reach the wrong person. Will's
asks sit in the footer and what happened is a line in the middle; no Will
bubble in a customer's chat.
3. Will's chat is the Lounge as it is today: her own Takes, each answer's
Feedback walk ("Your answer to {customer} is sent. Your feedback is
ready."), the Ideal Text card with its new tag, helper words and practice.
Send first, walk after (N236 item 2) holds: she sends in the customer's chat
and is coached in Will's.
4. No group chat. A team comes later as a shared queue: Assign to {name} on a
customer's chat and a Team filter. A second trichologist's blind labels stay
their own queue (N240 item 2).
5. A speaker without customer requests never sees the list: the Lounge opens
as today, and the record → Ideal Text → feedback loop is unchanged (Never 3).
6. The Lounge is a locked screen: this entry is the founder's OK for the list
and the customer chats. Their new words wait for the founder's OK (Never 4).
The walk page's E1 gets its line when it is built.
Was (N236 item 1, §1 C1): the request as the one ask in the answerer's
Lounge, every customer in one thread.
The rules: frontend
[`docs/flows/customer-requests.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/customer-requests.md)
§1 C, D5, F and K, §3, §5. The prototype, kept as N229 says:
`docs/design/customer-requests-2026-10-28/ariel/ariel-lounge.html` and
`6-answerer-side-in-her-lounge.pdf`. No migration in this entry.

**N257 · Updating a project's deck, inside the project (founder, the
Claude Code chat, 29 October 2026: "what happens if I want to update the
pitch? I'm starting without the pitch deck and then I want to add the pitch
deck to that. Or I want to change the pitch deck", then three answers on a
decision page, and "show it to me based on real screens from the
application on a clickable prototype").** For N254 item 6, N48.2 Q4 and
contract clause 4:
1. A speaker adds a deck to a project that has none, or replaces its deck,
inside the same project: the Take count, the coach's history and the plan
carry on (N149). Contract clause 4's "a changed deck starts a new Project"
and the server's refusal of a Take with a changed deck (409
PRESENTATION_LOCKED) give way to this.
2. The new deck is used from the next Take. That Take writes the whole
Ideal Text fresh on the new slides; the previous text stays in the history
(rule 5). Helper words move to a new slide with the same title; the others
wait in the history until the speaker picks new ones.
3. Where: the Ideal Text page's ⋯ menu, "Add slides" when the project has
no deck and "Update slides" when it has one; and in the chat, the same in
place of "Create project from updated deck".
4. The words, signed: "Add slides" · "Update slides" · "Upload the new PDF.
Your next Take uses it." · "Upload PDF" · "Cancel" · "New slides ready for
Take {n}."
5. The prototype on the real screens, signed the same day ("OK", then
"button"): https://claude.ai/artifact/8heRv4BC6fGg7EzuzuTo4A. In the chat,
Will answers "You can update the slides in this project. Your next Take
uses them." and the upload takes the message box's place as the WhatsApp
ask does ("the button should be like the button for whatsapp number
update"): a grey card with "Update slides" and item 4's sentence, then
"Cancel" | "Upload PDF". On the first Take with new slides the mic screen
says "New slides" in place of "Same presentation as Take 1". Both lines
signed.
The rules: frontend
[`docs/flows/ideal-text.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/ideal-text.md),
with the first code; contract clause 4 is amended in the same pull request
as that code. No migration in this entry.

**N258 · The companions and your why are signed, Will's guide is signed, and
the Life Panel's first-run page says "# note" (founder, the Claude Code chat,
29 October 2026: "yes" to removing the first-run page's paragraph on the old
tags or replacing it with a line about "# note", and "YES AND YES for the
sign offs").** For N241, N253 and N255:
1. The prototype "Principles Companions" (version 3,
<https://claude.ai/artifact/1hfLf8mCif8pgC1X1Z6caJ>) is the design: its words
are signed as drawn (Never 4), and its open choices as drawn: Strengths is a
pill of its own, right after Principles; 💪 marks a strength; the talk
reminder comes the first time the Lounge opens on the day before the talk;
the sales steps are marked 🚪 🔍 🎁 📨; your why's lines are marked 🔥 🔭 🤝 and
sit at the top of the Life Panel's Goals screen, above Life goals.
2. Will's guide "what is in your control" (the Claude Doc
<https://claude.ai/artifact/EL8NpV6kPKdcEb2rjYc9Fj>, as of 28 October) is
signed and goes into Will's instructions word for word; Will's replies are
its own words, from the guide.
3. The Life Panel's first-run page drops its two paragraphs on the old tags
(#mistake, #observation, #win, #add) and says instead: "The way in is the
chat you already use. Start a message with # note, or tap the small mic, and
it is kept as a note for you and Will. On Sunday, when your notes show a
pattern, Will asks what you take from it and suggests a principle."
The rules: frontend
[`docs/flows/principles.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/principles.md)
§1 K, §2, §5. No migration in this entry.

**N259 · A finished walk opened again is a scroll, with no buttons (founder,
the Claude Code chat, 29 October 2026: "on the reopened walk there is only a
scroll there should be no buttons!", then, asked, "Buttons only after a tap"
and, on the Sniper's Skip, "Keep it").** Amends N247, for N89 and N91:
1. A Take's walk opened again once it is done (from its Feedback walk,
"Review feedback", a paragraph or its orange helper words) is a scroll. No
buttons under the thread and no Next, on any step. The bar's ✕ and ‹ › stay,
and clips still play.
2. Helper words stay editable on the latest Take (C3): a tap on one brings
"Edit the helper words" and "Keep these" under the thread for those words.
Once chosen, they go again.
3. A walk not yet done keeps the buttons of what still waits (B10).
4. The Sniper's "Skip" stays the speaker's own bubble, in the walk and when
it is opened again.
5. No new words on screen; nothing changes on the server.
The rules: frontend
[`docs/flows/feedback-walk-and-chat.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/feedback-walk-and-chat.md)
§1 B9, B10 and C3. No migration.

**N260 · One project at a time in the chat too, and "Settings" in its
question (founder, the Claude Code chat, 29 October 2026, on the prototype
https://claude.ai/artifact/Ta5hMGw8EbA6ewUssUugMK: "not to bring it back
from data and consent but Settings tab in the (hamburger menu icon)", then
"ok it's good; you have my GO!").** For N254, N196 and N257:
1. The question's sentence ends "you can bring it back from Settings."
in place of "from Data & consent": the ☰ menu's Settings page (renamed
from Data & consent, N196) is where the project list and Unarchive are.
Everything else in N254 item 4 stands. Signed.
2. Will's "Create new project" button in the chat asks the same question
before a new project starts, when there is a current project. In the chat
it takes the message box's place, as the WhatsApp ask and N257's slides
upload do: a grey card with the title and the sentence, then "Cancel" |
"Continue". Continue archives the current project and opens the new
project's setup as before; Cancel brings the message box back and leaves
the button under Will's reply. With no current project the button starts
the project at once, as today.
3. Updating the slides from the chat (N257) is as drawn on the same
prototype; nothing changes there.
The rules: frontend
[`docs/flows/recording-screens.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/recording-screens.md),
with the code. No migration in this entry.

**N261 · Customer requests: WillpowerLab is the client's shop and calendar
by default, at no cut, with fair default rules the client can change
(founder, the Claude Code chat, 29 October 2026, on the onboarding prototype
<https://claude.ai/artifact/SymprqggVVrFkJjJt7iEP7>: "make it as a default
option. But also, if you don't want you can add them too", then "we don't
take a cut of that", "they can have their own calendar or they can use a
WillpowerLab calendar", and on the proposed rules "You have my okay").** For
N225 item 2, N234, N236 item 6, N239 and N252:
1. **Sell and book here by default.** A client adds its treatments and
products in WillpowerLab, the customer pays in the answer chat (one pay
sheet for products and the booking) and the booking lands in a WillpowerLab
calendar. Shopify and Fresha stay as options from the fixed list (N252 item
2), connected instead by a client that already runs them. Was (N239): the
client's own Fresha and Shopify.
2. **No cut.** WillpowerLab takes nothing from a sale or a booking. The money
goes to the client's own Stripe account; the client pays the card fee. The
client pays only per answered request (N252 items 6 and 7).
3. **The calendar is the client's choice:** the WillpowerLab calendar,
pre-selected, or its own Google or Outlook calendar kept in sync both ways,
so nothing is booked twice.
4. **Default rules, the same for every client, each one changeable by the
client:** a booking is paid when booked; free to cancel or move up to 24
hours before; later than that, half is refunded; a no-show is not refunded;
products are collected in the salon free or shipped at a price the client
sets; unopened products come back within 14 days for a full refund.
5. **Rules no client can change:** when the client cancels, the customer gets
everything back; a faulty product is refunded or replaced; a refund goes
back to the card within 5 working days; no rule is set below the law's
minimum (the 14-day return right for online sales in the EU).
6. Onboarding asks this in two screens: where customers buy and book (with
the calendar), and the rules. Their words wait for the founder's OK with the
rest (Never 4).
The rules: frontend
[`docs/flows/customer-requests.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/customer-requests.md)
§1 E and I; its lines come in their own frontend PR. No migration in this
entry.

**N262 · The plan's questions: record first, Will asks again when he hears
nothing, and takes a correction (founder, the Claude Code chat, 29 October
2026, going through the questions themselves: "these questions are being
forced on me. I just wanted to start a new take, but I cannot", "when I'm
silent, the system still takes that. And it shouldn't. It should tell me,
oh, I didn't quite get what you mean", "if it was something wrong and the
user says like, oh, it's not what I meant, the chat actually agrees and
re-registers that answer", "I cannot play back my answers even"; then,
asked, "Record now, rest after", "Will: didn't quite catch it", "Will hears
it and agrees" and "Safari on a Mac").** Amends N136 and N146 (the questions
can't be skipped) and Never 3's wording, for N139, N140 and N150:
1. **Record first.** While a new speaker's voice questions are asked before
their first Take, "Start your first recording" (signed, N161) sits under
"Record your answer" and opens the recording at once. A question not
answered yet comes back after that Take's walk, as a new event's questions
come after a Take (A3); nothing asked is lost, and the plan's practices
count that Take. The questions never stand between a speaker and their
first Take. Never 3 in both CLAUDE.md files reads "the plan's questions
come once, before the first Take, and never stop the speaker from
recording it" in place of "the plan's questions come once, before the
first Take".
2. **Nothing heard.** A voice answer is checked for speech before it is
transcribed, as a Take is (`services/min_content_gate.py`). One with no
speech, or that gives no words, is not kept and not sent to a provider,
and Will says "Sorry, I didn't quite catch that. Could you say it again?";
the same question stays. Signed.
3. **A correction.** When the speaker's answer puts Will right ("No,
that's not what I meant …") instead of answering his question, Will
agrees, "Got it, thank you for putting me right.", says back in one
sentence what he now has, in their words and under N150's rules, and asks
the same question again. The correction takes the old answer's place in
the plan; the old answer stays in the history. The AI that writes Will's
turn tells a correction from an answer; when it fails, the answer counts
as an answer, as today. Signed.
4. **A voice answer plays in Safari.** The app answers the byte-range
requests Safari makes before it plays audio, for the speaker's voice
bubbles, "How you said it" and the coach's player. No new words.
The rules: frontend
[`docs/flows/the-plan.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/the-plan.md)
§1 A1, B3, B8, B9 and K, with the code; Never 3 in this repo's
CLAUDE.md in this entry's pull request. No migration in this entry.

**N263 · The empty Principles page drops "#mistake" (founder, the Claude Code
chat, 29 October 2026: "take that out").** For N253 and N258: the Life
Panel's Principles page, while it has no principle, said "No principles yet.
The first one arrives when you send a case with #mistake." Since N253 a "#"
message is one note and #mistake no longer sends a case, so the second
sentence goes; the page says "No principles yet." No new words.
The rules: frontend
[`docs/flows/principles.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/principles.md)
§1 K, §6. No migration in this entry.

**N264 · The rows `in_control` and `sales_framing` are set at ring 5 by a
migration (founder, the Claude Code chat, 29 October 2026: "Set the rings
yourself.").** For N241 and N258: the founder was to make these two rows on
the CEO panel's rings page; instead a migration seeds both at ring 5, with
their first audit entries, as 0498 did for `your_why` and `strengths`. A
row the founder made in the meantime stays as it is. With them, Will's
answer to a worry (O) and the sales steps (P) are on at ring 5. The
migration gets its outside review before it is merged. No new words.
The rules: frontend
[`docs/flows/principles.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/principles.md)
§2 R1, §6.

**N265 · STOP's answer drops "deleted your number"; any other WhatsApp reply
is forwarded to the founder by email (founder, the Claude Code chat, 29
October 2026: "Do it!", to "STOP reply words: keep the signed ones, or use
'Done. We've stopped the WhatsApp messages.'" and to "Other replies: your
rule N171 says any reply that isn't STOP should be forwarded to you by email.
Nothing does that yet, so say if you want it built").** For N171 item 6, N174
item 5 and N237 items 3 and 4:
1. WhatsApp's answer to STOP is "Done. We've stopped the WhatsApp messages."
(signed, Never 4). It replaces N174 item 5's words and N237 item 3: for an
account that signs in with WhatsApp the number stays, so "deleted your
number" was not true for everyone.
2. Any other reply to our WhatsApp number is emailed to the founder
(`ADMIN_EMAIL`), as N171 item 6 says. The email gives the sender's number, a
link to the admin page of each account at that number, and the reply's text,
or what kind of message it was when it is not text (a photo, a voice
message). The person gets no answer. This replaces N237 item 4.
3. It stays off until the privacy version N171 names the replies in is
published: `WHATSAPP_FORWARD_REPLIES=true` on Railway turns it on (off by
default), as `BOOKING_WHATSAPP_TO_ACCOUNT` does for N207. Until then other
replies are not read.
The rules: frontend
[`docs/flows/feedback-walk-and-chat.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/feedback-walk-and-chat.md)
§2, the line for N171. No migration.
