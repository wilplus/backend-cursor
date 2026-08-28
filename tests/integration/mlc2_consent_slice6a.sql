\set ON_ERROR_STOP on

-- Run after migrations 0302-0306 in a disposable PostgreSQL database.
-- The policy/grant/withdrawal fixtures are transactional and roll back.
BEGIN;

INSERT INTO public.owner_principals (id, guest_secret_hash) VALUES (
    'd0000000-0000-4000-8000-000000000001', 'slice6a-founder'
);

SET ROLE service_role;

DO $$
BEGIN
    BEGIN
        PERFORM public.configure_mlc2_consent_policy_v1(
            'SLICE6A-REHEARSAL-BAD-HASH', repeat('0', 64),
            'Slice 6A approved copy', 'slice6a-consent-v1', '1.2', '1.2',
            'isolated-test', '2026-08-28T00:00:00Z', ARRAY['PL', 'EU'],
            '9(2)(a)_when_special_category', 'mlc2/legal/slice6a.json',
            repeat('2', 64), '2026-08-28T00:00:00Z'
        );
        RAISE EXCEPTION 'invalid copy hash unexpectedly configured a policy';
    EXCEPTION WHEN OTHERS THEN
        IF SQLERRM = 'invalid copy hash unexpectedly configured a policy' THEN
            RAISE;
        END IF;
    END;
END;
$$;

SELECT public.configure_mlc2_consent_policy_v1(
    'SLICE6A-REHEARSAL-ONLY',
    'bd79dae940c83a6bdc1be05deb9c9c8b35e0c7ebff2119c9fc0074d7b27c412c',
    'Slice 6A approved copy', 'slice6a-consent-v1', '1.2', '1.2',
    'isolated-test', '2026-08-28T00:00:00Z', ARRAY['PL', 'EU'],
    '9(2)(a)_when_special_category', 'mlc2/legal/slice6a.json',
    repeat('2', 64), '2026-08-28T00:00:00Z'
);

-- Configuration is idempotent only for byte-for-byte identical evidence.
SELECT public.configure_mlc2_consent_policy_v1(
    'SLICE6A-REHEARSAL-ONLY',
    'bd79dae940c83a6bdc1be05deb9c9c8b35e0c7ebff2119c9fc0074d7b27c412c',
    'Slice 6A approved copy', 'slice6a-consent-v1', '1.2', '1.2',
    'isolated-test', '2026-08-28T00:00:00Z', ARRAY['PL', 'EU'],
    '9(2)(a)_when_special_category', 'mlc2/legal/slice6a.json',
    repeat('2', 64), '2026-08-28T00:00:00Z'
);

DO $$
DECLARE
    status JSONB;
BEGIN
    status := public.get_mlc2_principal_consent_status_v1(
        'd0000000-0000-4000-8000-000000000001'
    );
    IF NOT (status ->> 'configured')::boolean
       OR (status ->> 'granted')::boolean
       OR status ->> 'consent_policy_version' <> 'slice6a-consent-v1'
       OR status ->> 'onboarding_copy' <> 'Slice 6A approved copy'
       OR status ->> 'article_6_basis' <> '6(1)(a)' THEN
        RAISE EXCEPTION 'pre-grant status is invalid: %', status;
    END IF;
END;
$$;

SELECT public.accept_mlc2_founder_consent_v1(
    'd0000000-0000-4000-8000-000000000001', repeat('3', 64),
    'supabase-auth-sub-v1', 'verified_account_link', repeat('4', 64),
    'slice6a-rehearsal', 'slice6a-consent-v1', 'PL/EU', '1.2', '1.2',
    '/v2/user/mlc2-consent',
    'slice6a-rehearsal-client', jsonb_build_object(
        'accepted', true,
        'copy_sha256',
        'bd79dae940c83a6bdc1be05deb9c9c8b35e0c7ebff2119c9fc0074d7b27c412c',
        'purposes', jsonb_build_array(
            'personalized_coaching', 'pooled_model_improvement'
        ),
        'checkbox_preselected', false
    ), now() - interval '2 minutes', true, 'slice6a-consent-grant'
);

DO $$
DECLARE
    status JSONB;
BEGIN
    status := public.get_mlc2_principal_consent_status_v1(
        'd0000000-0000-4000-8000-000000000001'
    );
    IF NOT (status ->> 'granted')::boolean
       OR NOT (status ->> 'speaker_bound')::boolean
       OR NULLIF(status ->> 'grant_event_id', '') IS NULL THEN
        RAISE EXCEPTION 'post-grant status is invalid: %', status;
    END IF;
END;
$$;

SELECT public.record_mlc2_consent_withdrawal_v1(
    'd0000000-0000-4000-8000-000000000001',
    (SELECT id FROM public.ml_consent_events
      WHERE idempotency_key = 'slice6a-consent-grant'),
    '/v2/user/mlc2-consent', 'slice6a-rehearsal-client',
    '{"withdrawn":true,"service_access_ends":true}'::jsonb,
    now() - interval '1 minute', 'slice6a-consent-withdrawal'
);

DO $$
DECLARE
    status JSONB;
BEGIN
    status := public.get_mlc2_principal_consent_status_v1(
        'd0000000-0000-4000-8000-000000000001'
    );
    IF (status ->> 'granted')::boolean
       OR NOT EXISTS (
           SELECT 1 FROM public.ml_purge_requests
            WHERE idempotency_key = 'slice6a-consent-withdrawal:purge'
       ) THEN
        RAISE EXCEPTION 'withdrawal/purge status is invalid: %', status;
    END IF;
END;
$$;

RESET ROLE;

DO $$
BEGIN
    IF has_function_privilege(
        'anon',
        'public.configure_mlc2_consent_policy_v1(text,text,text,text,text,text,text,timestamptz,text[],text,text,text,timestamptz)',
        'EXECUTE'
    ) OR has_function_privilege(
        'authenticated',
        'public.get_mlc2_principal_consent_status_v1(uuid)',
        'EXECUTE'
    ) THEN
        RAISE EXCEPTION 'browser role can execute Slice 6A consent RPCs';
    END IF;
END;
$$;

ROLLBACK;
