-- Phase Stress-Contrast (BE-3) — silent acoustic capture from
-- "The Lounge" chat surface.
--
-- Lets us compute how much a user's voice degrades under
-- official-recording pressure vs casual chat. Every time the user
-- speaks into the small mic on /v2/chat/query (Web Speech API
-- streams text → input field; MediaRecorder captures the raw blob
-- silently), the backend folds the blob through
-- services.audio_metrics.analyze_audio in a daemon thread and
-- persists the metric row here.
--
-- Read by services.db.compute_stress_contrast which medians the
-- last 5 rows here vs. the last 5 published charisma_snippets to
-- surface a per-metric delta ("you speak 12 WPM faster under
-- pressure").
--
-- session_id is NULLABLE — casual chat has no v2_sessions row by
-- default. The column exists only for the edge case where casual
-- capture happens to occur inside an active coaching session.
--
-- audio_storage_path is NULLABLE — by default we analyze the blob
-- in-memory and discard. Behind feature flag RETAIN_CASUAL_AUDIO,
-- the daemon may upload to casual_voice/<user_id>/<row_id>.webm
-- for QA, in which case this column is populated.
--
-- Run in Supabase SQL Editor. Idempotent.

DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'public'
      AND table_name = 'casual_voice_benchmarks'
  ) THEN
    CREATE TABLE casual_voice_benchmarks (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      user_id UUID NOT NULL
        REFERENCES auth.users(id) ON DELETE CASCADE,
      session_id UUID NULL
        REFERENCES v2_sessions(id) ON DELETE SET NULL,
      metrics JSONB NOT NULL,
      transcript_source TEXT NOT NULL
        CHECK (transcript_source IN ('web_speech', 'server_whisper')),
      audio_duration_ms INT NULL,
      audio_storage_path TEXT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );

    -- Hot read pattern: "last N benchmarks for this user, newest
    -- first" (get_recent_casual_voice_metrics + the contrast
    -- aggregator). Index aligned with that exact ORDER BY.
    CREATE INDEX idx_cvb_user_created
      ON casual_voice_benchmarks (user_id, created_at DESC);
  END IF;
END $$;

COMMENT ON TABLE casual_voice_benchmarks IS
  'Phase Stress-Contrast (BE-3) — silent acoustic snapshots of the '
  'user speaking casually during /v2/chat/query (multipart path). '
  'Compared against published charisma_snippets metrics to surface '
  'how much the user''s voice degrades under high-stakes pressure. '
  'Audio blob is NOT retained by default — only the computed '
  'metrics row persists.';

COMMENT ON COLUMN casual_voice_benchmarks.metrics IS
  'JSONB shape matches services.audio_metrics.analyze_audio return: '
  '{wpm, pause_ms, dynamic_db, emphasis_per_min, energy_ratio, '
  'pitch_center_st, pitch_frame_count, voiced_duration_sec}. '
  'Stored verbatim so future metric additions don''t require a '
  'schema migration.';

COMMENT ON COLUMN casual_voice_benchmarks.session_id IS
  'NULL for pure Lounge chat queries (the common case). Populated '
  'only when casual capture happens to coincide with an active '
  'coaching session — e.g. user opens /chat in another tab while '
  'mid-coaching.';

COMMENT ON COLUMN casual_voice_benchmarks.transcript_source IS
  'Which transcript the WPM in metrics was computed against. '
  '"web_speech" is the v1 default (frontend streams Web Speech API '
  'text into the input field and that text is forwarded as the '
  'transcript). "server_whisper" reserved for a future path that '
  're-transcribes server-side for higher accuracy.';

COMMENT ON COLUMN casual_voice_benchmarks.audio_storage_path IS
  'NULL by default — feature flag RETAIN_CASUAL_AUDIO (env var) '
  'must be true at the time of capture for the daemon to upload '
  'the blob to R2 and populate this. Used for QA replay of bad '
  'acoustic readings.';
