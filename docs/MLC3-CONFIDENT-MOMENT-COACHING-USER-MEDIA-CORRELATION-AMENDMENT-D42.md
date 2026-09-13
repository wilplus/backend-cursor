# MLC-3 Confident Moment Coaching Bundle — User Media Correlation Amendment D42

Status: proposed interface correction. D42 retains D38–D41 except where
replaced here. No gate, dataset, or learning change.

## 1. Frozen playback eligibility and memory admission

The eligible confidence-source object contract freezes a 25 MiB maximum at
acquisition and playback, independent of later runtime configuration. The exact
immutable `processing_audio_objects.byte_size` is part of both authority hashes.
Before this gate may ever activate, a SELECT-only readiness check must prove
that every eligible live confidence-source object is at most 25 MiB; otherwise
activation fails closed. Every later writer feeding this path must reject bytes
over 25 MiB before durable media validity is recorded. Consequently no object
that validly entered this path can later receive a user-facing size failure.

The route admits at most two concurrent buffered source playbacks per process
and at most 50 MiB aggregate buffered bytes. It reserves the exact frozen object
byte size before opening R2. Admission failure returns the retryable D39
condition before any R2 connection or ledger write. The reservation is always
released on success, failure, or cancellation.

An existing live object above 25 MiB is not `SOURCE_MEDIA_TOO_LARGE`; it is the
typed integrity condition `CONFIDENT_MOMENT_SOURCE_MEDIA_POLICY_INVALID`, is
never retried by the client, and blocks activation/readiness for its principal.

## 2. Bounded phase-3 reuse

After one successful buffered R2 read, phase 3 may make at most two non-waiting
revalidation attempts within a fixed two-second buffer TTL, using capped jittered
backoff and without re-entering phase 1 or rereading R2. Each attempt freshly
derives the current authority. An authority-hash mismatch immediately releases
all serializers, discards the buffer, and returns the retryable D39 condition;
it is never retried against that buffer. TTL expiry also discards it and requires
a full externally bounded retry.

The buffered byte SHA-256 is checked against the phase-1 frozen exact-byte hash,
which a successful phase-3 authority comparison has just proven is still
current. While making the final emit/no-emit decision, phase 3 holds the full
canonical serializers. No byte is emitted before that decision.

## 3. Failed playback and user state

The explicit regression matrix includes attempted playback ending in admission
contention, R2 connect timeout, R2 read timeout, cancellation, integrity-policy
failure, byte-hash mismatch, phase-3 contention exhaustion, authority drift,
or post-read invalidation. Every case leaves answer controls disabled, creates
no owner response, and preserves exactly one pre-existing visibility exposure
without duplicating it.

During phase 2 the UI shows only a neutral loading state and an explicit Cancel.
Cancel aborts the R2 request, releases memory admission, creates no playback or
response event, and leaves the rendered exposure unanswered.

All other D38–D41 family scope, exact decision projection, lock ordering,
privacy, exercise correlation, no-offer creation, no-label, and literal-default-
off clauses remain. The migration remains unnumbered and unmanifested.
