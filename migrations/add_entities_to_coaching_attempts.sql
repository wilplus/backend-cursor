-- Phase 4 of the snippet-CTA learning loop: entity propagation.
--
-- The LLM evaluator already reads each coaching answer to score
-- specificity / emotional movement / engagement. Phase 4 piggybacks
-- on that same call to extract named entities the user mentioned —
-- people, situations, themes — and persists them on the attempt row.
-- Recurring entities then feed the inferred learner profile so the
-- coach can say "how did that conversation with Sarah go?" on a
-- later attempt instead of asking again who Sarah is.
--
-- Shape stored
-- ------------
--   {
--     "people":     ["Sarah", "Mom"],
--     "situations": ["Q4 review meeting"],
--     "themes":     ["imposter syndrome", "perfectionism"]
--   }
--
-- All three keys are required by the LLM schema, each is a list of
-- short strings (typically 0-5 items). Case-preserved verbatim so
-- the surface form the user used is what the coach references later
-- (the aggregator normalises case only for counting).
--
-- Why a column (not a separate table)
-- -----------------------------------
-- We never query "find all attempts that mention Sarah across the
-- whole DB" — entities are always read in the context of a specific
-- user's recent window. A per-row JSONB blob is the right granularity:
-- cheap to write, no join cost for the aggregator, no migration when
-- the entity shape evolves.
--
-- Idempotent.

ALTER TABLE coaching_attempts
    ADD COLUMN IF NOT EXISTS entities JSONB;

COMMENT ON COLUMN coaching_attempts.entities IS
    'Phase 4 — entities extracted by the LLM evaluator on the same call '
    'that scores the exchange. Shape: {people: [...], situations: [...], '
    'themes: [...]}. NULL on attempts written before Phase 4 shipped '
    '(backfilled rows from Phase 2 and any rows where extraction failed).';
