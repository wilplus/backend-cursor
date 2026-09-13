# MLC-3 Confident Moment Coaching Bundle — User Media Correlation Amendment D46

Status: proposed final timing correction. D46 retains D38–D45 except where
replaced here. No gate, dataset, or learning change.

## 1. Request-local authorization window

The phase-3 value retains database `authorized_at` for audit description but no
database expiry controls the application. Immediately when the RPC returns, the
route starts a local monotonic 500 ms request-local authorization window. This
window is independent of wall-clock synchronization and begins only after
transport latency has ended. It is bounded by the still-running two-second
post-buffer TTL.

Within that 500 ms window the route recomputes SHA-256 over the actual buffered
bytes, validates the exact request UUID/authority/hash/closed authorization
shape, consumes the request-local authorization once, and constructs the
response. The 500 ms value is the reviewed maximum-size-buffer rehash margin;
tests benchmark the fixed 25 MiB boundary under an injected monotonic clock and
fail closed if construction exceeds it. The database value is still stateless,
read-only, uncached, and never returned to the browser.

## 2. Expiry and attempts

An authorization that exceeds its request-local 500 ms window is retryable
`CONFIDENT_MOMENT_USER_READ_RETRY_REQUIRED`, never an integrity condition. The
phase-3 RPC that produced it consumed one of the two permitted attempts. If one
attempt remains and its complete 500 ms database budget plus the 500 ms local
authorization window fit within the original two-second buffer TTL, the route
may perform that second phase-3 attempt against the same buffer without rereading
R2. Otherwise it discards the buffer and returns the same typed retry condition.
No expired value may authorize bytes.

All D38–D45 integrity, under-lock decision, exact transport deadline, admission,
privacy, correlation, no-label and literal-default-off clauses remain in force.
The migration stays unnumbered and unmanifested.
