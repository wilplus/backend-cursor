-- BLINDED A/B SLIDE VERDICTS (founder 2026-08-11) — the corpus that unblocks
-- piece (b) of the north star.
--
-- The audit found best-text-per-slide ranking blocked twice, and neither
-- block is code: power_score's DELIVERY term is ranking-inert until the
-- composite is anchored against blinded human ratings
-- (VOICE_CONFIDENCE_RANKING_ENABLED), and LINE-LEVEL cross-take selection is
-- hard-disabled until a fuzzy-alignment spike can run on real multi-take
-- arcs. One coach act produces both: comparing the same slide across two
-- takes gives a human preference to correlate the composite against AND a
-- matched cross-take pair for the alignment spike.
--
-- WHAT A ROW MEANS: "shown these two deliveries of the same slide, with no
-- idea which take was which, a coach judged THIS one landed better."
--
-- BLINDING, RECORDED. session_left / session_right are the sides as the
-- rater actually saw them, not a canonical order. Position bias is real and
-- the only way to measure it is to keep the layout: with these columns you
-- can ask "did left win more often than chance" and find out. Collapsing
-- them into winner/loser throws that away forever.
--
-- A TIE IS A VERDICT, not a missing row: winner_session_id NULL with
-- verdict='tie' means a human looked and could not separate them, which is
-- exactly the signal that tells you where the composite must NOT claim a
-- difference. Absence of a row means nobody looked.
--
-- THE TEXTS ARE STORED, deliberately duplicating the transcripts. A pair is
-- only alignment ground truth if you can still read both sides of it, and
-- the document reassembles on every take — the same lesson the decisions
-- ledger learned when a dismissed proposal became unrecoverable.
--
-- APPEND-ONLY. No UPDATE, no DELETE: a re-rating is a new row and the older
-- one stays. Labels are versioned/immutable by standing rule — and here it
-- also buys intra-rater reliability, which you cannot compute from a corpus
-- that overwrites.
CREATE TABLE IF NOT EXISTS public.slide_ab_verdicts (
    id                 BIGSERIAL PRIMARY KEY,
    arc_id             TEXT NOT NULL,
    slide_index        INTEGER NOT NULL,
    -- The sides AS SHOWN. Not winner/loser — see the blinding note above.
    session_left       TEXT NOT NULL,
    session_right      TEXT NOT NULL,
    verdict            TEXT NOT NULL CHECK (verdict IN ('left', 'right', 'tie')),
    -- NULL iff verdict = 'tie'.
    winner_session_id  TEXT,
    -- Both deliveries, as the rater read them: the alignment pair.
    left_text          TEXT,
    right_text         TEXT,
    rated_by           TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- The reads: every verdict for an arc (the corpus), and every verdict on one
-- pair (agreement between raters, and one rater with themselves over time).
CREATE INDEX IF NOT EXISTS idx_sav_arc_created
    ON public.slide_ab_verdicts (arc_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sav_pair
    ON public.slide_ab_verdicts (arc_id, slide_index, session_left, session_right);

-- Coach-authored, coach-only. The backend holds the service-role key and
-- bypasses RLS, so no policy is needed — but without this line the corpus is
-- readable, and often writable, by anyone holding the anon key out of the
-- browser bundle (docs/RLS-AUDIT.md).
ALTER TABLE public.slide_ab_verdicts ENABLE ROW LEVEL SECURITY;
