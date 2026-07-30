-- Life Panel — setup strategy-document uploads (founder-approved item 9,
-- 2026-07-30).
--
-- The setup wizard gains an optional "Current strategy" upload step. The user
-- may hand over an existing strategy document (.pdf / .docx / .txt / .md) and
-- OPTIONALLY draft goals from it; nothing is ever applied without the user
-- ticking each row in the review UI (N5), and the crafted strategy documents
-- may read the uploaded text so they align with what the user already wrote.
--
-- WHAT IS STORED, AND WHY NOT THE BINARY. Only the EXTRACTED TEXT is kept,
-- never the uploaded file bytes. This matches the panel's text-first
-- philosophy (life_strategy stores markdown bodies, life_notes stores text):
-- the text is the part the engine reads, it is exportable/deletable like every
-- other life_* row, and a binary blob column would be a second, unreadable
-- copy of confession-adjacent material with its own retention problem.
--
-- RUN THIS IN THE SUPABASE SQL EDITOR. Idempotent — every statement is
-- IF NOT EXISTS / guarded; re-running is a no-op. Nothing is dropped.
--
-- RLS IS PART OF THIS FILE, NOT A FOLLOW-UP SWEEP (N1, same as
-- add_life_panel.sql): no policies ON PURPOSE — RLS enabled with zero
-- policies means `anon` and `authenticated` can do nothing at all, while the
-- backend's service-role key bypasses RLS. Every read/write is served ONLY
-- through /v2/life/*, where the consent gate and the owner filter apply.

CREATE TABLE IF NOT EXISTS life_setup_documents (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        uuid        NOT NULL,
    file_name      text,
    mime_type      text,
    -- The extracted plain text, capped at extraction time (services/
    -- context_document.py caps at 40k chars). The binary is never stored.
    extracted_text text,
    char_count     int,
    status         text        NOT NULL DEFAULT 'processed'
                   CHECK (status IN ('processed', 'extraction_failed')),
    created_at     timestamptz NOT NULL DEFAULT now()
);

-- "Latest document first" is the read the setup step and the generator both
-- make.
CREATE INDEX IF NOT EXISTS life_setup_documents_user_created_idx
    ON life_setup_documents (user_id, created_at DESC);

ALTER TABLE life_setup_documents ENABLE ROW LEVEL SECURITY;

-- ─────────────────────────────────────────────────────────────────────────
-- POST-CONDITION — verify RLS actually landed (N1). A migration that
-- silently half-applies is how a table ends up exposed; raise, so a partial
-- run is a failed run.
-- ─────────────────────────────────────────────────────────────────────────
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
          FROM pg_class c
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = 'public'
           AND c.relname = 'life_setup_documents'
           AND NOT c.relrowsecurity
    ) THEN
        RAISE EXCEPTION
            'life_setup_documents was created without row level security';
    END IF;
END $$;
