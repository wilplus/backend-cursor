-- willab — the MASTER DOCUMENT block skeleton + saves (founder 2026-07-22).
--
-- The flip (supersedes decision #4 of 2026-07-20): the ideal text is ONE
-- persistent master document per project (arc). A new take NEVER replaces
-- it — it only contributes BLOCK-level upgrade offers where it beats the
-- master, judged by the shipped blended ranking.
--
-- ideal_text_blocks: one row per block of the skeleton.
--   * decked: block = slide (deterministic). Deckless: the take-1
--     transcript is chunked ONCE by an LLM into blocks (short talk:
--     Hook/Context/Core Message/Closer; longer: topic shifts) — the LLM
--     returns BOUNDARIES ONLY, never text; the skeleton then LOCKS.
--   * incumbent_pieces JSONB = [{snippet_id, text}] — the verbatim
--     recorded pieces the block currently shows; take_index is the
--     fragment's version badge (1.0/2.0…).
--   * status: 'settled' | 'pending_upgrade' (a better new-take block
--     waits, APPROVE-GATED — the master never changes silently) |
--     'candidate' (new material from a later take, approve-gated
--     addition; active=false until accepted).
--   * rejected_take_session_ids: offers the student kept-mine on —
--     remembered, never re-offered.
--   * block_key has GAPS (0,10,20…) so a candidate can sit between two
--     blocks at its mapped position.
--
-- ideal_text_saves: SAVE = accept-and-freeze (founder decision #3):
-- one row per saved version — the FE hides the badges and gates the
-- re-read button on the latest save.
--
-- L1: every stored piece is verbatim recorded speech. AC-9: take_index
-- is provenance, never a score. Idempotent; RLS on, no policy
-- (service-role only).
CREATE TABLE IF NOT EXISTS public.ideal_text_blocks (
    arc_id                     TEXT NOT NULL,
    block_key                  INT  NOT NULL,
    label                      TEXT NULL,
    active                     BOOLEAN NOT NULL DEFAULT TRUE,
    incumbent_take_session_id  TEXT NULL,
    incumbent_take_index       INT  NULL,
    incumbent_pieces           JSONB NOT NULL DEFAULT '[]',
    status                     TEXT NOT NULL DEFAULT 'settled'
        CHECK (status IN ('settled', 'pending_upgrade', 'candidate')),
    challenger_take_session_id TEXT NULL,
    challenger_take_index      INT  NULL,
    challenger_pieces          JSONB NULL,
    challenger_why             TEXT NULL,
    rejected_take_session_ids  JSONB NOT NULL DEFAULT '[]',
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (arc_id, block_key)
);
CREATE INDEX IF NOT EXISTS idx_ideal_text_blocks_arc
    ON public.ideal_text_blocks (arc_id);
ALTER TABLE public.ideal_text_blocks ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS public.ideal_text_saves (
    arc_id     TEXT NOT NULL,
    version    INT  NOT NULL,
    saved_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (arc_id, version)
);
ALTER TABLE public.ideal_text_saves ENABLE ROW LEVEL SECURITY;
