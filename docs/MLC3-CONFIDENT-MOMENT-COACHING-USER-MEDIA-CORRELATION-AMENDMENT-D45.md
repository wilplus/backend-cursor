# MLC-3 Confident Moment Coaching Bundle — User Media Correlation Amendment D45

Status: proposed final implementability correction. D45 retains D38–D44 except
where replaced here. No gate, dataset, or learning change.

## 1. Closed integrity outcomes

R2 `ContentLength` absent, non-integer, or unequal to the exact reserved size is
terminal `CONFIDENT_MOMENT_SOURCE_MEDIA_POLICY_INVALID` before body allocation.
A stream ending before that exact length is the same terminal condition. A body
whose exact-size bytes hash differs from the frozen hash is also terminal policy
invalid. None is externally retried. No extra byte is buffered.

## 2. Stateless, request-bound emit authorization

The application generates one internal UUID `playback_request_id` per incoming
source-playback request. It is never accepted from the browser. Phase 3 adds
`p_playback_request_id uuid`; its successful read-only result includes that UUID,
the exact authority hash, exact buffered-byte hash, `authorized_at`,
`expires_at=authorized_at + 250 milliseconds`, `emit_authorized=true`, a response
hash, and `dataset_eligible=false`.

The result is a stateless authorization value, not a persisted receipt. Phase 3
inserts or updates no row and creates no ledger event. A transport timeout is
therefore always no-emit and requires no reconciliation; it consumes one of the
two permitted phase-3 attempts.

Immediately before constructing the response body, the route requires the exact
request UUID, authority hash and a fresh SHA-256 of the actual buffer to equal the
authorization value, requires its database-issued expiry to be in the future,
and consumes the request-local authorization exactly once. Any second use,
expiry, mismatch, or missing value emits no bytes. The authorization object is
not cached, returned to the browser, or shared across requests.

## 3. Byte-only process admission

The count ceiling is removed. Admission is governed only by the exact 50 MiB
aggregate reserved-byte ceiling and the 25 MiB per-object ceiling. This preserves
the hard memory bound without allowing two cancelled small requests to exhaust a
process-wide count slot. The hosting worker's existing bounded request
concurrency remains outside this media-specific byte ledger.

## 4. Required regressions

Tests cover each named ContentLength/short-stream/hash integrity case as terminal
and non-retryable. Phase 3 is proven read-only and a timed-out call consumes one
attempt with no reconciliation. Foreign request UUID, expired authorization,
changed buffer after authorization, and attempted second use emit zero bytes.
Many cancelled small requests cannot exhaust count capacity; aggregate exact
bytes above 50 MiB still reject before R2; every admitted reservation returns to
zero by the hard eight-second bound.

All D38–D44 authority, deadline, privacy, correlation, no-offer, no-label,
readiness, and literal-default-off clauses remain in force. The migration stays
unnumbered and unmanifested.
