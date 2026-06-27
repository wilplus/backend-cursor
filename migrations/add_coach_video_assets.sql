-- willab — coach-video corpus (Subsystem V). CAPTURE ONLY; model deferred.
--
-- The coach records short feedback videos in two content types — take_summary
-- (per session) and breakthrough (per snippet). Today each is a BARE URL on a
-- user-facing row, and re-records OVERWRITE (deterministic key) → prior takes
-- lost. This turns them into a training corpus that can later feed avatar-
-- lipsync OR real-you photoreal generation. One row per recorded TAKE.
--
-- THE ONE RULE: TAG, DON'T GATE — every recorded video is stored; quality_rate
-- is a training-time FILTER label, never a store-or-discard decision.
--
-- PRIVATE/training-bound lane (AC-9 split-sink): RLS-enabled with NO policy, so
-- ONLY the service role (the backend) can read/write — never PostgREST/anon.
-- quality_rate / train_eligible / consent_scope MUST NEVER reach a user surface;
-- the user keeps seeing video from coach_snippet_drafts.breakthrough_video_ref /
-- v2_sessions.coach_video_ref. This table is write-at-ingest, read-for-training.
--
-- Idempotent; additive; safe to re-run.
CREATE TABLE IF NOT EXISTS coach_video_assets (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    video_ref                TEXT,                  -- storage URL/key of THIS take
    session_id               UUID NOT NULL,
    snippet_id               UUID,                  -- NULL for take_summary
    recorded_by              UUID,                  -- coach user_id ("whose style")
    content_type             TEXT NOT NULL,         -- take_summary | breakthrough
    comment_text_snapshot    TEXT,                  -- write-once, the comment AT RECORD time (may be NULL)
    comment_text_at_publish  TEXT,                  -- write-once, the FINAL delivered comment (set at publish)
    transcript               TEXT,                  -- backfilled async
    transcription_status     TEXT DEFAULT 'pending', -- pending | done | failed
    duration                 REAL,                  -- seconds; FE-sent or ffprobe-backfilled
    device                   TEXT,
    source                   TEXT,
    is_current               BOOLEAN NOT NULL DEFAULT TRUE,   -- the take shown to the client
    superseded_by            UUID,                  -- the take that replaced this one
    upload_idempotency_key   TEXT,                  -- client-generated per record action
    quality_rate             TEXT,                  -- good | usable | reject (latest cached)
    train_eligible           BOOLEAN NOT NULL DEFAULT TRUE,   -- computed once at insert; overridable
    consent_scope            TEXT[],                -- {internal_training, client_shown, synthetic_generation}
    origin                   TEXT NOT NULL DEFAULT 'recorded', -- recorded | generated
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Idempotency: dedupe a RETRIED upload of the same record action. PARTIAL so the
-- column can roll out before the FE sends it (many NULLs never collide).
CREATE UNIQUE INDEX IF NOT EXISTS idx_coach_video_assets_idem
    ON coach_video_assets (upload_idempotency_key)
    WHERE upload_idempotency_key IS NOT NULL;

-- "current take for this session/content/snippet" lookup (supersede + serve).
CREATE INDEX IF NOT EXISTS idx_coach_video_assets_current
    ON coach_video_assets (session_id, content_type, is_current);
CREATE INDEX IF NOT EXISTS idx_coach_video_assets_recorded_by
    ON coach_video_assets (recorded_by);

-- Append-only rating history — quality_rate / train_eligible are re-ratable over
-- time WITHOUT overwriting; the asset row holds the latest cached value.
CREATE TABLE IF NOT EXISTS coach_video_rating_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    video_asset_id  UUID NOT NULL,
    quality_rate    TEXT,                            -- good | usable | reject
    train_eligible  BOOLEAN,
    rated_by        UUID,
    rated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    note            TEXT
);
CREATE INDEX IF NOT EXISTS idx_coach_video_rating_events_asset
    ON coach_video_rating_events (video_asset_id, rated_at DESC);

-- PRIVATE LANE: enable RLS with NO policy → service-role only (deny everyone
-- else). Mirrors training_labels / recording_reviews.
ALTER TABLE coach_video_assets ENABLE ROW LEVEL SECURITY;
ALTER TABLE coach_video_rating_events ENABLE ROW LEVEL SECURITY;

-- Rollback (manual):
--   DROP TABLE IF EXISTS coach_video_rating_events;
--   DROP TABLE IF EXISTS coach_video_assets;
