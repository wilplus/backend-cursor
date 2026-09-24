-- An exercise can live without a post, and can say it is avatar-usable.
--
-- FOUNDER 2026-09-23, two decisions taken together in session.
--
-- 1. WHAT AN EXERCISE MINIMALLY IS. The original CHECK read
--
--      active = FALSE OR (journal_post_id IS NOT NULL
--                         AND explanation_video_url IS NOT NULL)
--
--    because the journal post WAS the explanation a learner read when the
--    exercise fired. The founder's decision is that the video and the one-line
--    instruction are enough on their own, and the write-up becomes an optional
--    companion rather than a precondition. The video stays required: an
--    exercise with nothing to show is not an exercise.
--
--    This RELAXES a constraint, so every row that satisfied the old rule
--    satisfies the new one. Nothing existing becomes invalid and nothing is
--    rewritten.
--
-- 2. THE AVATAR TICK, AND WHY IT CARRIES A LABEL. A coach marking a recording
--    "usable for a future avatar" is recording something PERISHABLE: only the
--    person in the room at record time knows whether the shirt, angle and
--    lighting matched. It cannot be recovered from the file later, which is
--    why it is captured now for a product that does not exist yet.
--
--    A bare boolean would not do the job it is being asked to do. "Usable"
--    says this clip was shot carefully; it cannot say these clips match EACH
--    OTHER, and matching each other is the whole requirement. So the flag
--    carries a setup label — one short string typed once and reused for every
--    clip shot the same way — and the CHECK below refuses the tick without it.
--    A hundred unlabelled "usable" clips is the manual sorting job the tick
--    existed to prevent.
--
-- NOTHING READS THESE COLUMNS YET, deliberately (founder: remember only). No
-- screen lists them, no set is assembled. They wait until an avatar project
-- exists and asks which clips are usable.
--
-- Idempotent: DROP ... IF EXISTS before each ADD, and ADD COLUMN IF NOT EXISTS.

ALTER TABLE public.diagnostic_exercise
    DROP CONSTRAINT IF EXISTS diagnostic_exercise_active_assets_check;

ALTER TABLE public.diagnostic_exercise
    ADD CONSTRAINT diagnostic_exercise_active_assets_check CHECK (
        active = FALSE OR explanation_video_url IS NOT NULL
    );

ALTER TABLE public.diagnostic_exercise
    ADD COLUMN IF NOT EXISTS avatar_training_eligible BOOLEAN NOT NULL
        DEFAULT FALSE;

ALTER TABLE public.diagnostic_exercise
    ADD COLUMN IF NOT EXISTS avatar_setup_label TEXT NULL;

ALTER TABLE public.diagnostic_exercise
    DROP CONSTRAINT IF EXISTS diagnostic_exercise_avatar_setup_check;

ALTER TABLE public.diagnostic_exercise
    ADD CONSTRAINT diagnostic_exercise_avatar_setup_check CHECK (
        avatar_training_eligible = FALSE
        OR (avatar_setup_label IS NOT NULL
            AND length(btrim(avatar_setup_label)) > 0)
    );

-- The one query this exists to make possible, once something wants it:
--   SELECT ... WHERE avatar_training_eligible
--     AND avatar_setup_label = '<a setup>';
CREATE INDEX IF NOT EXISTS diagnostic_exercise_avatar_setup_idx
    ON public.diagnostic_exercise (avatar_setup_label)
    WHERE avatar_training_eligible;
