-- Pre-take mindset-priming manipulation (founder 2026-07-13) — the framing the
-- student saw before a live take: threat / challenge / balanced (one condition
-- per batch position) + the exact phrase shown. A PRIVATE research-correlation
-- signal, stored on the take's session row alongside the arc/take_index it was
-- recorded under. Mirrors `recording_feelings` semantics (felt-state input),
-- but lives on v2_sessions so the write can never regress the feeling capture
-- and the session row is always present.
--
-- NEVER user-facing (AC-9): the phrase references "grading/score" as a priming
-- device, not a real analysis output — it must not reach the readout, the
-- instant view, or the student batch view. Correlated against the acoustic read
-- (pitch / rate / pauses / power) per take; exposed to the coach review only.
--
-- Idempotent; safe to re-run. No backfill (older takes stay null).

ALTER TABLE public.v2_sessions
    ADD COLUMN IF NOT EXISTS priming_condition text,
    ADD COLUMN IF NOT EXISTS priming_phrase    text;
