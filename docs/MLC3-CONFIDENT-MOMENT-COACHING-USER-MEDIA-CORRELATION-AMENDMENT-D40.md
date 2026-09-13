# MLC-3 Confident Moment Coaching Bundle — User Media Correlation Amendment D40

Status: proposed interface correction for ML/data review. D40 retains D38 and
D39 except where replaced below. No runtime, dataset, or learning gate changes.

## 1. Buffered source playback with one inclusive bound

The user source-playback route never streams or emits a response byte while the
private object read is in progress. It buffers the complete object in memory,
with a fixed reviewed maximum of 10 MiB. Objects over that cap fail closed.
Only after the complete byte SHA-256 matches the frozen authority and the full
post-read live revalidation succeeds may the response body be emitted.

The 500 ms request-side server budget is inclusive of lock acquisition, the
complete R2 connect/read round trip, hashing, and post-read validation. The R2
client has explicit connect and read timeouts strictly inside that remaining
budget. Budget exhaustion, oversize media, lock contention, identity drift, or
post-read invalidation releases all transaction serializers and returns
`CONFIDENT_MOMENT_USER_READ_RETRY_REQUIRED` with no payload or bytes. Writer
paths sharing these serializers must likewise use their reviewed bounded or
non-waiting acquisition behavior; this reader may not introduce an unbounded
writer wait.

## 2. Exact derived owner decision

`owner_decision` is not a stored Bundle column. It is derived under lock from
existing canonical response/binding or human-decision rows on every projection
read. It acquires no serializer outside the canonical writer-shared order and
is read at that order's sorted exact-feedback-response position.

`owner_decision=null` means exactly zero current decisions for that attachment.
A broken/foreign/stale binding, invalid authority, or more than one current
decision fails the entire projection with its typed error and no attachment
payload; it is never represented as null or as unanswered.

The closed object is:

```json
{
  "feedback_family": "confident_voice|rewrite_clarity|great_formulation",
  "response": "family-specific-value",
  "decision_id": "uuid",
  "owner_response_id": "uuid-or-null",
  "response_binding_id": "uuid-or-null"
}
```

The exact response vocabularies are:

- `confident_voice`: `yes`, `in_between`, `no`, `not_sure`, `audio_unclear`;
- `rewrite_clarity`: `apply_suggestion`, `keep_wording`;
- `great_formulation`: `useful`, `not_useful`, `not_sure`.

For confidence, both nullable IDs are non-null. For correction and praise, both
are null and `decision_id` is the exact canonical human decision. The projection
hash includes the complete object and therefore changes on null-to-object
transition; a cached unanswered projection cannot be served after response.

## 3. Retry and UI closure

HTTP 409 from either resolver creates no rendered-exposure ACK, playback event,
or other ledger row. (The independent visibility ACK may already exist because
the item was visibly rendered before the resolver was called; the resolver
itself never creates or duplicates it.) A failed or 409 playback leaves the
five-state controls disabled and the item unanswered.

The client performs bounded external retries of
`CONFIDENT_MOMENT_USER_READ_RETRY_REQUIRED` using the same exact request
identity and capped backoff; it never spins indefinitely. Exhaustion presents a
retry action and preserves the unanswered state.

## 4. Retained boundaries

D39's confidence-anchor-only exercise scope is unchanged. Correction and praise
return structural nonsemantic `not_supplied`. D14 visibility ACK remains
independent of playback; successful authenticated playback is only the UI
precondition for enabling the five-state response. Source playback remains
same-origin, private/no-store, transcript-free, storage-key-free and presigned-
URL-free. Exercise correlation remains read-only and creates no offer.

All required D38/D39 races and regressions remain, plus explicit oversize,
connect timeout, read timeout, post-read invalidation, no-byte-on-failure,
projection-hash transition, broken-decision whole-projection failure, no-ledger-
row-on-resolver-409, and bounded-client-retry tests.

All paths literal-default to disabled. Serving, collection, dataset creation,
training, evaluation and promotion remain disabled; the migration remains
unnumbered and unmanifested.
