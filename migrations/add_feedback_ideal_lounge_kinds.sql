-- willab — widen the lounge `kind` CHECK to admit the delivery-layer bubbles
-- "feedback" (grey ×3) + "ideal_text" (purple ×1) (founder fix-pack
-- 2026-07-16, BE-1 — P0).
--
-- PR #193 added both kinds to VALID_KINDS and made "Save and Publish full
-- analysis" insert them server-side — but no migration ever widened this
-- CHECK. Server-side inserts bypass validate_lounge_batch, so the constraint
-- was the only enforcement in front of them and silently rejected all 4
-- bubbles (insert_lounge_messages swallows the error and returns []), while
-- publish-analysis reported `bubbles: 4`. The student's Lounge got nothing.
--
-- Idempotent: drop-then-recreate the named constraint so re-running is safe
-- and the kind list converges. Mirrors VALID_KINDS in
-- services/lounge_messages.py — pinned by test_lounge_kind_migration.py, so
-- the next kind addition fails CI until a new migration (and pointer bump)
-- ships with it.
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
            'feedback', 'ideal_text'
        ));
END$$;
