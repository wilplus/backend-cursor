-- willab — admit kind='delivery' on moment_suggestions (founder decisions
-- 2026-07-18: the Measured delivery family — emphasis / pace / pause,
-- deterministic vs the speaker's own baseline, no LLM).
--
-- The modal action for these is the FE's snippet re-record mic (no
-- approve/fold — a delivery star never mutates text). `trigger` carries the
-- device: emphasis | pace_fast | pace_slow | pause.
--
-- Idempotent: drop-then-recreate the named CHECK so the kind list converges.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'moment_suggestions_kind_check'
    ) THEN
        ALTER TABLE public.moment_suggestions
            DROP CONSTRAINT moment_suggestions_kind_check;
    END IF;
    ALTER TABLE public.moment_suggestions
        ADD CONSTRAINT moment_suggestions_kind_check
        CHECK (kind IN ('emphasize', 'replace', 'structure', 'delivery'));
END$$;
