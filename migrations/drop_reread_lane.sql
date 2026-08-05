-- Delete the historical IDEAL-TEXT RE-READ sessions — founder 2026-08-05.
--
-- "Read out loud" (reading your settled ideal text back into the mic) is
-- retired: it brought no value to the coach or the user. The application
-- stopped accepting these in the same release that added this file
-- (routes/v2/lab_recording.py refuses a read without paired_snippet_id
-- with 422), so by the time this runs no NEW ones can appear.
--
-- ⚠️  THIS DESTROYS DATA, PERMANENTLY AND ON PURPOSE. ⚠️
--
--   The founder's explicit instruction (2026-08-05): "I want the historical
--   read sessions completely removed. We are not keeping dead data. I
--   understand this permanently destroys the old read-out-loud audio
--   history, and that is exactly what I want."
--
--   Every recording a user made by reading their ideal text aloud goes,
--   along with everything keyed to those sessions. There is no undo and no
--   backup step built in. If you want one, take it BEFORE running this.
--
-- ─────────────────────────────────────────────────────────────────────────
-- ⚠️  SCOPE CORRECTION — READ THIS BEFORE RUNNING. ⚠️
--
--   The founder asked for the columns (recording_kind, paired_session_id)
--   to be dropped too. They are NOT dropped here, and this is deliberate.
--
--   Those columns carry a SECOND, unrelated live feature: the DELIVERY-STAR
--   snippet re-record ("say it stronger" — re-record one snippet with a
--   star's feedback applied). It posts recording_kind='read' with a
--   paired_snippet_id, and it is reachable today from the ideal-text
--   overlay's moment sheet. Dropping the columns would silently break it,
--   and the coach would lose the folded re-recorded snippets with it.
--
--   The founder did not ask to remove delivery stars. Rather than destroy a
--   feature that was never in scope, this migration deletes ONLY the
--   ideal-text re-reads — the thing that was actually retired — and leaves
--   the columns in place.
--
--   TO ALSO DROP THE COLUMNS: delivery stars must be retired first (FE
--   services/api/reRecordSnippet.ts, the MomentSheet onReRecord handler, and
--   the coach packet's read fold). That is a separate decision and a
--   separate migration. Ask the founder before assuming it.
-- ─────────────────────────────────────────────────────────────────────────
--
-- NOT RUN AUTOMATICALLY. "On main" ≠ "run in prod" — the founder runs this
-- by hand.
--
-- Idempotent; safe to re-run.

BEGIN;

-- The ideal-text re-reads, and ONLY those: recording_kind='read' with the
-- read_target='ideal_text' tag the retired button stamped on its intake
-- context. A delivery-star re-record is also a 'read' but carries
-- paired_snippet_id instead and no read_target, so it is untouched here.
--
-- Dependents are NOT deleted explicitly: every FK pointing at
-- v2_sessions(id) is declared ON DELETE CASCADE or ON DELETE SET NULL
-- (charisma_snippets, recording_reviews, admin_annotations_log, the
-- recordings.session_v2_id link, …), so Postgres resolves them. Listing
-- them by hand would be one rename away from silently missing a table.
DELETE FROM public.v2_sessions
 WHERE recording_kind = 'read'
   AND intake_context ->> 'read_target' = 'ideal_text';

-- The read-only force-alignment table. Only ever populated for ideal-text
-- re-reads — services/read_alignment.py returned early unless
-- read_target='ideal_text', and that module is deleted in this release. With
-- no ideal-text re-reads left it can only ever be empty.
DROP TABLE IF EXISTS public.read_alignments;

COMMIT;
