-- Phase 17.1: wire the Phase 17 drift guard at publish time.
--
-- detect_classifier_drift (services/metrics_v2.py) was added as a
-- primitive in Phase 17. This migration gives it a place to write.
-- When the B6 Master Score and the D1/D2 classifier confidence
-- disagree by more than 40 percentage points on the same session,
-- the session is flagged here instead of being silently published
-- with potentially glitched numbers.
--
--   needs_admin_review  BOOLEAN  — TRUE when drift > threshold.
--                                 Default FALSE. Cleared by the next
--                                 compute-metrics run if drift
--                                 resolves (e.g. admin re-extracts
--                                 a snippet with better metrics).
--   drift_diagnostic    JSONB    — full output of
--                                 detect_classifier_drift:
--                                   { performance_score,
--                                     classifier_confidence,
--                                     deviation, threshold,
--                                     needs_admin_review, reason }
--                                 Lets admins see WHY a session got
--                                 flagged without rerunning the
--                                 compute. NULL when the check
--                                 hasn't run.
--
-- Soft-block behaviour: the publish flow doesn't refuse to ship a
-- flagged session — it just stamps the flag + writes the diagnostic.
-- Admin surfaces can render a banner; future Phase 17.2 can add a
-- hard block flag-gated on a separate env var if you want to make
-- the review mandatory.
--
-- Idempotent.

ALTER TABLE v2_sessions
    ADD COLUMN IF NOT EXISTS needs_admin_review BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS drift_diagnostic JSONB;

-- Most-common query: "show me everything that needs review across
-- all users." Partial index — only flagged rows are in it, so the
-- index stays tiny.
CREATE INDEX IF NOT EXISTS idx_v2_sessions_needs_review
    ON v2_sessions (created_at DESC)
    WHERE needs_admin_review = TRUE;

COMMENT ON COLUMN v2_sessions.needs_admin_review IS
    'Phase 17.1 — TRUE when the B6 Master Score and the D1/D2 '
    'classifier confidence disagreed by more than the configured '
    'threshold (default 0.40) at compute-metrics time. Flips back '
    'to FALSE on the next compute-metrics run if drift resolves.';
COMMENT ON COLUMN v2_sessions.drift_diagnostic IS
    'Phase 17.1 — diagnostic blob from detect_classifier_drift: '
    '{performance_score, classifier_confidence, deviation, '
    'threshold, needs_admin_review, reason}. NULL until the check '
    'has run on this session.';

NOTIFY pgrst, 'reload schema';
