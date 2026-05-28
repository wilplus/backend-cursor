-- Phase 18.x: immutable AI-draft baseline for session_kpi_narrative.
--
-- The user-facing narrative the LLM writes during finalize /
-- compute-metrics already lives at
-- v2_sessions.ai_task_alignment_comment (legacy column name; the
-- API surfaces it as `session_kpi_narrative`). That column is
-- EDITABLE — admins inline-edit it from the Performance summary
-- card on Tab 1 via PATCH /v2/admin/sessions/<id>/kpi-narrative.
--
-- The trivial-edit gate (services.utils.changed_word_tokens) on
-- that PATCH endpoint needs an IMMUTABLE baseline to diff
-- against — "how much did the admin diverge from the AI", not
-- "from the last save". Hence this column:
--
--   session_kpi_narrative_ai_draft
--     Pinned at generation time. Set ONLY by the narrative
--     generator paths (services.session_kpi_narrative +
--     compute-metrics re-runs). Admin edits never touch it.
--     On Compute Metrics re-runs the LLM overwrites BOTH the
--     editable column AND this one — a regenerated narrative is
--     the new baseline.
--
-- Legacy sessions where the LLM ran before this column existed:
-- the column stays NULL. The gate's empty-baseline bypass treats
-- NULL as "no draft to diff against → save freely, no gate" so
-- admins can edit pre-rollout sessions without friction.
--
-- Idempotent.

ALTER TABLE v2_sessions
    ADD COLUMN IF NOT EXISTS session_kpi_narrative_ai_draft TEXT;

COMMENT ON COLUMN v2_sessions.session_kpi_narrative_ai_draft IS
    'Phase 18.x — immutable AI draft of the session KPI narrative '
    'pinned at generation time. Diff baseline for the trivial-edit '
    'gate on PATCH /v2/admin/sessions/<id>/kpi-narrative. NULL on '
    'legacy sessions where the LLM ran before this column existed '
    '(gate bypasses NULL baseline). Admin edits NEVER touch this '
    'column; only the narrative generator overwrites it on (re-)'
    'compute-metrics.';

NOTIFY pgrst, 'reload schema';
