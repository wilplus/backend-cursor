-- Reference link on a coach-verified moment (ticket 6, 2026-07-26).
--
-- A "golden star" is a coach_snippet_drafts row that is `surfaced` and carries a
-- note and/or a breakthrough video — the ORANGE verified star in the student's
-- moment modal. The coach can now attach ONE blog post to such a moment, shown
-- at the bottom of that modal as further reading.
--
-- Founder decision: the coach assigns it MANUALLY, and only on golden stars.
-- No automatic or LLM matching — "matches exactly this problem" rules out fuzzy
-- similarity, and a wrongly-attached post reads as sloppy.
--
-- Stores the SLUG, not a URL, on purpose: the public path is moving
-- (/journal -> /blog) and a stored absolute URL would rot. The title and href
-- are resolved at read time, so a renamed or re-pathed post stays correct, and
-- an unpublished or deleted post drops out of the payload instead of serving a
-- dead link.
--
-- No RLS statement: coach_snippet_drafts already has row level security enabled
-- (its own creating migration, reinforced by the 2026-07-25 sweep). Adding a
-- column does not change that. A migration that CREATES a table must enable
-- RLS itself.
--
-- Idempotent; the write is best-effort (services/db.upsert_coach_snippet_draft
-- only sets this key when the coach actually sets it), so shipping the code
-- before running this is safe.

ALTER TABLE coach_snippet_drafts
    ADD COLUMN IF NOT EXISTS reference_post_slug text;
