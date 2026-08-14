-- SPEC §12.3 (founder 2026-08-14): the Intent Ledger. "Never re-litigated"
-- must survive LLM phrase drift, so a decision also carries WHERE it was
-- made (slide_index — the only cross-take location key) and WHICH CLASS of
-- suggestion it decided (lane_class — the deterministic Clarity/Flow/
-- Style/Delivery mapping, computed in services/ideal_decision_ledger).
-- The phrase key stays for the bake and history display; these two columns
-- are what the generation gate blocks on. Additive + idempotent; old rows
-- (NULL/NULL) simply never match an intent key — phrase behavior unchanged.
ALTER TABLE public.ideal_decision_ledger
  ADD COLUMN IF NOT EXISTS slide_index integer NULL;
ALTER TABLE public.ideal_decision_ledger
  ADD COLUMN IF NOT EXISTS lane_class text NULL;
COMMENT ON COLUMN public.ideal_decision_ledger.slide_index IS
  'Deck slide the decided snippet was spoken on (cross-take location; §12.3)';
COMMENT ON COLUMN public.ideal_decision_ledger.lane_class IS
  'Deterministic suggestion class (clarity/flow/style/delivery; §12.3)';
