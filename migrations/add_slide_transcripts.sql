-- willab #A (2026-06-22) — per-slide COMPLETE 1:1 transcript on the session.
--
-- The take viewer's per-slide transcript was built from only the ~10 SELECTED
-- salient snippets, so slides whose speech wasn't in a selected snippet
-- (typically the quiet first slide) came back empty → "the app doesn't catch
-- the first slide / everything is shifted". We now bucket the WHOLE-recording
-- Whisper word list by the slide-click timeline at record time and persist the
-- result here, so every slide shows exactly what was said while it was on
-- screen (1:1), and the list endpoint reads it directly (no per-request word
-- processing).
--
-- Shape: JSONB array, one entry per deck slide, in index order:
--   [{ "index": int, "transcript": str,
--      "start_offset_ms": int|null, "duration_ms": int|null }, ...]
--
-- Nullable + additive. set_session_slide_transcripts degrades gracefully if
-- this column is missing (recording is never blocked); the take viewer falls
-- back to the per-snippet split. Idempotent — safe to re-run.

ALTER TABLE public.v2_sessions
    ADD COLUMN IF NOT EXISTS slide_transcripts JSONB NULL;

-- Rollback (manual):
--   ALTER TABLE public.v2_sessions DROP COLUMN IF EXISTS slide_transcripts;
