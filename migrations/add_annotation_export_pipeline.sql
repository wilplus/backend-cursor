-- Annotation export pipeline + richer event metadata for learning operations.

-- 1) Extend annotation events with optional export-friendly metadata.
ALTER TABLE public.admin_annotation_events
  ADD COLUMN IF NOT EXISTS draft_id UUID,
  ADD COLUMN IF NOT EXISTS previous_value_hash TEXT,
  ADD COLUMN IF NOT EXISTS new_value_hash TEXT;

CREATE INDEX IF NOT EXISTS idx_admin_annotation_events_draft_id
  ON public.admin_annotation_events(draft_id);

-- 2) Export run ledger (operational proof + monitoring source).
CREATE TABLE IF NOT EXISTS public.admin_annotation_export_runs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  ended_at TIMESTAMPTZ,
  status TEXT NOT NULL DEFAULT 'running',
  checkpoint_created_at TIMESTAMPTZ,
  checkpoint_event_id UUID,
  processed_count INTEGER NOT NULL DEFAULT 0,
  exported_count INTEGER NOT NULL DEFAULT 0,
  failed_count INTEGER NOT NULL DEFAULT 0,
  export_uri TEXT,
  error_text TEXT,
  created_by TEXT,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  CONSTRAINT chk_admin_annotation_export_runs_status
    CHECK (status IN ('running', 'success', 'failed'))
);

CREATE INDEX IF NOT EXISTS idx_admin_annotation_export_runs_started_at
  ON public.admin_annotation_export_runs(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_admin_annotation_export_runs_status
  ON public.admin_annotation_export_runs(status, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_admin_annotation_export_runs_checkpoint
  ON public.admin_annotation_export_runs(checkpoint_created_at DESC);

GRANT ALL ON TABLE public.admin_annotation_export_runs TO service_role;
