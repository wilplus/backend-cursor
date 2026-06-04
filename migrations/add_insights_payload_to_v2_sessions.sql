-- willab beta — insights_payload (design §6b/§14, contract §1/§3.9).
--
-- The coach's user-facing lane, assembled + persisted at publish:
--   { overall_message: str|null,
--     snippet_notes: [ { snippet_id, note, tag: 'strong'|'to_work_on' } ] }
--
-- 1 per published session → a JSONB column on v2_sessions. The
-- user-facing Insights view (§6b) reads it; the strong-sides library
-- ingests the tagged notes on the user's READ (§3.11).
--
-- Split-sink (§2): this is the USER lane ONLY. The private training-
-- annotation/label lane (direction-v1, §14) lives elsewhere and must
-- NEVER be written here.
--
-- Idempotent.

ALTER TABLE v2_sessions
    ADD COLUMN IF NOT EXISTS insights_payload JSONB;

COMMENT ON COLUMN v2_sessions.insights_payload IS
    'willab beta §6b/§14 — coach user-facing lane assembled at publish: '
    '{overall_message, snippet_notes:[{snippet_id, note, tag}]}. Library '
    'floor (≥1 tagged note) enforced at the publish endpoint. USER lane '
    'only — never the private training labels (split-sink §2).';

NOTIFY pgrst, 'reload schema';
