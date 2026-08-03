-- Durable job state for the async recording pipeline (F1-SURFACE hardening).
--
-- Postgres — not Redis — is the source of truth for job state: Redis only
-- delivers work to the worker service. If Redis is wiped or a Railway
-- redeploy kills a worker mid-job, this table is what lets the sweeper
-- re-enqueue (or fail) the job instead of stranding the user's session in
-- "processing" forever.
--
-- Idempotent + additive: safe to re-run; never touches existing tables.
-- Backend uses the service role; RLS optional per project policy (matches
-- copilot_reference_upload_jobs).

CREATE TABLE IF NOT EXISTS public.processing_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- What kind of work this is; today only 'session_recording'
    -- (the record→take pipeline). TEXT, not an enum, so adding kinds
    -- never needs a migration.
    kind TEXT NOT NULL,
    user_id UUID REFERENCES auth.users (id) ON DELETE CASCADE,
    -- The v2_sessions row this job processes. No FK: v2_sessions cleanup
    -- scripts hard-delete rows and a dangling job must degrade to a no-op
    -- retry, not block the delete.
    session_id UUID,
    -- Idempotency / dedup: one ACTIVE job per unit of work, e.g.
    -- 'session_recording:<session_id>'. Enforced by the partial unique
    -- index below (only while pending/processing, so a retry after a
    -- failed/completed job can create a fresh row).
    dedup_key TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    -- Coarse progress for the FE poll (stage label + percent), same shape
    -- as copilot_reference_upload_jobs.
    stage TEXT,
    percent INTEGER NOT NULL DEFAULT 0,
    message TEXT,
    error TEXT,
    -- Job inputs (storage path/bucket, filename, flags). The worker re-reads
    -- the media from object storage — bytes never ride through the queue.
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- Small result summary for the FE (e.g. take_id, redirect hints).
    result JSONB,
    enqueued_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    -- Workers stamp this while running; the sweeper treats a 'processing'
    -- job with a stale heartbeat as orphaned (worker killed mid-job) and
    -- re-enqueues or fails it.
    heartbeat_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT processing_jobs_status_check CHECK (
        status IN ('pending', 'processing', 'completed', 'failed')
    ),
    CONSTRAINT processing_jobs_percent_check CHECK (
        percent >= 0
        AND percent <= 100
    )
);

-- One active job per dedup_key: double-clicked uploads / webhook replays
-- collapse onto the in-flight job instead of racing it.
CREATE UNIQUE INDEX IF NOT EXISTS idx_processing_jobs_active_dedup
ON public.processing_jobs (dedup_key)
WHERE dedup_key IS NOT NULL AND status IN ('pending', 'processing');

-- Sweeper scan: active jobs by staleness.
CREATE INDEX IF NOT EXISTS idx_processing_jobs_active
ON public.processing_jobs (status, heartbeat_at)
WHERE status IN ('pending', 'processing');

CREATE INDEX IF NOT EXISTS idx_processing_jobs_session
ON public.processing_jobs (session_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_processing_jobs_user
ON public.processing_jobs (user_id, created_at DESC);
