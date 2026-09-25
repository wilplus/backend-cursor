-- PENDING: not in manifest.txt. Never run without the founder's recorded
-- authorisation AND counsel's review of the prepared list.
--
-- F4 (founder, 2026-09-25): delete what was gathered for training under the
-- bundled-era consent. The DPIA calls that consent defective (§2.4), and
-- legal/mlc2-split-consent-v2.json treats everyone who accepted it as never
-- having validly agreed to training. The locked decisions this file follows:
--   5a  group A, every row;
--   5b  group B too (model_versions here; OpenAI copies and exports by hand,
--       each recorded);
--   5c  consent records (user_consents, ml_consent_events) are KEPT;
--   5d  group D (live tables) is a separate decision — not here;
--   5e  counsel reviews the prepared list before anything is deleted.
-- Group C (the dark MLC-2 foundation) is counted for the preview only.
--
-- WHY PENDING, AND WHY TWO STEPS. The pattern is cleanup_retired_sex_data.sql's
-- and the rule is CLAUDE.md's: cleanup is a separately authorised, previewed
-- operation, never a side effect of a migration running on boot. Nothing in
-- this file runs until someone applies it by hand. Once applied:
--
--   preview   counts, per table that exists (service_role may call it);
--   prepare   snapshots EXACTLY which rows (by primary key) and which stored
--             objects would go, with a SHA-256 of that list (owner only);
--   objects   scripts/bundled_era_erasure_storage.py deletes each listed
--             object and records the outcome (service_role, via two
--             functions that can do nothing else);
--   apply     accepts only that snapshot, by its hash, with a founder
--             authorisation reference, a counsel review reference and the
--             record of external copies deleted by hand; refuses while any
--             listed object has no recorded outcome (files first, then rows —
--             the account purge's order); re-checks every row is still there;
--             then deletes them past the retired-write guard, which it
--             disables for its own transaction only (owner only).
--
-- THE GUARD. add_phase1_processing_boundary.sql puts a BEFORE INSERT OR UPDATE
-- OR DELETE trigger on training_labels, shadow_predictions, model_versions,
-- reflection_clips and stress_snippets. apply is the only way past it: ALTER
-- TABLE … DISABLE TRIGGER inside the function's own transaction, ENABLE again
-- before it returns. If anything raises in between, the whole transaction —
-- the DISABLE included — rolls back.
--
-- Unknown production shapes. Two of these tables (stress_snippets,
-- snippet_labels) predate the migrations directory and exist only in
-- production. So nothing here assumes a column: each table's single-column
-- primary key is read from the catalogue (a table without one stops prepare),
-- and its stored-object references are every non-null text value in a column
-- whose name says it holds one (path, url, key, file, audio, storage, bucket).
-- The storage script decides which of those are ours; a foreign URL is
-- recorded as not_ours, never guessed at.

BEGIN;

CREATE TABLE IF NOT EXISTS public.bundled_era_erasure_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    payload JSONB NOT NULL,
    payload_sha256 TEXT NOT NULL CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
    prepared_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    applied_at TIMESTAMPTZ,
    founder_authorization_ref TEXT UNIQUE,
    counsel_review_ref TEXT,
    external_copies JSONB,
    applied_counts JSONB,
    CHECK (applied_at IS NULL OR (
        founder_authorization_ref IS NOT NULL
        AND counsel_review_ref IS NOT NULL
        AND jsonb_typeof(external_copies) = 'array'
    ))
);
ALTER TABLE public.bundled_era_erasure_snapshots ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.bundled_era_erasure_snapshots
    FROM PUBLIC, anon, authenticated, service_role;

CREATE TABLE IF NOT EXISTS public.bundled_era_erasure_objects (
    snapshot_id UUID NOT NULL
        REFERENCES public.bundled_era_erasure_snapshots(id) ON DELETE RESTRICT,
    ref TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('deleted', 'absent', 'not_ours')),
    detail TEXT,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (snapshot_id, ref)
);
ALTER TABLE public.bundled_era_erasure_objects ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.bundled_era_erasure_objects
    FROM PUBLIC, anon, authenticated, service_role;

-- The one list. Group A (5a) and group B's table (5b). Order is delete order:
-- dependants before what they point at, as far as the migrations show.
CREATE OR REPLACE FUNCTION public.bundled_era_erasure_tables_v1()
RETURNS TEXT[] LANGUAGE sql IMMUTABLE SET search_path = public AS $$
    SELECT ARRAY[
        'recording_review_annotations', 'recording_reviews',
        'snippet_labels', 'acoustic_labels', 'training_labels',
        'shadow_predictions', 'reflection_clips', 'stress_snippets',
        'strong_sides_library', 'admin_annotations_log', 'model_versions'
    ]::TEXT[];
$$;

-- Counted for the preview, never deleted here (group C, not decided).
CREATE OR REPLACE FUNCTION public.bundled_era_count_only_tables_v1()
RETURNS TEXT[] LANGUAGE sql IMMUTABLE SET search_path = public AS $$
    SELECT ARRAY[
        'ml_object_artifacts', 'ml_evidence_spans', 'ml_canonical_events',
        'ml_candidate_sets'
    ]::TEXT[];
$$;

CREATE OR REPLACE FUNCTION public.bundled_era_table_exists_v1(p_table TEXT)
RETURNS BOOLEAN LANGUAGE sql STABLE SET search_path = public AS $$
    SELECT EXISTS (
        SELECT 1 FROM pg_catalog.pg_class c
          JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = 'public' AND c.relname = p_table
           AND c.relkind IN ('r', 'p'));
$$;

CREATE OR REPLACE FUNCTION public.preview_bundled_era_erasure_v1()
RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER STABLE
SET search_path = public AS $$
DECLARE t TEXT; n BIGINT; erase JSONB := '{}'::jsonb; counted JSONB := '{}'::jsonb;
        acceptances JSONB := '[]'::jsonb;
BEGIN
    FOREACH t IN ARRAY bundled_era_erasure_tables_v1() LOOP
        IF bundled_era_table_exists_v1(t) THEN
            EXECUTE format('SELECT count(*) FROM public.%I', t) INTO n;
            erase := erase || jsonb_build_object(t, n);
        END IF;
    END LOOP;
    FOREACH t IN ARRAY bundled_era_count_only_tables_v1() LOOP
        IF bundled_era_table_exists_v1(t) THEN
            EXECUTE format('SELECT count(*) FROM public.%I', t) INTO n;
            counted := counted || jsonb_build_object(t, n);
        END IF;
    END LOOP;
    -- DPIA OPEN-1: how many people accepted which terms version.
    IF bundled_era_table_exists_v1('user_consents') THEN
        SELECT COALESCE(jsonb_agg(jsonb_build_object(
                   'terms_version', terms_version, 'people', people)
                   ORDER BY terms_version), '[]'::jsonb)
          INTO acceptances
          FROM (SELECT terms_version, count(DISTINCT user_id) AS people
                  FROM public.user_consents GROUP BY terms_version) grouped;
    END IF;
    RETURN jsonb_build_object(
        'erase_rows', erase, 'count_only_rows', counted,
        'terms_acceptances', acceptances,
        'kept', jsonb_build_array('user_consents', 'ml_consent_events'));
END;
$$;

CREATE OR REPLACE FUNCTION public.bundled_era_primary_key_v1(p_table TEXT)
RETURNS TEXT LANGUAGE plpgsql STABLE SET search_path = public AS $$
DECLARE columns TEXT[];
BEGIN
    SELECT array_agg(a.attname ORDER BY a.attnum) INTO columns
      FROM pg_catalog.pg_index i
      JOIN pg_catalog.pg_attribute a
        ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
     WHERE i.indrelid = format('public.%I', p_table)::regclass
       AND i.indisprimary;
    IF columns IS NULL OR cardinality(columns) <> 1 THEN
        RAISE EXCEPTION 'BUNDLED_ERA_TABLE_WITHOUT_SINGLE_PRIMARY_KEY:%', p_table;
    END IF;
    RETURN columns[1];
END;
$$;

CREATE OR REPLACE FUNCTION public.prepare_bundled_era_erasure_v1()
RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE t TEXT; pk TEXT; col TEXT; ids JSONB; refs JSONB; tables JSONB := '{}'::jsonb;
        all_refs JSONB := '[]'::jsonb; payload JSONB; digest TEXT; snapshot UUID;
BEGIN
    FOREACH t IN ARRAY bundled_era_erasure_tables_v1() LOOP
        CONTINUE WHEN NOT bundled_era_table_exists_v1(t);
        pk := bundled_era_primary_key_v1(t);
        EXECUTE format(
            'SELECT COALESCE(jsonb_agg(%I::text ORDER BY %I::text), ''[]''::jsonb) FROM public.%I',
            pk, pk, t) INTO ids;
        refs := '[]'::jsonb;
        FOR col IN
            SELECT a.attname FROM pg_catalog.pg_attribute a
             WHERE a.attrelid = format('public.%I', t)::regclass
               AND a.attnum > 0 AND NOT a.attisdropped
               AND a.atttypid IN ('text'::regtype, 'varchar'::regtype)
               AND a.attname ~ '(path|url|key|file|audio|storage|bucket)'
             ORDER BY a.attnum
        LOOP
            EXECUTE format(
                'SELECT COALESCE(jsonb_agg(DISTINCT %I), ''[]''::jsonb) FROM public.%I WHERE %I IS NOT NULL AND length(%I) > 0',
                col, t, col, col) INTO refs;
            all_refs := all_refs || COALESCE(refs, '[]'::jsonb);
        END LOOP;
        tables := tables || jsonb_build_object(t, jsonb_build_object(
            'primary_key', pk, 'ids', ids, 'rows', jsonb_array_length(ids)));
    END LOOP;
    SELECT COALESCE(jsonb_agg(DISTINCT value ORDER BY value), '[]'::jsonb)
      INTO all_refs FROM jsonb_array_elements_text(all_refs) AS value;
    payload := jsonb_build_object('tables', tables, 'storage_refs', all_refs);
    digest := encode(extensions.digest(payload::text, 'sha256'), 'hex');
    INSERT INTO public.bundled_era_erasure_snapshots (payload, payload_sha256)
    VALUES (payload, digest) RETURNING id INTO snapshot;
    RETURN jsonb_build_object(
        'snapshot_id', snapshot, 'sha256', digest,
        'rows', (SELECT jsonb_object_agg(k, v->'rows') FROM jsonb_each(tables) AS e(k, v)),
        'storage_refs', jsonb_array_length(all_refs));
END;
$$;

-- The storage script's only two doors: read one snapshot's refs, and record
-- what happened to one of them.
CREATE OR REPLACE FUNCTION public.bundled_era_erasure_storage_refs_v1(p_snapshot UUID)
RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER STABLE
SET search_path = public AS $$
DECLARE refs JSONB;
BEGIN
    SELECT payload->'storage_refs' INTO refs
      FROM public.bundled_era_erasure_snapshots
     WHERE id = p_snapshot AND applied_at IS NULL;
    IF refs IS NULL THEN RAISE EXCEPTION 'BUNDLED_ERA_SNAPSHOT_NOT_OPEN'; END IF;
    RETURN refs;
END;
$$;

CREATE OR REPLACE FUNCTION public.record_bundled_era_object_v1(
    p_snapshot UUID, p_ref TEXT, p_outcome TEXT, p_detail TEXT
) RETURNS VOID LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM public.bundled_era_erasure_snapshots s
         WHERE s.id = p_snapshot AND s.applied_at IS NULL
    ) THEN RAISE EXCEPTION 'BUNDLED_ERA_SNAPSHOT_NOT_OPEN'; END IF;
    INSERT INTO public.bundled_era_erasure_objects (snapshot_id, ref, outcome, detail)
    VALUES (p_snapshot, p_ref, p_outcome, p_detail)
    ON CONFLICT (snapshot_id, ref) DO UPDATE
       SET outcome = EXCLUDED.outcome, detail = EXCLUDED.detail,
           recorded_at = now();
END;
$$;

CREATE OR REPLACE FUNCTION public.apply_bundled_era_erasure_v1(
    p_snapshot UUID, p_sha256 TEXT, p_founder_authorization_ref TEXT,
    p_counsel_review_ref TEXT, p_external_copies JSONB
) RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE snap public.bundled_era_erasure_snapshots; t TEXT; pk TEXT; ids TEXT[];
        present BIGINT; removed BIGINT; guarded BOOLEAN; counts JSONB := '{}'::jsonb;
        missing BIGINT;
BEGIN
    SELECT * INTO snap FROM public.bundled_era_erasure_snapshots
     WHERE id = p_snapshot FOR UPDATE;
    IF snap.id IS NULL THEN RAISE EXCEPTION 'BUNDLED_ERA_SNAPSHOT_NOT_FOUND'; END IF;
    IF snap.applied_at IS NOT NULL THEN RAISE EXCEPTION 'BUNDLED_ERA_SNAPSHOT_ALREADY_APPLIED'; END IF;
    IF lower(coalesce(p_sha256, '')) <> snap.payload_sha256
       OR encode(extensions.digest(snap.payload::text, 'sha256'), 'hex') <> snap.payload_sha256
    THEN RAISE EXCEPTION 'BUNDLED_ERA_SNAPSHOT_HASH_MISMATCH'; END IF;
    IF length(trim(coalesce(p_founder_authorization_ref, ''))) = 0 THEN
        RAISE EXCEPTION 'BUNDLED_ERA_FOUNDER_AUTHORIZATION_REQUIRED'; END IF;
    IF length(trim(coalesce(p_counsel_review_ref, ''))) = 0 THEN
        RAISE EXCEPTION 'BUNDLED_ERA_COUNSEL_REVIEW_REQUIRED'; END IF;
    IF jsonb_typeof(p_external_copies) IS DISTINCT FROM 'array' THEN
        RAISE EXCEPTION 'BUNDLED_ERA_EXTERNAL_COPIES_RECORD_REQUIRED'; END IF;
    -- Files first: every listed object must have a recorded outcome.
    SELECT count(*) INTO missing
      FROM jsonb_array_elements_text(snap.payload->'storage_refs') AS listed(value)
     WHERE NOT EXISTS (
         SELECT 1 FROM public.bundled_era_erasure_objects o
          WHERE o.snapshot_id = snap.id AND o.ref = listed.value);
    IF missing > 0 THEN
        RAISE EXCEPTION 'BUNDLED_ERA_OBJECTS_NOT_RESOLVED:%', missing; END IF;

    FOREACH t IN ARRAY bundled_era_erasure_tables_v1() LOOP
        CONTINUE WHEN NOT (snap.payload->'tables' ? t);
        pk := snap.payload->'tables'->t->>'primary_key';
        SELECT ARRAY(SELECT jsonb_array_elements_text(snap.payload->'tables'->t->'ids'))
          INTO ids;
        EXECUTE format('SELECT count(*) FROM public.%I WHERE %I::text = ANY($1)', t, pk)
           INTO present USING ids;
        IF present <> cardinality(ids) THEN
            RAISE EXCEPTION 'BUNDLED_ERA_ROWS_CHANGED_SINCE_PREPARE:%', t; END IF;
        guarded := EXISTS (
            SELECT 1 FROM pg_catalog.pg_trigger g
             WHERE g.tgrelid = format('public.%I', t)::regclass
               AND g.tgname = t || '_retired_write_guard');
        IF guarded THEN
            EXECUTE format('ALTER TABLE public.%I DISABLE TRIGGER %I', t, t || '_retired_write_guard');
        END IF;
        EXECUTE format('DELETE FROM public.%I WHERE %I::text = ANY($1)', t, pk) USING ids;
        GET DIAGNOSTICS removed = ROW_COUNT;
        IF guarded THEN
            EXECUTE format('ALTER TABLE public.%I ENABLE TRIGGER %I', t, t || '_retired_write_guard');
        END IF;
        IF removed <> cardinality(ids) THEN
            RAISE EXCEPTION 'BUNDLED_ERA_DELETE_COUNT_MISMATCH:%', t; END IF;
        counts := counts || jsonb_build_object(t, removed);
    END LOOP;

    UPDATE public.bundled_era_erasure_snapshots
       SET applied_at = now(),
           founder_authorization_ref = trim(p_founder_authorization_ref),
           counsel_review_ref = trim(p_counsel_review_ref),
           external_copies = p_external_copies,
           applied_counts = counts
     WHERE id = snap.id;
    RETURN jsonb_build_object('snapshot_id', snap.id, 'deleted_rows', counts);
END;
$$;

-- Owner only, except the preview and the storage script's two doors.
REVOKE ALL ON FUNCTION public.bundled_era_erasure_tables_v1() FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.bundled_era_count_only_tables_v1() FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.bundled_era_table_exists_v1(TEXT) FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.bundled_era_primary_key_v1(TEXT) FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.prepare_bundled_era_erasure_v1() FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.apply_bundled_era_erasure_v1(UUID, TEXT, TEXT, TEXT, JSONB)
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.preview_bundled_era_erasure_v1() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.preview_bundled_era_erasure_v1() TO service_role;
REVOKE ALL ON FUNCTION public.bundled_era_erasure_storage_refs_v1(UUID) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.bundled_era_erasure_storage_refs_v1(UUID) TO service_role;
REVOKE ALL ON FUNCTION public.record_bundled_era_object_v1(UUID, TEXT, TEXT, TEXT) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.record_bundled_era_object_v1(UUID, TEXT, TEXT, TEXT) TO service_role;

COMMIT;
