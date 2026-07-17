-- willab — persist the student's in-place edit of the SD ideal text (founder
-- 2026-07-17). The post-recording screen IS the ideal text 1.0, editable in
-- place; this makes that edit survive reloads and show on every surface.
--
-- Reuses the existing per-(arc, user) row (user_arc_ideal_notes) rather than
-- a new table — but as a SIBLING pair, NOT by repurposing `text`: the legacy
-- perfected lane (flag OFF) still serves `text` as the separate notebook copy,
-- so overloading it would corrupt that lane. Under SD the edit lives in its
-- own columns:
--   user_text          — the student's edited ideal text
--   user_text_version  — the ideal-text version the edit was made against
--                        (edit wins display only while it equals the current
--                        version; a new take supersedes it — retained, not
--                        shown; BE-2 pinned default)
-- Idempotent; additive.
ALTER TABLE public.user_arc_ideal_notes
    ADD COLUMN IF NOT EXISTS user_text TEXT NULL,
    ADD COLUMN IF NOT EXISTS user_text_version INTEGER NULL;

-- `text` (the legacy notebook copy) is NOT NULL. An SD edit can create a row
-- with NO notebook copy, so a bare upsert (user_text only) would violate it
-- on INSERT. A DEFAULT '' lets the omitted column fill on INSERT while the
-- merge-duplicates UPDATE leaves any existing notebook copy untouched.
ALTER TABLE public.user_arc_ideal_notes
    ALTER COLUMN text SET DEFAULT '';
