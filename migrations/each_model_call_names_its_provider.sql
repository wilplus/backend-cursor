-- Every model-usage row names the processor that handled it. Historical rows
-- were OpenAI-only; the default backfills them truthfully. Mistral costs stay
-- NULL until a verified, versioned price table exists.

ALTER TABLE public.llm_usage
    ADD COLUMN IF NOT EXISTS provider TEXT;

UPDATE public.llm_usage
   SET provider = 'openai'
 WHERE provider IS NULL;

ALTER TABLE public.llm_usage
    ALTER COLUMN provider SET DEFAULT 'openai',
    ALTER COLUMN provider SET NOT NULL;

COMMENT ON COLUMN public.llm_usage.provider IS
    'The processor that handled the call (for example openai or mistral).';

COMMENT ON TABLE public.llm_usage IS
    'What we pay external model providers, one row per model call. Raw counts '
    'are ground truth; cost_usd is derived only from a verified price table. '
    'Never a source for user-facing prices (fence AC-9 / plan §6.2).';

-- Rollback (manual, never automatic):
--   ALTER TABLE public.llm_usage DROP COLUMN IF EXISTS provider;
