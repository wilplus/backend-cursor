-- 0422 · A deletion completes by itself after seven days (founder
--        2026-10-05, decisions log N48.4: Q14 A, Q17 A, Q19 A; PLF-T2,
--        PLF-T3, PLF-T4, L5).
--
-- THE FOUNDER'S WORDS. "Account deletion completes by itself after a 7-day
-- cancel window; a person acts only on rows no rule decides." "Speakers may
-- delete one project, after Q14." "After a deletion request the app shows a
-- one-line ended state."
--
-- WHAT WAS THERE. "Delete my account" called request_phase1_purge_v1, which
-- wrote a data_purge_requests row and a processing_service_blocks row at
-- once. Nothing could cancel it: the block is permanent and the open purge
-- request makes nineteen functions treat the person as being erased (0378).
-- Nothing finished it either: an operator had to run
-- scripts/run_phase1_data_purge.py by hand.
--
-- WHAT THIS ADDS.
--
--   1. account_deletion_requests: the person's request, kept apart from the
--      purge exactly as 0364 keeps project_deletion_requests apart. It holds
--      the seven-day window (completes_after = request + 7 days). While it is
--      pending the person is blocked at once, through the one status
--      function (2), and in-flight jobs, permits and carryovers are cancelled
--      as 0310's request does. Nothing is deleted while it is pending, so
--      the requester may cancel until completes_after; cancelling lifts the
--      block, because the block IS the pending request. When the window has
--      passed, start_due_account_deletion_v1 creates the real purge request
--      through request_phase1_purge_v1 (the permanent block, the purge row,
--      the 'requested' event) and the existing orchestrator runs it.
--      complete_phase1_account_deletion_v1 marks the request done only on
--      verified terminal evidence: the purge is 'done', its 'completed'
--      event exists, and no target is unresolved (L5, PLF-T4).
--   2. get_phase1_processing_authorization_v1 (0358) counts a pending,
--      started or finished account deletion as a block. Every caller
--      (require_current, recording intake, job sync, provider permits)
--      already reads it. Nothing else in it changes.
--   3. Learning stops for a person whose service is ending (PLF-T2,
--      PLF-T3): phase1_learning_stopped_v1 says so for an account deletion
--      that was not cancelled, or a termination/deletion block in effect.
--      At the request their pairs become not releasable
--      (stop_phase1_learning_v1); the weekly refresh (0405) keeps them so
--      while it holds, so the existing withdrawal path voids any release
--      that carried them; a training copy (0375) is refused; a pair not
--      releasable never joins a fine-tune run (0406 reads releasable).
--      request_phase1_purge_v1 (0310) gains the same stop for every kind it
--      blocks, and nothing else.
--   4. Project deletion (0364, 0380) keeps its seven days: the owner may
--      cancel only before due_at, and start_due_project_deletion_v1 confirms
--      a request once due_at has passed, as the system rather than an
--      operator. The operator's confirm (0380) is unchanged.
--   5. deletion_completion_lease: one row, so two completion runs never work
--      on the same purge at once.
--   6. Account deletions requested before this file (their data_purge_requests
--      rows) are carried into account_deletion_requests as 'started' (or
--      'done' with their evidence), under their own ids, so the status read
--      and the completion run see them. They were never cancellable.
--
-- WHAT THIS DOES NOT DO. It deletes nothing and runs no purge: the purge is
-- run by the application (services/deletion_completion.py), only when the
-- web service has PHASE1_PURGE_EXECUTION_ENABLED, the same kill switch the
-- operator script reads. A purge that meets rows no rule decides still stops
-- at review_required and deletes nothing (N14.3 stands: four append-only
-- tables stay external_review until retention schedule v1.4).
--
-- ADDITIVE AND IDEMPOTENT. CREATE TABLE/INDEX IF NOT EXISTS, CREATE OR
-- REPLACE FUNCTION, DROP TRIGGER IF EXISTS for this file's own trigger, and
-- an INSERT ... WHERE NOT EXISTS carry-over. No table, column or constraint
-- is dropped; no existing row is altered. No environment variable is read,
-- so no Railway service needs configuration first. The application code
-- that calls these functions ships in the same change.

BEGIN;

-- ── 1. The account deletion request ────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.account_deletion_requests (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    acquisition_principal_id    UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    state                       TEXT NOT NULL DEFAULT 'pending' CHECK (state IN (
        'pending', 'cancelled', 'started', 'done'
    )),
    requested_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    completes_after             TIMESTAMPTZ NOT NULL,
    cancelled_at                TIMESTAMPTZ NULL,
    started_at                  TIMESTAMPTZ NULL,
    completed_at                TIMESTAMPTZ NULL,
    purge_request_id            UUID NULL
        REFERENCES public.data_purge_requests(id) ON DELETE RESTRICT,
    completion_evidence_sha256  TEXT NULL CHECK (
        completion_evidence_sha256 IS NULL
        OR completion_evidence_sha256 ~ '^[0-9a-f]{64}$'
    ),
    idempotency_key             TEXT NOT NULL
        CHECK (length(btrim(idempotency_key)) BETWEEN 1 AND 200),
    reason_code                 TEXT NOT NULL
        CHECK (reason_code ~ '^[A-Z0-9_]{1,64}$'),
    UNIQUE (acquisition_principal_id, idempotency_key),
    CONSTRAINT account_deletion_window_check
        CHECK (completes_after > requested_at),
    CONSTRAINT account_deletion_state_fields_check CHECK (
        (state <> 'cancelled' OR cancelled_at IS NOT NULL)
        AND (state NOT IN ('started', 'done')
             OR (started_at IS NOT NULL AND purge_request_id IS NOT NULL))
        AND (state <> 'done'
             OR (completed_at IS NOT NULL
                 AND completion_evidence_sha256 IS NOT NULL))
    )
);

-- At most one pending request per person: a double tap is one request.
CREATE UNIQUE INDEX IF NOT EXISTS account_deletion_requests_one_pending_idx
    ON public.account_deletion_requests (acquisition_principal_id)
    WHERE state = 'pending';
CREATE INDEX IF NOT EXISTS account_deletion_requests_principal_idx
    ON public.account_deletion_requests (acquisition_principal_id, state);
CREATE INDEX IF NOT EXISTS account_deletion_requests_due_idx
    ON public.account_deletion_requests (state, completes_after);
CREATE UNIQUE INDEX IF NOT EXISTS account_deletion_requests_purge_idx
    ON public.account_deletion_requests (purge_request_id)
    WHERE purge_request_id IS NOT NULL;
-- The status function reads blocks by person on every request.
CREATE INDEX IF NOT EXISTS processing_service_blocks_principal_idx
    ON public.processing_service_blocks (acquisition_principal_id);

ALTER TABLE public.account_deletion_requests ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.account_deletion_requests
    FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT ON public.account_deletion_requests TO service_role;

COMMENT ON TABLE public.account_deletion_requests IS
    'A person''s account deletion request with its seven-day cancel window '
    '(0422, N48.4 Q14 A). The purge request is created only when the window '
    'has passed. Never a browser read; rows are never removed.';

-- A request is evidence: its identity and window never change, its state
-- only moves forward, and it is never removed.
CREATE OR REPLACE FUNCTION public.guard_account_deletion_request_v1()
RETURNS trigger LANGUAGE plpgsql SET search_path = public AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'ACCOUNT_DELETION_REQUEST_IMMUTABLE';
    END IF;
    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.acquisition_principal_id IS DISTINCT FROM OLD.acquisition_principal_id
       OR NEW.requested_at IS DISTINCT FROM OLD.requested_at
       OR NEW.completes_after IS DISTINCT FROM OLD.completes_after
       OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key
       OR NEW.reason_code IS DISTINCT FROM OLD.reason_code
       OR (OLD.cancelled_at IS NOT NULL
           AND NEW.cancelled_at IS DISTINCT FROM OLD.cancelled_at)
       OR (OLD.started_at IS NOT NULL
           AND NEW.started_at IS DISTINCT FROM OLD.started_at)
       OR (OLD.purge_request_id IS NOT NULL
           AND NEW.purge_request_id IS DISTINCT FROM OLD.purge_request_id)
       OR (OLD.completed_at IS NOT NULL
           AND NEW.completed_at IS DISTINCT FROM OLD.completed_at)
    THEN
        RAISE EXCEPTION 'ACCOUNT_DELETION_REQUEST_IMMUTABLE';
    END IF;
    IF NOT (NEW.state = OLD.state
            OR (OLD.state = 'pending' AND NEW.state IN ('cancelled', 'started'))
            OR (OLD.state = 'started' AND NEW.state = 'done')) THEN
        RAISE EXCEPTION 'ACCOUNT_DELETION_STATE_CANNOT_GO_BACK';
    END IF;
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION public.guard_account_deletion_request_v1()
    FROM PUBLIC, anon, authenticated;

DROP TRIGGER IF EXISTS account_deletion_request_guard
    ON public.account_deletion_requests;
CREATE TRIGGER account_deletion_request_guard
    BEFORE UPDATE OR DELETE ON public.account_deletion_requests
    FOR EACH ROW EXECUTE FUNCTION public.guard_account_deletion_request_v1();

-- ── 3. Learning stops while a service is ending ─────────────────────────────

-- True for a person with an account deletion that was not cancelled, or a
-- termination or deletion block in effect (the four kinds 0310's request
-- blocks). Only ever an answer about the person's service; the consent
-- ledger is not read or changed (L3).
CREATE OR REPLACE FUNCTION public.phase1_learning_stopped_v1(
    p_acquisition_principal_id UUID
) RETURNS BOOLEAN
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public
AS $$
    SELECT p_acquisition_principal_id IS NOT NULL AND (
        EXISTS (
            SELECT 1 FROM public.account_deletion_requests request
             WHERE request.acquisition_principal_id = p_acquisition_principal_id
               AND request.state IN ('pending', 'started', 'done')
        )
        OR EXISTS (
            SELECT 1 FROM public.processing_service_blocks block
             WHERE block.acquisition_principal_id = p_acquisition_principal_id
               AND block.block_kind IN ('service_termination', 'account_deletion',
                                        'retention_expiry', 'lawful_deletion')
               AND block.effective_at <= now()
        )
    );
$$;
REVOKE ALL ON FUNCTION public.phase1_learning_stopped_v1(UUID)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.phase1_learning_stopped_v1(UUID) TO service_role;

-- The person's pairs leave the releasable pool now, not at the weekly
-- refresh. Released files are left to that refresh, which voids any release
-- holding a pair that is no longer releasable (the withdrawal path, 0405).
CREATE OR REPLACE FUNCTION public.stop_phase1_learning_v1(
    p_acquisition_principal_id UUID
) RETURNS INTEGER
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    v_user TEXT;
    v_count INTEGER := 0;
BEGIN
    IF p_acquisition_principal_id IS NULL
       OR to_regclass('public.feedback_pairs') IS NULL THEN
        RETURN 0;
    END IF;
    SELECT principal.user_id::text INTO v_user
      FROM public.owner_principals principal
     WHERE principal.id = p_acquisition_principal_id;
    IF v_user IS NOT NULL THEN
        UPDATE public.feedback_pairs pair
           SET owner_principal_id = p_acquisition_principal_id
         WHERE pair.owner_principal_id IS NULL
           AND pair.owner_user_id = v_user;
    END IF;
    UPDATE public.feedback_pairs pair
       SET releasable = false
     WHERE pair.owner_principal_id = p_acquisition_principal_id
       AND pair.releasable;
    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END;
$$;
REVOKE ALL ON FUNCTION public.stop_phase1_learning_v1(UUID)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.stop_phase1_learning_v1(UUID) TO service_role;

-- 0310's request, byte for byte, with one statement added where it blocks:
-- a termination or deletion stops learning in the same transaction.
CREATE OR REPLACE FUNCTION public.request_phase1_purge_v1(
    p_acquisition_principal_id UUID, p_trigger_kind TEXT,
    p_idempotency_key TEXT, p_reason_code TEXT
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE req data_purge_requests;
BEGIN
    IF p_trigger_kind NOT IN (
        'service_termination', 'account_deletion', 'retention_expiry',
        'third_party_audio_report', 'lawful_deletion'
    ) THEN RAISE EXCEPTION 'INVALID_PURGE_TRIGGER'; END IF;
    INSERT INTO data_purge_requests (
        acquisition_principal_id, trigger_kind, idempotency_key
    ) VALUES (
        p_acquisition_principal_id, p_trigger_kind, p_idempotency_key
    ) ON CONFLICT (acquisition_principal_id, idempotency_key) DO NOTHING;
    SELECT * INTO req FROM data_purge_requests
     WHERE acquisition_principal_id = p_acquisition_principal_id
       AND idempotency_key = p_idempotency_key;

    IF p_trigger_kind IN ('service_termination', 'account_deletion',
                          'retention_expiry', 'lawful_deletion')
       AND NOT EXISTS (
           SELECT 1 FROM processing_service_blocks
            WHERE source_request_id = req.id
       ) THEN
        INSERT INTO processing_service_blocks (
            acquisition_principal_id, block_kind, source_request_id, reason_code
        ) VALUES (
            p_acquisition_principal_id,
            CASE WHEN p_trigger_kind = 'lawful_deletion'
                 THEN 'lawful_deletion' ELSE p_trigger_kind END,
            req.id, p_reason_code
        );
        UPDATE phase1_processing_jobs SET status = 'cancelled',
            updated_at = now(), last_error_code = 'PROCESSING_AUTHORITY_ENDED'
         WHERE acquisition_principal_id = p_acquisition_principal_id
           AND status IN ('pending', 'processing');
        UPDATE processing_provider_permits SET status = 'cancelled',
            revoked_at = now()
         WHERE acquisition_principal_id = p_acquisition_principal_id
           AND status = 'issued';
        UPDATE processing_job_carryovers SET cancelled_at = now(),
            cancellation_reason = 'PROCESSING_AUTHORITY_ENDED'
         WHERE acquisition_principal_id = p_acquisition_principal_id
           AND cancelled_at IS NULL;
        -- 0422 (PLF-T2, PLF-T3): learning stops with the service.
        PERFORM public.stop_phase1_learning_v1(p_acquisition_principal_id);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM data_purge_events
         WHERE purge_request_id = req.id AND event_kind = 'requested'
    ) THEN
        INSERT INTO data_purge_events (
            purge_request_id, event_kind, actor_kind,
            evidence_sha256, metadata
        ) VALUES (
            req.id, 'requested', 'system', encode(extensions.digest(concat_ws(':',
                req.id::text, p_trigger_kind, p_reason_code
            ), 'sha256'), 'hex'),
            jsonb_build_object('trigger_kind', p_trigger_kind,
                               'reason_code', p_reason_code)
        );
    END IF;
    RETURN jsonb_build_object('purge_request_id', req.id, 'state', req.state);
END;
$$;
REVOKE ALL ON FUNCTION public.request_phase1_purge_v1(UUID,TEXT,TEXT,TEXT)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.request_phase1_purge_v1(UUID,TEXT,TEXT,TEXT)
    TO service_role;

-- 0405's weekly refresh, with releasability also requiring that the owner's
-- learning has not stopped. A release voided because its owner's service
-- is ending says so; a withdrawal still reads 'consent_withdrawn'.
CREATE OR REPLACE FUNCTION public.refresh_feedback_pair_consent_v1(
    p_required_surfaces text[]
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    v_refreshed integer := 0;
    v_releasable integer := 0;
    v_voided integer := 0;
    v_reset integer := 0;
BEGIN
    UPDATE public.feedback_pairs pair
       SET owner_principal_id = principal.id
      FROM public.owner_principals principal
     WHERE pair.owner_principal_id IS NULL
       AND pair.owner_user_id IS NOT NULL
       AND principal.user_id::text = pair.owner_user_id;

    WITH stamped AS (
        SELECT pair.id,
               CASE
                   WHEN NOT (pair.surface = ANY (p_required_surfaces)) THEN 'not_needed'
                   WHEN pair.owner_principal_id IS NULL THEN 'unknown'
                   WHEN grant_row.id IS NOT NULL THEN 'yes'
                   ELSE 'no'
               END AS state,
               grant_row.id AS grant_id,
               grant_row.consent_policy_version AS policy_version,
               public.phase1_learning_stopped_v1(pair.owner_principal_id) AS stopped
          FROM public.feedback_pairs pair
          LEFT JOIN public.training_consent_active_grants grant_row
            ON grant_row.acquisition_principal_id = pair.owner_principal_id
    )
    UPDATE public.feedback_pairs pair
       SET consent_state = stamped.state,
           consent_grant_event_id = stamped.grant_id,
           consent_policy_version = stamped.policy_version,
           releasable = stamped.state IN ('yes', 'not_needed') AND NOT stamped.stopped
      FROM stamped
     WHERE stamped.id = pair.id;
    GET DIAGNOSTICS v_refreshed = ROW_COUNT;

    WITH void AS (
        UPDATE public.pair_releases release
           SET voided_at = now(),
               voided_reason = CASE
                   WHEN EXISTS (SELECT 1 FROM public.feedback_pairs pair
                                 WHERE pair.release_id = release.id
                                   AND NOT pair.releasable
                                   AND pair.consent_state IN ('yes', 'not_needed'))
                   THEN 'owner_service_ended'
                   ELSE 'consent_withdrawn' END
         WHERE release.voided_at IS NULL
           AND EXISTS (SELECT 1 FROM public.feedback_pairs pair
                        WHERE pair.release_id = release.id
                          AND NOT pair.releasable)
        RETURNING release.id
    )
    SELECT count(*) INTO v_voided FROM void;

    UPDATE public.feedback_pairs pair
       SET release_id = NULL, exported_at = NULL
      FROM public.pair_releases release
     WHERE pair.release_id = release.id
       AND release.voided_at IS NOT NULL;
    GET DIAGNOSTICS v_reset = ROW_COUNT;

    SELECT count(*) INTO v_releasable
      FROM public.feedback_pairs WHERE releasable AND exported_at IS NULL;

    RETURN jsonb_build_object(
        'refreshed', v_refreshed, 'releasable_waiting', v_releasable,
        'voided_releases', v_voided, 'pairs_reset', v_reset);
END;
$$;
REVOKE ALL ON FUNCTION public.refresh_feedback_pair_consent_v1(text[])
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.refresh_feedback_pair_consent_v1(text[]) TO service_role;

-- 0375's only door in, with one refusal added: no copy of a person whose
-- service is ending.
CREATE OR REPLACE FUNCTION public.record_training_corpus_item_v1(
    p_acquisition_principal_id UUID,
    p_training_grant_event_id UUID,
    p_source_project_id TEXT,
    p_source_take_id TEXT,
    p_source_ref TEXT,
    p_source_sha256 TEXT,
    p_item_kind TEXT,
    p_label_provenance TEXT,
    p_content JSONB,
    p_storage_provider TEXT,
    p_bucket TEXT,
    p_storage_key TEXT,
    p_object_sha256 TEXT
) RETURNS public.training_corpus_items
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    consent JSONB;
    rule public.data_retention_rules;
    existing public.training_corpus_items;
    created public.training_corpus_items;
BEGIN
    consent := public.get_mlc2_training_consent_status_v2(p_acquisition_principal_id);
    IF consent ->> 'active' IS DISTINCT FROM 'true'
       OR consent ->> 'grant_event_id' IS DISTINCT FROM p_training_grant_event_id::text THEN
        RAISE EXCEPTION 'TRAINING_CORPUS_NO_ACTIVE_YES';
    END IF;
    -- 0422 (PLF-T2): a deletion or termination stops every new copy.
    IF public.phase1_learning_stopped_v1(p_acquisition_principal_id) THEN
        RAISE EXCEPTION 'TRAINING_CORPUS_SERVICE_ENDING';
    END IF;
    SELECT * INTO rule FROM public.data_retention_rules
     WHERE rule_code = 'training_corpus' AND active;
    IF rule.id IS NULL THEN
        RAISE EXCEPTION 'TRAINING_CORPUS_RETENTION_RULE_INACTIVE';
    END IF;

    SELECT * INTO existing FROM public.training_corpus_items
     WHERE training_grant_event_id = p_training_grant_event_id
       AND item_kind = p_item_kind AND source_ref = p_source_ref;
    IF FOUND THEN
        IF existing.source_sha256 IS DISTINCT FROM p_source_sha256 THEN
            RAISE EXCEPTION 'TRAINING_CORPUS_SOURCE_CHANGED';
        END IF;
        RETURN existing;
    END IF;

    INSERT INTO public.training_corpus_items (
        acquisition_principal_id, training_grant_event_id, consent_state,
        consent_state_sha256, source_project_id, source_take_id, source_ref,
        source_sha256, item_kind, label_provenance, content, storage_provider,
        bucket, storage_key, object_sha256, retention_rule_id
    ) VALUES (
        p_acquisition_principal_id, p_training_grant_event_id, consent,
        encode(extensions.digest(convert_to(consent::text, 'UTF8'), 'sha256'), 'hex'),
        p_source_project_id, p_source_take_id, p_source_ref, p_source_sha256,
        p_item_kind, p_label_provenance, p_content, p_storage_provider,
        p_bucket, p_storage_key, p_object_sha256, rule.id
    ) RETURNING * INTO created;
    RETURN created;
END;
$$;
REVOKE ALL ON FUNCTION public.record_training_corpus_item_v1(
    UUID, UUID, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, JSONB, TEXT, TEXT, TEXT, TEXT)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.record_training_corpus_item_v1(
    UUID, UUID, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, JSONB, TEXT, TEXT, TEXT, TEXT)
    TO service_role;

-- ── 1, continued. Request, cancel, start, complete ─────────────────────────

-- The request. Idempotent on (person, key); a second request while one is
-- pending, running or finished returns that one, so a double tap with a new
-- key is still one request. Stops processing and learning at once, as a
-- block does (0310), and deletes nothing.
CREATE OR REPLACE FUNCTION public.request_phase1_account_deletion_v1(
    p_acquisition_principal_id UUID,
    p_idempotency_key TEXT,
    p_reason_code TEXT
) RETURNS public.account_deletion_requests
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    request public.account_deletion_requests;
    v_key TEXT := btrim(COALESCE(p_idempotency_key, ''));
    v_reason TEXT;
BEGIN
    IF v_key = '' OR length(v_key) > 200 THEN
        RAISE EXCEPTION 'ACCOUNT_DELETION_IDEMPOTENCY_KEY_REQUIRED';
    END IF;
    v_reason := CASE WHEN p_reason_code ~ '^[A-Z0-9_]{1,64}$'
                     THEN p_reason_code ELSE 'ACCOUNT_DELETION' END;
    -- One person's requests are decided one at a time.
    PERFORM 1 FROM public.owner_principals
     WHERE id = p_acquisition_principal_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'PROCESSING_PRINCIPAL_UNRESOLVED';
    END IF;

    SELECT * INTO request FROM public.account_deletion_requests
     WHERE acquisition_principal_id = p_acquisition_principal_id
       AND idempotency_key = v_key;
    IF request.id IS NOT NULL THEN
        RETURN request;
    END IF;
    SELECT * INTO request FROM public.account_deletion_requests
     WHERE acquisition_principal_id = p_acquisition_principal_id
       AND state IN ('pending', 'started', 'done')
     ORDER BY requested_at DESC, id DESC LIMIT 1;
    IF request.id IS NOT NULL THEN
        RETURN request;
    END IF;

    INSERT INTO public.account_deletion_requests (
        acquisition_principal_id, requested_at, completes_after,
        idempotency_key, reason_code
    ) VALUES (
        p_acquisition_principal_id, now(), now() + interval '7 days',
        v_key, v_reason
    ) RETURNING * INTO request;

    -- What 0310's request does when it blocks, so nothing keeps running for
    -- a person who asked to leave.
    UPDATE public.phase1_processing_jobs SET status = 'cancelled',
        updated_at = now(), last_error_code = 'PROCESSING_AUTHORITY_ENDED'
     WHERE acquisition_principal_id = p_acquisition_principal_id
       AND status IN ('pending', 'processing');
    UPDATE public.processing_provider_permits SET status = 'cancelled',
        revoked_at = now()
     WHERE acquisition_principal_id = p_acquisition_principal_id
       AND status = 'issued';
    UPDATE public.processing_job_carryovers SET cancelled_at = now(),
        cancellation_reason = 'PROCESSING_AUTHORITY_ENDED'
     WHERE acquisition_principal_id = p_acquisition_principal_id
       AND cancelled_at IS NULL;
    PERFORM public.stop_phase1_learning_v1(p_acquisition_principal_id);
    RETURN request;
END;
$$;

-- The cancel. Only the requester, only while pending (nothing deleted: the
-- purge does not exist yet), only before completes_after. Cancelling twice
-- returns the cancelled request.
CREATE OR REPLACE FUNCTION public.cancel_phase1_account_deletion_v1(
    p_acquisition_principal_id UUID,
    p_request_id UUID
) RETURNS public.account_deletion_requests
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    request public.account_deletion_requests;
BEGIN
    SELECT * INTO request FROM public.account_deletion_requests
     WHERE id = p_request_id FOR UPDATE;
    IF request.id IS NULL
       OR request.acquisition_principal_id IS DISTINCT FROM p_acquisition_principal_id THEN
        RAISE EXCEPTION 'ACCOUNT_DELETION_NOT_FOUND';
    END IF;
    IF request.state = 'cancelled' THEN
        RETURN request;
    END IF;
    IF request.state <> 'pending' OR request.purge_request_id IS NOT NULL THEN
        RAISE EXCEPTION 'ACCOUNT_DELETION_ALREADY_STARTED';
    END IF;
    IF now() >= request.completes_after THEN
        RAISE EXCEPTION 'ACCOUNT_DELETION_WINDOW_CLOSED';
    END IF;
    UPDATE public.account_deletion_requests
       SET state = 'cancelled', cancelled_at = now()
     WHERE id = request.id
    RETURNING * INTO request;
    RETURN request;
END;
$$;

-- The window has passed: create the purge request through 0310's request
-- (permanent block, purge row, 'requested' event). Idempotent: a started or
-- finished request is returned as it is.
CREATE OR REPLACE FUNCTION public.start_due_account_deletion_v1(
    p_request_id UUID
) RETURNS public.account_deletion_requests
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    request public.account_deletion_requests;
    purge JSONB;
BEGIN
    SELECT * INTO request FROM public.account_deletion_requests
     WHERE id = p_request_id FOR UPDATE;
    IF request.id IS NULL THEN
        RAISE EXCEPTION 'ACCOUNT_DELETION_NOT_FOUND';
    END IF;
    IF request.state IN ('started', 'done') THEN
        RETURN request;
    END IF;
    IF request.state <> 'pending' THEN
        RAISE EXCEPTION 'ACCOUNT_DELETION_NOT_PENDING';
    END IF;
    IF now() < request.completes_after THEN
        RAISE EXCEPTION 'ACCOUNT_DELETION_WINDOW_OPEN';
    END IF;
    purge := public.request_phase1_purge_v1(
        request.acquisition_principal_id, 'account_deletion',
        'account-deletion-window:' || request.id::text, request.reason_code
    );
    UPDATE public.account_deletion_requests
       SET state = 'started', started_at = now(),
           purge_request_id = (purge ->> 'purge_request_id')::uuid
     WHERE id = request.id
    RETURNING * INTO request;
    RETURN request;
END;
$$;

-- Done only on verified terminal evidence: the purge finalized as 'done',
-- its 'completed' event exists, and no target is unresolved. The event's
-- evidence hash is kept on the request.
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
    UPDATE public.account_deletion_requests
       SET state = 'done', completed_at = now(),
           completion_evidence_sha256 = evidence
     WHERE id = request.id
    RETURNING * INTO request;
    RETURN request;
END;
$$;

REVOKE ALL ON FUNCTION public.request_phase1_account_deletion_v1(UUID, TEXT, TEXT)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.request_phase1_account_deletion_v1(UUID, TEXT, TEXT)
    TO service_role;
REVOKE ALL ON FUNCTION public.cancel_phase1_account_deletion_v1(UUID, UUID)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.cancel_phase1_account_deletion_v1(UUID, UUID)
    TO service_role;
REVOKE ALL ON FUNCTION public.start_due_account_deletion_v1(UUID)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.start_due_account_deletion_v1(UUID)
    TO service_role;
REVOKE ALL ON FUNCTION public.complete_phase1_account_deletion_v1(UUID)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.complete_phase1_account_deletion_v1(UUID)
    TO service_role;

-- ── 2. The one status function counts the pending request as a block ──────

-- 0358's body; only `blocked` reads one more table.
CREATE OR REPLACE FUNCTION public.get_phase1_processing_authorization_v1(
    p_acquisition_principal_id UUID
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER STABLE SET search_path = public
AS $$
DECLARE
    policy processing_policy_versions;
    receipt processing_authorization_receipts;
    blocked BOOLEAN;
    held_version TEXT;
BEGIN
    SELECT * INTO policy FROM processing_policy_versions
     WHERE status = 'active' AND activated_at <= now()
       AND (retired_at IS NULL OR retired_at > now())
     ORDER BY activated_at DESC LIMIT 1;
    IF policy.id IS NULL THEN
        RETURN jsonb_build_object(
            'authorized', false, 'code', 'PROCESSING_POLICY_INACTIVE',
            'policy_available', false, 'pooled_learning_eligible', false
        );
    END IF;
    -- 0422: an account deletion blocks from the moment it is asked for. A
    -- cancelled one blocks nothing; once its purge starts, the purge's own
    -- block is here too.
    SELECT EXISTS (
        SELECT 1 FROM processing_service_blocks b
         WHERE b.acquisition_principal_id = p_acquisition_principal_id
           AND b.effective_at <= now()
    ) OR EXISTS (
        SELECT 1 FROM account_deletion_requests d
         WHERE d.acquisition_principal_id = p_acquisition_principal_id
           AND d.state IN ('pending', 'started', 'done')
    ) INTO blocked;
    SELECT r.* INTO receipt FROM processing_authorization_receipts r
     WHERE r.acquisition_principal_id = p_acquisition_principal_id
       AND r.policy_id = policy.id
     ORDER BY r.accepted_at DESC LIMIT 1;

    -- P10 (0358): read only when the active policy has no receipt.
    IF receipt.id IS NULL THEN
        SELECT older.version INTO held_version
          FROM processing_authorization_receipts r
          JOIN processing_policy_versions older ON older.id = r.policy_id
         WHERE r.acquisition_principal_id = p_acquisition_principal_id
         ORDER BY r.accepted_at DESC, r.id DESC LIMIT 1;
    END IF;

    RETURN jsonb_build_object(
        'authorized', receipt.id IS NOT NULL AND NOT blocked,
        'code', CASE
            WHEN blocked THEN 'PROCESSING_SERVICE_BLOCKED'
            WHEN receipt.id IS NULL THEN 'PROCESSING_AUTHORIZATION_REQUIRED'
            ELSE 'PROCESSING_AUTHORIZED' END,
        'policy_available', true, 'policy_id', policy.id,
        'policy_version', policy.version,
        'terms_version', policy.terms_version,
        'terms_copy', policy.terms_copy,
        'terms_copy_sha256', policy.terms_copy_sha256,
        'privacy_version', policy.privacy_version,
        'privacy_copy', policy.privacy_copy,
        'privacy_copy_sha256', policy.privacy_copy_sha256,
        'ai_notice_version', policy.ai_notice_version,
        'ai_notice_copy', policy.ai_notice_copy,
        'ai_notice_copy_sha256', policy.ai_notice_copy_sha256,
        'agreement_copy', policy.agreement_copy,
        'agreement_copy_sha256', policy.agreement_copy_sha256,
        'minimum_age', policy.minimum_age,
        'allowed_countries', policy.allowed_countries,
        'ai_notice_rendered', EXISTS (
            SELECT 1 FROM ai_transparency_exposures e
             WHERE e.acquisition_principal_id = p_acquisition_principal_id
               AND e.ai_notice_version = policy.ai_notice_version
        ),
        'receipt_id', receipt.id, 'pooled_learning_eligible', false,
        'reacceptance_required',
            receipt.id IS NULL AND held_version IS NOT NULL AND NOT blocked,
        'accepted_policy_version', held_version
    );
END;
$$;
REVOKE ALL ON FUNCTION public.get_phase1_processing_authorization_v1(UUID)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.get_phase1_processing_authorization_v1(UUID)
    TO service_role;

-- ── 4. A project deletion keeps its seven days ──────────────────────────────

-- 0364's cancel, refusing once the window (due_at) has passed: from then on
-- the deletion completes by itself.
CREATE OR REPLACE FUNCTION public.cancel_project_deletion_v1(
    p_acquisition_principal_id UUID,
    p_project_id UUID
) RETURNS public.project_deletion_requests
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    request public.project_deletion_requests;
BEGIN
    SELECT * INTO request FROM public.project_deletion_requests
     WHERE project_id = p_project_id
       AND acquisition_principal_id = p_acquisition_principal_id
       AND state IN ('pending', 'confirmed')
     FOR UPDATE;
    IF request.id IS NULL THEN
        RAISE EXCEPTION 'PROJECT_DELETION_NOT_PENDING';
    END IF;
    IF request.state <> 'pending' THEN
        RAISE EXCEPTION 'PROJECT_DELETION_ALREADY_CONFIRMED';
    END IF;
    IF now() >= request.due_at THEN
        RAISE EXCEPTION 'PROJECT_DELETION_WINDOW_CLOSED';
    END IF;
    UPDATE public.project_deletion_requests
       SET state = 'cancelled', cancelled_at = now()
     WHERE id = request.id
    RETURNING * INTO request;
    RETURN request;
END;
$$;
REVOKE ALL ON FUNCTION public.cancel_project_deletion_v1(UUID, UUID)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.cancel_project_deletion_v1(UUID, UUID)
    TO service_role;

-- The system's confirm once due_at has passed (N48.4 Q17 A): the same
-- purge request the operator's confirm makes (0380), with no operator.
-- Idempotent: a confirmed or finished request is returned as it is.
CREATE OR REPLACE FUNCTION public.start_due_project_deletion_v1(
    p_request_id UUID
) RETURNS public.project_deletion_requests
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    request public.project_deletion_requests;
    purge_id UUID;
BEGIN
    SELECT * INTO request FROM public.project_deletion_requests
     WHERE id = p_request_id FOR UPDATE;
    IF request.id IS NULL THEN
        RAISE EXCEPTION 'PROJECT_DELETION_NOT_FOUND';
    END IF;
    IF request.state IN ('confirmed', 'done') THEN
        RETURN request;
    END IF;
    IF request.state <> 'pending' THEN
        RAISE EXCEPTION 'PROJECT_DELETION_NOT_PENDING';
    END IF;
    IF now() < request.due_at THEN
        RAISE EXCEPTION 'PROJECT_DELETION_WINDOW_OPEN';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.projects project
         WHERE project.id = request.project_id
           AND project.owner_principal_id = request.acquisition_principal_id
    ) THEN
        RAISE EXCEPTION 'PURGE_PROJECT_NOT_OWNED';
    END IF;

    INSERT INTO public.data_purge_requests (
        acquisition_principal_id, trigger_kind, project_id, idempotency_key
    ) VALUES (
        request.acquisition_principal_id, 'project_deletion',
        request.project_id, 'project-deletion:' || request.id::text
    )
    ON CONFLICT (acquisition_principal_id, idempotency_key) DO NOTHING;
    SELECT id INTO purge_id FROM public.data_purge_requests
     WHERE acquisition_principal_id = request.acquisition_principal_id
       AND idempotency_key = 'project-deletion:' || request.id::text;

    UPDATE public.project_deletion_requests
       SET state = 'confirmed', confirmed_at = now(),
           confirmed_by = NULL, purge_request_id = purge_id
     WHERE id = request.id
    RETURNING * INTO request;
    RETURN request;
END;
$$;
REVOKE ALL ON FUNCTION public.start_due_project_deletion_v1(UUID)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.start_due_project_deletion_v1(UUID)
    TO service_role;

-- ── 5. One completion run at a time ─────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.deletion_completion_lease (
    id           SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    holder       TEXT NULL,
    lease_until  TIMESTAMPTZ NULL,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO public.deletion_completion_lease (id) VALUES (1)
    ON CONFLICT (id) DO NOTHING;
ALTER TABLE public.deletion_completion_lease ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.deletion_completion_lease
    FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT ON public.deletion_completion_lease TO service_role;

-- Take (or renew, for the same holder) the lease; false while another holds
-- an unexpired one.
CREATE OR REPLACE FUNCTION public.claim_deletion_completion_lease_v1(
    p_holder TEXT, p_seconds INTEGER
) RETURNS BOOLEAN
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
BEGIN
    IF COALESCE(btrim(p_holder), '') = '' OR p_seconds IS NULL
       OR p_seconds < 1 OR p_seconds > 7200 THEN
        RAISE EXCEPTION 'DELETION_LEASE_INVALID';
    END IF;
    UPDATE public.deletion_completion_lease
       SET holder = p_holder,
           lease_until = now() + make_interval(secs => p_seconds),
           updated_at = now()
     WHERE id = 1
       AND (lease_until IS NULL OR lease_until <= now() OR holder = p_holder);
    RETURN FOUND;
END;
$$;

CREATE OR REPLACE FUNCTION public.release_deletion_completion_lease_v1(
    p_holder TEXT
) RETURNS BOOLEAN
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
BEGIN
    UPDATE public.deletion_completion_lease
       SET holder = NULL, lease_until = NULL, updated_at = now()
     WHERE id = 1 AND holder = p_holder;
    RETURN FOUND;
END;
$$;
REVOKE ALL ON FUNCTION public.claim_deletion_completion_lease_v1(TEXT, INTEGER)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.claim_deletion_completion_lease_v1(TEXT, INTEGER)
    TO service_role;
REVOKE ALL ON FUNCTION public.release_deletion_completion_lease_v1(TEXT)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.release_deletion_completion_lease_v1(TEXT)
    TO service_role;

-- ── 6. Requests made before this file ───────────────────────────────────────

-- An account deletion requested through 0310's request carries over under
-- its own id: 'started' (its purge exists; it was never cancellable), or
-- 'done' with its completion evidence. Its window is request + 7 days.
INSERT INTO public.account_deletion_requests (
    id, acquisition_principal_id, state, requested_at, completes_after,
    started_at, completed_at, purge_request_id, completion_evidence_sha256,
    idempotency_key, reason_code
)
SELECT purge.id, purge.acquisition_principal_id,
       CASE WHEN finished.evidence IS NOT NULL THEN 'done' ELSE 'started' END,
       purge.requested_at, purge.requested_at + interval '7 days',
       purge.requested_at,
       CASE WHEN finished.evidence IS NOT NULL THEN purge.completed_at END,
       purge.id, finished.evidence,
       'carried-over:' || purge.id::text, 'ACCOUNT_DELETION'
  FROM public.data_purge_requests purge
  LEFT JOIN LATERAL (
      SELECT event.evidence_sha256 AS evidence
        FROM public.data_purge_events event
       WHERE event.purge_request_id = purge.id
         AND event.event_kind = 'completed'
         AND purge.state = 'done'
         AND purge.completed_at IS NOT NULL
       ORDER BY event.occurred_at DESC, event.id DESC LIMIT 1
  ) finished ON true
 WHERE purge.trigger_kind = 'account_deletion'
   AND purge.project_id IS NULL
   AND NOT EXISTS (
       SELECT 1 FROM public.account_deletion_requests carried
        WHERE carried.id = purge.id OR carried.purge_request_id = purge.id
   );

COMMIT;
