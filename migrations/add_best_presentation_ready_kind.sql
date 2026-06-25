-- Widen the lounge message `kind` CHECK to admit the bot-only
-- "best_presentation_ready" kind.
--
-- When an explore arc reaches 3 takes, the lab-recording handler inserts a
-- durable "Your best presentation for {topic} is ready" card via
-- db.insert_lounge_messages with kind='best_presentation_ready'. That
-- server-side path bypasses the Python validate_lounge_batch guard, so this
-- CHECK is the ONLY enforcement in front of it — without this migration every
-- such insert is silently rejected by lounge_messages_kind_check (the insert is
-- best-effort/try-excepted, so the failure is invisible: no card, but recording
-- + the best-presentation itself are unaffected — it's still openable from
-- Trainings).
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
            'best_presentation_ready'
        ));
END$$;
