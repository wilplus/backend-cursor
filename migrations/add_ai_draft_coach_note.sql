-- willab Phase 4 / Prompt 2 — AI-Commentator (per-snippet coach-comment clone).
--
-- The coach's FINAL note lives in coach_snippet_drafts.note (unchanged).
-- This adds the AI DRAFT the coach sees pre-filled, mirroring the existing
-- ai_draft_admin_comment pair on charisma_snippets. It is generated once at
-- process time and FROZEN — never overwritten by coach edits — so the
-- (draft, coach-final) diff survives for the comment-clone training corpus
-- (captured at publish into admin_annotation_events, section_type='coach_note').
--
-- Idempotent (IF NOT EXISTS). No backfill — pre-existing snippets simply have
-- no draft (the coach sees a blank field, same as today).

ALTER TABLE charisma_snippets
    ADD COLUMN IF NOT EXISTS ai_draft_coach_note TEXT,
    ADD COLUMN IF NOT EXISTS ai_draft_coach_note_generated_at TIMESTAMPTZ;

COMMENT ON COLUMN charisma_snippets.ai_draft_coach_note IS
    'AI-Commentator draft of the coach note (transcript + slide{title,body} + '
    'slide stickiness). Pre-fills the coach comment field; FROZEN at generation '
    'so the (draft, coach-final) RLHF pair survives. Coach edits go to '
    'coach_snippet_drafts.note, never here.';
