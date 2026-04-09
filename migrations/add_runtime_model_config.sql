-- Runtime model configuration (no redeploy needed for model promotion).
-- Used by OpenAIService to resolve model overrides from DB.

CREATE TABLE IF NOT EXISTS public.runtime_config (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_by TEXT,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_runtime_config_updated_at
  ON public.runtime_config(updated_at DESC);

GRANT ALL ON TABLE public.runtime_config TO service_role;
