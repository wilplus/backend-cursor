# MLC-3 Confident Moment Coaching Bundle — User Media Correlation Amendment D43

Status: proposed final interface correction. D43 retains D38–D42 except where
replaced here. No gate, dataset, or learning change.

## 1. Exact-size bounded buffering

The eligible confidence-source object contract freezes a 25 MiB maximum at
acquisition and playback. Before opening R2, the route reserves the exact frozen
`processing_audio_objects.byte_size`; buffer occupancy may never exceed that
reservation. The read aborts on the first byte beyond the reserved size, emits
nothing, releases the reservation, and returns
`CONFIDENT_MOMENT_SOURCE_MEDIA_POLICY_INVALID`. A stream ending before the exact
reserved size returns the same integrity condition. The exact byte SHA-256 must
also match the phase-1 frozen hash.

The per-process admission contract is at most two concurrent buffered source
playbacks and at most 50 MiB aggregate reserved bytes. Admission occurs before
any R2 connection or ledger write. Every success, named terminal/retryable path,
client cancellation, process-level request abort, and unhandled exception during
phase 2 releases its count and exact-byte reservation in a mandatory finalization
boundary. Tests must prove aggregate reserved count and bytes return to zero for
each outcome.

## 2. Buffer TTL and phase-3 attempts

The fixed two-second buffer TTL begins only when the complete exact-size R2 read
finishes successfully. Each phase-3 attempt has the D39 500 ms budget. An attempt
may begin only if its entire budget fits inside the remaining TTL. No more than
two attempts may begin for one buffer, and neither attempt rereads R2 or re-enters
phase 1.

Once an attempt has acquired the full canonical serializers, it completes the
emit/no-emit decision under its fresh phase-3 authority comparison even if wall
time crosses the TTL. The held-lock comparison, not the expired timer, governs
currency for that decision. An authority-hash mismatch releases serializers,
discards the buffer, and returns the retryable D39 condition. Contention-budget
exhaustion without a permitted next attempt discards the buffer and returns that
same retryable condition.

## 3. Regression closure

Regressions must prove exact-size overflow and underflow, byte-hash mismatch,
admission rejection before R2, TTL origin after read completion, insufficient
remaining-TTL rejection, at most two phase-3 attempts, successful decision that
finishes after TTL while serializers remain held, cancellation, process abort,
and unhandled phase-2 exception. Every non-success path emits zero bytes, creates
no owner response or playback event, preserves the pre-existing visibility
exposure as unanswered, and leaves both admission counters at zero.

All D38–D42 family scope, exact owner-decision projection, three-phase authority
hashing, server-derived lineage, privacy, exercise correlation, no-offer
creation, no-label, readiness, and literal-default-off clauses remain in force.
The migration remains unnumbered and unmanifested.
