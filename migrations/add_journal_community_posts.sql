-- Community Content Studio (founder 2026-07-26).
--
-- The Journal CMS gets one button under a post's body: it sends that post to
-- the model and derives the three OTHER community formats from the content
-- model in services/prompts/community_content_strategy.md. The journal post
-- itself is format ① Technique; these rows are ② Myth-bust, ③ Fear, ④ Win.
-- The founder copies them into Skool by hand — nothing here posts anywhere.
--
-- COMMUNITY-ONLY, BY CONSTRUCTION. These are not journal posts and must never
-- become them: no slug, no status, no published_at, no sort_order. A "Win"
-- post is `share yours below` — a community thread, not an article on
-- www.willpowerlab.com. No public /v2/journal/* handler reads this table;
-- every read and write goes through the password-gated
-- /v2/internal/journal/community/* routes.
--
-- Self-contained, like journal_post: nothing in the record → transcribe →
-- coach → read loop touches it, and no F1 assembly module may import the
-- service that writes it (grep-fenced in test_community_content.py).
--
-- Idempotent (IF NOT EXISTS throughout) and safe to run before or after the
-- code deploys — every db helper is best-effort and degrades to "no items"
-- when the table is absent.

CREATE TABLE IF NOT EXISTS journal_community_post (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),

    -- CASCADE: the derived posts are meaningless without their anchor, so
    -- deleting the journal post takes its community drafts with it.
    journal_post_id uuid        NOT NULL
                    REFERENCES journal_post(id) ON DELETE CASCADE,

    kind            text        NOT NULL,          -- myth_bust | fear | win
    title           text        NOT NULL DEFAULT '',
    body            text        NOT NULL DEFAULT '',

    -- ["construct"] and/or ["verify"] — the soft warnings the CMS renders
    -- above a body (retired score vocabulary / a claim the source essay does
    -- not make). Never a reason to drop a draft; a human reads every one.
    flags           jsonb       NOT NULL DEFAULT '[]'::jsonb,

    -- Batch-level fields, denormalized onto each row ON PURPOSE. Three rows
    -- always come from one generation, and regenerating a SINGLE format must
    -- not need a second table to keep the other two consistent — the writer
    -- inherits these from a surviving sibling instead of re-theming the week.
    pillar_id       integer,
    pillar_name     text,
    theme           text,
    soft_cta_line   text        NOT NULL DEFAULT '',
    app_proof_line  text        NOT NULL DEFAULT '',

    model           text,
    generated_at    timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);

-- One row per (post, format): regenerating a format REPLACES it instead of
-- piling up drafts. Also the upsert conflict target used by services/db.py.
CREATE UNIQUE INDEX IF NOT EXISTS journal_community_post_parent_kind_idx
    ON journal_community_post (journal_post_id, kind);

-- Value constraint as a CHECK rather than a PG enum: a CHECK can be amended
-- with a plain ALTER later, while adding a value to an enum type is a
-- migration hazard (the house precedent is the lounge-kind CHECK, and
-- journal_post's own category/status CHECKs). Added defensively so re-running
-- against an existing table is a no-op.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'journal_community_post_kind_check'
    ) THEN
        ALTER TABLE journal_community_post
            ADD CONSTRAINT journal_community_post_kind_check
            CHECK (kind IN ('myth_bust', 'fear', 'win'));
    END IF;
END $$;

-- ROW LEVEL SECURITY — load-bearing, not boilerplate.
--
-- The FE ships NEXT_PUBLIC_SUPABASE_ANON_KEY inlined into the browser bundle,
-- so anyone can read it out of the JS and call PostgREST directly. Without RLS
-- the default public-schema grants to `anon` would let a visitor
--     GET /rest/v1/journal_community_post
-- and read (or PATCH, or DELETE) every unpublished community draft without
-- ever seeing JOURNAL_ADMIN_PASSWORD. The Flask layer cannot defend a door
-- that bypasses Flask entirely.
--
-- No policies are added on purpose: with RLS enabled and zero policies, `anon`
-- and `authenticated` can do nothing at all, while the backend — which
-- connects with SUPABASE_SERVICE_ROLE_KEY (services/db.py) — bypasses RLS and
-- keeps full access. This is the standing rule from the 2026-07-25 RLS sweep:
-- every new public-schema table enables RLS in its creating migration.
ALTER TABLE journal_community_post ENABLE ROW LEVEL SECURITY;

-- The only query shape: everything for one parent post, and the CMS's
-- load-all-then-group-client-side listing.
CREATE INDEX IF NOT EXISTS journal_community_post_parent_idx
    ON journal_community_post (journal_post_id);

-- Rollback (manual):
--   DROP TABLE IF EXISTS journal_community_post;
