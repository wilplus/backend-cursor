-- 0255 · ideal_text_part — the document stops being a string.
--
-- SPEC-parts-locking-and-layers §3.1, Step 0. Identity ONLY: nothing here
-- locks anything, and there is no behaviour change beyond a part being able
-- to say which part it is. `locked_at` lands in PR 3, alongside the code that
-- reads it, so the schema never claims a capability the system does not have.
--
-- WHY IDENTITY HAS TO BE PERSISTED. A lock must survive both REORDERING and
-- REWORDING, and none of the three obvious alternatives does:
--
--   array index    shifts on reorder — and `splitSegments` drops empty
--                  segments, so it shifts on edits that are not reorders;
--   content hash   dies the moment an approved accentuation touches the
--                  paragraph, and locked text is exactly the text that keeps
--                  being restyled;
--   char offset    needs re-anchoring on every edit, which is a second
--                  segmentation problem beside the one F1 already owns.
--
-- `ord` is separate from `id` for the same reason `layer` is separate from
-- `kind` in §3.2: POSITION IS NOT IDENTITY.
--
-- ── THE KEY IS (arc_id, user_id), NOT arc_id ────────────────────────────────
--
-- §3.1 specifies `arc_id` alone. Reading the actual serve path changed that,
-- and the difference is worth stating rather than quietly widening:
--
-- The served document is DERIVED per request, not stored. It resolves from up
-- to four sources — the machine `auto_text`, the coach's `verified_text`, the
-- student's version-stamped edit in `user_arc_ideal_notes`, plus the fold /
-- sanitize / strip-moment transforms — so `arc_id` alone does not name a
-- document. `user_arc_ideal_notes` is keyed (arc_id, user_id) and IS the row
-- the arranger writes through, so parts key the same way. With one owner per
-- arc this is exactly §3.1's semantics; if an arc ever carries two, parts
-- cannot bleed between them.
--
-- ── NOT VERSION-SCOPED, DELIBERATELY ────────────────────────────────────────
--
-- The obvious third key column would be the ideal-text version. It is wrong:
-- a new take bumps the version, so version-scoped parts would mint fresh ids
-- on every take and DISCARD EVERY LOCK the student had set. §8 says the
-- opposite — when a later take beats a locked part, the LOCK WINS. Parts
-- outlive versions by construction, which is the whole point of them.
--
-- ── THE BACKEND NEVER SPLITS TEXT ───────────────────────────────────────────
--
-- There is no backfill here and no server-side paragraph splitter. §9 called
-- for one ("a one-time backfill runs the existing splitBadgeParagraphSpans
-- over stored texts"), and building it would have contradicted §2's own
-- argument: a real distinction with no single home gets re-derived slightly
-- differently by each consumer until they disagree. The FE's
-- `splitBadgeParagraphSpans` is marker-aware and refuses a split inside a
-- rich-marker token; a Python mirror of it would be a SECOND definition of
-- "paragraph", and the two would drift on exactly the documents where the
-- split is hard.
--
-- So the client mints part ids and sends them; this table stores them. The
-- split stays in one place, where the founder already confirmed it lives.
-- A document nobody has opened has no parts — which is fine, because nothing
-- can be locked on a document nobody has opened.
--
-- Idempotent. Safe to re-run. Non-destructive.

BEGIN;

CREATE TABLE IF NOT EXISTS public.ideal_text_part (
    -- STABLE, and minted by the client. Never regenerated, never reused.
    id          UUID        PRIMARY KEY,
    arc_id      TEXT        NOT NULL,
    user_id     TEXT        NOT NULL,

    -- Position in the document. Changes on reorder; `id` does not.
    ord         INTEGER     NOT NULL,
    text        TEXT        NOT NULL,

    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Two parts of one document cannot share a slot. Non-partial, so PostgREST's
-- `on_conflict` can use it as an arbiter — a partial unique index raises
-- 42P10 on every write and, behind a best-effort writer, does it silently
-- forever (the 2026-08-06 lesson, migration 0251).
--
-- NOTE this is NOT the write arbiter: parts are replaced wholesale per
-- document (delete-then-insert in one call), because a reorder changes many
-- rows' `ord` at once and an upsert-per-row would transiently violate this.
-- It is here as an INVARIANT — if a write path ever starts upserting per row,
-- the collision surfaces as an error instead of as two parts claiming slot 3.
CREATE UNIQUE INDEX IF NOT EXISTS uq_ideal_text_part_slot
    ON public.ideal_text_part (arc_id, user_id, ord);

-- The read: one document's parts, in order.
CREATE INDEX IF NOT EXISTS idx_ideal_text_part_document
    ON public.ideal_text_part (arc_id, user_id, ord);

ALTER TABLE public.ideal_text_part ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE public.ideal_text_part IS
    'SPEC-parts-locking-and-layers §3.1, Step 0. The ideal text as an ordered '
    'list of parts with STABLE ids, so a lock can survive reordering and '
    'rewording. Identity only — locking lands in PR 3. Keyed (arc_id, '
    'user_id) because the served document is derived per request and arc_id '
    'alone does not name one. Ids are minted CLIENT-SIDE: the paragraph split '
    'is marker-aware and lives in the FE, and a second implementation of it '
    'would be a second definition of "paragraph".';

COMMENT ON COLUMN public.ideal_text_part.ord IS
    'Position, not identity. Changes on every reorder; id never does.';

COMMIT;
