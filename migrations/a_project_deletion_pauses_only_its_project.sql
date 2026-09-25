-- A project deletion pauses only its project (P1-B, job 1 on the founder's
-- "finish line" page; SPEC-training-corpus §6.1, decisions log N8, N12).
--
-- THE PROBLEM. Nineteen functions ask "is this person being erased?" as
--
--     EXISTS (SELECT 1 FROM data_purge_requests purge
--              WHERE purge.acquisition_principal_id = <person>
--                AND purge.state <> 'done')
--
-- That was right while every purge request was a whole-account erasure. The
-- one-project delete (P1-B) will put a project's purge in the same table.
-- Left as it is, a project deletion waiting for review would, for that
-- person's WHOLE account:
--   * stop MLC-3 service, coach guidance, feedback v3 and practice;
--   * and in materialize_feedback_language_delivery_job_v1, close the delivery
--     jobs of their OTHER projects for good, as `source_deleted_or_purged`.
--
-- THE CHANGE. This file adds `data_purge_requests.project_id` (NULL for every
-- existing and every account-wide request) and narrows each of those
-- nineteen predicates to account-wide requests:
--
--     ... AND purge.state <> 'done' AND purge.project_id IS NULL
--
-- What a project deletion does to its own project's services lands with the
-- project purge itself, scoped to that project.
--
-- NOTHING CHANGES TODAY. Every existing row has project_id NULL, so each
-- predicate answers exactly as before. `trigger_kind` is not widened here, and
-- the CHECK below ties project_id to trigger_kind = 'project_deletion', so no
-- row can carry a project_id until a later, reviewed migration allows that
-- kind. The narrowing is in place before the first project purge can exist.
--
-- HOW THE FUNCTIONS ARE EDITED. Several are D11 writers whose lock preamble
-- was injected at runtime (0327, 0365, 0366); re-issuing them from source
-- would drop it. So, as 0366 and 0377 do, this edits the INSTALLED definition:
-- for each function it inserts ` AND <alias>.project_id IS NULL` right after
-- the purge-state predicate, re-runs the definition, and checks that exactly
-- one predicate per function was narrowed and that any D11 marker is still
-- there. It refuses if an installed function's predicate is not found, and
-- skips a function that is not installed (it cannot lock anyone).
-- Re-running finds the narrowed predicate and changes nothing.
--
-- ADDITIVE AND IDEMPOTENT. ADD COLUMN IF NOT EXISTS; constraints and the
-- index only if missing; function bodies only gain a filter. No row is
-- written, altered or removed.

BEGIN;

ALTER TABLE public.data_purge_requests
    ADD COLUMN IF NOT EXISTS project_id UUID NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'data_purge_requests_project_fkey'
           AND conrelid = 'public.data_purge_requests'::regclass
    ) THEN
        -- Projects are tombstoned, never removed (N9), so RESTRICT never
        -- blocks a purge; it keeps the request pointing at a real project.
        ALTER TABLE public.data_purge_requests
            ADD CONSTRAINT data_purge_requests_project_fkey
            FOREIGN KEY (project_id) REFERENCES public.projects(id)
            ON DELETE RESTRICT;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'data_purge_requests_project_scope_check'
           AND conrelid = 'public.data_purge_requests'::regclass
    ) THEN
        ALTER TABLE public.data_purge_requests
            ADD CONSTRAINT data_purge_requests_project_scope_check
            CHECK ((trigger_kind = 'project_deletion') = (project_id IS NOT NULL));
    END IF;
END;
$$;

CREATE INDEX IF NOT EXISTS data_purge_requests_open_account_idx
    ON public.data_purge_requests (acquisition_principal_id)
    WHERE project_id IS NULL AND state <> 'done';

DO $narrow_account_purge_predicates$
DECLARE
    spec RECORD;
    fn RECORD;
    definition TEXT;
    narrowed TEXT;
    pattern TEXT;
    edited INTEGER;
    had_d11 BOOLEAN;
    marker CONSTANT TEXT := '/* 0378: account-wide purges only */';
BEGIN
    FOR spec IN
        SELECT * FROM (VALUES
            ('create_synthetic_exercise_authoring_draft_v1', 'purge'),
            ('create_synthetic_exercise_practice_session_v1', 'purge'),
            ('materialize_feedback_language_delivery_job_v1', 'p'),
            ('prepare_coach_inline_blind_batch_v1', 'purge'),
            ('register_synthetic_service_no_match_request_v1', 'purge'),
            ('require_coach_guidance_assignment_live_v1', 'purge'),
            ('require_coach_guidance_authority_v1', 'purge'),
            ('require_coach_guidance_media_live_v1', 'purge'),
            ('require_coach_guidance_receipt_authority_v1', 'purge'),
            ('require_exercise_practice_service_live_v1', 'purge'),
            ('require_feedback_language_delivery_scan_authority_v1', 'p'),
            ('require_feedback_v3_service_membership_live_v1', 'purge'),
            ('require_mlc3_service_principal_v1', 'purge'),
            ('require_practice_source_live_v1', 'purge'),
            ('require_synthetic_feedback_v3_membership_live_v1', 'purge'),
            ('require_synthetic_root_content_live_v1', 'purge'),
            ('resolve_coach_inline_blind_audio_read_v1', 'purge'),
            ('resolve_confident_moment_source_playback_authority_v1', 'p'),
            ('resolve_mlc3_dual_purpose_receipt_v2', 'purge')
        ) AS t(name, alias)
    LOOP
        edited := 0;
        -- Every installed overload of the name that carries the predicate.
        FOR fn IN
            SELECT p.oid FROM pg_proc p
              JOIN pg_namespace n ON n.oid = p.pronamespace
             WHERE n.nspname = 'public' AND p.proname = spec.name
        LOOP
            definition := pg_get_functiondef(fn.oid);
            IF position('data_purge_requests' IN definition) = 0 THEN
                CONTINUE;
            END IF;
            IF position(marker IN definition) > 0 THEN
                edited := edited + 1;  -- narrowed by an earlier run
                CONTINUE;
            END IF;
            had_d11 := position('D11 writer' IN definition) > 0
                    OR position('D11 legacy root writer' IN definition) > 0;
            pattern := '(data_purge_requests\s+' || spec.alias
                    || '\s+WHERE[^;]*?\m' || spec.alias
                    || '\.state\s*<>\s*''done'')';
            narrowed := regexp_replace(
                definition, pattern,
                '\1 AND ' || spec.alias || '.project_id IS NULL ' || marker);
            IF narrowed = definition THEN
                RAISE EXCEPTION 'PURGE_SCOPE_PREDICATE_NOT_FOUND: %', spec.name;
            END IF;
            IF (length(narrowed) - length(replace(narrowed, marker, '')))
               / length(marker) <> 1 THEN
                RAISE EXCEPTION 'PURGE_SCOPE_PREDICATE_NOT_UNIQUE: %', spec.name;
            END IF;
            EXECUTE narrowed;
            definition := pg_get_functiondef(fn.oid);
            IF position(marker IN definition) = 0
               OR (had_d11 AND position('D11 ' IN definition) = 0) THEN
                RAISE EXCEPTION 'PURGE_SCOPE_EDIT_DID_NOT_LAND: %', spec.name;
            END IF;
            edited := edited + 1;
        END LOOP;
        -- A function that is not installed cannot lock anyone. Production
        -- has all nineteen; a rehearsal lane built from fewer migrations may
        -- not. tests/test_purge_scope_predicates.py fails the build if a
        -- later migration re-issues one of them, or adds a new one, without
        -- the filter.
        IF edited = 0 THEN
            RAISE NOTICE 'purge scope: % is not installed here', spec.name;
        END IF;
    END LOOP;
END
$narrow_account_purge_predicates$;

COMMIT;
