-- PENDING: not in manifest.txt; never run without separate founder approval.
--
-- This installs a database-owner-only two-step cleanup. PREPARE snapshots the
-- exact affected values and their SHA-256 inside PostgreSQL. APPLY accepts only
-- that immutable snapshot, re-verifies its hash and row counts, then strips the
-- retired fields. The application service role receives preview access only.

BEGIN;

CREATE TABLE IF NOT EXISTS public.retired_sex_cleanup_backups (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    payload JSONB NOT NULL,
    payload_sha256 TEXT NOT NULL CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
    preview_counts JSONB NOT NULL,
    prepared_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    applied_at TIMESTAMPTZ,
    founder_authorization_ref TEXT UNIQUE,
    CHECK (applied_at IS NULL OR founder_authorization_ref IS NOT NULL)
);

ALTER TABLE public.retired_sex_cleanup_backups ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.retired_sex_cleanup_backups
    FROM PUBLIC, anon, authenticated, service_role;

CREATE OR REPLACE FUNCTION public.strip_retired_sex_keys_v1(value JSONB)
RETURNS JSONB LANGUAGE plpgsql IMMUTABLE SET search_path = public AS $$
DECLARE item RECORD; output JSONB;
BEGIN
    IF value IS NULL THEN RETURN NULL; END IF;
    IF jsonb_typeof(value) = 'object' THEN
        output := '{}'::jsonb;
        FOR item IN SELECT key, value AS child FROM jsonb_each(value) LOOP
            IF item.key NOT IN ('sex','sex_source','profile_sex','speaker_sex')
            THEN output := output || jsonb_build_object(
                item.key, strip_retired_sex_keys_v1(item.child)
            ); END IF;
        END LOOP;
        RETURN output;
    ELSIF jsonb_typeof(value) = 'array' THEN
        SELECT COALESCE(jsonb_agg(strip_retired_sex_keys_v1(element)), '[]'::jsonb)
          INTO output FROM jsonb_array_elements(value) AS element;
        RETURN output;
    END IF;
    RETURN value;
END;
$$;

CREATE OR REPLACE FUNCTION public.preview_retired_sex_data_cleanup_v1()
RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER STABLE
SET search_path = public AS $$
DECLARE output JSONB := '{}'::jsonb; n BIGINT;
BEGIN
    SELECT count(*) INTO n FROM user_settings WHERE profile_sex IS NOT NULL;
    output := output || jsonb_build_object('user_settings_profile_sex', n);
    SELECT count(*) INTO n FROM v2_sessions
     WHERE intake_context ? 'speaker_sex';
    output := output || jsonb_build_object('session_speaker_sex', n);
    SELECT count(*) INTO n FROM snippets
     WHERE metrics::text ~ '"(sex|sex_source|profile_sex|speaker_sex)"';
    output := output || jsonb_build_object('snippet_metric_documents', n);
    SELECT count(*) INTO n FROM recordings
     WHERE performance_metrics_v2::text ~
           '"(sex|sex_source|profile_sex|speaker_sex)"';
    RETURN output || jsonb_build_object('recording_metric_documents', n);
END;
$$;

CREATE OR REPLACE FUNCTION public.prepare_retired_sex_data_cleanup_v1()
RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE backup_payload JSONB; counts JSONB; backup_id UUID; backup_hash TEXT;
BEGIN
    counts := preview_retired_sex_data_cleanup_v1();
    backup_payload := jsonb_build_object(
        'user_settings', COALESCE((SELECT jsonb_agg(jsonb_build_object(
            'user_id', user_id, 'profile_sex', profile_sex
        ) ORDER BY user_id) FROM user_settings WHERE profile_sex IS NOT NULL), '[]'::jsonb),
        'v2_sessions', COALESCE((SELECT jsonb_agg(jsonb_build_object(
            'id', id, 'speaker_sex', intake_context->'speaker_sex'
        ) ORDER BY id) FROM v2_sessions WHERE intake_context ? 'speaker_sex'), '[]'::jsonb),
        'snippets', COALESCE((SELECT jsonb_agg(jsonb_build_object(
            'id', id, 'metrics', metrics
        ) ORDER BY id) FROM snippets WHERE metrics::text ~
            '"(sex|sex_source|profile_sex|speaker_sex)"'), '[]'::jsonb),
        'recordings', COALESCE((SELECT jsonb_agg(jsonb_build_object(
            'id', id, 'performance_metrics_v2', performance_metrics_v2
        ) ORDER BY id) FROM recordings WHERE performance_metrics_v2::text ~
            '"(sex|sex_source|profile_sex|speaker_sex)"'), '[]'::jsonb)
    );
    backup_hash := encode(digest(backup_payload::text, 'sha256'), 'hex');
    INSERT INTO retired_sex_cleanup_backups (
        payload, payload_sha256, preview_counts
    ) VALUES (backup_payload, backup_hash, counts) RETURNING id INTO backup_id;
    RETURN jsonb_build_object(
        'backup_id', backup_id, 'payload_sha256', backup_hash,
        'preview_counts', counts
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.apply_retired_sex_data_cleanup_v1(
    p_backup_id UUID, p_founder_authorization_ref TEXT
) RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE backup retired_sex_cleanup_backups; current_counts JSONB;
        settings_count BIGINT; session_count BIGINT;
        snippet_count BIGINT; recording_count BIGINT; applied JSONB;
BEGIN
    IF length(btrim(p_founder_authorization_ref)) < 12 THEN
        RAISE EXCEPTION 'FOUNDER_AUTHORIZATION_REFERENCE_REQUIRED'; END IF;
    SELECT * INTO backup FROM retired_sex_cleanup_backups
     WHERE id = p_backup_id FOR UPDATE;
    IF backup.id IS NULL THEN RAISE EXCEPTION 'CLEANUP_BACKUP_NOT_FOUND'; END IF;
    IF encode(digest(backup.payload::text, 'sha256'), 'hex') <>
       backup.payload_sha256 THEN RAISE EXCEPTION 'CLEANUP_BACKUP_HASH_INVALID'; END IF;
    IF backup.applied_at IS NOT NULL THEN
        RETURN jsonb_build_object('already_applied', true,
                                  'preview_counts', backup.preview_counts);
    END IF;
    current_counts := preview_retired_sex_data_cleanup_v1();
    IF current_counts IS DISTINCT FROM backup.preview_counts THEN
        RAISE EXCEPTION 'CLEANUP_PREVIEW_COUNTS_CHANGED'; END IF;

    UPDATE user_settings SET profile_sex = NULL WHERE profile_sex IS NOT NULL;
    GET DIAGNOSTICS settings_count = ROW_COUNT;
    UPDATE v2_sessions SET intake_context = intake_context - 'speaker_sex'
     WHERE intake_context ? 'speaker_sex';
    GET DIAGNOSTICS session_count = ROW_COUNT;
    UPDATE snippets SET metrics = strip_retired_sex_keys_v1(metrics)
     WHERE metrics::text ~ '"(sex|sex_source|profile_sex|speaker_sex)"';
    GET DIAGNOSTICS snippet_count = ROW_COUNT;
    UPDATE recordings
       SET performance_metrics_v2 = strip_retired_sex_keys_v1(performance_metrics_v2)
     WHERE performance_metrics_v2::text ~
           '"(sex|sex_source|profile_sex|speaker_sex)"';
    GET DIAGNOSTICS recording_count = ROW_COUNT;
    applied := jsonb_build_object(
        'user_settings_profile_sex', settings_count,
        'session_speaker_sex', session_count,
        'snippet_metric_documents', snippet_count,
        'recording_metric_documents', recording_count
    );
    IF applied IS DISTINCT FROM backup.preview_counts THEN
        RAISE EXCEPTION 'CLEANUP_APPLIED_COUNTS_MISMATCH'; END IF;
    UPDATE retired_sex_cleanup_backups SET applied_at = now(),
        founder_authorization_ref = p_founder_authorization_ref
     WHERE id = backup.id;
    RETURN jsonb_build_object('already_applied', false,
                              'applied_counts', applied,
                              'backup_sha256', backup.payload_sha256);
END;
$$;

REVOKE ALL ON FUNCTION public.strip_retired_sex_keys_v1(JSONB)
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.preview_retired_sex_data_cleanup_v1()
    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.prepare_retired_sex_data_cleanup_v1()
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.apply_retired_sex_data_cleanup_v1(UUID,TEXT)
    FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.preview_retired_sex_data_cleanup_v1()
    TO service_role;

COMMIT;
