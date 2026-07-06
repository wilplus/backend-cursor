-- willab — widen the lounge `kind` CHECK to admit "transcript_ready" (founder
-- bug-batch 2026-07-06, item #1).
--
-- When an arc reaches 3 takes but the coach has NOT yet reviewed/assembled it
-- (or it isn't paid), the user must NOT see the best-presentation buttons —
-- they get a transcript_ready card instead (transcript text + strong sides).
-- The server-side insert bypasses validate_lounge_batch, so this CHECK is the
-- only enforcement in front of it — without this migration the card is
-- silently rejected (the insert is best-effort, so the failure is invisible).
--
-- Idempotent: drop-then-recreate the named constraint so re-running is safe and
-- the kind list converges. Mirrors VALID_KINDS in services/lounge_messages.py.
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
            'best_presentation_ready', 'transcript_ready'
        ));
END$$;
