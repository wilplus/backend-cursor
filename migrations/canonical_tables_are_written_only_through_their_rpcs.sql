-- canonical_tables_are_written_only_through_their_rpcs (0388)
--
-- R-1 (audit 2026-09-22, major). Migrations 0296 and 0299 created the
-- canonical learning-evidence tables and closed with
-- `GRANT ALL ON TABLE ... TO service_role` on 26 + 2 of them. service_role
-- bypasses row level security, so anything holding the service key — the web
-- service, the worker, a cron, a psql session — could INSERT into
-- candidate_sets, evidence_spans, dataset_release_items or any of the others
-- directly, skipping the SECURITY DEFINER RPCs that are the only place the
-- contract's checks live. The append-only triggers refuse UPDATE and DELETE;
-- they never saw an INSERT. The audit counted eighteen such tables on a lane
-- where ten of the granted tables were absent; the grant blocks themselves
-- name twenty-eight, and this file covers the blocks.
--
-- What this does, per table: REVOKE ALL FROM PUBLIC, anon, authenticated and
-- service_role, then GRANT SELECT back to service_role where service_role
-- could already read. Reads stay (the Ideal Text repository reads
-- evidence_spans directly; the purge counts rows before and after each
-- step). Writes go through the RPCs, every one of which is SECURITY DEFINER
-- and so runs as the table owner, untouched by grants. Two tables already
-- had a narrower shape and keep it: 0321 left correction_decisions at
-- SELECT, and the coaching bundle revoked feedback_revisions entirely, read
-- included — this file never widens, so it grants nothing there. It is the
-- same statement pair 0321 used.
--
-- The one writer that is not a definer is the trigger function
-- transfer_learning_surfaces_on_owner_claim() (0299), fired when
-- projects.owner_principal_id changes. It writes only when the
-- transaction-local willab.owner_claim_* settings match, which
-- claim_guest_owner (SECURITY DEFINER since 0282, last replaced by 0343)
-- sets inside its own transaction, so those writes run as the definer. A
-- service_role session that set the settings by hand and updated projects
-- directly now fails on the trigger's UPDATE instead of moving learning
-- surfaces between owners with no claim event — closed, as intended.
--
-- Idempotent: REVOKE and GRANT are. Degrades gracefully: a table or role
-- that does not exist in the target database is skipped with a NOTICE, not
-- an error. Additive: no table, column, row or function is dropped or
-- rewritten. No environment variable is read.
--
-- Rehearsed on the released lane (tests/integration/confident_moment_rehearsal.sh,
-- applied twice) and asserted by
-- tests/test_canonical_tables_are_rpc_only_postgres.py.

DO $$
DECLARE
    table_name TEXT;
    role_name TEXT;
    could_read BOOLEAN;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        -- 0296 add_canonical_feedback_data_contract.sql, lines 2339-2364
        'transcript_versions', 'slides', 'paragraphs', 'evidence_spans',
        'acoustic_feature_snapshots', 'candidate_sets', 'feedback_candidates',
        'feedback_exposures', 'machine_predictions', 'generation_runs',
        'evidence_review_assignments', 'confidence_self_reports',
        'confidence_coach_labels', 'confidence_peer_labels',
        'praise_helpfulness', 'correction_decisions', 'paragraph_decisions',
        'feedback_revisions', 'voice_album_admissions', 'accepted_flagships',
        'root_phrases', 'processing_stage_runs', 'dataset_releases',
        'dataset_split_assignments', 'dataset_release_items',
        'dataset_exclusions',
        -- 0299 add_learning_surface_exposure_receipts.sql, lines 119-120
        'learning_surface_presentations', 'learning_surface_exposure_receipts'
    ] LOOP
        IF to_regclass('public.' || table_name) IS NULL THEN
            RAISE NOTICE '0388: public.% is not present here; skipped',
                table_name;
            CONTINUE;
        END IF;
        -- Reads are preserved, never widened: SELECT comes back only where
        -- service_role held it before this file ran (second run: it holds
        -- what the first run granted, so the result is the same).
        could_read := EXISTS (SELECT 1 FROM pg_roles
                               WHERE rolname = 'service_role')
                      AND has_table_privilege('service_role',
                                              'public.' || table_name,
                                              'SELECT');
        EXECUTE format('REVOKE ALL ON TABLE public.%I FROM PUBLIC',
                       table_name);
        FOREACH role_name IN ARRAY ARRAY[
            'anon', 'authenticated', 'service_role'
        ] LOOP
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
                EXECUTE format('REVOKE ALL ON TABLE public.%I FROM %I',
                               table_name, role_name);
            END IF;
        END LOOP;
        IF could_read THEN
            EXECUTE format('GRANT SELECT ON TABLE public.%I TO service_role',
                           table_name);
        ELSE
            RAISE NOTICE '0388: service_role could not read public.% before; '
                         'left without SELECT', table_name;
        END IF;
    END LOOP;
END;
$$;
