# MLC-3 Confident Moment Coaching Bundle — User Media Correlation Amendment D41

Status: proposed interface correction. D41 retains D38–D40 except where
replaced below. No gate, dataset, or learning change.

## 1. Two-phase buffered playback authority

D41 replaces the requirement to hold database serializers across the R2
network read. Source playback uses three closed phases:

1. In a bounded database transaction, acquire the D39 non-waiting canonical
   locks, derive and hash the complete live read authority, then commit and
   release every serializer.
2. Buffer the complete private object with no database lock held. The object is
   limited by the existing acquisition invariant
   `Config.MLC3_PILOT_MAX_AUDIO_MB` (currently 25 MiB); this route may serve no
   object that exceeded that same ingest check. An oversize or inconsistent
   historical object returns terminal `CONFIDENT_MOMENT_SOURCE_MEDIA_TOO_LARGE`,
   which the client never retries and presents no retry action. The R2 connect,
   read and hashing phase has a fixed 8-second timeout and emits no bytes.
3. In a second bounded database transaction, reacquire the identical canonical
   lock graph, rederive the complete current authority, and require its hash to
   equal phase 1. While these serializers remain held, verify the buffered byte
   hash and all current authority/deletion/purge/retention/quarantine/media
   leaves and make the final emit/no-emit decision. Release follows that
   decision. Only a successful decision may construct the private response.

Each database phase has the D39 500 ms inclusive budget and non-waiting locks.
No serializer is held during network I/O, so this read cannot make a writer
wait on R2. Contention or identity change returns the retryable D39 condition;
oversize is terminal. The client retries with the same supplied Bundle and
attachment parameters while the server freshly derives identities each time.

## 2. Human-decision lock position

For `rewrite_clarity` and `great_formulation`, the canonical human-decision read
is covered by the same writer-shared serializer at the sorted exact-feedback-
response position. It acquires no additional lock. The derived owner-decision
rules and whole-projection failure semantics from D40 remain unchanged.

## 3. Explicit failed-playback regression

Tests must separately prove that an attempted playback ending in contention,
timeout, oversize, byte-hash mismatch, or post-read invalidation leaves the
five-state controls disabled and creates no owner response. A pre-existing
visibility exposure remains an unanswered exposure and is neither deleted nor
duplicated.

All other D38–D40 family scope, visibility, projection hash, response vocabulary,
privacy, exact lineage, no-offer-creation, no-label, and disabled-gate clauses
remain in force. The migration remains unnumbered and unmanifested.
