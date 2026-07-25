-- Public Journal (blog) + in-house CMS (founder 2026-07-25).
--
-- A marketing/content surface on www.willpowerlab.com: public read endpoints
-- (server-rendered with ISR by the FE) plus a password-gated CMS. Fully
-- self-contained — this table is touched ONLY by services/journal.py and the
-- routes/journal.py blueprint. Nothing in the record -> transcribe -> coach ->
-- read loop reads or writes it.
--
-- Two structural decisions baked into the shape:
--   * `body` is PLAIN TEXT, paragraphs separated by blank lines. Not HTML,
--     not Markdown — the FE splits on blank lines and renders <p>. No HTML is
--     stored, so there is no XSS surface to sanitize.
--   * `published_at` is the AUTHOR-SUPPLIED DISPLAY DATE and `status` is
--     visibility. They are independent: a published post can be backdated,
--     and a draft can already carry a date. `read_time_min` is likewise
--     author-supplied and never derived.
--
-- Idempotent (IF NOT EXISTS throughout) and safe to run before or after the
-- code deploys — every read/write in services/db is best-effort and degrades
-- to "no posts" when the table is absent.

CREATE TABLE IF NOT EXISTS journal_post (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),

    slug               text        NOT NULL UNIQUE,
    title              text        NOT NULL DEFAULT '',
    excerpt            text        NOT NULL DEFAULT '',
    category           text        NOT NULL DEFAULT 'others',
    read_time_min      integer     NOT NULL DEFAULT 1,

    cover_kind         text        NOT NULL DEFAULT 'image',
    cover_image_url    text,
    cover_alt          text,
    media_url          text,
    media_duration_sec integer,

    body               text        NOT NULL DEFAULT '',

    author_name        text        NOT NULL DEFAULT 'Willpower Lab',
    author_avatar_url  text,

    status             text        NOT NULL DEFAULT 'draft',
    published_at       timestamptz,
    sort_order         integer     NOT NULL DEFAULT 0,

    meta_title         text,
    meta_description   text,
    og_image_url       text,

    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now()
);

-- Value constraints as CHECKs rather than PG enums: a CHECK can be amended
-- with a plain ALTER later, while adding a value to a PG enum type is a
-- migration hazard (and the lounge-kind CHECK is the house precedent).
-- Added defensively so re-running against an existing table is a no-op.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'journal_post_category_check'
    ) THEN
        ALTER TABLE journal_post
            ADD CONSTRAINT journal_post_category_check
            CHECK (category IN ('physiology', 'physical_exercise', 'philosophy',
                                'voice', 'language', 'others'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'journal_post_cover_kind_check'
    ) THEN
        ALTER TABLE journal_post
            ADD CONSTRAINT journal_post_cover_kind_check
            CHECK (cover_kind IN ('image', 'video', 'audio'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'journal_post_status_check'
    ) THEN
        ALTER TABLE journal_post
            ADD CONSTRAINT journal_post_status_check
            CHECK (status IN ('draft', 'published'));
    END IF;
END $$;

-- ROW LEVEL SECURITY — load-bearing, not boilerplate.
--
-- The FE ships NEXT_PUBLIC_SUPABASE_ANON_KEY inlined into the browser bundle,
-- so anyone can read it out of the JS and call PostgREST directly. Without RLS
-- the default public-schema grants to `anon` would let a visitor
--     GET /rest/v1/journal_post?status=eq.draft
-- and read every unpublished draft — and PATCH/DELETE published ones — without
-- ever seeing JOURNAL_ADMIN_PASSWORD. The Flask layer's own published_only
-- filter cannot defend a door that bypasses Flask entirely.
--
-- No policies are added on purpose: with RLS enabled and zero policies, `anon`
-- and `authenticated` can do nothing at all, while the backend — which
-- connects with SUPABASE_SERVICE_ROLE_KEY (services/db.py) — bypasses RLS and
-- keeps full access. Every public read is therefore served ONLY through
-- /v2/journal/*, where the published_only filter applies.
ALTER TABLE journal_post ENABLE ROW LEVEL SECURITY;

-- The public index query: published posts newest-first.
CREATE INDEX IF NOT EXISTS journal_post_status_published_at_idx
    ON journal_post (status, published_at DESC);

-- Category filter + the manual "curated" ordering.
CREATE INDEX IF NOT EXISTS journal_post_category_idx ON journal_post (category);
CREATE INDEX IF NOT EXISTS journal_post_sort_order_idx ON journal_post (sort_order);

-- A published post MUST carry a display date. Postgres orders DESC as NULLS
-- FIRST, so a published row with published_at = NULL would pin itself to the
-- top of the public index permanently (and render a blank date on the card).
-- The API guarantees this on every write; this backfill covers a row inserted
-- directly via SQL. Idempotent — a no-op once every published row has a date.
UPDATE journal_post
   SET published_at = COALESCE(published_at, created_at, now())
 WHERE status = 'published' AND published_at IS NULL;
