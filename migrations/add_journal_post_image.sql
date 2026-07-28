-- Journal cover images, generated (founder 2026-07-28).
--
-- The CMS gets a "Draw a cover" button next to a post: the model reads the
-- post, writes an image brief, draws it, and the file lands in the same R2
-- journal bucket an uploaded cover would. A notes box steers the next attempt
-- ("darker, no hands, less literal") and "Regenerate" re-runs the brief WITH
-- that note plus the previous brief, so a note refines the image instead of
-- starting an unrelated one.
--
-- Why a table at all, when the post already has cover_image_url:
--   * Regenerate must not be destructive. Without a history, the second
--     attempt erases the first from the CMS forever (the R2 object survives
--     but nothing references it), and the third attempt is a coin flip the
--     founder cannot walk back. The history strip IS the undo.
--   * The notes lineage is the useful artifact. `parent_image_id` + `notes`
--     record which attempt a steer was applied to, so a good cover can be
--     re-derived later instead of re-guessed.
--   * cover_image_url stays the single source of truth for what the site
--     shows. A row here is a CANDIDATE; /image/select is what promotes one.
--
-- CMS-ONLY. Reachable exclusively through the password-gated
-- /v2/internal/journal/image/* routes. No public /v2/journal/* handler reads
-- this table — the public payload carries only the promoted cover_image_url
-- and cover_alt on journal_post itself. Self-contained like the rest of the
-- Journal: nothing in the record -> transcribe -> coach -> read loop touches
-- it (grep-fenced both ways in test_journal_image.py).
--
-- Idempotent (IF NOT EXISTS throughout) and safe to run before or after the
-- code deploys — every db helper is best-effort and degrades to "no history"
-- when the table is absent, which leaves generate working and only costs the
-- strip.

CREATE TABLE IF NOT EXISTS journal_post_image (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),

    -- CASCADE: a candidate cover is meaningless without its post.
    journal_post_id  uuid        NOT NULL
                     REFERENCES journal_post(id) ON DELETE CASCADE,

    -- Where the drawn file lives. The bytes come back from the model as
    -- base64, get PUT to R2 server-side, and this is the public URL — the
    -- model's own temporary URL is NEVER stored (DALL·E's expires in ~1h,
    -- which would silently blank every cover on the site an hour later).
    image_url        text        NOT NULL,
    storage_key      text,

    -- Written by the brief step alongside the prompt, so a generated cover
    -- arrives accessible instead of needing a second pass. Public copy once
    -- promoted — hence the construct guard in services/journal_image.py.
    alt_text         text        NOT NULL DEFAULT '',

    -- The brief actually sent to the image model, and what the image model
    -- says it drew (DALL·E 3 rewrites prompts and returns revised_prompt).
    -- Kept because the next refinement reads them: a note steers the PREVIOUS
    -- brief rather than the post from scratch.
    prompt           text        NOT NULL DEFAULT '',
    revised_prompt   text,

    -- The founder's steer that produced THIS attempt ("" for a first draw).
    notes            text        NOT NULL DEFAULT '',

    -- The attempt this one refines. SET NULL, not CASCADE: deleting a bad
    -- middle attempt must not delete the good one derived from it.
    parent_image_id  uuid        REFERENCES journal_post_image(id)
                     ON DELETE SET NULL,

    -- ["construct"] when the retired score vocabulary reached the alt text or
    -- the brief. A flag, never a drop: the CMS shows a warning on a draft a
    -- human is already looking at.
    flags            jsonb       NOT NULL DEFAULT '[]'::jsonb,

    model            text,
    size             text,
    quality          text,

    created_at       timestamptz NOT NULL DEFAULT now()
);

-- The only query: this post's attempts, newest first.
CREATE INDEX IF NOT EXISTS journal_post_image_parent_created_idx
    ON journal_post_image (journal_post_id, created_at DESC);

-- ROW LEVEL SECURITY — load-bearing, same reasoning as journal_post.
--
-- The FE ships NEXT_PUBLIC_SUPABASE_ANON_KEY in the browser bundle, so anyone
-- can read it out of the JS and call PostgREST directly. Without RLS the
-- default public-schema grants to `anon` would expose every candidate cover
-- for every DRAFT post — the visual roadmap of unpublished work — and allow
-- DELETEs, without ever seeing JOURNAL_ADMIN_PASSWORD.
--
-- No policies on purpose: RLS enabled with zero policies means `anon` and
-- `authenticated` can do nothing, while the backend (SUPABASE_SERVICE_ROLE_KEY
-- in services/db.py) bypasses RLS and keeps full access.
ALTER TABLE journal_post_image ENABLE ROW LEVEL SECURITY;
