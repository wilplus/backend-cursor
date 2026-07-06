-- willab — coach transcript correction (founder 2026-07-06: a real new
-- coach-authored artifact, distinct from the immutable raw Whisper transcript).
--
-- Lives on coach_snippet_drafts (the SAME USER-lane table as `note`/`tag` —
-- split-sink §2: this is coach-authored, user-facing content, not the
-- private direction-label lane). Freely re-editable, same semantics as
-- `note` (not write-once). Assembled into insights_payload.snippet_notes at
-- publish (only when `surfaced`), exactly like `note` — no new visibility
-- mechanism needed.
--
-- FREE TIER (founder 2026-07-06): once the coach saves + surfaces it, this
-- renders to the user UNCONDITIONALLY — never gated by arc payment. Only the
-- coach-corrected IDEAL TEXT, the breakthroughs LIST, the game, and the
-- snippet library are paid deliverables.
ALTER TABLE coach_snippet_drafts
    ADD COLUMN IF NOT EXISTS transcript_corrected TEXT NULL;

-- Rollback (manual):
--   ALTER TABLE coach_snippet_drafts DROP COLUMN IF EXISTS transcript_corrected;
