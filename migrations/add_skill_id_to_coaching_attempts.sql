-- Phase 7 of the snippet-CTA learning loop: per-attempt skill tag.
--
-- Each contextual coaching session is keyed by an INTENT ("charisma"
-- or "stress" today; arbitrary skill ids tomorrow). Until now that
-- intent was a runtime concept only — it picked the system prompt
-- and shaped the LLM call but was never persisted on the attempt
-- row. This column closes that gap so:
--
--   - per-skill analytics become possible (avg score on charisma vs
--     stress, weakest skill, skill-level trend),
--   - the few-shot retrieval can route per-skill examples (today it
--     already filters by snippet_type, which happens to coincide;
--     decoupling means a future skill that re-uses snippet types
--     stays cleanly partitioned),
--   - the learner mirror can speak about specific skills by name.
--
-- The value space is whatever services/skills/ registers — TEXT
-- rather than an enum because the registry is the source of truth.
-- A CHECK constraint would force a migration every time a new skill
-- is added, which defeats the point of the skill-file refactor.
--
-- Idempotent. Existing rows stay NULL (legacy attempts predate the
-- skill concept); new writes carry the id.

ALTER TABLE coaching_attempts
    ADD COLUMN IF NOT EXISTS skill_id TEXT;

CREATE INDEX IF NOT EXISTS idx_coaching_attempts_skill
    ON coaching_attempts (skill_id, score DESC)
    WHERE skill_id IS NOT NULL;

COMMENT ON COLUMN coaching_attempts.skill_id IS
    'Phase 7 — the skill registered in services/skills/ that this attempt '
    'practised ("charisma", "stress", ...). NULL on backfilled rows and '
    'on any attempt where intent resolution failed at write time.';
