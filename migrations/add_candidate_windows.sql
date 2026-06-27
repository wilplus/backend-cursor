-- willab — candidate-window capture (automation-audit fix #1: "offered vs chosen").
--
-- The Lab pipeline scores a GENEROUS pool of candidate windows per recording
-- (~up to SALIENCE_CANDIDATE_POOL), narrows to the ~NOTABLE_POOL_SIZE "notable"
-- set, surfaces the best <=SEGMENT_MAX_SNIPPETS to the coach (charisma_snippets),
-- and DISCARDS the rest in-memory. This table preserves the FULL pool + each
-- window's raw feature vector + WHICH cut it made, so the SELECTION step (which
-- moments to surface) can one day be learned. Without it the offered-but-dropped
-- windows are lost on every session, irreversibly.
--
-- SPLIT-SINK / AC-9: training-bound ONLY. Never read by any user or coach
-- surface, never serialized to a user. (Storing != surfacing.)
--
-- FENCE (services/snippet_salience.py — read it): the transient salience /
-- control SELECTION score is NOT stored here. We store the raw ACOUSTIC feature
-- vector (`metrics`, from which any score is recomputable) plus the heuristic's
-- PROVISIONAL decision (`notable`/`surfaced`/`surfaced_rank`) and chronological
-- position. `surfaced` is the HEURISTIC's call, NOT a coach-truth label and NOT
-- a validation draw: any future validation/anchor sample MUST be drawn
-- INDEPENDENTLY over the raw pool (random/stratified), never "WHERE surfaced".
--
-- Idempotent; append-only. Safe to re-run.
CREATE TABLE IF NOT EXISTS candidate_windows (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id         UUID NOT NULL,
    recording_id       UUID,
    user_id            UUID,                  -- speaker; may be NULL on authed
                                              -- direct upload today (join via
                                              -- session_id -> v2_sessions.user_id)
    start_offset_ms    INTEGER NOT NULL,      -- window start in the parent audio
    duration_ms        INTEGER,
    pool_position      INTEGER,               -- chronological index in the pool
    notable            BOOLEAN NOT NULL DEFAULT FALSE,  -- made the activation pool
    surfaced           BOOLEAN NOT NULL DEFAULT FALSE,  -- shown to the coach (<=10)
    surfaced_rank      INTEGER,               -- overall rank IF surfaced, else NULL
    snippet_id         UUID,                  -- charisma_snippets.id IF surfaced
                                              -- (joins the coach lane: labels/notes)
    metrics            JSONB,                 -- raw acoustic feature vector (NO score)
    transcript         TEXT,
    heuristic_version  TEXT,                  -- which SELECTOR produced this pool
    features_version   TEXT,                  -- which FEATURE-EXTRACTOR produced
                                              -- `metrics` (drifts independently of
                                              -- the selector — keep the corpus
                                              -- segmentable by extractor gen)
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Idempotent capture: one row per (recording, window). A re-process no-ops
-- (ON CONFLICT DO NOTHING) — so the FIRST capture is frozen ("what was offered
-- at the time"); snippet_id is valid against that run's charisma_snippets. The
-- dedup guarantee depends on recording_id being non-NULL (it always is on the
-- Lab path); a NULL-recording row would not dedup (Postgres treats NULLs as
-- distinct). `surfaced_rank` blends an acoustic + a slide-delivery signal; only
-- the acoustic `metrics` are captured here (v1 limitation, documented).
CREATE UNIQUE INDEX IF NOT EXISTS idx_candidate_windows_recording_window
    ON candidate_windows (recording_id, start_offset_ms);

CREATE INDEX IF NOT EXISTS idx_candidate_windows_session
    ON candidate_windows (session_id);
CREATE INDEX IF NOT EXISTS idx_candidate_windows_user
    ON candidate_windows (user_id);

-- Rollback (manual):
--   DROP TABLE IF EXISTS candidate_windows;
