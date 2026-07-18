-- willab — admit the STRUCTURAL star kind (founder 2026-07-18).
--
-- Star suggestions (#215) fire only on acoustic/content triggers, so an
-- even-toned take gets zero stars. Structural stars add a THIRD family:
-- rhetorical devices detectable in the transcript, restricted to exactly
-- two with real evidence behind them — the contrast and the list of three.
-- They are DELIVERY PROMPTS, not text edits (no replacement, no fold), so
-- `replacement_text` stays NULL and `why` carries the verbatim quote.
--
-- Additive: widen the kind CHECK to include 'structure'. Idempotent
-- drop-then-re-add of the named constraint (same pattern as the lounge-kind
-- migrations). Behind STRUCTURAL_STARS_ENABLED — safe to run early.
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
        CHECK (kind IN ('emphasize', 'replace', 'structure'));
END$$;
