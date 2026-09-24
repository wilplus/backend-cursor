-- 0356 · A speaker the database will actually accept.
--
-- R-2 (major), ML provenance audit 2026-09-22.
--
-- `record_mlc3_self_speaker_target_v1` minted a speaker with two bare
-- INSERTs that named ONE column each:
--
--     INSERT INTO ml_speakers(id) VALUES (speaker_value);
--     INSERT INTO ml_speaker_principals(speaker_id, acquisition_principal_id)
--          VALUES (speaker_value, p_acquisition_principal_id);
--
-- The released `ml_speakers` requires identity_version, identity_hash
-- (UNIQUE, CHECK length = 64) and created_by. The released
-- `ml_speaker_principals` requires binding_kind, binding_proof_hash and
-- bound_by. Six NOT NULL columns, no defaults. The first time this service
-- had to mint a speaker it would have raised a not-null violation, and all
-- three entry points into it — the self-speaker target, its candidate wrapper
-- and its practice wrapper — would have failed with it.
--
-- WHY A GREEN TEST SUITE DID NOT CATCH THIS, WHICH IS THE PART TO REMEMBER.
-- `tests/test_mlc3_general_user_service_d4_postgres.py` calls this function
-- and asserts on the speaker it returns. It passes. It passes because the
-- lane it runs in is cloned from the narrow fixture, where
-- `tests/integration/mlc3_exercise_foundation_prerequisites.sql` declares
--
--     CREATE TABLE public.ml_speakers (id UUID PRIMARY KEY);
--
-- one column, no constraints. The fixture had removed exactly the constraints
-- the code violates, so the test exercised the defect and reported success.
--
-- Correcting that fixture is NOT in this migration's change, and the reason
-- is a measurement: tightening it to the released shape turns four lanes red
-- at once (m33 30 failed + 83 errors, d3 14 errors, service 23 failed,
-- confident-moment narrow 47 failed, d4 17 failed). Roughly a hundred cases
-- across suites this change does not own have been minting speakers with no
-- identity for as long as the fixture allowed it. That is the audit's
-- Workstream 10 — make the tests test the released schema — and doing it
-- inside an R-2 fix would bury a one-function correction under a hundred
-- unrelated edits. R-2's own regression test therefore runs on the RELEASED
-- lane, where `ml_speakers` has always had its constraints.
--
-- ONE WRITER, NOT TWO. The fix routes through
-- `register_ml_speaker_principal_v1` — the canonical writer MLC-2 already
-- owns — instead of a second hand-rolled pair of INSERTs. That also restores
-- two behaviours the bare INSERTs silently skipped: the refusal to re-bind a
-- principal that is already bound to a different identity, and
-- `assign_ml_speaker_split_v1`, without which a speaker created here would
-- have had no split assignment at all.
--
-- ADDITIVE AND IDEMPOTENT. One CREATE OR REPLACE FUNCTION and the grants it
-- already carries. No table, column, row or grant is created, altered or
-- dropped, and no role gains anything. Every path other than the speaker
-- block is byte-identical to what runs today.
--
-- THIS OPENS NOTHING. The D4 service stays behind MLC3_SERVICE_ENABLED and
-- the rollout state; this only means that when it is opened, its first write
-- succeeds instead of raising.

CREATE OR REPLACE FUNCTION public.record_mlc3_self_speaker_target_v1(
    p_acquisition_principal_id UUID,
    p_owner_user_id UUID,
    p_recording_attempt_id UUID,
    p_audio_object_id UUID,
    p_clip_id UUID,
    p_idempotency_key TEXT
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path = public AS $$
DECLARE
    access_row JSONB;
    attempt public.processing_recording_attempts;
    audio public.processing_audio_objects;
    clip public.snippets;
    practice_attempt public.exercise_practice_attempts;
    existing_assertion public.mlc3_self_speaker_assertions;
    acquisition_revision public.mlc3_speaker_acquisition_revisions;
    target_binding public.mlc3_target_speaker_bindings;
    speaker_value UUID;
    transcript_hash TEXT;
    assertion_hash TEXT;
    acquisition_hash TEXT;
    binding_hash TEXT;
    next_acquisition_revision INTEGER;
    next_target_revision INTEGER;
    target_start INTEGER;
    target_duration INTEGER;
    target_text TEXT;
    target_clip_id UUID;
    target_practice_attempt_id UUID;
BEGIN
    IF COALESCE(btrim(p_idempotency_key), '') = '' THEN
        RAISE EXCEPTION 'MLC3_SELF_SPEAKER_IDEMPOTENCY_REQUIRED';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'mlc3-service-principal:' || p_acquisition_principal_id::TEXT, 0
    ));
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'mlc3-self-speaker:' || p_recording_attempt_id::TEXT, 0
    ));
    -- Every identity writer shares this lock with eligibility, assignment and
    -- judgment readers. A later correction therefore cannot cross a frozen
    -- comparison boundary while the reader is committing.
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'mlc3-speaker-attempt:' || p_recording_attempt_id::TEXT, 0
    ));
    access_row := public.require_mlc3_service_access_v2(
        p_acquisition_principal_id, NULL, NULL
    );
    IF NOT EXISTS (
        SELECT 1 FROM public.owner_principals principal
         WHERE principal.id = p_acquisition_principal_id
           AND principal.user_id = p_owner_user_id
           AND principal.guest_secret_hash IS NULL
    ) THEN RAISE EXCEPTION 'MLC3_SELF_SPEAKER_OWNER_REQUIRED'; END IF;
    SELECT * INTO STRICT attempt
     FROM public.processing_recording_attempts row
     WHERE row.id = p_recording_attempt_id
       AND row.acquisition_principal_id = p_acquisition_principal_id
       AND row.status IN ('completed', 'accepted')
     FOR SHARE;
    SELECT * INTO STRICT audio
      FROM public.processing_audio_objects row
     WHERE row.id = p_audio_object_id
       AND row.acquisition_principal_id = p_acquisition_principal_id
       AND row.recording_attempt_id = attempt.id
       AND row.verified_at IS NOT NULL
       AND row.deleted_at IS NULL
     FOR SHARE;
    IF EXISTS (
        SELECT 1 FROM public.processing_audio_object_deletion_events event
         WHERE event.audio_object_id = audio.id
    ) THEN RAISE EXCEPTION 'MLC3_SELF_SPEAKER_AUDIO_NOT_LIVE'; END IF;
    IF p_clip_id IS NOT NULL THEN
        SELECT * INTO STRICT clip
          FROM public.snippets row
         WHERE row.id = p_clip_id
           AND row.recording_id = attempt.recording_id
           AND row.start_offset_ms >= 0
           AND row.duration_ms > 0
           AND length(btrim(COALESCE(row.transcript, ''))) > 0
         FOR SHARE;
        target_start := clip.start_offset_ms;
        target_duration := clip.duration_ms;
        target_text := clip.transcript;
        target_clip_id := clip.id;
        target_practice_attempt_id := NULL;
    ELSE
        SELECT * INTO STRICT practice_attempt
          FROM public.exercise_practice_attempts row
         WHERE row.processing_recording_attempt_id = attempt.id
           AND row.processing_audio_object_id = audio.id
           AND row.acquisition_principal_id = p_acquisition_principal_id
           AND row.transcript_state = 'available'
           AND row.state NOT IN ('cancelled', 'quarantined')
           AND length(btrim(COALESCE(row.transcript_text, ''))) > 0
         FOR SHARE;
        target_start := 0;
        target_duration := practice_attempt.duration_ms;
        target_text := practice_attempt.transcript_text;
        target_clip_id := NULL;
        target_practice_attempt_id := practice_attempt.id;
    END IF;
    transcript_hash := public.exercise_json_sha256_v1(
        jsonb_build_object('transcript', target_text)
    );
    assertion_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'contract_version', 'mlc3-self-speaker-assertion-v1',
        'acquisition_principal_id', p_acquisition_principal_id,
        'owner_user_id', p_owner_user_id,
        'recording_attempt_id', attempt.id,
        'audio_object_id', audio.id,
        'audio_sha256', audio.exact_bytes_sha256,
        'clip_id', target_clip_id,
        'practice_attempt_id', target_practice_attempt_id,
        'start_offset_ms', target_start,
        'duration_ms', target_duration,
        'transcript_sha256', transcript_hash,
        'authorization_receipt_id', access_row->>'authorization_receipt_id',
        'authorization_policy_id', access_row->>'authorization_policy_id',
        'assertion', 'this_is_my_voice',
        'idempotency_key', p_idempotency_key
    ));
    SELECT * INTO existing_assertion
      FROM public.mlc3_self_speaker_assertions row
     WHERE row.acquisition_principal_id = p_acquisition_principal_id
       AND row.recording_attempt_id = attempt.id
       AND row.idempotency_key = p_idempotency_key;
    IF existing_assertion.id IS NOT NULL THEN
        IF existing_assertion.assertion_sha256 <> assertion_hash
           OR existing_assertion.audio_object_id <> audio.id
        THEN RAISE EXCEPTION 'MLC3_SELF_SPEAKER_REPLAY_CONFLICT'; END IF;
        SELECT * INTO STRICT target_binding
          FROM public.mlc3_target_speaker_bindings row
         WHERE row.self_speaker_assertion_id = existing_assertion.id;
        RETURN jsonb_build_object(
            'assertion_id', existing_assertion.id,
            'speaker_id', target_binding.speaker_id,
            'target_binding_id', target_binding.id,
            'replayed', true
        );
    END IF;
    SELECT link.speaker_id INTO speaker_value
      FROM public.ml_speaker_principals link
     WHERE link.acquisition_principal_id = p_acquisition_principal_id
     FOR SHARE;
    IF speaker_value IS NULL THEN
        -- R-2 (audit 2026-09-22). THIS USED TO BE TWO BARE INSERTS:
        --     INSERT INTO ml_speakers(id) VALUES (speaker_value);
        --     INSERT INTO ml_speaker_principals(speaker_id, ...) VALUES (...);
        -- `ml_speakers` requires identity_version, identity_hash (UNIQUE,
        -- exactly 64 chars) and created_by; `ml_speaker_principals` requires
        -- binding_kind, binding_proof_hash and bound_by. All six are NOT NULL
        -- with no default, so the FIRST speaker this service ever had to mint
        -- would have raised a not-null violation and taken the Take down with
        -- it. The path is dark, so nobody had run it.
        --
        -- It now goes through register_ml_speaker_principal_v1, the canonical
        -- writer MLC-2 already owns, rather than a second hand-rolled pair of
        -- INSERTs. That writer also refuses to re-bind a principal already
        -- bound to a DIFFERENT identity, and calls assign_ml_speaker_split_v1
        -- — which the bare INSERTs skipped, so a speaker created here would
        -- have had no split assignment at all.
        --
        -- The identity is derived from the owner's user id and is therefore
        -- deterministic: a replay resolves to the same speaker instead of
        -- minting a second one. `initial` is the binding kind because this is
        -- the speaker's first identity, not a claim or a re-link.
        SELECT link.speaker_id INTO speaker_value
          FROM public.register_ml_speaker_principal_v1(
              p_acquisition_principal_id,
              encode(extensions.digest(
                  'mlc3-self-speaker-owner-v1:' || p_owner_user_id::TEXT,
                  'sha256'), 'hex'),
              'mlc3-self-speaker-owner-v1',
              'initial',
              encode(extensions.digest(
                  'mlc3-self-speaker-proof-v1:'
                  || p_acquisition_principal_id::TEXT || ':'
                  || p_owner_user_id::TEXT, 'sha256'), 'hex'),
              'mlc3-self-speaker-v1'
          ) link;
        IF speaker_value IS NULL THEN
            RAISE EXCEPTION 'MLC3_SELF_SPEAKER_BINDING_FAILED';
        END IF;
    END IF;
    INSERT INTO public.mlc3_self_speaker_assertions (
        acquisition_principal_id, owner_user_id, recording_attempt_id,
        audio_object_id, authorization_receipt_id, authorization_policy_id,
        assertion_value, target_start_ms, target_duration_ms, policy_version,
        idempotency_key, assertion_sha256
    ) VALUES (
        p_acquisition_principal_id, p_owner_user_id, attempt.id, audio.id,
        (access_row->>'authorization_receipt_id')::UUID,
        (access_row->>'authorization_policy_id')::UUID,
        'this_is_my_voice', target_start, target_duration,
        'mlc3-self-speaker-assertion-v1', p_idempotency_key, assertion_hash
    ) RETURNING * INTO existing_assertion;
    SELECT COALESCE(max(row.revision_number), 0) + 1
      INTO next_acquisition_revision
      FROM public.mlc3_speaker_acquisition_revisions row
     WHERE row.recording_attempt_id = attempt.id;
    acquisition_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'recording_attempt_id', attempt.id,
        'audio_object_id', audio.id,
        'speaker_count_status', 'unknown',
        'speaker_identity_status', 'resolved',
        'speaker_id', speaker_value,
        'assertion_id', existing_assertion.id,
        'revision_number', next_acquisition_revision
    ));
    INSERT INTO public.mlc3_speaker_acquisition_revisions (
        acquisition_principal_id, recording_attempt_id, audio_object_id,
        revision_number, supersedes_revision_id, speaker_count_status,
        speaker_identity_status, speaker_id, count_policy_version,
        identity_policy_version, evidence_source, audio_sha256, binding_sha256
    ) SELECT
        p_acquisition_principal_id, attempt.id, audio.id,
        next_acquisition_revision,
        (SELECT row.id FROM public.mlc3_speaker_acquisition_revisions row
          WHERE row.recording_attempt_id = attempt.id
          ORDER BY row.revision_number DESC LIMIT 1),
        'unknown', 'resolved', speaker_value,
        'self-speaker-count-v1', 'self-speaker-identity-v1', 'self_speaker',
        audio.exact_bytes_sha256, acquisition_hash
    RETURNING * INTO acquisition_revision;
    SELECT COALESCE(max(row.revision_number), 0) + 1
      INTO next_target_revision
      FROM public.mlc3_target_speaker_bindings row
     WHERE row.recording_attempt_id = attempt.id;
    binding_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'acquisition_revision_id', acquisition_revision.id,
        'speaker_id', speaker_value,
        'clip_id', target_clip_id,
        'practice_attempt_id', target_practice_attempt_id,
        'audio_sha256', audio.exact_bytes_sha256,
        'start_offset_ms', target_start,
        'duration_ms', target_duration,
        'transcript_sha256', transcript_hash,
        'assertion_id', existing_assertion.id,
        'revision_number', next_target_revision
    ));
    INSERT INTO public.mlc3_target_speaker_bindings (
        acquisition_principal_id, recording_attempt_id, audio_object_id,
        acquisition_revision_id, speaker_id, self_speaker_assertion_id,
        revision_number, supersedes_binding_id, binding_state, clip_id,
        practice_attempt_id,
        target_start_ms, target_duration_ms, transcript_span,
        transcript_sha256, audio_sha256, segmentation_policy_version,
        segmentation_run_version, target_binding_sha256
    ) SELECT
        p_acquisition_principal_id, attempt.id, audio.id,
        acquisition_revision.id, speaker_value, existing_assertion.id,
        next_target_revision,
        (SELECT row.id FROM public.mlc3_target_speaker_bindings row
          WHERE row.recording_attempt_id = attempt.id
          ORDER BY row.revision_number DESC LIMIT 1),
        'active', target_clip_id, target_practice_attempt_id,
        target_start, target_duration,
        jsonb_build_object(
            'snippet_id', target_clip_id,
            'practice_attempt_id', target_practice_attempt_id,
            'text', target_text
        ),
        transcript_hash, audio.exact_bytes_sha256,
        'self-speaker-target-span-v1', 'explicit-user-assertion-v1',
        binding_hash
    RETURNING * INTO target_binding;
    RETURN jsonb_build_object(
        'assertion_id', existing_assertion.id,
        'speaker_id', speaker_value,
        'acquisition_revision_id', acquisition_revision.id,
        'target_binding_id', target_binding.id,
        'replayed', false
    );
END;
$$;

-- CREATE OR REPLACE preserves a function's ACL; this restates what 0331
-- already granted, so a reader auditing the identity writer does not have to
-- open another file to learn it is service_role-only.
REVOKE ALL ON FUNCTION public.record_mlc3_self_speaker_target_v1(
    UUID,UUID,UUID,UUID,UUID,TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.record_mlc3_self_speaker_target_v1(
    UUID,UUID,UUID,UUID,UUID,TEXT
) TO service_role;
