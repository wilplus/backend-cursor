-- 0435 · a corpus import is processed under the founder's corpus basis
-- (founder 2026-10-07, panel answer CO2, decisions log N58: "no need for
-- license check pls; we have it legally recorded and we don't need license
-- to prove it! this version is agreed with the counsel and it is my
-- executive decision")
--
-- WHY. Under PLF1_PROCESSING_AUTHORIZATION_MODE=enforce every provider call
-- (Whisper and the rest) needs a permit from the database, and the only
-- permit writer, issue_phase1_provider_permit_v1, grants one solely on a
-- person's acceptance receipt for the principal that acquired the audio. A
-- corpus import (v2_sessions.source = 'training_import', created by a coach
-- through POST /v2/coach/training-imports) has no acquiring principal and
-- no receipt: the voice on it is not a user of the product, and the
-- importing coach's own acceptance covers the coach's recordings, never a
-- third party's audio (the B-2 class closed by 0355). So every import was
-- refused before Whisper. N58 records ONE founder-held corpus processing
-- basis instead, the separate authorization CLAUDE.md requires; no per-import
-- licence record.
--
-- WHAT. Beside the Phase-1 ledger, never inside it:
--
--   corpus_processing_bases       the founder's basis, one row per decision.
--                                 Seeded with N58. Retire-only: a row's
--                                 retired_at may be set once, nothing else
--                                 ever changes and no row is ever removed.
--   corpus_import_registrations   one row per import, written when the coach
--                                 import route creates it, naming the basis.
--                                 Immutable.
--   corpus_provider_permits       a permit per provider call of an import,
--   corpus_provider_operations    naming the basis (id and decision) and the
--                                 session; the operations ledger beside it.
--   register_corpus_import_v1     the route's registration.
--   issue_corpus_provider_permit_v1, record_corpus_provider_operation_v1
--                                 the permit writer and its event log.
--
-- WHY IT CANNOT AUTHORIZE ANYTHING ELSE. The corpus writer never reads or
-- writes a principal, a receipt or a snapshot, and
-- resolve_phase1_acquisition_principal_v1 is untouched: nothing a person
-- records, as a user or a guest, is ever judged against the corpus basis. A
-- corpus permit is issued only for a session that, at registration AND at
-- every permit, (1) is registered by the import route, (2) has
-- source = 'training_import', (3) has no owner principal and no project
-- (every ordinary and guest Take has an owner), (4) has its registered
-- recording on it with recording_origin = 'admin_import', and (5) whose
-- recording has no Phase-1 acquisition attempt (no user's intake). A forged
-- source flag on an owned Take fails (3); on any session the route did not
-- create it fails (1). The service key cannot write these tables directly:
-- every write privilege is revoked and only the SECURITY DEFINER functions
-- below write them.
--
-- AND THE OTHER WAY ROUND. issue_phase1_provider_permit_v1 (0355) is
-- restated with ONE check added first: it refuses a corpus import (a
-- training_import session, a recording whose own session is one, or a
-- registered import's session or recording)
-- with PROCESSING_SOURCE_IS_CORPUS_IMPORT. 0355's ownership check stays
-- silent for a Take with no owner, and an import has none, so until now a
-- permit for an import could have been minted under any principal holding a
-- receipt, the importing coach's included. The rest of the function is
-- byte-identical, so every Take of a person passes exactly as before.
--
-- PHASE 2 STAYS CLOSED. Dataset releases, training, evaluation and promotion
-- are untouched; every row carries pooled_learning_eligible = false under a
-- CHECK. Nothing trains.
--
-- ADDITIVE AND IDEMPOTENT. CREATE TABLE IF NOT EXISTS, CREATE OR REPLACE,
-- DROP TRIGGER IF EXISTS then CREATE, the seed ON CONFLICT DO NOTHING. No
-- existing table, column or row changes; the one existing function changed
-- is the Phase-1 permit writer, as above. No env var: the switch
-- is the code constant Config.TRAINING_IMPORT_ENABLED (False until the
-- founder flips it), read by services/processing_authorization.py before
-- every corpus permit.
--
-- Rollback (a new forward migration): retire the N58 basis row; every
-- corpus permit is refused from then on.

BEGIN;

-- ── the four tables, written once ──────────────────────────────────────────
-- One text, with the names unqualified: run under search_path = public it
-- builds the real tables; run under search_path = pg_temp with ON COMMIT
-- DROP (%1$s) it builds the reference copy the guard at the end of this file
-- compares them with. A temporary function, gone with this session.
CREATE OR REPLACE FUNCTION pg_temp.corpus_shape_0435(on_commit text)
RETURNS text
LANGUAGE sql IMMUTABLE
AS $shape$
SELECT format($ddl$
CREATE TABLE IF NOT EXISTS corpus_processing_bases (
    id                       uuid        PRIMARY KEY,
    decision_ref             text        NOT NULL UNIQUE,
    decided_on               date        NOT NULL,
    recorded_by              text        NOT NULL,
    legal_basis              text        NOT NULL,
    founder_note             text        NOT NULL,
    covers_source            text        NOT NULL,
    pooled_learning_eligible boolean     NOT NULL DEFAULT false,
    retired_at               timestamptz,
    created_at               timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT corpus_processing_bases_decision_shape
        CHECK (decision_ref ~ '^N[0-9]+$'),
    CONSTRAINT corpus_processing_bases_founder_only
        CHECK (recorded_by = 'founder'),
    CONSTRAINT corpus_processing_bases_basis_present
        CHECK (char_length(btrim(legal_basis)) > 0
               AND char_length(btrim(founder_note)) > 0),
    CONSTRAINT corpus_processing_bases_imports_only
        CHECK (covers_source = 'training_import'),
    CONSTRAINT corpus_processing_bases_never_pooled
        CHECK (NOT pooled_learning_eligible),
    -- The pair a permit names, so its decision can never disagree with its id.
    CONSTRAINT corpus_processing_bases_id_decision UNIQUE (id, decision_ref)
)%1$s;
ALTER TABLE corpus_processing_bases ENABLE ROW LEVEL SECURITY;
-- At most ONE basis is in force for a source at any moment, so which basis an
-- import is registered under is never a choice by recency.
CREATE UNIQUE INDEX IF NOT EXISTS corpus_processing_bases_one_in_force
    ON corpus_processing_bases (covers_source)
    WHERE retired_at IS NULL;

CREATE TABLE IF NOT EXISTS corpus_import_registrations (
    session_id     uuid        PRIMARY KEY,
    recording_id   uuid        NOT NULL UNIQUE,
    basis_id       uuid        NOT NULL REFERENCES
        corpus_processing_bases(id) ON DELETE RESTRICT,
    registered_via text        NOT NULL,
    registered_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT corpus_import_registrations_route_only
        CHECK (registered_via = 'coach_import_route')
)%1$s;
ALTER TABLE corpus_import_registrations ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS corpus_provider_permits (
    id                       uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    basis_id                 uuid        NOT NULL,
    basis_decision_ref       text        NOT NULL,
    session_id               uuid        NOT NULL REFERENCES
        corpus_import_registrations(session_id) ON DELETE RESTRICT,
    recording_id             uuid        NOT NULL,
    provider                 text        NOT NULL,
    operation_kind           text        NOT NULL,
    minimum_data_manifest    jsonb       NOT NULL,
    issued_at                timestamptz NOT NULL DEFAULT now(),
    expires_at               timestamptz NOT NULL,
    revoked_at               timestamptz,
    status                   text        NOT NULL DEFAULT 'issued',
    started_at               timestamptz,
    finished_at              timestamptz,
    idempotency_key          text        NOT NULL UNIQUE,
    pooled_learning_eligible boolean     NOT NULL DEFAULT false,
    CONSTRAINT corpus_provider_permits_analysis_only
        CHECK (operation_kind IN ('audio_download', 'transcription',
                                  'feedback_generation',
                                  'ideal_text_generation')),
    -- One provider call per permit: issued -> (started) -> used | failed, or
    -- issued -> cancelled. Expiry is expires_at alone (no status mirrors it).
    -- revoked_at is set exactly when the permit is cancelled.
    CONSTRAINT corpus_provider_permits_status_check
        CHECK (status IN ('issued', 'used', 'failed', 'cancelled')),
    CONSTRAINT corpus_provider_permits_revocation_matches_status
        CHECK ((status = 'cancelled') = (revoked_at IS NOT NULL)),
    CONSTRAINT corpus_provider_permits_finish_matches_status
        CHECK ((status IN ('used', 'failed')) = (finished_at IS NOT NULL)
               AND (finished_at IS NULL OR started_at IS NOT NULL)),
    CONSTRAINT corpus_provider_permits_expiry_check
        CHECK (expires_at > issued_at),
    CONSTRAINT corpus_provider_permits_never_pooled
        CHECK (NOT pooled_learning_eligible),
    CONSTRAINT corpus_provider_permits_basis_pair
        FOREIGN KEY (basis_id, basis_decision_ref)
        REFERENCES corpus_processing_bases (id, decision_ref)
        ON DELETE RESTRICT
)%1$s;
ALTER TABLE corpus_provider_permits ENABLE ROW LEVEL SECURITY;
CREATE INDEX IF NOT EXISTS idx_corpus_provider_permits_session
    ON corpus_provider_permits (session_id);

CREATE TABLE IF NOT EXISTS corpus_provider_operations (
    id                     uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    permit_id              uuid        NOT NULL REFERENCES
        corpus_provider_permits(id) ON DELETE RESTRICT,
    provider_operation_ref text,
    event_kind             text        NOT NULL,
    error_code             text,
    occurred_at            timestamptz NOT NULL DEFAULT now(),
    metadata               jsonb       NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT corpus_provider_operations_event_check
        CHECK (event_kind IN ('started', 'completed', 'failed', 'cancelled',
                              'deleted', 'delete_failed'))
)%1$s;
ALTER TABLE corpus_provider_operations ENABLE ROW LEVEL SECURITY;
$ddl$, on_commit)
$shape$;

-- Every column (type, NOT NULL, default), constraint, index and the RLS flag
-- of the four tables in schema s, one line each, schema names removed so the
-- public tables and the pg_temp copy print alike.
CREATE OR REPLACE FUNCTION pg_temp.corpus_shape_seen_0435(s text)
RETURNS SETOF text
LANGUAGE sql STABLE
AS $seen$
WITH t(name) AS (VALUES ('corpus_processing_bases'),
                        ('corpus_import_registrations'),
                        ('corpus_provider_permits'),
                        ('corpus_provider_operations')),
r AS (SELECT t.name, to_regclass(s || '.' || t.name) AS rel FROM t)
SELECT regexp_replace(line, '(public|pg_temp(_[0-9]+)?)\.', '', 'g')
  FROM (
    SELECT r.name || ' column ' || a.attname || ' '
           || format_type(a.atttypid, a.atttypmod)
           || CASE WHEN a.attnotnull THEN ' not null' ELSE '' END
           || COALESCE(' default ' || pg_get_expr(d.adbin, d.adrelid), '') AS line
      FROM r
      JOIN pg_attribute a ON a.attrelid = r.rel AND a.attnum > 0
                         AND NOT a.attisdropped
      LEFT JOIN pg_attrdef d ON d.adrelid = r.rel AND d.adnum = a.attnum
    UNION ALL
    SELECT r.name || ' constraint ' || c.conname || ' '
           || pg_get_constraintdef(c.oid)
      FROM r JOIN pg_constraint c ON c.conrelid = r.rel
    UNION ALL
    SELECT r.name || ' index ' || pg_get_indexdef(i.indexrelid)
      FROM r JOIN pg_index i ON i.indrelid = r.rel
    UNION ALL
    SELECT r.name || ' row level security ' || k.relrowsecurity
      FROM r JOIN pg_class k ON k.oid = r.rel
    UNION ALL
    SELECT r.name || ' missing' FROM r WHERE r.rel IS NULL
  ) shape(line)
$seen$;

DO $$
DECLARE
    caller_path text := current_setting('search_path');
BEGIN
    PERFORM set_config('search_path', 'public', true);
    EXECUTE pg_temp.corpus_shape_0435('');
    PERFORM set_config('search_path', caller_path, true);
END $$;
COMMENT ON TABLE public.corpus_processing_bases IS
    'The founder''s processing basis for training-corpus imports (0435, N58). '
    'Not a person''s consent and not a per-import licence: one recorded basis, '
    'agreed with counsel, under which an import registered by the coach import '
    'route may be analysed. Retire-only. Authorizes no Phase-2 use.';
COMMENT ON TABLE public.corpus_import_registrations IS
    'One row per training-corpus import created by POST '
    '/v2/coach/training-imports (0435, N58): the session, its recording and '
    'the basis it is processed under. No principal, no user id. Immutable.';
COMMENT ON TABLE public.corpus_provider_permits IS
    'A provider permit for one call on a training-corpus import (0435, N58), '
    'granted under the corpus basis it names, never under a person''s '
    'acceptance. Separate from the Phase-1 permit ledger by design.';

INSERT INTO public.corpus_processing_bases (
    id, decision_ref, decided_on, recorded_by, legal_basis, founder_note,
    covers_source
) VALUES (
    '0d580435-5858-4058-8058-000000000058', 'N58', DATE '2026-10-07',
    'founder',
    'legal basis recorded by the founder, agreed with counsel',
    'no need for license check pls; we have it legally recorded and we don''t '
    'need license to prove it! this version is agreed with the counsel and it '
    'is my executive decision',
    'training_import'
) ON CONFLICT (decision_ref) DO NOTHING;

-- ── what never changes ─────────────────────────────────────────────────────

-- A basis may be retired once, with immediate effect (retired_at is the
-- moment it was retired, never a date in the future); nothing else about it
-- ever changes and it is never removed. Raised before anything could be returned for any other
-- operation, so the same function serves the statement-level trigger.
CREATE OR REPLACE FUNCTION public.corpus_processing_bases_retire_only()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
BEGIN
    IF TG_OP = 'UPDATE'
       AND OLD.retired_at IS NULL AND NEW.retired_at IS NOT NULL
       AND NEW.retired_at <= now()
       AND (NEW.id, NEW.decision_ref, NEW.decided_on, NEW.recorded_by,
            NEW.legal_basis, NEW.founder_note, NEW.covers_source,
            NEW.pooled_learning_eligible, NEW.created_at)
           IS NOT DISTINCT FROM
           (OLD.id, OLD.decision_ref, OLD.decided_on, OLD.recorded_by,
            OLD.legal_basis, OLD.founder_note, OLD.covers_source,
            OLD.pooled_learning_eligible, OLD.created_at)
    THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'CORPUS_BASIS_IMMUTABLE: a corpus basis is only ever retired'
        USING ERRCODE = 'check_violation';
END;
$$;

CREATE OR REPLACE FUNCTION public.corpus_import_registrations_never_change()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
BEGIN
    RAISE EXCEPTION 'CORPUS_REGISTRATION_IMMUTABLE: an import keeps its registration'
        USING ERRCODE = 'check_violation';
END;
$$;

-- The permit and operation ledgers keep their history: an operation is never
-- changed or removed, and a permit is never removed (only the permit writer
-- and the event recorder above change a permit's state).
CREATE OR REPLACE FUNCTION public.corpus_provider_ledger_keeps_history()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
BEGIN
    RAISE EXCEPTION 'CORPUS_LEDGER_IMMUTABLE: the corpus provider ledger keeps its history'
        USING ERRCODE = 'check_violation';
END;
$$;

DROP TRIGGER IF EXISTS corpus_provider_operations_never_change
    ON public.corpus_provider_operations;
CREATE TRIGGER corpus_provider_operations_never_change
    BEFORE UPDATE OR DELETE ON public.corpus_provider_operations
    FOR EACH ROW EXECUTE FUNCTION public.corpus_provider_ledger_keeps_history();
DROP TRIGGER IF EXISTS corpus_provider_operations_never_truncate
    ON public.corpus_provider_operations;
CREATE TRIGGER corpus_provider_operations_never_truncate
    BEFORE TRUNCATE ON public.corpus_provider_operations
    FOR EACH STATEMENT EXECUTE FUNCTION public.corpus_provider_ledger_keeps_history();
-- A permit's request never changes after it is issued; only its state does
-- (status, started_at, finished_at, revoked_at, written by the event
-- recorder above).
CREATE OR REPLACE FUNCTION public.corpus_provider_permit_request_never_changes()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
BEGIN
    IF (NEW.id, NEW.basis_id, NEW.basis_decision_ref, NEW.session_id,
        NEW.recording_id, NEW.provider, NEW.operation_kind,
        NEW.minimum_data_manifest, NEW.issued_at, NEW.expires_at,
        NEW.idempotency_key, NEW.pooled_learning_eligible)
       IS DISTINCT FROM
       (OLD.id, OLD.basis_id, OLD.basis_decision_ref, OLD.session_id,
        OLD.recording_id, OLD.provider, OLD.operation_kind,
        OLD.minimum_data_manifest, OLD.issued_at, OLD.expires_at,
        OLD.idempotency_key, OLD.pooled_learning_eligible)
    THEN
        RAISE EXCEPTION 'CORPUS_LEDGER_IMMUTABLE: a permit keeps its request'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS corpus_provider_permits_request_never_changes
    ON public.corpus_provider_permits;
CREATE TRIGGER corpus_provider_permits_request_never_changes
    BEFORE UPDATE ON public.corpus_provider_permits
    FOR EACH ROW EXECUTE FUNCTION public.corpus_provider_permit_request_never_changes();
DROP TRIGGER IF EXISTS corpus_provider_permits_never_removed
    ON public.corpus_provider_permits;
CREATE TRIGGER corpus_provider_permits_never_removed
    BEFORE DELETE ON public.corpus_provider_permits
    FOR EACH ROW EXECUTE FUNCTION public.corpus_provider_ledger_keeps_history();
DROP TRIGGER IF EXISTS corpus_provider_permits_never_truncate
    ON public.corpus_provider_permits;
CREATE TRIGGER corpus_provider_permits_never_truncate
    BEFORE TRUNCATE ON public.corpus_provider_permits
    FOR EACH STATEMENT EXECUTE FUNCTION public.corpus_provider_ledger_keeps_history();

DROP TRIGGER IF EXISTS corpus_processing_bases_retire_only
    ON public.corpus_processing_bases;
CREATE TRIGGER corpus_processing_bases_retire_only
    BEFORE UPDATE OR DELETE ON public.corpus_processing_bases
    FOR EACH ROW EXECUTE FUNCTION public.corpus_processing_bases_retire_only();
DROP TRIGGER IF EXISTS corpus_processing_bases_never_truncate
    ON public.corpus_processing_bases;
CREATE TRIGGER corpus_processing_bases_never_truncate
    BEFORE TRUNCATE ON public.corpus_processing_bases
    FOR EACH STATEMENT EXECUTE FUNCTION public.corpus_processing_bases_retire_only();

DROP TRIGGER IF EXISTS corpus_import_registrations_never_change
    ON public.corpus_import_registrations;
CREATE TRIGGER corpus_import_registrations_never_change
    BEFORE UPDATE OR DELETE ON public.corpus_import_registrations
    FOR EACH ROW EXECUTE FUNCTION public.corpus_import_registrations_never_change();
DROP TRIGGER IF EXISTS corpus_import_registrations_never_truncate
    ON public.corpus_import_registrations;
CREATE TRIGGER corpus_import_registrations_never_truncate
    BEFORE TRUNCATE ON public.corpus_import_registrations
    FOR EACH STATEMENT EXECUTE FUNCTION public.corpus_import_registrations_never_change();

-- ── the one eligibility rule, checked at registration and at every permit ──

-- Read through to_jsonb so a schema without one of the columns refuses
-- (the value reads NULL) instead of failing to compile.
CREATE OR REPLACE FUNCTION public.corpus_import_refusal_v1(
    p_session_id uuid, p_recording_id uuid
) RETURNS text
LANGUAGE plpgsql STABLE
SET search_path = public, pg_temp
AS $$
DECLARE
    take jsonb;
    recording jsonb;
BEGIN
    SELECT to_jsonb(s) INTO take FROM public.v2_sessions s WHERE s.id = p_session_id;
    IF take IS NULL OR take->>'source' IS DISTINCT FROM 'training_import' THEN
        RETURN 'CORPUS_SOURCE_NOT_IMPORT';
    END IF;
    -- Every ordinary Take and every guest Take has an owner principal; a
    -- corpus import never has one, nor a project.
    IF take->>'owner_principal_id' IS NOT NULL OR take->>'project_id' IS NOT NULL THEN
        RETURN 'CORPUS_SESSION_HAS_OWNER';
    END IF;
    SELECT to_jsonb(r) INTO recording FROM public.recordings r
     WHERE r.id = p_recording_id;
    IF recording IS NULL
       OR recording->>'session_v2_id' IS DISTINCT FROM p_session_id::text
       OR recording->>'recording_origin' IS DISTINCT FROM 'admin_import' THEN
        RETURN 'CORPUS_RECORDING_NOT_IMPORT';
    END IF;
    -- A recording a person handed over through the Phase-1 intake is theirs,
    -- whatever its session says.
    IF EXISTS (SELECT 1 FROM public.processing_recording_attempts attempt
                WHERE attempt.recording_id = p_recording_id) THEN
        RETURN 'CORPUS_RECORDING_ACQUIRED';
    END IF;
    RETURN NULL;
END;
$$;

-- ── the route's registration ───────────────────────────────────────────────

CREATE OR REPLACE FUNCTION public.register_corpus_import_v1(
    p_session_id uuid, p_recording_id uuid
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    existing public.corpus_import_registrations;
    basis public.corpus_processing_bases;
    refusal text;
BEGIN
    IF p_session_id IS NULL OR p_recording_id IS NULL THEN
        RAISE EXCEPTION 'CORPUS_IMPORT_UNREGISTERED';
    END IF;
    SELECT * INTO existing FROM public.corpus_import_registrations
     WHERE session_id = p_session_id;
    IF existing.session_id IS NULL THEN
        refusal := public.corpus_import_refusal_v1(p_session_id, p_recording_id);
        IF refusal IS NOT NULL THEN RAISE EXCEPTION '%', refusal; END IF;
        -- The one basis in force for imports (a unique index allows no
        -- second); none in force refuses. FOR SHARE: a retirement running at
        -- the same moment waits for this registration, or wins and leaves
        -- no basis in force here.
        SELECT * INTO basis FROM public.corpus_processing_bases
         WHERE covers_source = 'training_import' AND retired_at IS NULL
           FOR SHARE;
        IF basis.id IS NULL THEN RAISE EXCEPTION 'CORPUS_BASIS_ABSENT'; END IF;
        INSERT INTO public.corpus_import_registrations (
            session_id, recording_id, basis_id, registered_via
        ) VALUES (
            p_session_id, p_recording_id, basis.id, 'coach_import_route'
        ) ON CONFLICT (session_id) DO NOTHING;
        SELECT * INTO existing FROM public.corpus_import_registrations
         WHERE session_id = p_session_id;
    END IF;
    IF existing.recording_id IS DISTINCT FROM p_recording_id THEN
        RAISE EXCEPTION 'CORPUS_IMPORT_CONFLICT';
    END IF;
    SELECT * INTO basis FROM public.corpus_processing_bases
     WHERE id = existing.basis_id;
    RETURN jsonb_build_object(
        'session_id', existing.session_id,
        'recording_id', existing.recording_id,
        'basis_id', basis.id,
        'basis_decision_ref', basis.decision_ref,
        'registered_at', existing.registered_at
    );
END;
$$;

-- ── the permit writer ──────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION public.issue_corpus_provider_permit_v1(
    p_session_id uuid, p_recording_id uuid, p_provider text,
    p_operation_kind text, p_minimum_data_manifest jsonb,
    p_idempotency_key text, p_ttl_seconds integer DEFAULT 900
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    registration public.corpus_import_registrations;
    basis public.corpus_processing_bases;
    permit public.corpus_provider_permits;
    refusal text;
BEGIN
    -- Every input that defines the request is required.
    IF p_session_id IS NULL OR p_recording_id IS NULL THEN
        RAISE EXCEPTION 'CORPUS_IMPORT_UNREGISTERED';
    END IF;
    IF p_provider IS NULL OR char_length(btrim(p_provider)) = 0 THEN
        RAISE EXCEPTION 'CORPUS_PROVIDER_REQUIRED';
    END IF;
    IF p_minimum_data_manifest IS NULL
       OR jsonb_typeof(p_minimum_data_manifest) <> 'object' THEN
        RAISE EXCEPTION 'CORPUS_MANIFEST_REQUIRED';
    END IF;
    SELECT * INTO registration FROM public.corpus_import_registrations
     WHERE session_id = p_session_id;
    IF registration.session_id IS NULL
       OR registration.recording_id <> p_recording_id THEN
        RAISE EXCEPTION 'CORPUS_IMPORT_UNREGISTERED';
    END IF;
    -- Re-checked on every permit: a session that has since been given an
    -- owner, or had its source changed, is not a corpus import any more.
    refusal := public.corpus_import_refusal_v1(
        registration.session_id, registration.recording_id);
    IF refusal IS NOT NULL THEN RAISE EXCEPTION '%', refusal; END IF;
    -- FOR SHARE, as at registration: no permit is issued under a basis
    -- being retired at the same moment.
    SELECT * INTO basis FROM public.corpus_processing_bases
     WHERE id = registration.basis_id
       AND covers_source = 'training_import'
       AND retired_at IS NULL
       FOR SHARE;
    IF basis.id IS NULL THEN RAISE EXCEPTION 'CORPUS_BASIS_ABSENT'; END IF;
    IF p_operation_kind IS NULL OR p_operation_kind NOT IN (
        'audio_download', 'transcription', 'feedback_generation',
        'ideal_text_generation'
    ) THEN
        RAISE EXCEPTION 'CORPUS_OPERATION_NOT_COVERED';
    END IF;
    IF p_ttl_seconds IS NULL OR p_ttl_seconds < 30 OR p_ttl_seconds > 3600 THEN
        RAISE EXCEPTION 'INVALID_PERMIT_TTL';
    END IF;
    IF p_idempotency_key IS NULL OR char_length(btrim(p_idempotency_key)) = 0 THEN
        RAISE EXCEPTION 'IDEMPOTENCY_KEY_REQUIRED';
    END IF;
    INSERT INTO public.corpus_provider_permits (
        basis_id, basis_decision_ref, session_id, recording_id, provider,
        operation_kind, minimum_data_manifest, expires_at, idempotency_key
    ) VALUES (
        basis.id, basis.decision_ref, registration.session_id,
        registration.recording_id, p_provider, p_operation_kind,
        p_minimum_data_manifest,
        now() + make_interval(secs => p_ttl_seconds), p_idempotency_key
    ) ON CONFLICT (idempotency_key) DO NOTHING;
    SELECT * INTO permit FROM public.corpus_provider_permits
     WHERE idempotency_key = p_idempotency_key;
    -- A replayed key returns its permit only when the request is the same
    -- request: same import, recording, provider, operation, manifest and
    -- basis. Anything else is a different request under a reused key.
    IF (permit.session_id, permit.recording_id, permit.provider,
        permit.operation_kind, permit.minimum_data_manifest, permit.basis_id)
       IS DISTINCT FROM
       (registration.session_id, p_recording_id, p_provider,
        p_operation_kind, p_minimum_data_manifest, basis.id) THEN
        RAISE EXCEPTION 'IDEMPOTENCY_CONFLICT';
    END IF;
    RETURN jsonb_build_object(
        'permit_id', permit.id, 'provider', permit.provider,
        'operation_kind', permit.operation_kind,
        'expires_at', permit.expires_at,
        'basis_id', permit.basis_id,
        'basis_decision_ref', permit.basis_decision_ref,
        'session_id', permit.session_id,
        'recording_id', permit.recording_id,
        'status', permit.status
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.record_corpus_provider_operation_v1(
    p_permit_id uuid, p_event_kind text, p_provider_operation_ref text,
    p_error_code text, p_metadata jsonb
) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    event_id uuid;
    permit public.corpus_provider_permits;
BEGIN
    IF p_event_kind IS NULL OR p_event_kind NOT IN (
        'started', 'completed', 'failed', 'cancelled', 'deleted', 'delete_failed'
    ) THEN RAISE EXCEPTION 'INVALID_PROVIDER_EVENT'; END IF;
    -- Locked, so two events for one permit can never both pass the order
    -- check below.
    SELECT * INTO permit FROM public.corpus_provider_permits
     WHERE id = p_permit_id FOR UPDATE;
    IF permit.id IS NULL THEN RAISE EXCEPTION 'PROVIDER_PERMIT_INVALID'; END IF;
    -- The one order a permit's events may take (one provider call each):
    --   started              only on an issued, unexpired permit, once;
    --   completed | failed   only after started, once, ending it (used | failed);
    --   cancelled            only on an issued permit never started;
    --   deleted | delete_failed  (removing the provider's copy) only after
    --                        the call ended, at any time after.
    IF p_event_kind = 'started' THEN
        IF permit.status <> 'issued' OR permit.started_at IS NOT NULL
           OR permit.expires_at <= now() THEN
            RAISE EXCEPTION 'PROVIDER_PERMIT_INVALID';
        END IF;
        UPDATE public.corpus_provider_permits SET started_at = now()
         WHERE id = p_permit_id;
    ELSIF p_event_kind IN ('completed', 'failed') THEN
        IF permit.status <> 'issued' OR permit.started_at IS NULL THEN
            RAISE EXCEPTION 'PROVIDER_EVENT_OUT_OF_ORDER';
        END IF;
        UPDATE public.corpus_provider_permits
           SET status = CASE p_event_kind WHEN 'completed' THEN 'used'
                                          ELSE 'failed' END,
               finished_at = now()
         WHERE id = p_permit_id;
    ELSIF p_event_kind = 'cancelled' THEN
        IF permit.status <> 'issued' OR permit.started_at IS NOT NULL THEN
            RAISE EXCEPTION 'PROVIDER_EVENT_OUT_OF_ORDER';
        END IF;
        UPDATE public.corpus_provider_permits
           SET status = 'cancelled', revoked_at = now()
         WHERE id = p_permit_id;
    ELSE
        IF permit.status NOT IN ('used', 'failed') THEN
            RAISE EXCEPTION 'PROVIDER_EVENT_OUT_OF_ORDER';
        END IF;
    END IF;
    INSERT INTO public.corpus_provider_operations (
        permit_id, provider_operation_ref, event_kind, error_code, metadata
    ) VALUES (
        p_permit_id, p_provider_operation_ref, p_event_kind, p_error_code,
        COALESCE(p_metadata, '{}'::jsonb)
    ) RETURNING id INTO event_id;
    RETURN event_id;
END;
$$;

-- ── the Phase-1 writer refuses a corpus import ──────────────────────────────
-- 0355's issue_phase1_provider_permit_v1, restated byte for byte with one
-- check added first (marked 0435 inside). Nothing else in it changes.

CREATE OR REPLACE FUNCTION public.issue_phase1_provider_permit_v1(
    p_acquisition_principal_id UUID, p_source_take_id UUID,
    p_source_recording_id UUID, p_provider TEXT, p_operation_kind TEXT,
    p_pseudonymous_subject_ref TEXT, p_minimum_data_manifest JSONB,
    p_idempotency_key TEXT, p_ttl_seconds INTEGER DEFAULT 900
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    auth JSONB;
    receipt processing_authorization_receipts;
    purpose TEXT;
    snapshot_id UUID;
    permit processing_provider_permits;
    authority_hash TEXT;
    carryover processing_job_carryovers;
    source_job phase1_processing_jobs;
    source_principal UUID;
    session_owner UUID;
BEGIN
    -- 0435 (N58, founder 2026-10-07). A corpus import is never processed
    -- under a person's acceptance, the importing coach's included: the B-2
    -- check below stays silent for a Take with no owner, and an import has
    -- none. Its provider calls are permitted only by
    -- issue_corpus_provider_permit_v1, under the founder's corpus basis.
    -- Refused on positive evidence only (the named session's source, the
    -- recording's own session's source, the import route's registration), so
    -- every Take of a person passes as before. The recording's own session is
    -- read too, so naming another session beside an import's recording
    -- cannot get it through.
    IF EXISTS (
           SELECT 1 FROM v2_sessions take
            WHERE take.id = p_source_take_id
              AND to_jsonb(take)->>'source' = 'training_import'
       ) OR EXISTS (
           SELECT 1 FROM recordings rec
             JOIN v2_sessions own
               ON own.id::text = to_jsonb(rec)->>'session_v2_id'
            WHERE rec.id = p_source_recording_id
              AND to_jsonb(own)->>'source' = 'training_import'
       ) OR EXISTS (
           SELECT 1 FROM corpus_import_registrations registration
            WHERE registration.session_id = p_source_take_id
               OR registration.recording_id = p_source_recording_id
       )
    THEN
        RAISE EXCEPTION 'PROCESSING_SOURCE_IS_CORPUS_IMPORT';
    END IF;

    -- B-2 (audit 2026-09-22). THIS FUNCTION READ THE AUTHORIZATION OF ONE
    -- PRINCIPAL AND STAMPED IT ONTO ANOTHER PRINCIPAL'S RECORDING. It checked
    -- that p_acquisition_principal_id holds a receipt and then inserted
    -- p_source_take_id / p_source_recording_id verbatim, with no statement
    -- anywhere that those coordinates were that principal's to name. The
    -- auditor minted a permit for P1's recording under P2's receipt, and
    -- processing_authorization_snapshots then held two rows for one recording
    -- naming different principals. Nothing downstream can tell which one is
    -- the truth: the permit lineage attests that the later account authorized
    -- the earlier acquisition.
    --
    -- The check runs FIRST, before the authorization read, so a caller cannot
    -- learn anything about another principal's authorization state by probing
    -- with their recording id.
    IF p_source_recording_id IS NOT NULL THEN
        SELECT attempt.acquisition_principal_id INTO source_principal
          FROM processing_recording_attempts attempt
         WHERE attempt.recording_id = p_source_recording_id;
    END IF;
    IF source_principal IS NOT NULL THEN
        -- The attempt row is the acquisition record itself. It is written
        -- once, at intake, and is authoritative wherever it exists.
        IF source_principal <> p_acquisition_principal_id THEN
            RAISE EXCEPTION 'PROCESSING_SOURCE_PRINCIPAL_MISMATCH';
        END IF;
    ELSIF p_source_take_id IS NOT NULL THEN
        -- No attempt row: every recording acquired while the gate was off.
        -- Product ownership is the only statement left, and claim_guest_owner
        -- rewrites v2_sessions.owner_principal_id when a guest signs up, so
        -- the acquirer is either the session's current owner or a principal
        -- claimed INTO it. Both are accepted; a third principal is not.
        --
        -- A source we cannot place is left alone rather than refused: a
        -- missing session row is an absence of evidence, and turning it into
        -- a refusal would take the live loop down for a data gap this
        -- function did not create. What is provable is enforced; what is not
        -- provable is not invented.
        SELECT take.owner_principal_id INTO session_owner
          FROM v2_sessions take WHERE take.id = p_source_take_id;
        IF session_owner IS NOT NULL
           AND session_owner <> p_acquisition_principal_id
           AND NOT EXISTS (
               SELECT 1 FROM owner_claim_events event
                WHERE event.target_owner_principal_id = session_owner
                  AND event.source_owner_principal_id =
                      p_acquisition_principal_id
           )
        THEN RAISE EXCEPTION 'PROCESSING_SOURCE_PRINCIPAL_MISMATCH'; END IF;
    END IF;

    auth := get_phase1_processing_authorization_v1(p_acquisition_principal_id);
    IF NOT COALESCE((auth->>'authorized')::boolean, false) THEN
        IF p_operation_kind NOT IN (
            'audio_download', 'transcription', 'feedback_generation',
            'ideal_text_generation'
        ) THEN
            RAISE EXCEPTION '%', COALESCE(
                auth->>'code', 'PROCESSING_AUTHORIZATION_REQUIRED'
            );
        END IF;
        SELECT j.* INTO source_job
          FROM phase1_processing_jobs j
          JOIN processing_recording_attempts a
            ON a.id = j.recording_attempt_id
         WHERE j.acquisition_principal_id = p_acquisition_principal_id
           AND a.recording_id = p_source_recording_id
           AND j.job_kind = 'recording_transcription_ranking_feedback'
           AND j.status IN ('pending', 'processing')
         ORDER BY j.created_at DESC LIMIT 1;
        IF source_job.id IS NOT NULL THEN
            SELECT c.* INTO carryover
              FROM processing_job_carryovers c
             WHERE c.processing_job_id = source_job.id
               AND c.acquisition_principal_id = p_acquisition_principal_id
               AND c.exact_operation =
                   'recording_transcription_ranking_feedback'
               AND c.cancelled_at IS NULL
               AND c.cutoff_at <= now() AND c.expires_at > now()
             ORDER BY c.created_at DESC LIMIT 1;
        END IF;
        IF carryover.id IS NULL THEN
            RAISE EXCEPTION '%', COALESCE(
                auth->>'code', 'PROCESSING_AUTHORIZATION_REQUIRED'
            );
        END IF;
    END IF;
    IF p_ttl_seconds < 30 OR p_ttl_seconds > 3600 THEN
        RAISE EXCEPTION 'INVALID_PERMIT_TTL';
    END IF;
    purpose := CASE p_operation_kind
        WHEN 'audio_download' THEN 'recording_voice_processing'
        WHEN 'transcription' THEN 'transcription_feedback'
        WHEN 'feedback_generation' THEN 'transcription_feedback'
        WHEN 'ideal_text_generation' THEN 'transcription_feedback'
        WHEN 'coach_delivery' THEN 'coach_review'
        ELSE NULL END;
    IF purpose IS NULL THEN RAISE EXCEPTION 'INVALID_PROVIDER_OPERATION'; END IF;
    IF COALESCE((auth->>'authorized')::boolean, false) THEN
        SELECT * INTO receipt FROM processing_authorization_receipts
         WHERE id = (auth->>'receipt_id')::uuid;
    ELSE
        SELECT r.* INTO receipt
          FROM processing_authorization_snapshots s
          JOIN processing_authorization_receipts r ON r.id = s.receipt_id
         WHERE s.id = source_job.authorization_snapshot_id;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM processing_authorization_receipt_purposes
         WHERE receipt_id = receipt.id AND purpose_id = purpose
    ) THEN RAISE EXCEPTION 'PROCESSING_PURPOSE_NOT_AUTHORIZED'; END IF;

    authority_hash := encode(extensions.digest(concat_ws(':', receipt.id::text,
        p_source_take_id::text, p_source_recording_id::text,
        p_provider, p_operation_kind, p_idempotency_key), 'sha256'), 'hex');
    INSERT INTO processing_authorization_snapshots (
        acquisition_principal_id, receipt_id, policy_id, purpose_id,
        operation_kind, source_take_id, source_recording_id,
        authority_evidence_sha256, pooled_learning_eligible
    ) VALUES (
        p_acquisition_principal_id, receipt.id, receipt.policy_id, purpose,
        p_operation_kind, p_source_take_id, p_source_recording_id,
        authority_hash, false
    ) RETURNING id INTO snapshot_id;
    INSERT INTO processing_provider_permits (
        acquisition_principal_id, authorization_snapshot_id, provider,
        operation_kind, pseudonymous_subject_ref, minimum_data_manifest,
        expires_at, idempotency_key
    ) VALUES (
        p_acquisition_principal_id, snapshot_id, p_provider,
        p_operation_kind, p_pseudonymous_subject_ref,
        p_minimum_data_manifest, now() + make_interval(secs => p_ttl_seconds),
        p_idempotency_key
    ) ON CONFLICT (idempotency_key) DO NOTHING;
    SELECT * INTO permit FROM processing_provider_permits
     WHERE idempotency_key = p_idempotency_key;
    IF permit.acquisition_principal_id <> p_acquisition_principal_id
       OR permit.operation_kind <> p_operation_kind THEN
        RAISE EXCEPTION 'IDEMPOTENCY_CONFLICT';
    END IF;
    RETURN jsonb_build_object(
        'permit_id', permit.id, 'provider', permit.provider,
        'operation_kind', permit.operation_kind,
        'expires_at', permit.expires_at,
        'authorization_snapshot_id', permit.authorization_snapshot_id
    );
END;
$$;

REVOKE ALL ON FUNCTION public.issue_phase1_provider_permit_v1(
    UUID,UUID,UUID,TEXT,TEXT,TEXT,JSONB,TEXT,INTEGER
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.issue_phase1_provider_permit_v1(
    UUID,UUID,UUID,TEXT,TEXT,TEXT,JSONB,TEXT,INTEGER
) TO service_role;

-- ── who may call and write ─────────────────────────────────────────────────
-- The three entry points are the service key's alone; the helper and the
-- trigger functions are nobody's. Every write privilege on the four tables
-- is revoked from every API role, the service key included, so only the
-- definer functions above write them; the service key keeps SELECT.

REVOKE ALL ON FUNCTION public.register_corpus_import_v1(uuid, uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.issue_corpus_provider_permit_v1(uuid, uuid, text, text, jsonb, text, integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.record_corpus_provider_operation_v1(uuid, text, text, text, jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.corpus_import_refusal_v1(uuid, uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.corpus_processing_bases_retire_only() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.corpus_import_registrations_never_change() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.corpus_provider_ledger_keeps_history() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.corpus_provider_permit_request_never_changes() FROM PUBLIC;
REVOKE ALL ON TABLE public.corpus_processing_bases FROM PUBLIC;
REVOKE ALL ON TABLE public.corpus_import_registrations FROM PUBLIC;
REVOKE ALL ON TABLE public.corpus_provider_permits FROM PUBLIC;
REVOKE ALL ON TABLE public.corpus_provider_operations FROM PUBLIC;

DO $$
DECLARE
    v_role text;
BEGIN
    FOREACH v_role IN ARRAY ARRAY['anon', 'authenticated', 'service_role'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = v_role) THEN
            EXECUTE format('REVOKE ALL ON FUNCTION public.register_corpus_import_v1(uuid, uuid) FROM %I', v_role);
            EXECUTE format('REVOKE ALL ON FUNCTION public.issue_corpus_provider_permit_v1(uuid, uuid, text, text, jsonb, text, integer) FROM %I', v_role);
            EXECUTE format('REVOKE ALL ON FUNCTION public.record_corpus_provider_operation_v1(uuid, text, text, text, jsonb) FROM %I', v_role);
            EXECUTE format('REVOKE ALL ON FUNCTION public.corpus_import_refusal_v1(uuid, uuid) FROM %I', v_role);
            EXECUTE format('REVOKE ALL ON FUNCTION public.corpus_processing_bases_retire_only() FROM %I', v_role);
            EXECUTE format('REVOKE ALL ON FUNCTION public.corpus_import_registrations_never_change() FROM %I', v_role);
            EXECUTE format('REVOKE ALL ON FUNCTION public.corpus_provider_ledger_keeps_history() FROM %I', v_role);
            EXECUTE format('REVOKE ALL ON FUNCTION public.corpus_provider_permit_request_never_changes() FROM %I', v_role);
            EXECUTE format('REVOKE ALL ON TABLE public.corpus_processing_bases FROM %I', v_role);
            EXECUTE format('REVOKE ALL ON TABLE public.corpus_import_registrations FROM %I', v_role);
            EXECUTE format('REVOKE ALL ON TABLE public.corpus_provider_permits FROM %I', v_role);
            EXECUTE format('REVOKE ALL ON TABLE public.corpus_provider_operations FROM %I', v_role);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT EXECUTE ON FUNCTION public.register_corpus_import_v1(uuid, uuid) TO service_role;
        GRANT EXECUTE ON FUNCTION public.issue_corpus_provider_permit_v1(uuid, uuid, text, text, jsonb, text, integer) TO service_role;
        GRANT EXECUTE ON FUNCTION public.record_corpus_provider_operation_v1(uuid, text, text, text, jsonb) TO service_role;
        GRANT SELECT ON TABLE public.corpus_processing_bases TO service_role;
        GRANT SELECT ON TABLE public.corpus_import_registrations TO service_role;
        GRANT SELECT ON TABLE public.corpus_provider_permits TO service_role;
        GRANT SELECT ON TABLE public.corpus_provider_operations TO service_role;
    END IF;
END $$;



-- ── refuse an older shape ──────────────────────────────────────────────────
-- CREATE ... IF NOT EXISTS and ON CONFLICT DO NOTHING keep whatever already
-- exists. So, on every run, the four tables must be exactly the shape above
-- and the N58 row must be the founder's, or the migration stops here (the
-- deploy fails loudly; nothing is half-applied, the file is one transaction).
-- The shape is compared with a reference copy built from the same text on the
-- same server, so it never depends on how a server version prints a
-- definition, and any difference counts: a column, a type, a default, a
-- CHECK body, a UNIQUE, a foreign key, an index or RLS, missing or extra.
-- Last in the file: the copy lives in pg_temp until COMMIT drops it, and
-- nothing runs after it that could mistake it for the real tables.
DO $$
DECLARE
    caller_path text := current_setting('search_path');
    differences text;
BEGIN
    PERFORM set_config('search_path', 'pg_temp', true);
    EXECUTE pg_temp.corpus_shape_0435(' ON COMMIT DROP');
    PERFORM set_config('search_path', caller_path, true);
    SELECT string_agg(line, '; ' ORDER BY line) INTO differences
      FROM ((SELECT * FROM pg_temp.corpus_shape_seen_0435('public')
             EXCEPT SELECT * FROM pg_temp.corpus_shape_seen_0435('pg_temp'))
            UNION
            (SELECT * FROM pg_temp.corpus_shape_seen_0435('pg_temp')
             EXCEPT SELECT * FROM pg_temp.corpus_shape_seen_0435('public'))
           ) AS d(line);
    IF differences IS NOT NULL THEN
        RAISE EXCEPTION 'CORPUS_SCHEMA_MISMATCH: %', differences;
    END IF;
    -- The whole N58 row as the founder recorded it. retired_at is not
    -- compared: retiring N58 later is allowed, and a rerun must not fail then.
    IF NOT EXISTS (
        SELECT 1 FROM public.corpus_processing_bases
         WHERE id = '0d580435-5858-4058-8058-000000000058'
           AND decision_ref = 'N58' AND decided_on = DATE '2026-10-07'
           AND recorded_by = 'founder' AND covers_source = 'training_import'
           AND legal_basis = 'legal basis recorded by the founder, agreed with counsel'
           AND founder_note = 'no need for license check pls; we have it legally recorded and we don''t '
                              'need license to prove it! this version is agreed with the counsel and it '
                              'is my executive decision'
           AND NOT pooled_learning_eligible
    ) THEN
        RAISE EXCEPTION 'CORPUS_BASIS_SEED_MISMATCH: the N58 row is not the founder''s';
    END IF;
END $$;

COMMIT;
