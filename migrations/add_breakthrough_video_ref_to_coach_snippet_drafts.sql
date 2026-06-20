-- willab — per-snippet coach BREAKTHROUGH VIDEO (USER lane).
--
-- A coach attaches one short explanatory video to a breakthrough snippet
-- during review. It's a public URL, surfaced on the user readout next to the
-- breakthrough badge ("🥳 …you turned your stress into charisma!"). The
-- explanation TEXT is the coach note itself (no new text field) — this column
-- stores only the video URL.
--
-- Same lane / same path as note/tag: folded into
-- v2_sessions.insights_payload.snippet_notes at publish (_assemble_insights_
-- from_drafts → validate_insights_payload), then surfaced per snippet by
-- build_readout_from_session as the top-level `breakthrough_video_ref`.
-- Idempotent; nullable; never leaks pre-publish (insights_payload is written
-- only at publish).
ALTER TABLE coach_snippet_drafts
    ADD COLUMN IF NOT EXISTS breakthrough_video_ref text;
