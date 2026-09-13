# MLC-3 Confident Moment Coaching Bundle — User Media Correlation Amendment D39

Status: proposed interface correction for ML/data review. D39 retains D38 except
where explicitly replaced below. It changes no runtime gate, serving state,
dataset eligibility, or learning surface.

## 1. Exercise family scope

Bundle-to-exercise correlation is intentionally available only for the exact
`confident_voice` attachment that is the Bundle's `confidence_anchor`.
`rewrite_clarity` and `great_formulation` attachments structurally return the
closed `not_supplied` response because they are Feedback Language items, not
exercise subjects. This is an explicit family rule, not a failed lookup or a
no-match result.

For `confident_voice`, the resolver requires the exact current
`feedback_v3_service_response_bindings` row produced by its acknowledged
five-state response. No correction/praise decision may substitute. Exercise
correlation therefore cannot become `available` before the owner has heard the
clip and submitted that exact response.

## 2. Bounded, non-waiting read locks

Both D38 read resolvers are synchronous user paths and may never wait
unboundedly on a writer. At entry they set a transaction-local `lock_timeout`
of at most 50 ms and a closed request-side server budget of at most 500 ms.
Every advisory serializer is acquired with `pg_try_advisory_xact_lock`; every
row serializer uses `NOWAIT`. Any unavailable lock, elapsed budget, or identity
set drift returns the one typed retry condition
`CONFIDENT_MOMENT_USER_READ_RETRY_REQUIRED`, mapped to HTTP 409 with no payload
or bytes. No partially derived identity may be followed after a failed lock.

The order remains the canonical writer-shared order: rollout policy, principal,
Project/Take inventory, then sorted exact feedback response, offer/catalogue,
recording/audio and media identities. The resolvers discover under coarse
locks, acquire the frozen fine set, rederive and hash it, and only then read or
stream. The source playback route repeats the complete live validation after
the R2 read while all transaction serializers remain held.

## 3. Visibility, playback and answer are distinct events

D14's exposure boundary is unchanged. Two painted visible frames trigger the
exact rendered-exposure ACK independently of playback. A visible but unplayed
item is therefore one exposure with no response.

The product state machine additionally disables the five-state answer controls
until authenticated source playback has completed successfully. Playback is a
UI precondition for answering, not a precondition for recording exposure. A
user who closes, skips, times out, or never plays leaves an unanswered rendered
exposure. Playback creates no second exposure and no confidence label.

The ordering is therefore:

```text
visible item -> rendered ACK (independent ledger)
authenticated source playback completed -> enable five-state response
exact response -> reveal concise Comment and later controls
```

## 4. Durable exact owner-decision projection

The database-owned Bundle projection must permit a hard reload to reconstruct
the interaction without browser memory or supplemental reads. Each attachment
therefore includes exactly one nullable `owner_decision` object derived under
the same D11/D39 stabilized projection locks.

Before any response it is null. After a valid exact response it is:

```json
{
  "feedback_family": "confident_voice|rewrite_clarity|great_formulation",
  "response": "closed-family-value",
  "decision_id": "uuid",
  "owner_response_id": "uuid-or-null",
  "response_binding_id": "uuid-or-null"
}
```

For `confident_voice`, both nullable IDs are non-null and equal the exact D16
response result lineage. For correction/praise both are null and `decision_id`
is the exact D16 human decision. Zero decisions is null. More than one current
decision, a foreign exposure, broken response binding, invalidated authority,
or stale identity makes the projection fail closed. The projection response
hash includes this object. It does not copy the value into a machine feature,
qualification, confidence truth, adequacy, outcome, dataset, or learning row.

`Save the text` may use these exact persisted IDs after reload. It remains the
single Bundle-level `save_owner_selected_root` action; `Lock` remains separate.

## 5. Retained D38 boundaries and added regressions

The user source-playback route remains same-origin, private/no-store, byte-hash
verified before/after R2 read, transcript-free, storage-key-free and presigned-
URL-free. The exercise resolver remains read-only, derives all identities
server-side, creates no offer, and reuses the canonical offer/playback/practice/
attempt/speaker chain. `not_supplied` remains nonsemantic.

In addition to D38 tests, prove:

- correction and praise return structural `not_supplied` without querying or
  creating an offer; only the exact confidence anchor can return `available`;
- every unavailable advisory/row lock returns HTTP 409 within the fixed budget
  and no bytes/payload, in both writer/read commit orders;
- visible-unplayed creates one rendered exposure and zero responses; playback
  completion enables response without creating another exposure;
- hard reload before response remains unanswered; hard reload after response
  reconstructs the exact D16 decision and permits only its exact downstream
  source matrix; foreign/duplicate/broken decisions fail closed.

All paths require the complete existing Bundle gate set and literal default to
disabled. Serving, collection, dataset creation, training, evaluation and
promotion remain disabled. The migration stays unnumbered and unmanifested.
