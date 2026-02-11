-- Add post_answers to v2_sessions so POST /v2/homework/session/:id/post-answers can persist answers.
-- Required when v2_sessions was created from a schema that did not include post_answers. Canonical schema: .taskmaster/docs/schema.sql (includes post_answers in DO block).
-- Run in Supabase SQL Editor (or your Postgres client). Idempotent.

ALTER TABLE v2_sessions ADD COLUMN IF NOT EXISTS post_answers JSONB;

COMMENT ON COLUMN v2_sessions.post_answers IS 'Post-recording question answers: [{ question_id, answer_text }, ...]. Set by POST post-answers.';
