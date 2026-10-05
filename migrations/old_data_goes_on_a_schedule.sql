-- 0423 · Old data goes on a schedule (founder 2026-10-05: decisions log
--        N48.4 Q16 A, "go with wave 3"; N45 Q3b and Q4; N46; retention
--        schedule v1.0 §1, carried over unchanged by v1.2 and v1.3).
--
-- The scheduled clean-up the signed schedule promises and nothing yet did:
--
--   1. an unclaimed guest goes 30 days after it was created, recordings and
--      all (a guest who signed up is claimed and is never counted);
--   2. audio goes 12 months after its last use, and its voice measurements
--      go with it, never after it (schedule §1). Last use is the later of
--      when the recording was made and the last change to any project of
--      its owner; a claimed guest's recordings count under the account that
--      claimed them (N46);
--   3. technical logs go 90 days after creation: exactly the five tables the
--      report names, nothing else.
--
-- ONE DEFINITION OF WHAT IS DUE. Everything below `retention_report_v1`
-- decides what is due, and three readers use it and nothing else:
-- scripts/retention_report.sql (the founder's read-only report), a dry run
-- and a live run (services/retention_cleaner.py). Their numbers cannot
-- disagree because there is nothing for them to disagree about. The
-- definitions are the report's own (2026-10-05), with four refinements a
-- real run needs, each of which can only make a number smaller:
--
--   * audio counts as live only while no deletion event names it. The
--     report read `deleted_at`, which the append-only audio row never gets:
--     a deletion is a row in processing_audio_object_deletion_events
--     (0312), the test every other reader of these objects already uses;
--   * a guest whose erasure finished is erased, and is not counted again;
--   * audio of a person (or a project) with an erasure under way belongs
--     to that erasure, and this clean-up stays out of its way;
--   * a processing_jobs row that deletion evidence points at is kept (and
--     counted on its own line): deleting it would rewrite that evidence
--     (processing_stage_runs, processing_transition_events: ON DELETE SET
--     NULL), and retained evidence is never touched.
--
-- WHAT A LIVE RUN DOES, AND WHERE. This file holds the selection, the
-- evidence and the column-level erasure; it holds no row removal, because
-- the migration runner refuses a file that does (scripts/migrate.py, and
-- MIGRATE_ON_BOOT=1 would then block every later migration). Rows are
-- removed by services/retention_cleaner.py through PostgREST, from the
-- relations its reviewed registry names, as the account purge removes
-- rows (services/data_purge.py):
--
--   * rule 1 opens a `retention_expiry` request for the guest and runs the
--     account purge on it (request_phase1_purge_v1, DataPurgeOrchestrator):
--     the same inventory, byte-hash-verified object deletion, tombstones,
--     retention rules and review stops as any erasure. An erasure that
--     stopped for review is left for a person and never run again, as
--     0422's completion run leaves one. Being a purge, rule 1 runs only
--     while the web service has PHASE1_PURGE_EXECUTION_ENABLED, the purge
--     kill switch the operator script and 0422's completion run obey;
--   * rule 2 claims one recording at a time. The claim empties the Take's
--     voice measurements first (the columns listed in
--     retention_measurement_stores_v1; the rows it lists go next, from the
--     service), then the service deletes the object by its byte hash and
--     settles the claim with a deletion event naming this run. Measurements
--     first: if anything fails after them, the recording outlives its
--     measurements, which the schedule allows, and never the reverse;
--   * rule 3 removes the due rows of the five logs by id, in batches.
--
-- THE RUN RECORD. retention_cleaner_runs keeps every run: dry or live,
-- what was asked for and what ran, any refusal, the report's lines at the
-- start (`due`), what a live run did (`done`), the lines still due at its
-- end (`left_due`), and when. A finished record never changes again.
-- retention_cleaner_audio_claims keeps each recording a live run claimed and
-- how it ended.
--
-- THREE NARROW OPENINGS IN EXISTING GUARDS, each for a live run only:
--   * processing_audio_object_deletion_events.purge_request_id may be NULL
--     when the new retention_run_id names the run instead (exactly one of
--     the two, by CHECK). Existing rows are untouched;
--   * reject_canonical_feedback_mutation lets a running live retention run
--     empty `features` on acoustic_feature_snapshots of the one Take whose
--     recording it has claimed -- the column the lineage tombstone (0379)
--     erases, nothing the receipt keeps;
--   * reject_mlc3_general_service_mutation_v1 lets a row of
--     mlc3_service_backpressure_events older than 90 days be removed, and
--     service_role may remove one (it can read only id and created_at).
-- Both functions are patched in place from their installed bodies, as 0418
-- and 0421 patch theirs, so nothing production carries is lost.
--
-- NOTHING RUNS FROM THIS FILE. It creates two empty tables, functions and
-- three guard openings, and changes no existing row. A live run also needs
-- RETENTION_CLEANER_LIVE = True in services/retention_cleaner.py, which the
-- founder sets in a reviewed change after reading a dry run (N45).
--
-- Idempotent: IF NOT EXISTS, CREATE OR REPLACE, guarded constraints, and
-- the two patches skip a body that already carries their marker.

BEGIN;

-- ── 1. The run record ────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.retention_cleaner_runs (
    id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    requested_mode  text        NOT NULL CHECK (requested_mode IN ('dry_run', 'live')),
    mode            text        NOT NULL CHECK (mode IN ('dry_run', 'live')),
    state           text        NOT NULL DEFAULT 'running' CHECK (state IN (
        'running', 'completed', 'refused', 'failed', 'interrupted')),
    refusal         text        NULL,
    as_of           timestamptz NOT NULL,
    cleaner_version text        NOT NULL,
    due             jsonb       NOT NULL DEFAULT '[]'::jsonb,
    done            jsonb       NOT NULL DEFAULT '{}'::jsonb,
    left_due        jsonb       NULL,
    error_code      text        NULL,
    started_at      timestamptz NOT NULL DEFAULT clock_timestamp(),
    finished_at     timestamptz NULL,
    CONSTRAINT retention_cleaner_runs_live_was_asked
        CHECK (mode = 'dry_run' OR requested_mode = 'live'),
    CONSTRAINT retention_cleaner_runs_refusal_named
        CHECK ((state = 'refused') = (refusal IS NOT NULL)),
    CONSTRAINT retention_cleaner_runs_finish_recorded
        CHECK ((state = 'running') = (finished_at IS NULL))
);
ALTER TABLE public.retention_cleaner_runs ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.retention_cleaner_runs
    FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT ON public.retention_cleaner_runs TO service_role;
CREATE INDEX IF NOT EXISTS retention_cleaner_runs_started_idx
    ON public.retention_cleaner_runs (started_at DESC);
-- One live run at a time.
CREATE UNIQUE INDEX IF NOT EXISTS retention_cleaner_runs_one_live_idx
    ON public.retention_cleaner_runs ((true))
    WHERE mode = 'live' AND state = 'running';
COMMENT ON TABLE public.retention_cleaner_runs IS
    'One row per run of the scheduled clean-up (0423): dry or live, the '
    'report''s lines at the start (due), what a live run did (done), the '
    'lines still due at its end (left_due). Counts only; nothing about a '
    'person. Kept, and final once finished.';

CREATE TABLE IF NOT EXISTS public.retention_cleaner_audio_claims (
    run_id          uuid        NOT NULL REFERENCES
        public.retention_cleaner_runs(id) ON DELETE RESTRICT,
    audio_object_id uuid        NOT NULL REFERENCES
        public.processing_audio_objects(id) ON DELETE RESTRICT,
    claimed_at      timestamptz NOT NULL DEFAULT clock_timestamp(),
    measurements    jsonb       NOT NULL DEFAULT '{}'::jsonb,
    outcome         text        NULL CHECK (outcome IN (
        'deleted', 'already_absent', 'failed')),
    error_code      text        NULL,
    settled_at      timestamptz NULL,
    PRIMARY KEY (run_id, audio_object_id),
    CONSTRAINT retention_cleaner_audio_claims_settled
        CHECK ((outcome IS NULL) = (settled_at IS NULL))
);
ALTER TABLE public.retention_cleaner_audio_claims ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.retention_cleaner_audio_claims
    FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT ON public.retention_cleaner_audio_claims TO service_role;
COMMENT ON TABLE public.retention_cleaner_audio_claims IS
    'Each recording a live clean-up run claimed (0423): the voice '
    'measurements it emptied first, and how the deletion of the recording '
    'ended. The deletion itself is the event in '
    'processing_audio_object_deletion_events that names the run.';

CREATE OR REPLACE FUNCTION public.guard_retention_cleaner_run_v1()
RETURNS trigger LANGUAGE plpgsql SET search_path = public
AS $$
BEGIN
    IF TG_OP <> 'UPDATE' THEN
        RAISE EXCEPTION 'RETENTION_RUN_RECORD_IS_KEPT';
    END IF;
    IF OLD.finished_at IS NOT NULL
       OR NEW.id <> OLD.id OR NEW.requested_mode <> OLD.requested_mode
       OR NEW.mode <> OLD.mode OR NEW.as_of <> OLD.as_of
       OR NEW.cleaner_version <> OLD.cleaner_version
       OR NEW.started_at <> OLD.started_at OR NEW.due <> OLD.due THEN
        RAISE EXCEPTION 'RETENTION_RUN_RECORD_IS_FINAL';
    END IF;
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION public.guard_retention_cleaner_run_v1()
    FROM PUBLIC, anon, authenticated;
DROP TRIGGER IF EXISTS retention_cleaner_runs_guard
    ON public.retention_cleaner_runs;
CREATE TRIGGER retention_cleaner_runs_guard
    BEFORE UPDATE OR DELETE ON public.retention_cleaner_runs
    FOR EACH ROW EXECUTE FUNCTION public.guard_retention_cleaner_run_v1();

CREATE OR REPLACE FUNCTION public.guard_retention_cleaner_audio_claim_v1()
RETURNS trigger LANGUAGE plpgsql SET search_path = public
AS $$
BEGIN
    IF TG_OP <> 'UPDATE' THEN
        RAISE EXCEPTION 'RETENTION_CLAIM_IS_KEPT';
    END IF;
    IF OLD.outcome IS NOT NULL
       OR NEW.run_id <> OLD.run_id
       OR NEW.audio_object_id <> OLD.audio_object_id
       OR NEW.claimed_at <> OLD.claimed_at THEN
        RAISE EXCEPTION 'RETENTION_CLAIM_IS_FINAL';
    END IF;
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION public.guard_retention_cleaner_audio_claim_v1()
    FROM PUBLIC, anon, authenticated;
DROP TRIGGER IF EXISTS retention_cleaner_audio_claims_guard
    ON public.retention_cleaner_audio_claims;
CREATE TRIGGER retention_cleaner_audio_claims_guard
    BEFORE UPDATE OR DELETE ON public.retention_cleaner_audio_claims
    FOR EACH ROW EXECUTE FUNCTION public.guard_retention_cleaner_audio_claim_v1();

-- A recording's deletion event names the act that deleted it: a purge
-- request (0312) or, from this file on, a retention run. Exactly one.
ALTER TABLE public.processing_audio_object_deletion_events
    ADD COLUMN IF NOT EXISTS retention_run_id uuid NULL
        REFERENCES public.retention_cleaner_runs(id) ON DELETE RESTRICT;
ALTER TABLE public.processing_audio_object_deletion_events
    ALTER COLUMN purge_request_id DROP NOT NULL;
DO $deletion_event_names_its_act$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'processing_audio_object_deletion_events_one_act'
           AND conrelid = 'public.processing_audio_object_deletion_events'::regclass
    ) THEN
        ALTER TABLE public.processing_audio_object_deletion_events
            ADD CONSTRAINT processing_audio_object_deletion_events_one_act
            CHECK (num_nonnulls(purge_request_id, retention_run_id) = 1);
    END IF;
END
$deletion_event_names_its_act$;

-- ── 2. What is due: the one definition ──────────────────────────────────

-- The founder's three periods, and nowhere else.
CREATE OR REPLACE FUNCTION public.retention_cutoffs_v1(p_as_of timestamptz)
RETURNS TABLE (guest_cut timestamptz, audio_cut timestamptz, log_cut timestamptz)
LANGUAGE sql STABLE SET search_path = public
AS $$
    SELECT p_as_of - interval '30 days',
           p_as_of - interval '12 months',
           p_as_of - interval '90 days'
$$;

-- Does this relation (and, when named, this column) exist here? A store a
-- database lacks holds nothing of anyone's.
CREATE OR REPLACE FUNCTION public.retention_column_present_v1(
    p_relation text, p_column text
) RETURNS boolean
LANGUAGE sql STABLE SET search_path = public
AS $$
    SELECT to_regclass(format('public.%I', p_relation)) IS NOT NULL
       AND (p_column IS NULL OR EXISTS (
           SELECT 1 FROM pg_attribute a
            WHERE a.attrelid = to_regclass(format('public.%I', p_relation))
              AND a.attname = p_column AND a.attnum > 0
              AND NOT a.attisdropped))
$$;

-- Audio that still exists: no deletion recorded for it. The owner is the
-- account that claimed a guest, or the acquirer itself.
CREATE OR REPLACE FUNCTION public.retention_live_audio_v1(
    p_audio_object_id uuid DEFAULT NULL,
    p_owner_principal_id uuid DEFAULT NULL
) RETURNS TABLE (
    audio_object_id uuid, take_id uuid, acquisition_principal_id uuid,
    owner_principal_id uuid, project_id uuid, created_at timestamptz
)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = public
AS $$
#variable_conflict use_column
BEGIN
    RETURN QUERY
    SELECT o.id, o.recording_attempt_id, o.acquisition_principal_id,
           COALESCE(op.claimed_by_owner_principal_id, op.id),
           pra.project_id, o.created_at
      FROM public.processing_audio_objects o
      JOIN public.owner_principals op ON op.id = o.acquisition_principal_id
      JOIN public.processing_recording_attempts pra
        ON pra.id = o.recording_attempt_id
     WHERE (p_audio_object_id IS NULL OR o.id = p_audio_object_id)
       AND (p_owner_principal_id IS NULL
            OR COALESCE(op.claimed_by_owner_principal_id, op.id)
               = p_owner_principal_id)
       AND o.deleted_at IS NULL
       AND NOT EXISTS (
           SELECT 1 FROM public.processing_audio_object_deletion_events d
            WHERE d.audio_object_id = o.id);
END;
$$;

-- Rule 1. Unclaimed guests older than 30 days that are not yet erased.
CREATE OR REPLACE FUNCTION public.retention_due_guests_v1(
    p_as_of timestamptz, p_principal_id uuid DEFAULT NULL
) RETURNS TABLE (principal_id uuid)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = public
AS $$
#variable_conflict use_column
BEGIN
    RETURN QUERY
    SELECT p.id
      FROM public.owner_principals p, public.retention_cutoffs_v1(p_as_of) c
     WHERE (p_principal_id IS NULL OR p.id = p_principal_id)
       AND p.user_id IS NULL
       AND p.guest_secret_hash IS NOT NULL
       AND p.claimed_at IS NULL
       AND p.created_at < c.guest_cut
       AND NOT EXISTS (
           SELECT 1 FROM public.owner_claim_events e
            WHERE e.source_owner_principal_id = p.id)
       AND NOT EXISTS (
           SELECT 1 FROM public.data_purge_requests r
            WHERE r.acquisition_principal_id = p.id
              AND r.project_id IS NULL AND r.state = 'done');
END;
$$;

-- Rule 2. Live audio made more than 12 months ago whose owner changed no
-- project in those 12 months (N46), unless an erasure of its person or its
-- project is under way.
CREATE OR REPLACE FUNCTION public.retention_due_audio_v1(
    p_as_of timestamptz, p_audio_object_id uuid DEFAULT NULL
) RETURNS TABLE (
    audio_object_id uuid, take_id uuid, acquisition_principal_id uuid,
    owner_principal_id uuid, project_id uuid
)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = public
AS $$
#variable_conflict use_column
BEGIN
    RETURN QUERY
    SELECT a.audio_object_id, a.take_id, a.acquisition_principal_id,
           a.owner_principal_id, a.project_id
      FROM public.retention_live_audio_v1(p_audio_object_id) a,
           public.retention_cutoffs_v1(p_as_of) c
     WHERE a.created_at < c.audio_cut
       AND NOT EXISTS (
           SELECT 1 FROM public.projects pr
            WHERE pr.owner_principal_id = a.owner_principal_id
              AND pr.updated_at >= c.audio_cut)
       AND NOT EXISTS (
           SELECT 1 FROM public.data_purge_requests r
            WHERE r.acquisition_principal_id IN (
                      a.acquisition_principal_id, a.owner_principal_id)
              AND r.state <> 'done'
              AND (r.project_id IS NULL OR r.project_id = a.project_id));
END;
$$;

-- The accounts whose every live recording is due: when a run deletes them,
-- nothing the account's measurement aggregates were made from is left.
CREATE OR REPLACE FUNCTION public.retention_last_audio_accounts_v1(
    p_as_of timestamptz
) RETURNS TABLE (owner_principal_id uuid, user_id text)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = public
AS $$
#variable_conflict use_column
BEGIN
    RETURN QUERY
    WITH due AS (
        SELECT d.audio_object_id, d.owner_principal_id
          FROM public.retention_due_audio_v1(p_as_of) d
    )
    SELECT acct.id, acct.user_id::text
      FROM public.owner_principals acct
     WHERE acct.user_id IS NOT NULL
       AND acct.id IN (SELECT due.owner_principal_id FROM due)
       AND NOT EXISTS (
           SELECT 1 FROM public.retention_live_audio_v1(NULL, acct.id) live
            WHERE live.audio_object_id NOT IN (
                SELECT due.audio_object_id FROM due));
END;
$$;

-- Where a recording's voice measurements are kept (policy §3: pitch, its
-- variation and movement, loudness, pace, pauses, energy). `take` stores
-- belong to the Take that recorded the audio; `account` stores are
-- aggregates over all of a speaker's recordings and go when the last of
-- them goes. `wipe` empties the listed columns (the row also holds words
-- that outlive the audio, DPIA M5.3); `delete` removes the row, which the
-- service does (services/retention_cleaner.py keeps the same list).
CREATE OR REPLACE FUNCTION public.retention_measurement_stores_v1()
RETURNS TABLE (
    store text, relation text, scope text, action text, key_column text,
    columns text[]
)
LANGUAGE sql IMMUTABLE SET search_path = public
AS $$
    SELECT * FROM (VALUES
        ('acoustic_feature_snapshots.features', 'acoustic_feature_snapshots',
         'take', 'wipe', 'evidence_span_id', ARRAY['features']),
        ('arc_part_acoustics', 'arc_part_acoustics',
         'account', 'delete', 'user_id', NULL::text[]),
        ('candidate_windows.metrics', 'candidate_windows',
         'take', 'wipe', 'session_id', ARRAY['metrics']),
        ('dimension_evaluations', 'dimension_evaluations',
         'take', 'delete', 'session_id', NULL::text[]),
        ('session_sniper_metrics', 'session_sniper_metrics',
         'take', 'delete', 'session_id', NULL::text[]),
        ('snippets.metrics', 'snippets',
         'take', 'wipe', 'session_id', ARRAY['metrics']),
        ('user_acoustic_baseline', 'user_acoustic_baseline',
         'account', 'delete', 'user_id', NULL::text[]),
        ('v2_sessions.voice_measures', 'v2_sessions',
         'take', 'wipe', 'id', ARRAY['global_wpm', 'global_pause_ms',
                                     'global_dynamic_db', 'global_pitch_center',
                                     'global_energy', 'kpi_score'])
    ) AS s(store, relation, scope, action, key_column, columns)
$$;

-- The rows of one store that belong to the given keys ($1, text[]: Take
-- ids for a `take` store, user ids for an `account` one), over alias t.
-- A voice snapshot names its Take through its evidence span.
CREATE OR REPLACE FUNCTION public.retention_measurement_rows_sql_v1(
    p_relation text, p_key_column text
) RETURNS text
LANGUAGE sql IMMUTABLE SET search_path = public
AS $$
    SELECT CASE
        WHEN p_relation = 'acoustic_feature_snapshots' THEN
            't.evidence_span_id IN (SELECT e.id FROM public.evidence_spans e '
            'WHERE e.take_id::text = ANY($1))'
        ELSE format('t.%I::text = ANY($1)', p_key_column)
    END
$$;

-- Is this store here, with the coordinate its rows are found by?
CREATE OR REPLACE FUNCTION public.retention_store_present_v1(
    p_relation text, p_key_column text
) RETURNS boolean
LANGUAGE sql STABLE SET search_path = public
AS $$
    SELECT CASE
        WHEN p_relation = 'acoustic_feature_snapshots' THEN
            public.retention_column_present_v1(p_relation, 'evidence_span_id')
            AND public.retention_column_present_v1('evidence_spans', 'take_id')
        ELSE public.retention_column_present_v1(p_relation, p_key_column)
    END
$$;

-- A row still holding a measurement: any listed column not yet erased
-- (NULL, '{}', '[]', '[erased]' are erased: purge_lineage_value_erased_v1,
-- 0379). A `delete` store's every row counts. NULL: no listed column here.
CREATE OR REPLACE FUNCTION public.retention_measurement_dirty_sql_v1(
    p_relation text, p_action text, p_columns text[]
) RETURNS text
LANGUAGE plpgsql STABLE SET search_path = public
AS $$
DECLARE present text[];
BEGIN
    IF p_action = 'delete' THEN
        RETURN 'true';
    END IF;
    present := ARRAY(
        SELECT a.attname::text FROM pg_attribute a
         WHERE a.attrelid = to_regclass(format('public.%I', p_relation))
           AND a.attnum > 0 AND NOT a.attisdropped
           AND a.attname = ANY(p_columns)
         ORDER BY a.attname);
    IF cardinality(present) = 0 THEN
        RETURN NULL;
    END IF;
    RETURN (SELECT string_agg(format(
                'NOT public.purge_lineage_value_erased_v1(to_jsonb(t.%I))',
                x), ' OR ')
              FROM unnest(present) AS x);
END;
$$;

CREATE OR REPLACE FUNCTION public.retention_count_measurements_v1(
    p_relation text, p_action text, p_key_column text, p_columns text[],
    p_keys text[]
) RETURNS bigint
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = public
AS $$
DECLARE dirty text; n bigint := 0;
BEGIN
    IF cardinality(COALESCE(p_keys, '{}'::text[])) = 0
       OR NOT public.retention_store_present_v1(p_relation, p_key_column) THEN
        RETURN 0;
    END IF;
    dirty := public.retention_measurement_dirty_sql_v1(
        p_relation, p_action, p_columns);
    IF dirty IS NULL THEN
        RETURN 0;
    END IF;
    EXECUTE format('SELECT count(*) FROM public.%I t WHERE %s AND (%s)',
                   p_relation,
                   public.retention_measurement_rows_sql_v1(p_relation, p_key_column),
                   dirty)
       INTO n USING p_keys;
    RETURN n;
END;
$$;

-- Empty a `wipe` store's listed columns on the given keys' rows: NULL, or
-- '{}' for a JSON column that may not be NULL. A NOT NULL column of any
-- other type is refused: emptying it would mean inventing a value.
CREATE OR REPLACE FUNCTION public.retention_wipe_measurements_v1(
    p_relation text, p_key_column text, p_columns text[], p_keys text[]
) RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE dirty text; set_list text; n bigint := 0;
BEGIN
    IF cardinality(COALESCE(p_keys, '{}'::text[])) = 0
       OR NOT public.retention_store_present_v1(p_relation, p_key_column) THEN
        RETURN 0;
    END IF;
    dirty := public.retention_measurement_dirty_sql_v1(
        p_relation, 'wipe', p_columns);
    IF dirty IS NULL THEN
        RETURN 0;
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_attribute a
         WHERE a.attrelid = to_regclass(format('public.%I', p_relation))
           AND a.attnum > 0 AND NOT a.attisdropped
           AND a.attname = ANY(p_columns) AND a.attnotnull
           AND a.atttypid NOT IN ('jsonb'::regtype, 'json'::regtype)
    ) THEN
        RAISE EXCEPTION 'RETENTION_MEASUREMENT_COLUMN_NOT_ERASABLE:%', p_relation;
    END IF;
    SELECT string_agg(format('%I = %s', a.attname,
               CASE WHEN a.attnotnull THEN '''{}''' ELSE 'NULL' END),
               ', ' ORDER BY a.attname)
      INTO set_list
      FROM pg_attribute a
     WHERE a.attrelid = to_regclass(format('public.%I', p_relation))
       AND a.attnum > 0 AND NOT a.attisdropped
       AND a.attname = ANY(p_columns);
    EXECUTE format('UPDATE public.%I t SET %s WHERE %s AND (%s)',
                   p_relation, set_list,
                   public.retention_measurement_rows_sql_v1(p_relation, p_key_column),
                   dirty)
       USING p_keys;
    GET DIAGNOSTICS n = ROW_COUNT;
    RETURN n;
END;
$$;

-- Rule 2's measurements: how many rows of each store a run would empty or
-- remove with the audio that is due.
CREATE OR REPLACE FUNCTION public.retention_due_measurements_v1(
    p_as_of timestamptz
) RETURNS TABLE (store text, how_many bigint)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = public
AS $$
#variable_conflict use_column
DECLARE s record; takes text[]; users text[];
BEGIN
    takes := ARRAY(SELECT d.take_id::text FROM public.retention_due_audio_v1(p_as_of) d);
    users := ARRAY(SELECT l.user_id FROM public.retention_last_audio_accounts_v1(p_as_of) l);
    FOR s IN SELECT * FROM public.retention_measurement_stores_v1() m
              ORDER BY m.store LOOP
        store := s.store;
        how_many := public.retention_count_measurements_v1(
            s.relation, s.action, s.key_column, s.columns,
            CASE WHEN s.scope = 'take' THEN takes ELSE users END);
        RETURN NEXT;
    END LOOP;
END;
$$;

-- Rule 3. Exactly the five technical logs (the report's list, 2026-10-05),
-- and, for each, the evidence whose rows keep a log row alive: a row that
-- evidence points at is kept, because deleting it would rewrite that
-- evidence (ON DELETE SET NULL on append-only, retained rows).
CREATE OR REPLACE FUNCTION public.retention_log_relations_v1()
RETURNS TABLE (relation text, kept_when_referenced_by text[])
LANGUAGE sql IMMUTABLE SET search_path = public
AS $$
    SELECT * FROM (VALUES
        ('admin_annotations_log', ARRAY[]::text[]),
        ('dev_bugs', ARRAY[]::text[]),
        ('life_reminder_log', ARRAY[]::text[]),
        ('mlc3_service_backpressure_events', ARRAY[]::text[]),
        ('processing_jobs', ARRAY['processing_stage_runs.processing_job_id',
                                  'processing_transition_events.processing_job_id'])
    ) AS l(relation, kept_when_referenced_by)
$$;

-- The WHERE clause over alias t for a log's rows older than the cut ($1):
-- the ones to remove, or (p_kept) the ones evidence keeps.
CREATE OR REPLACE FUNCTION public.retention_log_condition_v1(
    p_relation text, p_kept boolean
) RETURNS text
LANGUAGE plpgsql STABLE SET search_path = public
AS $$
DECLARE refs text[]; ref text; parts text[] := ARRAY[]::text[];
BEGIN
    SELECT l.kept_when_referenced_by INTO refs
      FROM public.retention_log_relations_v1() l WHERE l.relation = p_relation;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'RETENTION_LOG_RELATION_UNKNOWN';
    END IF;
    FOREACH ref IN ARRAY refs LOOP
        IF public.retention_column_present_v1(
               split_part(ref, '.', 1), split_part(ref, '.', 2)) THEN
            parts := parts || format(
                'EXISTS (SELECT 1 FROM public.%I e WHERE e.%I = t.id)',
                split_part(ref, '.', 1), split_part(ref, '.', 2));
        END IF;
    END LOOP;
    RETURN format('t.created_at < $1 AND %s(%s)',
                  CASE WHEN p_kept THEN '' ELSE 'NOT ' END,
                  COALESCE(NULLIF(array_to_string(parts, ' OR '), ''), 'false'));
END;
$$;

CREATE OR REPLACE FUNCTION public.retention_due_logs_v1(p_as_of timestamptz)
RETURNS TABLE (relation text, due bigint, kept bigint)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = public
AS $$
#variable_conflict use_column
DECLARE l record; cut timestamptz;
BEGIN
    SELECT c.log_cut INTO cut FROM public.retention_cutoffs_v1(p_as_of) c;
    FOR l IN SELECT * FROM public.retention_log_relations_v1() r
              ORDER BY r.relation LOOP
        relation := l.relation;
        due := 0;
        kept := CASE WHEN cardinality(l.kept_when_referenced_by) > 0
                     THEN 0 END;
        IF public.retention_column_present_v1(l.relation, 'id')
           AND public.retention_column_present_v1(l.relation, 'created_at') THEN
            EXECUTE format('SELECT count(*) FROM public.%I t WHERE %s',
                           l.relation,
                           public.retention_log_condition_v1(l.relation, false))
               INTO due USING cut;
            IF kept IS NOT NULL THEN
                EXECUTE format('SELECT count(*) FROM public.%I t WHERE %s',
                               l.relation,
                               public.retention_log_condition_v1(l.relation, true))
                   INTO kept USING cut;
            END IF;
        END IF;
        RETURN NEXT;
    END LOOP;
END;
$$;

CREATE OR REPLACE FUNCTION public.retention_due_log_ids_v1(
    p_as_of timestamptz, p_relation text, p_limit integer
) RETURNS TABLE (row_id text)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = public
AS $$
#variable_conflict use_column
DECLARE cut timestamptz;
BEGIN
    IF NOT public.retention_column_present_v1(p_relation, 'id')
       OR NOT public.retention_column_present_v1(p_relation, 'created_at') THEN
        RETURN;
    END IF;
    SELECT c.log_cut INTO cut FROM public.retention_cutoffs_v1(p_as_of) c;
    RETURN QUERY EXECUTE format(
        'SELECT t.id::text FROM public.%I t WHERE %s '
        'ORDER BY t.created_at, t.id LIMIT %s',
        p_relation, public.retention_log_condition_v1(p_relation, false),
        p_limit)
        USING cut;
END;
$$;

-- THE REPORT. One row per rule and line, counts only; nothing by person.
-- scripts/retention_report.sql reads exactly this, and so does every run.
CREATE OR REPLACE FUNCTION public.retention_report_v1(
    p_as_of timestamptz DEFAULT now()
) RETURNS TABLE (rule integer, would_delete text, how_many bigint)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = public
AS $$
#variable_conflict use_column
BEGIN
    RETURN QUERY
    SELECT lines.rule, lines.would_delete, lines.how_many FROM (
        SELECT 1::integer AS rule,
               'unclaimed guests older than 30 days'::text AS would_delete,
               (SELECT count(*) FROM public.retention_due_guests_v1(p_as_of))::bigint
                   AS how_many
        UNION ALL
        SELECT 1, 'their recordings (audio files)',
               (SELECT count(*) FROM public.retention_live_audio_v1() a
                 WHERE a.acquisition_principal_id IN (
                     SELECT g.principal_id
                       FROM public.retention_due_guests_v1(p_as_of) g))::bigint
        UNION ALL
        SELECT 2, 'audio files not used for 12 months',
               (SELECT count(*) FROM public.retention_due_audio_v1(p_as_of))::bigint
        UNION ALL
        SELECT 2, 'voice measurements with that audio: ' || m.store, m.how_many
          FROM public.retention_due_measurements_v1(p_as_of) m
        UNION ALL
        SELECT 3, 'log rows older than 90 days: ' || l.relation, l.due
          FROM public.retention_due_logs_v1(p_as_of) l
        UNION ALL
        SELECT 3, 'log rows older than 90 days kept, deletion evidence points '
                  'at them: ' || l.relation, l.kept
          FROM public.retention_due_logs_v1(p_as_of) l
         WHERE l.kept IS NOT NULL
    ) AS lines
    ORDER BY lines.rule, lines.would_delete;
END;
$$;

CREATE OR REPLACE FUNCTION public.retention_report_json_v1(p_as_of timestamptz)
RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public
AS $$
    SELECT COALESCE(jsonb_agg(jsonb_build_object(
               'rule', r.rule, 'would_delete', r.would_delete,
               'how_many', r.how_many) ORDER BY r.rule, r.would_delete),
           '[]'::jsonb)
      FROM public.retention_report_v1(p_as_of) r
$$;

-- ── 3. The run's writers (service_role only) ─────────────────────────────

-- A run may look back (a cut earlier than today selects a subset of what
-- is due today) but never ahead.
CREATE OR REPLACE FUNCTION public.retention_run_moment_v1(p_as_of timestamptz)
RETURNS timestamptz
LANGUAGE plpgsql STABLE SET search_path = public
AS $$
BEGIN
    IF p_as_of IS NOT NULL AND p_as_of > now() THEN
        RAISE EXCEPTION 'RETENTION_AS_OF_IN_THE_FUTURE';
    END IF;
    RETURN COALESCE(p_as_of, now());
END;
$$;

-- A dry run: count, record, delete nothing. A refused live request is
-- recorded the same way, with its refusal.
CREATE OR REPLACE FUNCTION public.record_retention_dry_run_v1(
    p_requested_mode text, p_cleaner_version text,
    p_refusal text DEFAULT NULL, p_as_of timestamptz DEFAULT NULL
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    moment timestamptz := public.retention_run_moment_v1(p_as_of);
    started timestamptz := clock_timestamp();
    lines jsonb;
    run public.retention_cleaner_runs;
BEGIN
    IF p_requested_mode IS NULL OR p_requested_mode NOT IN ('dry_run', 'live') THEN
        RAISE EXCEPTION 'RETENTION_MODE_INVALID';
    END IF;
    IF (p_refusal IS NOT NULL) <> (p_requested_mode = 'live') THEN
        RAISE EXCEPTION 'RETENTION_REFUSAL_INVALID';
    END IF;
    IF length(btrim(COALESCE(p_cleaner_version, ''))) = 0 THEN
        RAISE EXCEPTION 'RETENTION_CLEANER_VERSION_REQUIRED';
    END IF;
    lines := public.retention_report_json_v1(moment);
    INSERT INTO public.retention_cleaner_runs (
        requested_mode, mode, state, refusal, as_of, cleaner_version, due,
        started_at, finished_at
    ) VALUES (
        p_requested_mode, 'dry_run',
        CASE WHEN p_refusal IS NULL THEN 'completed' ELSE 'refused' END,
        left(p_refusal, 160), moment, left(p_cleaner_version, 80), lines,
        started, clock_timestamp()
    ) RETURNING * INTO run;
    RETURN to_jsonb(run);
END;
$$;

CREATE OR REPLACE FUNCTION public.begin_retention_live_run_v1(
    p_cleaner_version text, p_as_of timestamptz DEFAULT NULL
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    moment timestamptz := public.retention_run_moment_v1(p_as_of);
    started timestamptz := clock_timestamp();
    run public.retention_cleaner_runs;
BEGIN
    IF length(btrim(COALESCE(p_cleaner_version, ''))) = 0 THEN
        RAISE EXCEPTION 'RETENTION_CLEANER_VERSION_REQUIRED';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended('retention-cleaner-live', 0));
    -- A live run whose process died is closed after six hours; a younger
    -- one may still be working, and a second one waits for it.
    UPDATE public.retention_cleaner_runs
       SET state = 'interrupted', finished_at = clock_timestamp(),
           error_code = 'RETENTION_RUN_ABANDONED'
     WHERE mode = 'live' AND state = 'running'
       AND started_at < clock_timestamp() - interval '6 hours';
    IF EXISTS (SELECT 1 FROM public.retention_cleaner_runs
                WHERE mode = 'live' AND state = 'running') THEN
        RAISE EXCEPTION 'RETENTION_LIVE_RUN_IN_PROGRESS';
    END IF;
    INSERT INTO public.retention_cleaner_runs (
        requested_mode, mode, state, as_of, cleaner_version, due, started_at
    ) VALUES (
        'live', 'live', 'running', moment, left(p_cleaner_version, 80),
        public.retention_report_json_v1(moment), started
    ) RETURNING * INTO run;
    RETURN to_jsonb(run);
END;
$$;

CREATE OR REPLACE FUNCTION public.retention_live_run_v1(
    p_run_id uuid, p_lock boolean DEFAULT false
) RETURNS public.retention_cleaner_runs
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE run public.retention_cleaner_runs;
BEGIN
    IF p_lock THEN
        SELECT * INTO run FROM public.retention_cleaner_runs
         WHERE id = p_run_id FOR UPDATE;
    ELSE
        SELECT * INTO run FROM public.retention_cleaner_runs
         WHERE id = p_run_id;
    END IF;
    IF run.id IS NULL OR run.mode <> 'live' OR run.state <> 'running' THEN
        RAISE EXCEPTION 'RETENTION_RUN_NOT_LIVE';
    END IF;
    RETURN run;
END;
$$;

-- What a live run works through, in a stable order, at the run's moment.
CREATE OR REPLACE FUNCTION public.list_retention_due_v1(
    p_run_id uuid, p_rule text, p_relation text DEFAULT NULL,
    p_limit integer DEFAULT 100
) RETURNS TABLE (item_id text)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = public
AS $$
#variable_conflict use_column
DECLARE run public.retention_cleaner_runs;
BEGIN
    SELECT * INTO run FROM public.retention_cleaner_runs WHERE id = p_run_id;
    IF run.id IS NULL OR run.mode <> 'live' OR run.state <> 'running' THEN
        RAISE EXCEPTION 'RETENTION_RUN_NOT_LIVE';
    END IF;
    IF p_limit IS NULL OR p_limit < 1 OR p_limit > 1000 THEN
        RAISE EXCEPTION 'RETENTION_LIMIT_INVALID';
    END IF;
    -- Work never tried before comes first, so a guest whose erasure stopped
    -- for review (left for a person), or a recording whose object would not
    -- go (tried again), cannot hold the rest back.
    IF p_rule = 'guests' THEN
        RETURN QUERY SELECT g.principal_id::text
                       FROM public.retention_due_guests_v1(run.as_of) g
                      ORDER BY EXISTS (
                                   SELECT 1 FROM public.data_purge_requests r
                                    WHERE r.acquisition_principal_id = g.principal_id),
                               1
                      LIMIT p_limit;
    ELSIF p_rule = 'audio' THEN
        RETURN QUERY SELECT d.audio_object_id::text
                       FROM public.retention_due_audio_v1(run.as_of) d
                      ORDER BY EXISTS (
                                   SELECT 1 FROM public.retention_cleaner_audio_claims c
                                    WHERE c.audio_object_id = d.audio_object_id),
                               1
                      LIMIT p_limit;
    ELSIF p_rule = 'logs' AND EXISTS (
              SELECT 1 FROM public.retention_log_relations_v1() l
               WHERE l.relation = p_relation) THEN
        RETURN QUERY SELECT x.row_id
                       FROM public.retention_due_log_ids_v1(
                           run.as_of, p_relation, p_limit) x;
    ELSE
        RAISE EXCEPTION 'RETENTION_RULE_UNKNOWN';
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION public.retention_count_v1(
    p_run_id uuid, p_key text, p_n bigint
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE done_now jsonb;
BEGIN
    IF p_key IS NULL
       OR p_key !~ '^(guests|audio|measurements|logs)\.[a-z0-9_.]+$'
       OR p_n IS NULL OR p_n < 0 THEN
        RAISE EXCEPTION 'RETENTION_COUNTER_INVALID';
    END IF;
    UPDATE public.retention_cleaner_runs
       SET done = jsonb_set(done, ARRAY[p_key],
                            to_jsonb(COALESCE((done ->> p_key)::bigint, 0) + p_n))
     WHERE id = p_run_id AND mode = 'live' AND state = 'running'
    RETURNING done INTO done_now;
    IF done_now IS NULL THEN
        RAISE EXCEPTION 'RETENTION_RUN_NOT_LIVE';
    END IF;
    RETURN done_now;
END;
$$;

-- What the service reports it did (guest erasures, rows it removed).
CREATE OR REPLACE FUNCTION public.count_retention_outcome_v1(
    p_run_id uuid, p_key text, p_n integer DEFAULT 1
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
BEGIN
    RETURN public.retention_count_v1(p_run_id, p_key, p_n);
END;
$$;

-- Rule 1, one guest: still due at the run's moment, no other account-wide
-- erasure of it open (a project's deletion pauses only that project, 0378),
-- then the account purge's own request (it blocks the guest's
-- processing and records the request); the service runs the purge.
CREATE OR REPLACE FUNCTION public.request_retention_guest_purge_v1(
    p_run_id uuid, p_principal_id uuid
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    run public.retention_cleaner_runs := public.retention_live_run_v1(p_run_id);
    purge_key text := 'retention-cleaner:unclaimed-guest-30-days:'
                      || p_principal_id::text;
    receipt jsonb;
BEGIN
    -- The guest's row, so that a sign-up claiming it waits, or wins.
    PERFORM 1 FROM public.owner_principals
     WHERE id = p_principal_id FOR UPDATE;
    IF NOT EXISTS (
        SELECT 1 FROM public.retention_due_guests_v1(run.as_of, p_principal_id)
    ) THEN
        RETURN jsonb_build_object('principal_id', p_principal_id,
                                  'skipped', 'not_due');
    END IF;
    IF EXISTS (
        SELECT 1 FROM public.data_purge_requests r
         WHERE r.acquisition_principal_id = p_principal_id
           AND r.state <> 'done'
           AND r.project_id IS NULL /* 0378: account-wide purges only */
           AND r.idempotency_key <> purge_key
    ) THEN
        RETURN jsonb_build_object('principal_id', p_principal_id,
                                  'skipped', 'another_erasure_open');
    END IF;
    -- Its own erasure stopped on rows no rule decides: a person takes it
    -- from here, and no run tries it again (a re-run of a frozen purge
    -- cannot get past what stopped it). 0422's completion run does the same.
    IF EXISTS (
        SELECT 1 FROM public.data_purge_requests r
         WHERE r.acquisition_principal_id = p_principal_id
           AND r.idempotency_key = purge_key
           AND r.state = 'review_required'
    ) THEN
        RETURN jsonb_build_object('principal_id', p_principal_id,
                                  'skipped', 'left_for_a_person');
    END IF;
    receipt := public.request_phase1_purge_v1(
        p_principal_id, 'retention_expiry', purge_key,
        'RETENTION_UNCLAIMED_GUEST_30_DAYS');
    RETURN receipt || jsonb_build_object('principal_id', p_principal_id);
END;
$$;

-- May a running live retention run empty this voice snapshot? Only for the
-- Take whose recording it has claimed and not yet settled, and only while
-- the claim names it (willab.retention_*, set by the claim alone).
CREATE OR REPLACE FUNCTION public.retention_wipe_authorized_v1(
    p_evidence_span_id uuid
) RETURNS boolean
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    run_text text := current_setting('willab.retention_run_id', true);
    audio_text text := current_setting('willab.retention_audio_object_id', true);
BEGIN
    IF NULLIF(run_text, '') IS NULL OR NULLIF(audio_text, '') IS NULL THEN
        RETURN false;
    END IF;
    RETURN EXISTS (
        SELECT 1
          FROM public.retention_cleaner_runs r
          JOIN public.retention_cleaner_audio_claims c ON c.run_id = r.id
          JOIN public.processing_audio_objects o ON o.id = c.audio_object_id
          JOIN public.evidence_spans e ON e.take_id = o.recording_attempt_id
         WHERE r.id::text = run_text AND r.mode = 'live' AND r.state = 'running'
           AND c.audio_object_id::text = audio_text AND c.outcome IS NULL
           AND e.id = p_evidence_span_id);
END;
$$;

-- Rule 2, one recording: still due at the run's moment and not shared with
-- anyone else's registry row. The claim empties the Take's measurement
-- columns now, before anything touches the recording, and tells the
-- service what is left to do: the measurement rows, the object, by its
-- coordinates and byte hash, and the account's aggregates when this is the
-- account's last live recording.
CREATE OR REPLACE FUNCTION public.claim_retention_audio_v1(
    p_run_id uuid, p_audio_object_id uuid
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
#variable_conflict use_column
DECLARE
    run public.retention_cleaner_runs := public.retention_live_run_v1(p_run_id, true);
    audio public.processing_audio_objects;
    due_row record;
    s record;
    n bigint;
    wiped jsonb := '{}'::jsonb;
    account_user text;
    last_audio boolean;
BEGIN
    SELECT * INTO audio FROM public.processing_audio_objects
     WHERE id = p_audio_object_id;
    IF audio.id IS NULL THEN
        RAISE EXCEPTION 'RETENTION_AUDIO_NOT_FOUND';
    END IF;
    -- D11's lock order (0327): the rollout policy, the person, the Take.
    PERFORM pg_advisory_xact_lock(hashtextextended('mlc3-rollout-policy-v2', 0));
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'mlc3-service-principal:' || audio.acquisition_principal_id::text, 0));
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'confident-moment-take-inventory:' || audio.recording_attempt_id::text, 0));
    SELECT * INTO due_row
      FROM public.retention_due_audio_v1(run.as_of, p_audio_object_id);
    IF NOT FOUND THEN
        PERFORM public.retention_count_v1(p_run_id, 'audio.skipped_not_due', 1);
        RETURN jsonb_build_object('audio_object_id', p_audio_object_id,
                                  'skipped', 'not_due');
    END IF;
    IF EXISTS (
        SELECT 1 FROM public.processing_orphan_objects x
         WHERE x.storage_provider = audio.storage_provider
           AND x.bucket = audio.bucket AND x.object_key = audio.object_key
           AND x.acquisition_principal_id <> audio.acquisition_principal_id
    ) THEN
        PERFORM public.retention_count_v1(p_run_id, 'audio.skipped_shared', 1);
        RETURN jsonb_build_object('audio_object_id', p_audio_object_id,
                                  'skipped', 'shared_object');
    END IF;
    IF EXISTS (
        SELECT 1 FROM public.retention_cleaner_audio_claims c
         WHERE c.run_id = p_run_id AND c.audio_object_id = p_audio_object_id
           AND c.outcome IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'RETENTION_CLAIM_ALREADY_SETTLED';
    END IF;
    INSERT INTO public.retention_cleaner_audio_claims (run_id, audio_object_id)
    VALUES (p_run_id, p_audio_object_id)
    ON CONFLICT (run_id, audio_object_id) DO NOTHING;

    PERFORM set_config('willab.retention_run_id', p_run_id::text, true);
    PERFORM set_config('willab.retention_audio_object_id',
                       p_audio_object_id::text, true);
    FOR s IN SELECT * FROM public.retention_measurement_stores_v1() m
              WHERE m.scope = 'take' AND m.action = 'wipe'
              ORDER BY m.store LOOP
        n := public.retention_wipe_measurements_v1(
            s.relation, s.key_column, s.columns, ARRAY[due_row.take_id::text]);
        wiped := wiped || jsonb_build_object(s.store, n);
        IF n > 0 THEN
            PERFORM public.retention_count_v1(
                p_run_id, 'measurements.' || replace(s.store, '.', '_'), n);
        END IF;
    END LOOP;
    PERFORM set_config('willab.retention_audio_object_id', '', true);
    PERFORM set_config('willab.retention_run_id', '', true);
    UPDATE public.retention_cleaner_audio_claims SET measurements = wiped
     WHERE run_id = p_run_id AND audio_object_id = p_audio_object_id;

    SELECT acct.user_id::text INTO account_user
      FROM public.owner_principals acct WHERE acct.id = due_row.owner_principal_id;
    last_audio := NOT EXISTS (
        SELECT 1 FROM public.retention_live_audio_v1(NULL, due_row.owner_principal_id) a
         WHERE a.audio_object_id <> p_audio_object_id);
    RETURN jsonb_build_object(
        'audio_object_id', audio.id, 'take_id', due_row.take_id,
        'storage_provider', audio.storage_provider, 'bucket', audio.bucket,
        'object_key', audio.object_key,
        'exact_bytes_sha256', audio.exact_bytes_sha256,
        'account_user_id', account_user,
        'last_audio_of_account', last_audio,
        'wiped', wiped);
END;
$$;

-- Rule 2, the end of one claim. `deleted` (the service deleted the object
-- after matching its byte hash) and `already_absent` (it was verified
-- gone) record the deletion event, naming this run; `failed` keeps the
-- recording, and the next run finds it again.
CREATE OR REPLACE FUNCTION public.settle_retention_audio_v1(
    p_run_id uuid, p_audio_object_id uuid, p_outcome text,
    p_error_code text DEFAULT NULL
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    run public.retention_cleaner_runs := public.retention_live_run_v1(p_run_id, true);
    claim public.retention_cleaner_audio_claims;
    audio public.processing_audio_objects;
BEGIN
    IF p_outcome IS NULL
       OR p_outcome NOT IN ('deleted', 'already_absent', 'failed') THEN
        RAISE EXCEPTION 'RETENTION_OUTCOME_INVALID';
    END IF;
    SELECT * INTO claim FROM public.retention_cleaner_audio_claims
     WHERE run_id = run.id AND audio_object_id = p_audio_object_id FOR UPDATE;
    IF claim.run_id IS NULL OR claim.outcome IS NOT NULL THEN
        RAISE EXCEPTION 'RETENTION_CLAIM_NOT_OPEN';
    END IF;
    IF p_outcome <> 'failed' THEN
        SELECT * INTO audio FROM public.processing_audio_objects
         WHERE id = p_audio_object_id;
        PERFORM pg_advisory_xact_lock(hashtextextended('mlc3-rollout-policy-v2', 0));
        PERFORM pg_advisory_xact_lock(hashtextextended(
            'mlc3-service-principal:' || audio.acquisition_principal_id::text, 0));
        INSERT INTO public.processing_audio_object_deletion_events (
            audio_object_id, purge_request_id, retention_run_id,
            acquisition_principal_id, storage_provider, bucket, object_key,
            exact_bytes_sha256, evidence_sha256
        ) VALUES (
            audio.id, NULL, run.id, audio.acquisition_principal_id,
            audio.storage_provider, audio.bucket, audio.object_key,
            audio.exact_bytes_sha256,
            encode(extensions.digest(concat_ws(':',
                run.id::text, audio.id::text, audio.storage_provider,
                audio.bucket, audio.object_key, audio.exact_bytes_sha256,
                'retention_' || p_outcome), 'sha256'), 'hex')
        ) ON CONFLICT (audio_object_id) DO NOTHING;
    END IF;
    UPDATE public.retention_cleaner_audio_claims
       SET outcome = p_outcome, error_code = left(p_error_code, 160),
           settled_at = clock_timestamp()
     WHERE run_id = run.id AND audio_object_id = p_audio_object_id;
    RETURN public.retention_count_v1(run.id, 'audio.' || p_outcome, 1);
END;
$$;

CREATE OR REPLACE FUNCTION public.finish_retention_live_run_v1(
    p_run_id uuid, p_state text, p_error_code text DEFAULT NULL
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE run public.retention_cleaner_runs := public.retention_live_run_v1(p_run_id, true);
BEGIN
    IF p_state IS NULL OR p_state NOT IN ('completed', 'failed') THEN
        RAISE EXCEPTION 'RETENTION_STATE_INVALID';
    END IF;
    UPDATE public.retention_cleaner_runs
       SET state = p_state, error_code = left(p_error_code, 160),
           left_due = public.retention_report_json_v1(run.as_of),
           finished_at = clock_timestamp()
     WHERE id = run.id
    RETURNING * INTO run;
    RETURN to_jsonb(run);
END;
$$;

-- ── 4. Two guards open, each for a live run only ─────────────────────────

-- reject_canonical_feedback_mutation (0379 is the body production runs):
-- one more governed UPDATE beside the owner claim and the purge wipe.
DO $retention_wipe_branch$
DECLARE
    target regprocedure := 'public.reject_canonical_feedback_mutation()'::regprocedure;
    definition text;
    marker constant text := '/* 0423 retention measurement wipe */';
    anchor constant text :=
        'RAISE EXCEPTION ''canonical feedback evidence is append-only'';';
    branch constant text := $branch$/* 0423 retention measurement wipe */
    -- A live retention run empties `features` of the voice snapshots of the
    -- one Take whose recording it has claimed, and nothing else.
    IF TG_OP = 'UPDATE' AND TG_TABLE_NAME = 'acoustic_feature_snapshots'
       AND NULLIF(current_setting('willab.retention_run_id', true), '') IS NOT NULL THEN
        IF (to_jsonb(OLD) - 'features') = (to_jsonb(NEW) - 'features')
           AND public.purge_lineage_value_erased_v1(to_jsonb(NEW) -> 'features')
           AND public.retention_wipe_authorized_v1(OLD.evidence_span_id) THEN
            RETURN NEW;
        END IF;
    END IF;
    $branch$;
BEGIN
    definition := pg_get_functiondef(target);
    IF position(marker IN definition) > 0 THEN
        RETURN;  -- applied by an earlier run
    END IF;
    IF (length(definition) - length(replace(definition, anchor, '')))
       / length(anchor) <> 1 THEN
        RAISE EXCEPTION 'RETENTION_WIPE_ANCHOR_NOT_UNIQUE';
    END IF;
    EXECUTE replace(definition, anchor, branch || anchor);
    IF position(marker IN pg_get_functiondef(target)) = 0 THEN
        RAISE EXCEPTION 'RETENTION_WIPE_BRANCH_DID_NOT_LAND';
    END IF;
END
$retention_wipe_branch$;
REVOKE ALL ON FUNCTION public.reject_canonical_feedback_mutation()
    FROM PUBLIC, anon, authenticated;

-- reject_mlc3_general_service_mutation_v1 (0326): a backpressure event older
-- than the log period may be removed. Skipped where MLC-3 never landed.
DO $retention_log_branch$
DECLARE
    target regprocedure := to_regprocedure(
        'public.reject_mlc3_general_service_mutation_v1()');
    definition text;
    marker constant text := '/* 0423 retention log period */';
    anchor constant text := 'RAISE EXCEPTION ''MLC3_GENERAL_SERVICE_APPEND_ONLY'';';
    branch constant text := $branch$/* 0423 retention log period */
    -- Technical logs go 90 days after creation (retention schedule §1).
    IF TG_OP = 'DELETE' AND TG_TABLE_NAME = 'mlc3_service_backpressure_events' THEN
        IF OLD.created_at < (SELECT c.log_cut
                               FROM public.retention_cutoffs_v1(now()) c) THEN
            RETURN OLD;
        END IF;
    END IF;
    $branch$;
BEGIN
    IF target IS NULL THEN
        RETURN;
    END IF;
    definition := pg_get_functiondef(target);
    IF position(marker IN definition) = 0 THEN
        IF (length(definition) - length(replace(definition, anchor, '')))
           / length(anchor) <> 1 THEN
            RAISE EXCEPTION 'RETENTION_LOG_ANCHOR_NOT_UNIQUE';
        END IF;
        EXECUTE replace(definition, anchor, branch || anchor);
        IF position(marker IN pg_get_functiondef(target)) = 0 THEN
            RAISE EXCEPTION 'RETENTION_LOG_BRANCH_DID_NOT_LAND';
        END IF;
    END IF;
    IF to_regclass('public.mlc3_service_backpressure_events') IS NOT NULL THEN
        EXECUTE 'GRANT SELECT (id, created_at), DELETE ON '
                'public.mlc3_service_backpressure_events TO service_role';
    END IF;
END
$retention_log_branch$;

-- ── 5. Grants ────────────────────────────────────────────────────────────
-- Every function above: no browser role, ever. service_role calls the
-- run's writers and may read the report, the two registries and the three
-- periods; the selection functions that return ids stay with their owner,
-- reached only through a live run (list_retention_due_v1).

REVOKE ALL ON FUNCTION public.retention_cutoffs_v1(timestamptz) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.retention_column_present_v1(text, text) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.retention_live_audio_v1(uuid, uuid) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.retention_due_guests_v1(timestamptz, uuid) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.retention_due_audio_v1(timestamptz, uuid) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.retention_last_audio_accounts_v1(timestamptz) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.retention_measurement_stores_v1() FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.retention_measurement_rows_sql_v1(text, text) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.retention_store_present_v1(text, text) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.retention_measurement_dirty_sql_v1(text, text, text[]) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.retention_count_measurements_v1(text, text, text, text[], text[]) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.retention_wipe_measurements_v1(text, text, text[], text[]) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.retention_due_measurements_v1(timestamptz) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.retention_log_relations_v1() FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.retention_log_condition_v1(text, boolean) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.retention_due_logs_v1(timestamptz) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.retention_due_log_ids_v1(timestamptz, text, integer) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.retention_report_v1(timestamptz) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.retention_report_json_v1(timestamptz) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.retention_run_moment_v1(timestamptz) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.record_retention_dry_run_v1(text, text, text, timestamptz) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.begin_retention_live_run_v1(text, timestamptz) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.retention_live_run_v1(uuid, boolean) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.list_retention_due_v1(uuid, text, text, integer) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.retention_count_v1(uuid, text, bigint) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.count_retention_outcome_v1(uuid, text, integer) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.request_retention_guest_purge_v1(uuid, uuid) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.retention_wipe_authorized_v1(uuid) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.claim_retention_audio_v1(uuid, uuid) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.settle_retention_audio_v1(uuid, uuid, text, text) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.finish_retention_live_run_v1(uuid, text, text) FROM PUBLIC, anon, authenticated;

-- The log period, read by the backpressure guard as whoever deletes.
GRANT EXECUTE ON FUNCTION public.retention_cutoffs_v1(timestamptz) TO service_role;
GRANT EXECUTE ON FUNCTION public.retention_report_v1(timestamptz) TO service_role;
GRANT EXECUTE ON FUNCTION public.retention_measurement_stores_v1() TO service_role;
GRANT EXECUTE ON FUNCTION public.retention_log_relations_v1() TO service_role;
GRANT EXECUTE ON FUNCTION public.record_retention_dry_run_v1(text, text, text, timestamptz) TO service_role;
GRANT EXECUTE ON FUNCTION public.begin_retention_live_run_v1(text, timestamptz) TO service_role;
GRANT EXECUTE ON FUNCTION public.list_retention_due_v1(uuid, text, text, integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.count_retention_outcome_v1(uuid, text, integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.request_retention_guest_purge_v1(uuid, uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.claim_retention_audio_v1(uuid, uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.settle_retention_audio_v1(uuid, uuid, text, text) TO service_role;
GRANT EXECUTE ON FUNCTION public.finish_retention_live_run_v1(uuid, text, text) TO service_role;

COMMIT;

NOTIFY pgrst, 'reload schema';
