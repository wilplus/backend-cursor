-- Explore-Session Multi-Take (willab Prompt A §4) — widen the lounge
-- message `kind` CHECK to admit the bot-only "cadence" kind.
--
-- The cadence flow inserts staged guidance bubbles into the Lounge via
-- db.insert_lounge_messages with kind='cadence'. That server-side path
-- bypasses the Python validate_lounge_batch guard, so this CHECK is the
-- ONLY enforcement in front of it — without this migration every cadence
-- insert is silently rejected by lounge_messages_kind_check (the insert
-- is best-effort/try-excepted, so the failure is invisible: no bubble).
--
-- Idempotent: drop-then-recreate the named constraint so re-running is
-- safe and the kind list converges. Mirrors the VALID_KINDS tuple in
-- services/lounge_messages.py.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'lounge_messages_kind_check'
    ) THEN
        ALTER TABLE lounge_messages DROP CONSTRAINT lounge_messages_kind_check;
    END IF;
    ALTER TABLE lounge_messages ADD CONSTRAINT lounge_messages_kind_check
        CHECK (kind IN (
            'text', 'joke', 'status', 'recording_summary', 'insight', 'cadence'
        ));
END$$;
