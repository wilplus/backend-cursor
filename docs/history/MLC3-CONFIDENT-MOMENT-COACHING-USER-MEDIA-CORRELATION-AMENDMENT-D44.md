# MLC-3 Confident Moment Coaching Bundle — User Media Correlation Amendment D44

Status: proposed implementability correction. D44 retains D38–D43 except where
replaced here. No gate, dataset, or learning change.

## 1. Database-owned final emit authorization

Phase 3 is a distinct service-role-only RPC:

```text
authorize_confident_moment_source_playback_emit_v1(
  p_acquisition_principal_id uuid,
  p_bundle_id uuid,
  p_bundle_attachment_id uuid,
  p_expected_authority_sha256 text,
  p_buffered_bytes_sha256 text
) returns jsonb
```

Inside one transaction it acquires the same complete bounded writer-shared lock
graph as the phase-1 resolver, rederives the exact authority, compares it with
`p_expected_authority_sha256`, compares `p_buffered_bytes_sha256` with the exact
current media hash, and performs the final emit/no-emit decision while those
locks remain held. Only success returns the closed receipt
`confident-moment-source-playback-emit-v1` with exact principal, Bundle,
attachment, authority hash, byte hash, `emit_authorized=true`, receipt hash, and
`dataset_eligible=false`. The application performs no authority comparison of
its own and may construct a byte response only from that exact receipt. A later
invalidation does not reinterpret the immutable decision that the read was
authorized at that instant, just as a writer commit after any authenticated
read cannot retract bytes already authorized.

Authority drift returns `CONFIDENT_MOMENT_USER_READ_RETRY_REQUIRED`; invalid
bytes or a terminal media leaf return the exact terminal condition. No failure
returns an emit receipt.

## 2. Enforceable transport deadlines

Each phase-1, phase-3, and exercise-correlation PostgREST request uses a
dedicated service-role HTTP transport with a 500 ms total request deadline, no
automatic retry, and closed response validation. Transport timeout maps to the
typed HTTP 409 retry condition and returns no payload or bytes. SQL retains its
non-waiting serializers and internal 500 ms cutoff as defence in depth.

The private R2 reader uses no SDK retry, starts a monotonic 7.5-second internal
deadline before connect, and uses connect/read operations capped at 250 ms.
It reads in bounded chunks, checking the deadline before each operation; the
250 ms maximum overrun keeps the complete phase below D43's eight-second outer
bound. It requires R2 `ContentLength` to equal the exact reserved byte size
before allocation and reads exactly that length. It does not perform an
additional one-byte buffered probe. Hashing is included in the 7.5-second
internal deadline. Any timeout closes the body and returns the typed retry.

Frontend Cancel aborts the browser/BFF request immediately and leaves the item
unanswered. WSGI does not expose a reliable client-disconnect signal before a
buffered response is written, so server work already inside R2 may continue only
until the hard eight-second bound; its mandatory `finally` then releases the
exact reservation. The contract does not falsely claim earlier server-side
cancellation. No byte is emitted to the cancelled client, and two abandoned
requests cannot hold process admission beyond the hard bound.

## 3. Required regressions

Tests must prove the app cannot emit from the phase-1 authority alone; only the
exact phase-3 receipt permits response construction. Invalidation in either
order around phase 3 yields either the fully authorized prior read or no bytes.
Foreign/changed authority or byte hashes produce no receipt. PostgREST phase-1,
phase-3, and correlation delays exceed neither 500 ms nor one closed retry
response. Slow-progress and blocked R2 reads terminate below eight seconds,
release counters, and emit no bytes. R2 length underflow/overflow is rejected
before body buffering. Browser cancellation is immediate; server admission is
proven released by the hard deadline even when WSGI supplies no disconnect
signal.

All D38–D43 family scope, exact owner-decision projection, privacy, exercise
correlation, no-offer creation, no-label, readiness, and literal-default-off
clauses remain in force. The migration remains unnumbered and unmanifested.
