-- Arousal capture (founder 2026-07-24, capture-first / surface-later).
--
-- A baseline-relative ACTIVATION read per snippet (calm↔activated), computed
-- deterministically from the speaker's own delivery cues (see
-- services/delivery_stars.arousal_z, patterns from Juslin & Laukka, 2003).
-- It is captured for the coach-labeled learning loop to weight later; it is
-- NEVER surfaced to a user and NEVER fed into ranking (activation is not
-- quality). It reads the arousal axis only, never a discrete emotion.
--
-- Idempotent + degrades gracefully: the column is nullable and every write is
-- best-effort (services/db.set_snippet_arousal swallows a missing column), so
-- shipping the code before running this migration is safe.

ALTER TABLE charisma_snippets
    ADD COLUMN IF NOT EXISTS arousal_z double precision;
