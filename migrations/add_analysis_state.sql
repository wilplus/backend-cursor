-- Async analysis state (founder 2026-07-15) — the recording's analysis now
-- runs in a server-side background thread so closing the tab / locking the
-- phone never kills it. The session row carries the job state the FE polls.
--   processing → the daemon is running (the 202 state)
--   ready      → analysis finished; the readout is servable
--   failed     → the daemon raised; analysis_error carries a short reason
-- NULL (older sessions / sync path) reads as ready — pre-async rows were
-- only ever persisted after a completed synchronous analysis.
-- Idempotent; safe to re-run.

ALTER TABLE public.v2_sessions
    ADD COLUMN IF NOT EXISTS analysis_state text,
    ADD COLUMN IF NOT EXISTS analysis_error text;
