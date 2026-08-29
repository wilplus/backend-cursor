# Product/legal onboarding and processing flow — PLF-1.1

**Status:** PRODUCT LOCKED · IMPLEMENTATION NOT YET AUTHORIZED
**Decision date:** 2026-08-29
**Owner:** Artur Willoński

PLF-1.1 supersedes PLF-1. Its material change is the separation of required
service processing from optional pooled model improvement.

This document does not activate a legal policy, change deployed Terms, collect
an authorization, enable learning writes, create a dataset, train or promote a
model, or authorize deployment.

## Locked authorization model

### Required service processing

Recording and coaching require active acceptance of the current service Terms
and processing notice. Required service processing covers only the purposes
needed to provide the requested product:

- `core_recording_voice_processing`
- `coach_review`
- `personalized_exercise_recommendation`

If the user does not accept, or later terminates the service agreement,
recording and coaching are unavailable.

### Optional pooled model improvement

`pooled_model_improvement` is a separate authorization state and a separate
affirmative action:

- its control begins unchecked;
- accepting service processing never silently enables it;
- the user may decline it and still record and receive coaching; and
- the user may later withdraw it while continuing to use the service.

Withdrawal immediately prevents the data from entering future dataset
releases, training or retry, evaluation, and model promotion. It does not erase
the immutable acquisition history, make previous processing unlawful, or
claim that trained model weights were automatically deleted.

Whole-service termination and pooled-improvement withdrawal are different
actions with different effects.

## User flow

1. During account or guest setup, the user actively accepts the current
   required service Terms/notice.
2. A separate, initially unchecked control offers pooled model improvement.
3. The Terms state that the user may provide only recordings containing their
   own voice. There is no per-recording sole-speaker checkbox.
4. Setup stores an `18+ confirmed` result with version and timestamp. No full
   date of birth is collected and age is never inferred from voice.
5. Setup collects country of residence once.
6. Gateway location is reassessed only after a versioned risk signal or
   material account circumstance change, not on every session or recording.
7. Applicable AI interaction/inference information appears at first exposure.
8. Feedback from the current approved model does not wait for dataset
   construction or training.

## Identity and provenance

- Reuse `owner_principal_id` as the durable account/guest owner.
- Acquisition records reference it as `acquisition_principal_id`; this is not
  a second identity system.
- Reuse the existing canonical speaker identity for ML splitting.
- A future `learning_profile_id` belongs to the separately approved MLC-3
  exercise-matching design.
- Every accepted recording references the immutable required-service
  acquisition snapshot active at capture.
- Pooled authorization is recorded independently and is rechecked at every
  downstream learning boundary.
- Store an SHA-256 fingerprint of the exact immutable audio bytes used by a
  clip or release item. It verifies the file, not the speaker, and remains
  protected personal-data metadata while linked to the recording.

## Dataset eligibility

Dataset eligibility is never inherited from a policy flag or an old snapshot.
Every prospective release item must receive a fresh, immutable eligibility
decision that verifies:

1. the original acquisition snapshot;
2. current pooled-improvement authorization;
3. exact acquisition-principal and canonical-speaker lineage;
4. current retention, withdrawal and deletion state;
5. a newly recomputed audio-object SHA-256; and
6. the applicable surface-specific MLC-2 or MLC-3 eligibility contract.

Runtime events never feed training directly. Dataset creation, training,
evaluation and promotion retain independent technical and approval gates.

## Withdrawal, termination and deletion

### Pooled-improvement withdrawal

- leaves recording and coaching active;
- cancels pending dataset/training/evaluation/promotion work for that data;
- prevents new release inclusion;
- invalidates affected not-yet-permitted learning lineage where required; and
- preserves the immutable grant/withdrawal history.

It does not automatically trigger deletion of product recordings needed to
continue coaching.

### Service termination or account deletion

- blocks new recording, coaching, provider upload and exercise processing;
- cancels pending product and learning jobs;
- prevents new dataset inclusion and promotion;
- deletes applicable database, R2, provider and dataset artifacts;
- invalidates affected lineage and quarantines affected completed models for
  retraining/unlearning review; and
- retains only narrowly justified legal/security/billing evidence under an
  approved retention rule.

If third-party audio is reported or discovered, processing stops and the audio
is removed from learning eligibility through the same audited mechanisms.

## Legal duty versus product control

| Control | Classification |
| --- | --- |
| Stop unnecessary processing and erase deletable data after termination, subject to lawful exceptions | Legal/operational requirement |
| Applicable first-exposure AI disclosure | Legal requirement when the relevant AI Act duty applies |
| Voice-only Terms rule | Willab product/risk control |
| Required service acceptance | Willab contract/product control governed by the approved legal artifact |
| Optional pooled-improvement choice | Independent learning authorization governed by the approved legal artifact |
| `18+ confirmed` receipt | Willab product policy |
| Residence country and risk-triggered reassessment | Willab launch/risk control; other laws may apply |
| Minimal location/IP retention | Data-minimisation implementation choice subject to security/legal retention |
| Feedback does not wait for training | Product architecture |
| Audio-object SHA-256 lineage | Technical accountability, training and deletion safeguard |

No product control may be presented as “required by GDPR” without an
authoritative legal determination for the deployed circumstances.

## Activation prerequisites

- approved DPIA;
- exact approved Terms, Privacy Policy and optional pooled-improvement copy;
- lawful-basis and Article 9 treatment per purpose;
- processor DPAs and international-transfer arrangements;
- retention schedule and data-subject-rights process;
- security and breach procedures;
- documented AI Act classification;
- tested provider/R2/database/dataset cancellation and deletion; and
- current-authorization checks at every downstream boundary.

PLF-1.1 supersedes any earlier assumption that pooled model improvement is
mandatory to receive recording/coaching, that one service acceptance silently
authorizes pooled learning, or that pooled withdrawal must terminate the
service.
