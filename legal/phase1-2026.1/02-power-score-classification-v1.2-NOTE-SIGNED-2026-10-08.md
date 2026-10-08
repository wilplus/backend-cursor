# Document 02, version 1.2 — note for the learned detector (detector training) — SIGNED by the founder 2026-10-08

**SIGNED by the founder, 8 October 2026** (in chat: "I sign the 3.5 pack of 8 October 2026 as drafted"; decisions log N68). **Counsel has not seen these changes**; the founder signed knowing that.

    artifact_kind:       power_score_classification
    version:             1.2 — supersedes 1.1 (signed 2026-10-02) by version bump, never in place (04 §5)
    form:                this note lists the changes; on signature v1.2 is rendered as v1.1's full text with
                         these changes applied (a new §3c, a §9 addition, the metadata), then signed and hashed
    approving_authority: Artur Willoński (founder and controller) — controller's own determination, NOT counsel-reviewed
    approved_at:         2026-10-08 (in chat: "I sign the 3.5 pack of 8 October 2026 as drafted"; decisions log N68; counsel has not seen it)
    object_key:          phase1-2026.1/legal/power-score-classification-v1.2.pdf
    sha256:              [[computed from the signed PDF at registration time]]
    metadata: {
      "pipeline_version": "voice-confidence-universal-v3",
      "detector_versions": {"rushing": "rules-v1", "word_compression": "rules-v1", "ending_compression": "rules-v1"},
      "detector_candidates": {"tuned": "shadow", "learned": "shadow, fit gated by DETECTOR_TRAINING_AUTHORISED"},
      "biometric_identification": false,
      "sex_gender_inference": false,
      "emotion_intention_inference": false
    }

## Why a v1.2

v1.1 §3b and §9 keep `DETECTOR_TRAINING_AUTHORISED` off "until counsel
confirms" (the §9 note on gate 6d; `config.py`, the comment above the
constant; decisions log N26 and N29). The founder asked on 2026-10-08 to open
every learning pipe. Detector training is the one pipe that rests on this
document, so the document must either keep it shut or say, as the
controller's own determination, why fitting the detector changes nothing in
§9 and on what condition it may run. v1.2 does the second and keeps the
first's honesty: counsel's confirmation (question 1 of
`21-counsel-questions-2026-10.md`) is still outstanding and still requested.

## The changes

### New §3c — the learned detector (facts)

> **What would be trained.** `LearnedDetector` in
> `services/detector_candidates.py`: one small model per speaking error
> (rushing, word compression, ending compression), on eight timing features
> of a clip already computed for the rules detectors: words per minute,
> pause ratio, pause regularity, median gap between words, share of very
> tight gaps, word occupancy, word-recognition confidence, ending duration
> ratio. Its label is a coach's blind answer to "Do you hear [the pattern]
> here?" (gate 6a, `services/error_presence_audit.py`), never an answer about
> the speaker's state. Its output is the same as the rules detector's: "this
> pattern occurs in this clip", yes or no.
>
> **What is not trained on.** No audio, no pitch contour, no voice-confidence
> composite, no transcript text, no owner answer, no peer rating (L3). Only
> clips whose speaker holds an active training yes under training-only-v2
> (Privacy 3.5 §3 and §4a; the fit must filter, 22-…, E3).
>
> **Where.** On WillpowerLab's own systems. Nothing is sent to OpenAI.
>
> **State on 2026-10-08.** `fit` raises `NotImplementedError`; the learned
> candidate scores nothing and runs in shadow only. A fitted detector would
> join the shadow registry first and route an exercise only when made live
> by its own reviewed change (`LIVE_DETECTOR`).

### §9 — addition after the Q7 note

> **Detector training, 2026-10-08.** Fitting the detectors on coaches' blind
> answers does not change any line above. The trained detector answers the
> question the rules detector answers, about a delivery, from the same
> timing features; its labels are a listener's answer about a speaking
> pattern, not a judgement of a feeling, so training on them moves the
> detector further from the §7.2 case for inclusion (a construct validated
> against human judgements of confidence), not closer. It identifies no one
> and infers no sex or gender (§5, §6). The three booleans hold for the
> trained detector as for the rules.
>
> **What the controller decides.** v1.1 kept gate 6d shut until counsel
> confirms. v1.2 replaces that condition, for gate 6d only, by these three:
> (a) the fit reads only clips of speakers with an active training yes under
> Privacy 3.5; (b) a fitted detector runs in shadow until a separate reviewed
> change makes it live; (c) it routes exercises only, never a verdict shown to
> anyone (AC-9). **The founder signs knowing that §9's own condition is
> engaged and counsel's confirmation is overdue: until counsel answers, an
> unreviewed determination is applied to other people's voices, and now also
> to a model trained on coaches' answers about them.** If counsel answers
> `true` on any line, gate 6d closes again by a reviewed change the same day.

### Not changed

§§1–8 and the rest of §9, word for word. The deployment fence (§8, Terms §7,
not for employers or schools) is unchanged and matters more once a detector
learns: a learned detector deployed in a workplace would sit beside Article
5(1)(f).

## For counsel, with question 1

1. Does fitting the detectors on coaches' blind answers change your answer
   on Article 3(39) for them?
2. Fine-tuned text models (Privacy 3.5 §4a, doors 3 and 4): engineering's
   reading is that fine-tuning a general-purpose model by a small fraction of
   its original training compute does not make WillpowerLab the provider of a
   general-purpose AI model (the Commission's guidelines on GPAI providers,
   July 2025), and that the generated text stays under document 03's
   Article 50(2) marking. Please confirm or correct.
