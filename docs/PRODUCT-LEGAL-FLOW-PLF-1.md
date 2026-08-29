# Product/legal onboarding and processing flow — PLF-1

**Status:** PRODUCT LOCKED · IMPLEMENTATION NOT YET AUTHORIZED  
**Decision date:** 2026-08-29  
**Owner:** Artur Willoński

This document is the authoritative product decision for onboarding,
recording eligibility, AI transparency, termination, deletion, and audio
lineage. It distinguishes legal duties from Willab product and risk controls.

It does **not** itself activate a legal policy, change the deployed Terms or
Privacy Policy, enable canonical learning writes, create a dataset, start
training, promote a model, or authorize deployment. An approved legal artifact
and separately reviewed implementation remain required.

## Locked user flow

1. During account or guest setup, the user actively accepts the current Terms.
   Recording and coaching remain unavailable without that acceptance.
2. The Terms state that a user may provide only recordings containing their
   own voice. There is no per-recording sole-speaker checkbox.
3. Setup records an `18+ confirmed` receipt with the applicable version and
   timestamp. Willab does not collect a full date of birth and never infers age
   from voice.
4. Setup collects country of residence once.
5. Location is rechecked only when risk signals or account circumstances
   materially change, not on every session or recording. The system stores the
   minimum result and policy version needed for enforcement and avoids
   unnecessary raw IP history, subject to separately approved security and
   legal-retention rules.
6. Applicable AI interaction and inference information is disclosed at first
   exposure. A persistent AI badge is a product choice, not an assertion that
   GDPR or the AI Act always mandates one.
7. The current approved model may generate and return feedback without waiting
   for dataset construction, fine-tuning, or model promotion.
8. Rejecting the required Terms means no recording/coaching service. Later
   ending the agreement is described as **termination**, not withdrawal of a
   mandatory consent while continuing to use the same service.

## Processing and learning boundary

Accepting a recording may atomically append an immutable authorization and
provenance event through the transactional outbox. This does **not** mean that
a dataset release or training job is immediately created.

The permitted sequence is:

```text
recording accepted
  -> immutable acquisition evidence and outbox event committed
  -> current approved model produces product feedback
  -> separately authorized eligibility and release processes may run later
```

Runtime events never feed training directly. Dataset creation, training,
evaluation, and promotion retain their existing independent authorization
gates. MLC-3 dataset creation additionally remains disabled until exact audio
object lineage, an approved label specification, and Product/legal release
authorization exist.

## Identity and audio lineage

- Keep the existing durable `owner_principal_id` for account and guest
  ownership.
- Canonical acquisition records reference that principal as
  `acquisition_principal_id`; this is not a second identity system.
- Reuse the existing canonical speaker identity instead of introducing a
  parallel subject graph.
- Exercise matching may add a `learning_profile_id` linked to the canonical
  speaker, subject to the separately approved MLC-3 design.
- Store an SHA-256 fingerprint of the exact immutable audio object used by a
  clip, dataset item, or deletion traversal. The hash verifies file identity;
  it does not identify a person from their voice. Because it remains linked to
  the recording, treat it as protected personal-data metadata.

## Termination and deletion

Termination or applicable account deletion must:

1. block new recording, coaching, provider upload, and exercise processing;
2. cancel pending provider, dataset, and training jobs;
3. prevent new dataset inclusion and model promotion;
4. delete applicable source data and artifacts from the database, R2,
   processors, and model providers;
5. invalidate affected dataset and model lineage and quarantine affected
   completed models for retraining or unlearning review; and
6. retain only narrowly justified evidence required by an approved retention
   rule, without treating historical acceptance receipts as current authority.

If third-party audio is reported or discovered, processing stops and the audio
is removed from learning eligibility under the same audited mechanisms.

## Legal duty versus product control

| Control | Classification |
| --- | --- |
| Stop unnecessary processing and erase deletable data after termination, subject to lawful exceptions | Legal/operational requirement |
| Applicable first-exposure AI disclosure | Legal requirement when the relevant AI Act duty applies |
| Voice-only Terms rule | Willab product/risk control |
| Active Terms acceptance | Willab contract/product control |
| `18+ confirmed` receipt | Willab product policy |
| Residence-country collection and risk-triggered location recheck | Willab launch/risk control; other laws may apply |
| Minimal location/IP retention | Data-minimisation implementation choice subject to security/legal retention |
| Refuse recording after rejection or termination | Willab service design |
| Feedback does not wait for training | Product architecture |
| Audio-object SHA-256 lineage | Technical accountability, training, and deletion safeguard |

No optional product control may be presented to users as “required by GDPR”
unless an authoritative legal artifact says so for the deployed circumstances.

## Preconditions for production activation

Before this flow is activated in production, the release evidence must include:

- an approved DPIA;
- exact approved Terms and Privacy Policy;
- processor DPAs and international-transfer arrangements;
- a retention schedule;
- a tested data-subject-rights process;
- security and breach-response procedures;
- documented AI Act classification for confidence and learning-profile
  processing;
- tested cross-provider deletion and cancellation; and
- current-authorization checks at every applicable downstream boundary.

No checklist or UI wording is represented as guaranteeing immunity from
regulatory action. Compliance depends on the actual deployed and operated
system.

## Supersession boundary

PLF-1 supersedes earlier conversational assumptions that Willab would:

- ask for a sole-speaker confirmation before every recording;
- collect a full date of birth;
- perform a country check before every recording; or
- make the user wait for model training before receiving feedback.

PLF-1 does not retroactively change the currently deployed consent contract or
the historical MLC-2 implementation record. Any lawful-basis change must be
made through the approved Product/legal configuration and migration process.
