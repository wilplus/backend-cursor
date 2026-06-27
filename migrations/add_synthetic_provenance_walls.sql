-- willab — Subsystem S provenance walls (capture-now; NO generation, NO game UI).
--
-- Two future subsystems need clean provenance BEFORE any synthetic snippet is
-- ever generated, or the coach-truth corpus + any validation/holdout get
-- silently contaminated (the governing fence: services/snippet_salience.py
-- validation-independence). This PR builds ONLY the walls.
--
-- (1) DATA-ORIGIN + LINEAGE on the snippet tables. We deliberately DO NOT widen
--     the existing source_type CHECK ('student','internet') — there are two
--     drift-y charisma_snippets CREATE definitions, so CHECK surgery is unsafe.
--     Instead an ADDITIVE `data_origin` column (drift-proof ALTER ... IF NOT
--     EXISTS lands on the one physical table). NULL = real/unknown (every
--     existing row); generated rows will set 'synthetic'. parent_snippet_id +
--     generator_version are the lineage back to the real seed snippet so a
--     synthetic child is always traceable, dedupable, and weightable below its
--     parent. Nothing writes 'synthetic' yet (generation is deferred) — the
--     column just exists so generation can never masquerade as real.
--
-- (2) SNIPPET_PEER_LABELS — a multi-rater, SECOND-ORDER (non-coach) label lane.
--     The swipe game + the existing user self-verification (charisma_snippets.
--     user_charisma_label, a single boolean that can't hold N raters) feed here.
--     L2/L3 fence: a peer signal may only sit BELOW coach truth — this table is
--     SEPARATE from training_labels (the coach-truth corpus) and is never joined
--     into it by the export; a future model blends it at a low weight.
--
-- Idempotent; additive; safe to re-run.

-- ALTER TABLE IF EXISTS so a missing table in some env degrades gracefully.
ALTER TABLE IF EXISTS public.charisma_snippets ADD COLUMN IF NOT EXISTS data_origin TEXT;
ALTER TABLE IF EXISTS public.charisma_snippets ADD COLUMN IF NOT EXISTS parent_snippet_id UUID;
ALTER TABLE IF EXISTS public.charisma_snippets ADD COLUMN IF NOT EXISTS generator_version TEXT;

ALTER TABLE IF EXISTS public.stress_snippets ADD COLUMN IF NOT EXISTS data_origin TEXT;
ALTER TABLE IF EXISTS public.stress_snippets ADD COLUMN IF NOT EXISTS parent_snippet_id UUID;
ALTER TABLE IF EXISTS public.stress_snippets ADD COLUMN IF NOT EXISTS generator_version TEXT;

-- Fast "exclude synthetic" + "find a seed's children" reads.
CREATE INDEX IF NOT EXISTS idx_charisma_snippets_data_origin
    ON public.charisma_snippets (data_origin);
CREATE INDEX IF NOT EXISTS idx_charisma_snippets_parent
    ON public.charisma_snippets (parent_snippet_id);
CREATE INDEX IF NOT EXISTS idx_stress_snippets_data_origin
    ON public.stress_snippets (data_origin);

-- Multi-rater, second-order (non-coach) label lane.
CREATE TABLE IF NOT EXISTS snippet_peer_labels (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    snippet_id       UUID NOT NULL,
    rater_id         UUID,                   -- the user/peer (NULL = anon)
    label            TEXT,                   -- the swipe choice (e.g. charisma | not_charisma)
    is_second_order  BOOLEAN NOT NULL DEFAULT TRUE,  -- always a non-coach signal
    weight           REAL NOT NULL DEFAULT 1.0,      -- below-coach weighting (model side)
    source           TEXT,                   -- game | self_verification | synthetic_seed
    shown_origin     TEXT,                   -- the data_origin of the snippet AS SHOWN (real|synthetic)
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_snippet_peer_labels_snippet
    ON snippet_peer_labels (snippet_id);
CREATE INDEX IF NOT EXISTS idx_snippet_peer_labels_rater
    ON snippet_peer_labels (rater_id);

-- Training-bound lane: RLS on, no policy → service-role only (mirrors
-- training_labels). Never a user-facing read.
ALTER TABLE snippet_peer_labels ENABLE ROW LEVEL SECURITY;

-- Rollback (manual):
--   DROP TABLE IF EXISTS snippet_peer_labels;
--   ALTER TABLE public.charisma_snippets DROP COLUMN IF EXISTS data_origin, DROP COLUMN IF EXISTS parent_snippet_id, DROP COLUMN IF EXISTS generator_version;
--   ALTER TABLE public.stress_snippets DROP COLUMN IF EXISTS data_origin, DROP COLUMN IF EXISTS parent_snippet_id, DROP COLUMN IF EXISTS generator_version;
