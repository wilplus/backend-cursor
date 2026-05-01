-- Funnel configuration table for storing funnel-level settings
-- Currently used for afterwards video URL in Curiosity Gate funnel

CREATE TABLE IF NOT EXISTS funnel_config (
  id SERIAL PRIMARY KEY,
  key VARCHAR(255) UNIQUE NOT NULL,
  value TEXT,
  updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- Seed the afterwards_video_url key with NULL value
INSERT INTO funnel_config (key, value, updated_at)
VALUES ('afterwards_video_url', NULL, CURRENT_TIMESTAMP)
ON CONFLICT (key) DO NOTHING;

-- Index on key for fast lookups
CREATE INDEX IF NOT EXISTS idx_funnel_config_key ON funnel_config(key);
