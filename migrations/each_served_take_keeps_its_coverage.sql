-- 0437 · each served Take keeps its coverage and its lane outcomes
-- (build plan D-ML-5; contract 24c, 24d, 25; N32.4; ledger A166; the V4
-- exit gate "coverage holds").
--
-- WHY. Contract 24c sets the coverage ladder on selection: of the Slides
-- that yield at least one valid block, at least 70% on Take 1, 80% on Take
-- 2 and 100% from Take 3. 24d makes it a target, never a floor on output:
-- a shortfall is a defect to investigate. Contract 25 types an honest empty
-- verbal lane as `no_defensible_candidate`. Until now all three lived only
-- in the in-memory service frame and one log line per Take
-- (services/mlc3_first_client_feedback.py `_log_coverage`): nothing could
-- be counted over time, and the V4 exit gate needs "coverage holds" as
-- data, not as a log search.
--
-- WHAT. One row per Take V3 served: the policy version that served it, the
-- Take's index, how many Slides formed at least one valid block, how many
-- carry a selected Confident Voice item, the floor for that Take, whether
-- the floor is met, the uncovered Slides by index with their typed reasons,
-- and each lane's typed outcome (`selected` or `no_defensible_candidate`).
-- Counts, Slide indexes and type names only: no transcript, no candidate
-- text, no score. Written by the serve path, best-effort (a failed write
-- never blocks serving: LIVE LOOP); a shortfall also raises a warning
-- event there (24d).
--
-- NEVER IN A USER PAYLOAD (AC-9): no route reads this table. RLS is on with
-- no policy and the browser roles hold nothing; the app writes it with the
-- service key. Purged with the Take (services/data_purge_registry.py).
--
-- Additive; idempotent; no env var; no lock on an existing table.
-- Rollback (a new forward migration): drop the table.

BEGIN;

CREATE TABLE IF NOT EXISTS public.take_feedback_coverage (
    take_session_id     text             PRIMARY KEY,
    project_id          text             NULL,
    take_index          integer          NULL,
    policy_version      text             NOT NULL,
    slides_with_blocks  integer          NOT NULL,
    slides_covered      integer          NOT NULL,
    required_floor      double precision NOT NULL,
    floor_met           boolean          NOT NULL,
    uncovered           jsonb            NOT NULL DEFAULT '[]'::jsonb,
    lane_outcomes       jsonb            NOT NULL DEFAULT '{}'::jsonb,
    first_served_at     timestamptz      NOT NULL DEFAULT now(),
    last_served_at      timestamptz      NOT NULL DEFAULT now(),
    CONSTRAINT take_feedback_coverage_counts CHECK (
        slides_with_blocks >= 0
        AND slides_covered >= 0
        AND slides_covered <= slides_with_blocks),
    CONSTRAINT take_feedback_coverage_floor_range CHECK (
        required_floor >= 0 AND required_floor <= 1),
    CONSTRAINT take_feedback_coverage_shapes CHECK (
        jsonb_typeof(uncovered) = 'array'
        AND jsonb_typeof(lane_outcomes) = 'object')
);
CREATE INDEX IF NOT EXISTS take_feedback_coverage_project_idx
    ON public.take_feedback_coverage (project_id) WHERE project_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS take_feedback_coverage_shortfall_idx
    ON public.take_feedback_coverage (first_served_at) WHERE NOT floor_met;
ALTER TABLE public.take_feedback_coverage ENABLE ROW LEVEL SECURITY;
COMMENT ON TABLE public.take_feedback_coverage IS
    'One row per Take V3 served (0437, D-ML-5; contract 24c, 24d, 25): the '
    'policy version, Slides with at least one valid block, Slides covered, '
    'the floor and whether it is met, uncovered Slides with typed reasons, '
    'and each lane''s typed outcome including no_defensible_candidate. '
    'Internal only, never in a user payload (AC-9). Purged with the Take.';

-- Browser roles get nothing, whatever default privileges the schema
-- carries: RLS with no policy already returns no row, and this makes the
-- boundary explicit. The app writes it with the service key.
DO $$
DECLARE
    v_role text;
BEGIN
    REVOKE ALL ON TABLE public.take_feedback_coverage FROM PUBLIC;
    FOREACH v_role IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = v_role) THEN
            EXECUTE format('REVOKE ALL ON TABLE public.take_feedback_coverage FROM %I', v_role);
        END IF;
    END LOOP;
END $$;

COMMIT;
