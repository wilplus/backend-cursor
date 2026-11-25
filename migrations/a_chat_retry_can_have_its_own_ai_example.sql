ALTER TABLE public.ai_voice_cycles
    ADD COLUMN IF NOT EXISTS chat_retry_id uuid REFERENCES public.lounge_voice_replies(message_id) ON DELETE CASCADE,
    ADD COLUMN IF NOT EXISTS chat_audio bytea CHECK (
        chat_audio IS NULL OR (chat_retry_id IS NOT NULL AND octet_length(chat_audio) BETWEEN 1 AND 4194304)
    );

CREATE UNIQUE INDEX IF NOT EXISTS ai_voice_cycles_one_per_practice_and_retry
    ON public.ai_voice_cycles (practice_id, chat_retry_id) NULLS NOT DISTINCT;
CREATE INDEX IF NOT EXISTS ai_voice_cycles_chat_retry
    ON public.ai_voice_cycles (chat_retry_id) WHERE chat_retry_id IS NOT NULL;

ALTER TABLE public.ai_voice_cycles DROP CONSTRAINT IF EXISTS ai_voice_cycles_practice_id_key;

COMMENT ON COLUMN public.ai_voice_cycles.chat_retry_id IS
    'Exact speaker-owned chat recording that cleared the prior cue. NULL is the regular AI example.';

-- Serialize creating the example with redaction of its source.
CREATE OR REPLACE FUNCTION public.require_live_chat_ai_retry()
RETURNS trigger LANGUAGE plpgsql SET search_path = '' AS $$
BEGIN
    PERFORM message_id FROM public.lounge_voice_replies
        WHERE message_id = NEW.chat_retry_id AND analysis IS NOT NULL FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Chat practice retry is unavailable';
    END IF;
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION public.require_live_chat_ai_retry() FROM PUBLIC, anon, authenticated;

CREATE OR REPLACE TRIGGER require_live_chat_ai_retry
    BEFORE INSERT ON public.ai_voice_cycles FOR EACH ROW WHEN (NEW.chat_retry_id IS NOT NULL)
    EXECUTE FUNCTION public.require_live_chat_ai_retry();

CREATE OR REPLACE FUNCTION public.erase_redacted_chat_ai_retry()
RETURNS trigger LANGUAGE plpgsql SET search_path = '' AS $$
BEGIN
    UPDATE public.ai_voice_cycles
        SET status = 'deleted', demo = 'none', chat_audio = NULL, content_sha256 = NULL,
            prepared_text = NULL, selection = NULL, generation_metadata = NULL, validation = NULL,
            metrics_before = NULL, metrics_after = NULL, duration_ms = NULL, updated_at = now()
        WHERE chat_retry_id = OLD.message_id;
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION public.erase_redacted_chat_ai_retry() FROM PUBLIC, anon, authenticated;

CREATE OR REPLACE TRIGGER erase_redacted_chat_ai_retry
    AFTER UPDATE OF analysis ON public.lounge_voice_replies
    FOR EACH ROW WHEN (OLD.analysis IS NOT NULL AND NEW.analysis IS NULL)
    EXECUTE FUNCTION public.erase_redacted_chat_ai_retry();

NOTIFY pgrst, 'reload schema';
