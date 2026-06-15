-- willab — Audit Delivery (Prompt C §2).
--
-- A coach-curated PDF audit, attributed to a user. DISTINCT from the lab
-- Readout (v2_sessions.source='audit_upload' / the "user_audit" assembly) —
-- this is a separate, human-made PDF deliverable the coach uploads once per
-- user; the user opens it from the audits page + an email link.
--
-- The PDF bytes live in R2 (coach_feedback_videos bucket, willab_audits/*
-- keys); storage_path holds the object key. Idempotent; safe to re-run.
CREATE TABLE IF NOT EXISTS user_audits (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      UUID NOT NULL,
    name         TEXT NOT NULL,                       -- e.g. "Speaking Impact Audit, Booksy pitch"
    audit_date   TIMESTAMPTZ NOT NULL DEFAULT now(),  -- shown next to the name
    storage_path TEXT NOT NULL,                       -- R2 object key for the PDF
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- The user's list read is "my audits, newest first".
CREATE INDEX IF NOT EXISTS idx_user_audits_user
    ON user_audits (user_id, audit_date DESC);
