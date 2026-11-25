CREATE TABLE IF NOT EXISTS public.lounge_voice_replies (
    message_id uuid PRIMARY KEY REFERENCES public.lounge_messages(id) ON DELETE CASCADE,
    content_type text CHECK (content_type IN ('audio/webm', 'audio/mp4', 'audio/ogg', 'audio/wav')),
    audio bytea CHECK (octet_length(audio) BETWEEN 1 AND 4194304),
    sha256 text CHECK (char_length(sha256) = 64),
    analysis jsonb CHECK (jsonb_typeof(analysis) = 'object'),
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (
        (audio IS NOT NULL AND content_type IS NOT NULL AND sha256 IS NOT NULL AND analysis IS NOT NULL)
        OR (audio IS NULL AND content_type IS NULL AND sha256 IS NULL AND analysis IS NULL)
    )
);
ALTER TABLE public.lounge_voice_replies ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.lounge_voice_replies FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.lounge_voice_replies TO service_role;

COMMENT ON TABLE public.lounge_voice_replies IS
    'Speaker-confirmed chat audio and private evidence. Its message links it to its project and Take when present.';

-- Serialize attaching audio with erasure of its parent turn.
CREATE OR REPLACE FUNCTION public.require_live_lounge_voice_turn()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = ''
AS $$
BEGIN
    PERFORM id FROM public.lounge_messages
        WHERE id = NEW.message_id AND NOT chat_erased FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Voice turn is unavailable';
    END IF;
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION public.require_live_lounge_voice_turn() FROM PUBLIC, anon, authenticated;

CREATE OR REPLACE TRIGGER require_live_lounge_voice_turn
    BEFORE INSERT ON public.lounge_voice_replies FOR EACH ROW
    EXECUTE FUNCTION public.require_live_lounge_voice_turn();

-- Chat erasure redacts a message in place. Its attachment is erased too.
CREATE OR REPLACE FUNCTION public.erase_redacted_lounge_voice_reply()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = ''
AS $$
BEGIN
    UPDATE public.lounge_voice_replies
        SET audio = NULL, content_type = NULL, sha256 = NULL, analysis = NULL
        WHERE message_id = NEW.id;
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION public.erase_redacted_lounge_voice_reply() FROM PUBLIC, anon, authenticated;

CREATE OR REPLACE TRIGGER erase_redacted_lounge_voice_reply
    AFTER UPDATE OF chat_erased ON public.lounge_messages
    FOR EACH ROW WHEN (NEW.chat_erased AND NOT OLD.chat_erased)
    EXECUTE FUNCTION public.erase_redacted_lounge_voice_reply();
