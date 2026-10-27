-- 0497 · A deleted account keeps no way to sign in (Privacy 3.8 sections 7
--        and 9; founder 2026-10-21, N95: where the code and the docs
--        disagree, the docs win and the code is the bug).
--
-- WHAT WAS THERE. When an account deletion's seven days had passed, the purge
-- erased the person's data and complete_phase1_account_deletion_v1 (0422)
-- marked the request done. Nothing touched Supabase Auth: the auth user kept
-- the sign-in email, the sign-in phone (WhatsApp sign-in, N214), the password
-- hash, the name and picture a Google or LinkedIn sign-in brought, its linked
-- sign-ins and its sessions. Privacy 3.8 says account records are deleted when
-- the account is closed (section 7) and names the only three things that
-- survive (section 9); the sign-in email and phone are not among them.
--
-- WHY A SCRUB AND NOT A DELETE. The auth user's id is kept. Deleting the row
-- would cascade (ON DELETE CASCADE) into owner_principals, the row every
-- retained record points at, and into user_consents and user_consent_events
-- (the older terms records, kept as authorization evidence). The proof-of-
-- processing records and the training-choice record (ml_consent_events) point
-- at owner_principals ON DELETE RESTRICT, so the delete would either fail or,
-- where it cascades, erase what section 9 says survives. Supabase's own soft
-- delete keeps a SHA-256 of the user id and the email, which anyone holding
-- the email can check against the known id; this writes NULL instead. Every
-- statement is an UPDATE: no row is deleted, here or when the functions run.
--
-- WHAT THIS ADDS.
--
--   1. erase_deleted_account_sign_in_v1(request): for an account deletion
--      whose purge is done, the auth user of the request's own principal
--      keeps its id and nothing to sign in with or be recognised by:
--        - auth.users: email, phone, pending email and phone changes and the
--          password hash cleared; every one-time token blanked; the profile a
--          sign-in brought (raw_user_meta_data) emptied; raw_app_meta_data
--          keeps only `provider` and `providers` (how the account was made,
--          which the sign-up count reads, 0494); banned until 9999-12-31;
--          deleted_at set, as Supabase marks a deleted user;
--        - auth.identities (the linked Google, LinkedIn, email and phone
--          sign-ins): the email, name and picture each brought emptied, and
--          the provider's id for the person replaced by the identity's own
--          id, so no Google or LinkedIn sign-in finds this user again;
--        - auth.sessions ended now, with their device and IP address
--          cleared; every refresh token revoked; one-time codes no longer
--          name the email or phone they went to; a sign-in flow in progress
--          loses the provider's tokens; a second factor loses its phone and
--          name and is no longer verified.
--      Supabase Auth's own clean-up deletes ended sessions, revoked refresh
--      tokens, old sign-in flows and unverified factors after a day or three.
--      account_sign_in_remains_v1 (3) checks the result, and the function
--      raises ACCOUNT_SIGN_IN_REMAINS if anything is left, so nothing is
--      reported done that is not. A request whose principal has no user (a
--      guest) has no sign-in to erase.
--   2. complete_phase1_account_deletion_v1: 0422's body; it erases the
--      sign-in, in the same transaction, just before it marks the request
--      done. Done therefore means the sign-in is gone too. If the erasure
--      raises, the request stays 'started' and the next completion run tries
--      again (services/deletion_completion.py reports the error code).
--   3. account_sign_in_remains_v1(user), and account_sign_ins_left_v1(): the
--      done account deletions whose sign-in is still there, which the
--      completion run erases (accounts deleted before this file). Ids and
--      dates only.
--
-- WHAT THIS DOES NOT DO. It changes no row when it runs: the accounts
-- already deleted are erased by the completion run, only when the web
-- service has PHASE1_PURGE_EXECUTION_ENABLED (a dry run lists them as
-- would_erase_sign_in). It does not touch auth.audit_log_entries (Supabase
-- Auth's own log, which names an email in its payload and has no user
-- column), a project deletion (the account stays), or a purge of another kind
-- (service termination, lawful deletion), which an operator runs by hand.
--
-- BEFORE MERGING. The function owner (the role that runs this file,
-- `postgres` on Supabase) must be able to UPDATE auth.users,
-- auth.identities, auth.sessions, auth.refresh_tokens, auth.one_time_tokens,
-- auth.flow_state and auth.mfa_factors. Supabase keeps that for `postgres`;
-- without it the erasure raises, nothing is marked done, and each run reports
-- the error. No environment variable is read, so no Railway service needs
-- configuration first. The application code that calls these functions ships
-- in the same change. An outside review (GPT or Grok) through the founder
-- before merge.
--
-- ADDITIVE AND IDEMPOTENT. CREATE OR REPLACE FUNCTION only; nothing dropped,
-- no row changed.

BEGIN;

-- ── 3 first: what still signs in, or names the person ─────────────────────

CREATE OR REPLACE FUNCTION public.account_sign_in_remains_v1(
    p_user UUID
) RETURNS BOOLEAN
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = ''
AS $$
    SELECT EXISTS (
               SELECT 1 FROM auth.users u
                WHERE u.id = p_user
                  AND (u.email IS NOT NULL OR u.phone IS NOT NULL
                       OR u.encrypted_password IS NOT NULL
                       OR COALESCE(u.raw_user_meta_data, '{}'::jsonb) <> '{}'::jsonb
                       OR u.banned_until IS NULL OR u.banned_until <= now()))
        OR EXISTS (
               SELECT 1 FROM auth.identities i
                WHERE i.user_id = p_user
                  AND (i.identity_data <> '{}'::jsonb
                       OR i.provider_id <> i.id::text))
        OR EXISTS (
               SELECT 1 FROM auth.sessions s
                WHERE s.user_id = p_user
                  AND (s.not_after IS NULL OR s.not_after > now()
                       OR s.user_agent IS NOT NULL OR s.ip IS NOT NULL))
        OR EXISTS (
               SELECT 1 FROM auth.refresh_tokens t
                WHERE t.user_id::text = p_user::text
                  AND t.revoked IS NOT TRUE)
        OR EXISTS (
               SELECT 1 FROM auth.one_time_tokens t
                WHERE t.user_id = p_user AND t.relates_to <> '')
        OR EXISTS (
               SELECT 1 FROM auth.flow_state f
                WHERE f.user_id = p_user
                  AND (COALESCE(f.provider_access_token, '') <> ''
                       OR COALESCE(f.provider_refresh_token, '') <> ''))
        OR EXISTS (
               SELECT 1 FROM auth.mfa_factors f
                WHERE f.user_id = p_user
                  AND (f.phone IS NOT NULL
                       OR COALESCE(f.friendly_name, '') <> ''
                       OR f.status::text <> 'unverified'));
$$;

REVOKE ALL ON FUNCTION public.account_sign_in_remains_v1(UUID)
    FROM PUBLIC, anon, authenticated, service_role;

-- The done account deletions whose sign-in is still there.
CREATE OR REPLACE FUNCTION public.account_sign_ins_left_v1()
RETURNS TABLE (request_id UUID, completes_after TIMESTAMPTZ)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = ''
AS $$
    SELECT request.id, request.completes_after
      FROM public.account_deletion_requests request
      JOIN public.owner_principals principal
        ON principal.id = request.acquisition_principal_id
     WHERE request.state = 'done'
       AND principal.user_id IS NOT NULL
       AND public.account_sign_in_remains_v1(principal.user_id)
     ORDER BY request.completed_at, request.id;
$$;

REVOKE ALL ON FUNCTION public.account_sign_ins_left_v1()
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.account_sign_ins_left_v1()
    TO service_role;

-- ── 1. Erase the sign-in of an account whose purge is done ────────────────

CREATE OR REPLACE FUNCTION public.erase_deleted_account_sign_in_v1(
    p_request_id UUID
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER SET search_path = ''
AS $$
DECLARE
    request public.account_deletion_requests;
    purge_state TEXT;
    account_user UUID;
    user_found BOOLEAN;
BEGIN
    SELECT * INTO request FROM public.account_deletion_requests
     WHERE id = p_request_id;
    IF request.id IS NULL THEN
        RAISE EXCEPTION 'ACCOUNT_DELETION_NOT_FOUND';
    END IF;
    IF request.state NOT IN ('started', 'done') THEN
        RAISE EXCEPTION 'ACCOUNT_DELETION_NOT_STARTED';
    END IF;
    SELECT purge.state INTO purge_state FROM public.data_purge_requests purge
     WHERE purge.id = request.purge_request_id;
    IF purge_state IS DISTINCT FROM 'done' THEN
        RAISE EXCEPTION 'ACCOUNT_PURGE_NOT_DONE';
    END IF;
    SELECT principal.user_id INTO account_user
      FROM public.owner_principals principal
     WHERE principal.id = request.acquisition_principal_id;
    IF account_user IS NULL THEN
        RETURN jsonb_build_object('request_id', request.id, 'user_id', NULL,
                                  'erased', false);
    END IF;

    UPDATE auth.users
       SET email = NULL,
           phone = NULL,
           email_change = '',
           phone_change = '',
           encrypted_password = NULL,
           confirmation_token = '',
           recovery_token = '',
           email_change_token_current = '',
           email_change_token_new = '',
           phone_change_token = '',
           reauthentication_token = '',
           raw_user_meta_data = '{}'::jsonb,
           raw_app_meta_data = jsonb_strip_nulls(jsonb_build_object(
               'provider', raw_app_meta_data -> 'provider',
               'providers', raw_app_meta_data -> 'providers')),
           banned_until = '9999-12-31 00:00:00+00',
           deleted_at = COALESCE(deleted_at, now()),
           updated_at = now()
     WHERE id = account_user;
    user_found := FOUND;
    UPDATE auth.identities
       SET identity_data = '{}'::jsonb, provider_id = id::text, updated_at = now()
     WHERE user_id = account_user;
    UPDATE auth.sessions
       SET not_after = LEAST(COALESCE(not_after, now()), now()),
           user_agent = NULL, ip = NULL, updated_at = now()
     WHERE user_id = account_user;
    UPDATE auth.refresh_tokens
       SET revoked = true, updated_at = now()
     WHERE user_id::text = account_user::text AND revoked IS NOT TRUE;
    UPDATE auth.one_time_tokens
       SET relates_to = '', updated_at = now()
     WHERE user_id = account_user;
    UPDATE auth.flow_state
       SET provider_access_token = '', provider_refresh_token = '',
           updated_at = now()
     WHERE user_id = account_user;
    UPDATE auth.mfa_factors
       SET phone = NULL, friendly_name = '', status = 'unverified',
           updated_at = now()
     WHERE user_id = account_user;

    IF public.account_sign_in_remains_v1(account_user) THEN
        RAISE EXCEPTION 'ACCOUNT_SIGN_IN_REMAINS';
    END IF;
    RETURN jsonb_build_object('request_id', request.id,
                              'user_id', account_user, 'erased', user_found);
END;
$$;

REVOKE ALL ON FUNCTION public.erase_deleted_account_sign_in_v1(UUID)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.erase_deleted_account_sign_in_v1(UUID)
    TO service_role;

-- ── 2. Done means the sign-in is gone too ─────────────────────────────────

-- 0422's body; only the erasure before the request is marked done is new.
CREATE OR REPLACE FUNCTION public.complete_phase1_account_deletion_v1(
    p_request_id UUID
) RETURNS public.account_deletion_requests
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    request public.account_deletion_requests;
    purge public.data_purge_requests;
    evidence TEXT;
BEGIN
    SELECT * INTO request FROM public.account_deletion_requests
     WHERE id = p_request_id FOR UPDATE;
    IF request.id IS NULL THEN
        RAISE EXCEPTION 'ACCOUNT_DELETION_NOT_FOUND';
    END IF;
    IF request.state = 'done' THEN
        RETURN request;
    END IF;
    IF request.state <> 'started' THEN
        RAISE EXCEPTION 'ACCOUNT_DELETION_NOT_STARTED';
    END IF;
    SELECT * INTO purge FROM public.data_purge_requests
     WHERE id = request.purge_request_id;
    IF purge.id IS NULL OR purge.state IS DISTINCT FROM 'done'
       OR purge.completed_at IS NULL THEN
        RAISE EXCEPTION 'ACCOUNT_PURGE_NOT_DONE';
    END IF;
    SELECT event.evidence_sha256 INTO evidence
      FROM public.data_purge_events event
     WHERE event.purge_request_id = purge.id
       AND event.event_kind = 'completed'
     ORDER BY event.occurred_at DESC, event.id DESC LIMIT 1;
    IF evidence IS NULL THEN
        RAISE EXCEPTION 'ACCOUNT_PURGE_EVIDENCE_MISSING';
    END IF;
    IF EXISTS (
        SELECT 1 FROM public.data_purge_targets target
         WHERE target.purge_request_id = purge.id
           AND (target.state IN ('pending', 'failed', 'unknown')
                OR (target.state IN ('deleted', 'not_found')
                    AND COALESCE(target.remaining_match_count, 1) <> 0))
    ) THEN
        RAISE EXCEPTION 'ACCOUNT_PURGE_TARGETS_UNRESOLVED';
    END IF;
    PERFORM public.erase_deleted_account_sign_in_v1(request.id);
    UPDATE public.account_deletion_requests
       SET state = 'done', completed_at = now(),
           completion_evidence_sha256 = evidence
     WHERE id = request.id
    RETURNING * INTO request;
    RETURN request;
END;
$$;

REVOKE ALL ON FUNCTION public.complete_phase1_account_deletion_v1(UUID)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.complete_phase1_account_deletion_v1(UUID)
    TO service_role;

COMMIT;
