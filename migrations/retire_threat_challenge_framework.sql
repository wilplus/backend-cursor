-- Founder decision 2026-08-22: retire the threat/challenge framework and its
-- product experiments. Canonical confidence and Voice Album data is untouched.

ALTER TABLE IF EXISTS public.v2_sessions
    DROP COLUMN IF EXISTS priming_condition,
    DROP COLUMN IF EXISTS priming_phrase;

ALTER TABLE IF EXISTS public.coach_snippet_drafts
    DROP COLUMN IF EXISTS breakthrough_video_ref;

DROP TABLE IF EXISTS public.game_saves;
DROP TABLE IF EXISTS public.training_labels;
DROP TABLE IF EXISTS public.shadow_predictions;
DROP TABLE IF EXISTS public.model_versions;
DROP TABLE IF EXISTS public.reflection_clips;
