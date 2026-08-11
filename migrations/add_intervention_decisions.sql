-- The intervention decision ground truth + per-take spend ledger.
--
-- Two founder decisions land in one table:
--
-- 1 · SPEC-parts-locking-and-layers §3.3/§6 — `intervention_decision` is
--     "the only direct ground truth for Manager Engine precision this
--     product will ever collect": we proposed this, and the person it was
--     for said no. Vocabulary is the SPEC's: 'approved' | 'disregarded'.
--     ABSENCE of a row means UNDECIDED, which is NOT disregarded (R4) —
--     no code path may bulk-write refusals the student never made.
--
-- 2 · Founder 2026-08-10: "each feedback needs to be there; full and end
--     to end and waiting; not that it appears once the other is accepted."
--     The ≤3 budget is PER TAKE, so the serve subtracts this table's count
--     for the take — a decided offer keeps its slot and nothing trickles
--     in behind it.
--
-- change_key is the offer's identity (star:<target>:<snippet> /
-- prior_take:<normalized phrase> / block:<key>:<offered take>) — UNIQUE per
-- (arc, take) so a re-tap updates in place and never double-spends. A
-- reverted star DELETES its row: undecided again, the slot returns.
--
-- lane / intervention_type make the row joinable to `intervention_arms`
-- (0253) per SPEC §6: arms are keyed (session_id=take, dimension_id=lane),
-- so PPV becomes a measurement instead of the assumption in LANE_PPV.
--
-- Idempotent; no environment dependency (CONFIG-FIRST clean).

CREATE TABLE IF NOT EXISTS intervention_decisions (
    id BIGSERIAL PRIMARY KEY,
    arc_id TEXT NOT NULL,
    take_session_id TEXT NOT NULL DEFAULT '',
    change_key TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('approved', 'disregarded')),
    lane TEXT,
    intervention_type TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (arc_id, take_session_id, change_key)
);

CREATE INDEX IF NOT EXISTS idx_intervention_decisions_arc_take
    ON intervention_decisions (arc_id, take_session_id);

-- RLS in the same migration (docs/RLS-AUDIT.md): the backend uses the
-- service-role key and bypasses this; the anon key gets nothing.
ALTER TABLE public.intervention_decisions ENABLE ROW LEVEL SECURITY;
