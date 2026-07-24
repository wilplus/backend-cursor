-- dev_bugs.images — support MULTIPLE attached images per bug (multi-select from
-- the gallery). New rows store all data-URLs in `images` (a JSONB array);
-- `image_url` keeps the FIRST image for backward-compat with old single-image
-- consumers. Rows created before this migration have images=[] and their single
-- image in `image_url` — services.dev_bugs._bug_images() falls back to it.
--
-- Idempotent; safe to re-run.

ALTER TABLE public.dev_bugs
    ADD COLUMN IF NOT EXISTS images JSONB NOT NULL DEFAULT '[]'::jsonb;
