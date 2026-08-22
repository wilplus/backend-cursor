-- Willab canonical Voice Album introduction frequency.
--
-- The introduction is onboarding, not a per-Project lifecycle event. Persist
-- it on the user so a second qualifying Project (or a cleared Lounge thread)
-- cannot cause the same onboarding bubble to appear again.

ALTER TABLE public.user_settings
    ADD COLUMN IF NOT EXISTS voice_album_introduced_at TIMESTAMPTZ NULL;

COMMENT ON COLUMN public.user_settings.voice_album_introduced_at IS
    'When the one-time Voice Album introduction was first emitted for this '
    'user. NULL means it has never been introduced. This is user-scoped, not '
    'Project-scoped.';

-- Existing users who already received the old per-Project bubble must not be
-- introduced again. Preserve the earliest observed introduction.
INSERT INTO public.user_settings (user_id, voice_album_introduced_at)
SELECT
    lm.user_id,
    MIN(COALESCE(lm.created_at, lm.client_created_at, CURRENT_TIMESTAMP))
FROM public.lounge_messages AS lm
WHERE
    lm.metadata->>'note' = 'voice_album_ready'
    OR lm.metadata->>'voice_album_ready' = 'true'
GROUP BY lm.user_id
ON CONFLICT (user_id) DO UPDATE
SET voice_album_introduced_at = COALESCE(
    public.user_settings.voice_album_introduced_at,
    EXCLUDED.voice_album_introduced_at
);

NOTIFY pgrst, 'reload schema';
