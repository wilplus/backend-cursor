-- Phase 10: AI prefill + implicit-approval RLHF on snippet annotations.
--
-- Three admin-typed fields currently get no learning signal:
--   1. charisma_snippets.admin_comment       — typed from scratch.
--   2. charisma_snippets.follow_up_question  — AI-generated when comment
--                                              is saved, but the ORIGINAL
--                                              AI version is lost if the
--                                              admin edits it.
--   3. stress_snippets.coach_label_notes     — typed from scratch.
--
-- Phase 10 adds an ``ai_draft_*`` column next to each so the original
-- AI suggestion survives admin edits. At publish time we emit an
-- admin_annotation_events row comparing draft vs final — both "edited"
-- and "approved as-is" produce training signal. No new admin clicks
-- needed; publication is the implicit approval moment.
--
-- The fine-tuning export script (services/ml_finetuning_export.py)
-- already reads admin_annotation_events keyed on (section_type,
-- field_name) so this new data flows into the same JSONL pipeline
-- without any export-side changes.
--
-- Idempotent.

ALTER TABLE charisma_snippets
    ADD COLUMN IF NOT EXISTS ai_draft_admin_comment TEXT,
    ADD COLUMN IF NOT EXISTS ai_draft_admin_comment_generated_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS ai_draft_follow_up_question TEXT,
    ADD COLUMN IF NOT EXISTS ai_draft_follow_up_question_generated_at TIMESTAMPTZ;

ALTER TABLE stress_snippets
    ADD COLUMN IF NOT EXISTS ai_draft_coach_notes TEXT,
    ADD COLUMN IF NOT EXISTS ai_draft_coach_notes_generated_at TIMESTAMPTZ;

COMMENT ON COLUMN charisma_snippets.ai_draft_admin_comment IS
    'Phase 10 — AI-suggested admin comment, generated when the snippet '
    'is first extracted. Survives admin edits to admin_comment so the '
    '(draft, final) pair can be emitted at publish time for RLHF.';
COMMENT ON COLUMN charisma_snippets.ai_draft_follow_up_question IS
    'Phase 10 — original AI-generated follow-up question, frozen at '
    'generation time. follow_up_question may be edited by the admin; '
    'this column preserves the pre-edit version for RLHF comparison.';
COMMENT ON COLUMN stress_snippets.ai_draft_coach_notes IS
    'Phase 10 — AI-suggested coach notes for stress snippets. Same '
    'pattern as charisma_snippets.ai_draft_admin_comment.';

NOTIFY pgrst, 'reload schema';
