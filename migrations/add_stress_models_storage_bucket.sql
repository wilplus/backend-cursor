-- Private bucket for stress baseline classifier JSON artifacts (shared across app instances).
-- Run in Supabase SQL Editor. Set env: STRESS_MODEL_BUCKET=stress_models (default in config).

INSERT INTO storage.buckets (id, name, public)
VALUES ('stress_models', 'stress_models', false)
ON CONFLICT (id) DO NOTHING;
