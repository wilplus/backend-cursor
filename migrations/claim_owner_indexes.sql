-- claim_owner_indexes (0474)
--
-- A guest's sign-in claim (claim_guest_owner, 0413 and after) moves every
-- row of the Take graph to the account with ~20 statements of the shape
-- `UPDATE <table> SET owner_principal_id = target WHERE owner_principal_id
-- = guest`. Twelve of those tables have no index on owner_principal_id, so
-- each UPDATE reads the whole table, inside one transaction that holds both
-- principals and the guest's Attempts locked. The founder's boot stopwatch
-- (2026-10-16) put one such claim at 4.7 s with two database calls, and
-- every other request of that boot waited behind it.
--
-- projects, v2_sessions, takes and recording_attempts already have an
-- index that starts with owner_principal_id (0338 / 0395), so they are not
-- repeated here. snippets(session_id) is indexed since 0260 (the rename
-- kept charisma_snippets' indexes). ideal_text_part is matched on user_id
-- alone by move_guest_ideal_text_parts_v1, and its only user_id indexes
-- start with arc_id, so it gets one too.
--
-- Plain CREATE INDEX, not CONCURRENTLY: the runner sends a file as one
-- statement batch, which Postgres treats as a transaction block, where
-- CONCURRENTLY is refused. Each build holds a SHARE lock on its table for
-- the duration (writes wait, reads continue); at this product's row counts
-- that is well under a second per table.
--
-- Idempotent + additive, per the standing constraint: safe to re-run.
-- Nothing dropped; no env var.

CREATE INDEX IF NOT EXISTS rejected_takes_owner_principal_idx
    ON public.rejected_takes (owner_principal_id);
CREATE INDEX IF NOT EXISTS moment_suggestions_owner_principal_idx
    ON public.moment_suggestions (owner_principal_id);
CREATE INDEX IF NOT EXISTS transcript_versions_owner_principal_idx
    ON public.transcript_versions (owner_principal_id);
CREATE INDEX IF NOT EXISTS slides_owner_principal_idx
    ON public.slides (owner_principal_id);
CREATE INDEX IF NOT EXISTS paragraphs_owner_principal_idx
    ON public.paragraphs (owner_principal_id);
CREATE INDEX IF NOT EXISTS evidence_spans_owner_principal_idx
    ON public.evidence_spans (owner_principal_id);
CREATE INDEX IF NOT EXISTS acoustic_feature_snapshots_owner_principal_idx
    ON public.acoustic_feature_snapshots (owner_principal_id);
CREATE INDEX IF NOT EXISTS candidate_sets_owner_principal_idx
    ON public.candidate_sets (owner_principal_id);
CREATE INDEX IF NOT EXISTS machine_predictions_owner_principal_idx
    ON public.machine_predictions (owner_principal_id);
CREATE INDEX IF NOT EXISTS generation_runs_owner_principal_idx
    ON public.generation_runs (owner_principal_id);
CREATE INDEX IF NOT EXISTS processing_stage_runs_owner_principal_idx
    ON public.processing_stage_runs (owner_principal_id);
CREATE INDEX IF NOT EXISTS processing_transition_events_owner_principal_idx
    ON public.processing_transition_events (owner_principal_id);
CREATE INDEX IF NOT EXISTS ideal_text_part_user_idx
    ON public.ideal_text_part (user_id);
