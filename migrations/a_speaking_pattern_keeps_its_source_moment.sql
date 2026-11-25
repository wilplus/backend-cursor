-- Private founder calibration examples. No audio, provider output, or retry lives here.
CREATE TABLE IF NOT EXISTS public.speaking_pattern_examples (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    curator_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    session_id uuid NOT NULL REFERENCES public.v2_sessions(id) ON DELETE CASCADE,
    snippet_id uuid NOT NULL REFERENCES public.snippets(id) ON DELETE CASCADE,
    source text NOT NULL CHECK (source IN ('take', 'corpus')),
    kind text NOT NULL CHECK (kind IN ('error', 'praise', 'control', 'unsure')),
    pattern text NOT NULL CHECK (char_length(btrim(pattern)) BETWEEN 1 AND 100),
    start_ms integer NOT NULL CHECK (start_ms >= 0),
    end_ms integer NOT NULL CHECK (end_ms > start_ms),
    note text NOT NULL DEFAULT '' CHECK (char_length(note) <= 1000),
    intervention jsonb CHECK (jsonb_typeof(intervention) = 'object'),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS speaking_pattern_curator_created
    ON public.speaking_pattern_examples (curator_id, created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS speaking_pattern_session
    ON public.speaking_pattern_examples (session_id);
CREATE INDEX IF NOT EXISTS speaking_pattern_snippet
    ON public.speaking_pattern_examples (snippet_id);

ALTER TABLE public.speaking_pattern_examples ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.speaking_pattern_examples FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.speaking_pattern_examples TO service_role;

NOTIFY pgrst, 'reload schema';
