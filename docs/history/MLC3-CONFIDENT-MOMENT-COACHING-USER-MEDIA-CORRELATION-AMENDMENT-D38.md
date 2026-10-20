# MLC-3 Confident Moment Coaching Bundle — User Media Correlation Amendment D38

Status: proposed interface closure for ML/data review. This document changes no
runtime gate, serving state, dataset status, or learning surface.

## 1. Problem and retained boundaries

The Bundle projection intentionally returns `exercise: null` and must not join
exercise offers or private exercise media. The user interaction nevertheless
requires (a) playback of the exact opaque source clip before the five-state
response and (b) reuse of an already-created canonical MLC-3 exercise offer,
when one exists, for playback and optional re-recording.

An opaque presentation UUID is not a URL. Absence from either resolver means
only `not_supplied`; it is never a no-match, confidence, adequacy, improvement,
or learning signal. Neither resolver creates an offer, assignment, exposure,
response, practice record, outcome, dataset row, or ninth learning surface.

## 2. User source-audio playback

Add the authenticated same-origin route:

```text
GET /v2/user/confident-moment-bundles/{bundle_id}/attachments/{bundle_attachment_id}/source-playback
```

The browser supplies only the two opaque UUIDs. The authenticated owner user is
resolved to the acquisition principal server-side. A service-role-only SQL
resolver derives and returns a short-lived internal read authority containing
the exact Bundle/attachment, membership/candidate/evidence span, canonical
presentation, recording/audio lineage, bucket/object version, exact byte hash,
content type, principal, Project, source Take, policy and authorization
identities. It returns no transcript or storage key to the browser.

The route reads bytes through the existing private R2 client. It performs the
same current D4 dual-purpose authority, principal, deletion/purge/retention,
quarantine, media-version and exact-hash checks immediately before and after
the object read. The before/after authorities must be identical. Any foreign,
stale, deleted, invalid, ambiguous, changed, or hash-mismatched state returns no
bytes. Responses are `private, no-store` and same-origin; presigned URLs are
forbidden.

This playback is a read only. The existing Bundle item rendered-exposure ACK
remains the sole exposure ledger and is emitted only after authenticated visible
render; playback itself creates no second exposure.

## 3. Read-only Bundle-to-exercise correlation

Add:

```text
GET /v2/user/mlc3/confident-moment-exercise/{bundle_id}/{bundle_attachment_id}
```

and the service-role-only SQL resolver:

```text
resolve_confident_moment_exercise_offer_v1(
  p_acquisition_principal_id uuid,
  p_bundle_id uuid,
  p_bundle_attachment_id uuid
) returns jsonb
```

The browser cannot assert Project, Take, membership, candidate, evidence,
response binding, authorization check, acquisition receipt, candidate set, or
offer identity. PostgreSQL derives them through the exact immutable Bundle and
attachment lineage and the existing D2/D4 service records.

An `available` result requires exactly one current live offer whose
`acquisition_principal_id`, Project, source Take, feedback membership,
candidate, source audio lineage and feedback response binding equal the exact
Bundle attachment lineage. The response binding must still be current for the
exact rendered response. The offer's authorization check, N1 candidate-set
snapshot, selected exercise version and source acquisition receipt must still
be current/live and belong to the same principal and source acquisition.
Current D4 access, both required service purposes, deletion, media and catalogue
authorization are revalidated after contention and on exact replay.

The resolver acquires the existing rollout/principal and source Project/Take
inventory serializers, then the exact feedback response, offer, catalogue and
media serializers in the canonical sorted order shared with their writers. It
re-derives the identity set under lock. An identity-set change yields one typed
retry; zero valid rows yields `not_supplied`; more than one valid row or broken
lineage fails closed as projection invalidity.

Closed response shapes are:

```json
{
  "contract_version": "confident-moment-exercise-correlation-v1",
  "status": "not_supplied",
  "bundle_id": "uuid",
  "bundle_attachment_id": "uuid",
  "offer_id": null,
  "correlation_sha256": "64-lowercase-hex",
  "dataset_eligible": false
}
```

or:

```json
{
  "contract_version": "confident-moment-exercise-correlation-v1",
  "status": "available",
  "bundle_id": "uuid",
  "bundle_attachment_id": "uuid",
  "offer_id": "uuid",
  "feedback_response_binding_id": "uuid",
  "n1_candidate_set_id": "uuid",
  "authorization_check_id": "uuid",
  "source_acquisition_receipt_id": "uuid",
  "correlation_sha256": "64-lowercase-hex",
  "dataset_eligible": false
}
```

No other keys are permitted. `not_supplied` is valid-empty and nonsemantic.
Once `offer_id` is available, the browser must reuse the existing canonical
`GET offer -> authenticated playback -> render/playback events -> create
practice session -> upload practice attempt -> speaker confirmation` chain.
It may not call offer creation as a lookup.

## 4. Frontend ordering and retry identity

The user overlay is a state machine:

```text
visible exact source playback -> exact rendered ACK -> five-state response
-> concise Comment -> optional Rephrase Update/Cancel -> correlated exercise
when available -> playback -> optional re-record -> Save the text/Cancel
```

The render-instance UUID and idempotency key are generated once per exact
Bundle/attachment/presentation identity and retained outside the overlay until
the server ACK succeeds. Network failure retries the same identity. Remount,
close/reopen, or React remount may not create a different exposure attempt.
Only an acknowledged exact exposure may be used by the response.

`Save the text` is one Bundle-level action, never repeated per attachment. It
uses `save_owner_selected_root` and the exact source matrix: response and text
revision for accepted wording; practice attempt and both source/practice
speaker bindings for a chosen re-recording. `Lock` remains a distinct later
action. Null or mixed provenance fails before mutation.

## 5. Required regressions

- Source bytes are unavailable before/after authority withdrawal, deletion,
  purge, quarantine, media replacement, hash mismatch, or foreign binding;
  two-connection races in both commit orders return either one fully validated
  prior read or no bytes, never mixed authority.
- Playback returns no transcript, R2 key, presigned URL, or cross-principal data.
- Correlation returns exact `available` for one live matching offer and exact
  `not_supplied` for zero; duplicate, stale, foreign, or changed identities fail
  closed. It creates zero offers/events/practice/outcome/learning rows.
- Frontend cannot show Comment before the exact five-state response; render
  retry/remount reuses one identity and one exposure.
- Existing canonical exercise playback/practice flow is reused unchanged.
- Valid-empty first-owner Ideal Text state remains editable; multiple Bundle
  identities in one Paragraph remain separately reachable.
- Every mutation response is recursively closed and validates echoed identity,
  bigint strings, content hashes and `dataset_eligible=false`.

## 6. Gates

All new backend and frontend paths require the existing complete Confident
Moment Bundle gate set and literal default to disabled. All serving, collection,
dataset creation, training, evaluation and promotion gates remain disabled.
The migration remains unnumbered and unmanifested. No activation is authorized.
