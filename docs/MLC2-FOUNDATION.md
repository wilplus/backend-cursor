# MLC-2 Foundation Slice 1

Contract: `MLC-2` · epoch: `1` · engineering design: `ED-2.4`

Decision-filter stamp:

`FILTER: ADVANCE-F2 — cat F2 — fences clear — locks clear — redirect: preserve the live loop while provenance foundations remain dark.`

## Scope and activation boundary

Migration `0302` is additive and dark by default. It creates the canonical
foundation but redirects no product write. It does not import historical data,
create a dataset release, train or promote a model, change a legacy learning
path, or activate a surface cutover.

`MLC2_FOUNDATION_ENABLED=false` is the application kill switch. Dataset
release, training and promotion flags are hard-coded false rather than
environment toggles. Enabling any of those capabilities requires a later
reviewed implementation and explicit authorization.

## Schema map

```text
ml_contract_epochs ── ml_learning_surfaces ── ml_learning_surface_aliases
                              │
owner_principals ── ml_speaker_principals ── ml_speakers
                              │                  │
                              │        ml_speaker_split_assignments
                              │                  │
ml_product_legal_approvals ── ml_consent_policies
                              │
                       ml_consent_events
                              │
                    ml_consent_event_purposes
                              │
                     ml_consent_snapshots
                              │
product transaction ── ml_outbox_events
                              │ leased, retryable, idempotent
                       ml_canonical_events
                        │       │       │
              ml_evidence_spans │  ml_product_actions
                        │       │   (never a judgment)
              ml_object_artifacts
                        │
              ml_object_verifications
                        │
              ml_semantic_artifacts
                        │
                 ml_presentations
                        │ authenticated post-paint ACK
              ml_rendered_exposures

ml_review_assignments ── ml_review_assignment_events ── ml_judgments
        blind packet           submit before reveal       immutable revisions
```

## Canonical registry and semantic walls

`ml_learning_surfaces` is the sole authority for exactly seven systems:

1. `confidence_classification`
2. `correction_generation`
3. `coach_comment_generation`
4. `praise_generation`
5. `praise_selection`
6. `correction_selection`
7. `ideal_text_generation`

Explicit aliases resolve to one canonical identifier. The ambiguous legacy
name `moment_suggestion` is registered as rejected and cannot be used for a
canonical write.

Meaning, computation and mutation remain independent:

- `feedback_family`: `confident_voice`, `great_formulation`,
  `rewrite_clarity`
- `pipeline_stage`: `classify`, `generate`, `select`
- `product_operation`: `replace`, `lock`, `unlock`, `style_orange`,
  `remove_orange`, `none`

Paragraph and orange decisions exist only in `ml_product_actions`. They may be
generation context, but are not judgments or supervision.

## Identity and splitting

Every canonical event must bind both:

- `acquisition_principal_id`: the exact account or guest through which the
  data entered the product;
- `speaker_id`: the stable person identity used for splitting.

The database enforces that the two are explicitly bound. A principal cannot be
silently rebound to another speaker. The same stable speaker receives one
deterministic 80/10/10 assignment for a split-policy version, regardless of
account, project, Take, clip or learning surface.

## Consent

No consent policy can become active without a foreign key to an immutable
`ml_product_legal_approvals` record containing the actual approval reference,
approved copy and evidence checksum.

The bundled UI acceptance creates two purpose records:

- personalized coaching;
- pooled model improvement.

Both use the counsel-approved Article 6(1)(a) basis. Article 9(2)(a) is also
captured when the approved classification of the processed voice data requires
it. Consent snapshots bind the exact acquisition principal and recording
attempt or Take. A later withdrawal is append-only and prevents creation of a
new eligible snapshot.

No Product/legal approval row or active policy is seeded by migration `0302`.
This is intentional: a chat statement is not an operational approval artifact.

## At-least-once outbox

Future surface-specific product RPCs must append their product state and call
`enqueue_mlc2_outbox_event_v1` within the same PostgreSQL transaction. A worker
claims events with a renewable lease and `FOR UPDATE SKIP LOCKED`.

`finalize_mlc2_outbox_event_v1` atomically inserts the immutable canonical
envelope and marks the outbox event processed. Duplicate delivery returns the
same canonical result through the source-event and idempotency constraints.
This is at-least-once delivery with effectively-once canonical results—not an
exactly-once transport claim.

Failures release the lease, retain a non-sensitive error code and schedule a
retry. They never reverse product state or redirect to a legacy learning table.

The service role receives read access to foundation tables, not direct write
access. Runtime writes pass through reviewed `SECURITY DEFINER` functions so a
caller cannot bypass identity, consent, idempotency, blindness or exposure
checks with a raw table insert.

## Blindness and exposures

`ml_review_assignments` freezes the exact packet hash, taxonomy and blindness
policy for one coach or peer. Assignment events are append-only. The reveal RPC
rejects a reveal until an immutable submission event exists.

`ml_presentations` means prepared/delivered. It is not exposure. Only
`ack_mlc2_rendered_exposure_v1`, with authenticated principal, secret token,
stable render identity and matching payload hash, creates a rendered exposure.
Shadow/evaluation packets cannot be acknowledged.

User practice self-reports, independently blind coach/peer ratings and
professional `yes/no/refine` decisions remain distinct. Professional and any
currently revealed coach-practice control are evaluation-only.

## R2 verification

`ml_object_artifacts` stores immutable R2 coordinates and expected SHA-256.
Content hashes are verification metadata, not global record identity. Multiple
speakers may legitimately produce identical content. Every download or release
check appends an `ml_object_verifications` row; the original artifact is never
overwritten.

## Monitoring

`get_mlc2_foundation_health_v1()` is aggregate-only and service-role-only. It
reports:

- pending and failed outbox events;
- oldest pending event;
- principals without resolved speakers;
- R2 artifacts without a matching successful verification;
- hard-disabled dataset, training and promotion state.

Logs and dashboards must use IDs and error codes, never transcripts, audio or
blind payload contents.

The Confidence founder-canary adds
`get_mlc2_confidence_canary_readiness_v1()`, also aggregate-only and
service-role-only. It validates Product/legal consent configuration, exact
founder-principal scope, non-founder isolation, outbox and lineage invariants,
blindness integrity, and hard-disabled downstream capabilities. The operator
check is independent of product routes and cannot activate a producer.

## Rollback

Application rollback disables future foundation producers. It does not delete
append-only rows. Queued outbox events remain durable and retryable. Rollback
must never re-enable a legacy training write.

For Confidence, one code-reviewed tri-state chooses both writer boundaries:
`dark` means canonical off/prior learning on; `founder_canary` means canonical
on/prior learning off; `killed` means both off. An invalid state fails as
`killed`. Once canary cutover occurs, rollback is to `killed`, never to `dark`.

Because migration `0302` is additive, database objects remain inert until the
next approved version. Removing them is not an incident rollback strategy.

## Next gates

Before any surface cutover:

1. Finish and approve that surface's dependency audit.
2. Implement its typed payload and write path.
3. Prove product mutation and outbox insertion are one transaction.
4. Prove blindness, exposure, idempotency and lineage behavior.
5. Obtain ML/data review.
6. Obtain separate cutover and deployment authorization.

Dataset release creation, training and promotion remain outside this slice.
