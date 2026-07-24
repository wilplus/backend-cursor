-- dev_bugs — internal founder-only bug collector (dev.willpowerlab.com).
--
-- A tiny jotter: the founder saves bugs (text and/or a compressed image, typed
-- or dictated) from phone or PC; a Railway cron emails all `open` bugs to
-- DEV_BUGS_TO every 3 days as an LLM-ready triage prompt, then flips them to
-- `shipped`. Shipped rows are kept forever as read-only history (never
-- auto-deleted). See routes/dev_bugs.py + services/dev_bugs.py.
--
-- image_url holds either an object-storage URL or, more commonly here, the
-- compressed data: URL string directly (the frontend caps images at ~<=200 KB).
--
-- Access is gated at the API by DEV_BUGS_KEY; the runtime uses the Supabase
-- service-role key (bypasses RLS), so RLS is enabled with no policies —
-- consistent with the other service-role-only tables in this project.
--
-- Idempotent; safe to re-run.

CREATE TABLE IF NOT EXISTS public.dev_bugs (
    id          BIGSERIAL   PRIMARY KEY,
    text        TEXT        NOT NULL DEFAULT '',
    image_url   TEXT,                               -- object-storage URL or a data: URL string
    status      TEXT        NOT NULL DEFAULT 'open', -- 'open' | 'shipped'
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    sent_at     TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS dev_bugs_status_idx
    ON public.dev_bugs (status, created_at);

-- Guard the status domain (CHECK has no IF NOT EXISTS; add once).
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'dev_bugs_status_check'
    ) THEN
        ALTER TABLE public.dev_bugs
            ADD CONSTRAINT dev_bugs_status_check
            CHECK (status IN ('open', 'shipped'));
    END IF;
END $$;

ALTER TABLE public.dev_bugs ENABLE ROW LEVEL SECURITY;
