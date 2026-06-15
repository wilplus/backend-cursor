-- willab — pre-recording feeling capture (U10 wiring; correlation input).
--
-- The FE asks "how are you feeling about this one?" before a take and the user
-- names a state (nervous/excited/calm/unsure). Until now that answer lived only
-- in the browser (localStorage) "under the BE freeze". This is the BE sink it
-- POSTs to once the freeze lifts.
--
-- SPLIT-SINK / AC-9: this is the user NAMING their own state — NEVER a score,
-- verdict, or judgement, and NEVER shown back to the user. It is stored
-- PRIVATELY and factored ONLY at the audit stage (correlate felt-state ×
-- performance — the audit's "Performance under feeling"). Mirrors the privacy
-- posture of training_labels.
--
-- Grain: one row per captured feeling, attached to the recording/take it
-- precedes. user_id is nullable (lab takes start as unclaimed guest sessions;
-- attribute via session_id on claim, OR via user_id when the take was made
-- signed-in). Idempotent; safe to re-run.
CREATE TABLE IF NOT EXISTS recording_feelings (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      UUID,                       -- nullable: guest take until claim
    session_id   UUID NOT NULL,
    recording_id UUID,
    arc_id       UUID,                        -- explore-arc context (optional)
    take_index   INTEGER,                     -- which take in the arc (optional)
    feeling      TEXT NOT NULL
                 CHECK (feeling IN ('nervous', 'excited', 'calm', 'unsure')),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- The audit correlation reads "this user's feelings"; the claim path reads
-- "this session's feeling".
CREATE INDEX IF NOT EXISTS idx_recording_feelings_user
    ON recording_feelings (user_id);
CREATE INDEX IF NOT EXISTS idx_recording_feelings_session
    ON recording_feelings (session_id);
CREATE INDEX IF NOT EXISTS idx_recording_feelings_arc
    ON recording_feelings (arc_id);
