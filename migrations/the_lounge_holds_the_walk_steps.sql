-- The Lounge holds the walk's steps (founder lock 2026-10-12, moment and
-- feedback chat, section 1: "One thread, stored once. It's the Lounge
-- thread (lounge_messages). Every step of the review is a message in it").
--
-- Widens the lounge `kind` CHECK to admit "walk_step": one message per
-- step of a Take's review, posted by the app through the existing
-- POST /v2/user/lounge/messages. Its metadata carries the Take, the step
-- and the answer; no score, band or read (AC-9).
--
-- Idempotent, the same pattern as add_feedback_ideal_lounge_kinds.sql: the
-- named CHECK is recreated with the full kind list, which only grows; no
-- table, column or row is dropped. Mirrors VALID_KINDS in
-- services/lounge_messages.py.
--
-- Verify after running:
--   SELECT pg_get_constraintdef(oid) FROM pg_constraint
--    WHERE conname = 'lounge_messages_kind_check';
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'lounge_messages_kind_check'
    ) THEN
        ALTER TABLE lounge_messages DROP CONSTRAINT lounge_messages_kind_check;
    END IF;
    ALTER TABLE lounge_messages ADD CONSTRAINT lounge_messages_kind_check
        CHECK (kind IN (
            'text', 'joke', 'status', 'recording_summary', 'insight', 'cadence',
            'best_presentation_ready', 'transcript_ready',
            'feedback', 'ideal_text', 'walk_step'
        ));
END$$;
