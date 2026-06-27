-- willab — rejected-take capture (automation-audit fix #2c: survivorship).
--
-- The min-content gate rejects too-short / no-speech / corrupt uploads BEFORE
-- any storage, so gate-FAILED takes left no record anywhere — we had no "what a
-- bad take looks like" data. This logs the gate METRICS of each rejected
-- attempt (reason + measured duration/voiced seconds + thresholds), NOT the
-- audio (privacy + cost). Training-bound; append-only; best-effort.
--
-- Idempotent; safe to re-run.
CREATE TABLE IF NOT EXISTS rejected_takes (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id           UUID,               -- authed uploader, else NULL (guest)
    guest_session_id  TEXT,               -- the FE session id, if provided
    arc_id            TEXT,               -- FE-sent arc id, if a continuing take
    take_index        INTEGER,
    reason            TEXT,               -- 'too_short' | 'no_speech' | 'no_audio'
    duration_sec      REAL,
    voiced_sec        REAL,
    thresholds        JSONB,
    recording_origin  TEXT DEFAULT 'willab_lab',
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_rejected_takes_user
    ON rejected_takes (user_id);
CREATE INDEX IF NOT EXISTS idx_rejected_takes_created
    ON rejected_takes (created_at DESC);

-- Rollback (manual):
--   DROP TABLE IF EXISTS rejected_takes;
