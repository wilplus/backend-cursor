-- The exposure record still demanded V2's three, and V3 brings four.
--
-- PRODUCTION, 2026-09-21, minutes after #599 and #600 put the bookmarks
-- back. Every V3 Take now logs, on every open:
--
--     take feedback exposure insert failed: {'code': '23514', 'message':
--      'new row for relation "take_feedback_exposure" violates check
--       constraint "take_feedback_exposure_selected_keys_check"'}
--
-- THE THIRD COPY OF ONE RULE. `add_feedback_manager_and_part_commits.sql`
-- gave `take_feedback_exposure.selected_keys` an inline CHECK of exactly
-- three keys -- V2's budget, one item from each of three families. 0347
-- moved the frozen set (`ideal_text_feedback_sets`) to V3's rule and #599
-- moved the client-side guards; this table's constraint was the copy
-- nobody listed. So the exposure row -- the record of the complete ranking
-- that was shown, beside the frozen selection -- is refused for every V3
-- Take, and the caller logs a warning and moves on. The bookmarks render;
-- the audit of what was ranked behind them does not exist.
--
-- THE SAME RULE 0347 WROTE, on the same column name, for the same reason:
-- one to sixty-four identities, at least one of them Confident Voice. Not
-- a budget -- the Manager owns that (L2) -- but the shape of a coherent
-- record of what was served. Sixty-four is the storage ceiling
-- `MAX_SELECTED_KEYS` in `services.take_feedback_set` and the bound in
-- `claim_ideal_text_feedback_set_v1`; it must stay equal to both.
--
-- IDEMPOTENT: drop-if-exists then add, under the name PostgreSQL gave the
-- inline CHECK, so a second run lands on the same constraint.

BEGIN;

ALTER TABLE public.take_feedback_exposure
    DROP CONSTRAINT IF EXISTS take_feedback_exposure_selected_keys_check;

ALTER TABLE public.take_feedback_exposure
    ADD CONSTRAINT take_feedback_exposure_selected_keys_check CHECK (
        jsonb_typeof(selected_keys) = 'array'
        AND jsonb_array_length(selected_keys) BETWEEN 1 AND 64
        AND selected_keys @> '[{"feedback_family":"confident_voice"}]'::jsonb
    );

COMMIT;
