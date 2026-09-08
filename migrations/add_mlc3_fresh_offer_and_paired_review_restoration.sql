-- 0320: MLC-3 P2 fresh-offer, paired-review, and post-blind authoring
-- restoration. Synthetic-only, non-serving, and non-dataset.

BEGIN;

CREATE TABLE IF NOT EXISTS public.exercise_service_offers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    acquisition_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    project_id UUID NOT NULL REFERENCES public.projects(id) ON DELETE RESTRICT,
    source_take_id UUID NOT NULL REFERENCES public.takes(id) ON DELETE RESTRICT,
    source_audio_lineage_id UUID NOT NULL
        REFERENCES public.exercise_audio_lineages(id) ON DELETE RESTRICT,
    feedback_membership_id UUID NOT NULL
        REFERENCES public.feedback_v3_memberships(id) ON DELETE RESTRICT,
    feedback_candidate_id UUID NOT NULL,
    n1_candidate_set_id UUID NOT NULL
        REFERENCES public.exercise_n1_pattern_snapshots(candidate_set_id)
        ON DELETE RESTRICT,
    authorization_check_id UUID NOT NULL
        REFERENCES public.exercise_authorization_checks(id) ON DELETE RESTRICT,
    selected_exercise_version_id UUID NULL
        REFERENCES public.exercise_versions(id) ON DELETE RESTRICT,
    outcome TEXT NOT NULL CHECK (outcome IN ('synthetic_matched', 'synthetic_no_match')),
    candidate_count INTEGER NOT NULL CHECK (candidate_count >= 0),
    eligible_count INTEGER NOT NULL CHECK (
        eligible_count BETWEEN 0 AND candidate_count
    ),
    inventory JSONB NOT NULL CHECK (jsonb_typeof(inventory) = 'array'),
    inventory_sha256 TEXT NOT NULL CHECK (inventory_sha256 ~ '^[0-9a-f]{64}$'),
    matching_policy_version TEXT NOT NULL CHECK (
        matching_policy_version = 'exercise-proximity-service-v1'
    ),
    offer_sha256 TEXT NOT NULL CHECK (offer_sha256 ~ '^[0-9a-f]{64}$'),
    idempotency_key TEXT NOT NULL UNIQUE CHECK (
        length(btrim(idempotency_key)) BETWEEN 1 AND 200
    ),
    prepared_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    FOREIGN KEY (feedback_membership_id, feedback_candidate_id)
        REFERENCES public.feedback_v3_membership_items(membership_id, candidate_id)
        ON DELETE RESTRICT,
    CHECK ((outcome = 'synthetic_matched' AND selected_exercise_version_id IS NOT NULL)
        OR (outcome = 'synthetic_no_match' AND selected_exercise_version_id IS NULL)),
    UNIQUE (feedback_membership_id, feedback_candidate_id, matching_policy_version),
    UNIQUE (id, acquisition_principal_id)
);

CREATE TABLE IF NOT EXISTS public.exercise_service_offer_candidates (
    offer_id UUID NOT NULL REFERENCES public.exercise_service_offers(id)
        ON DELETE RESTRICT,
    acquisition_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    exercise_version_id UUID NOT NULL REFERENCES public.exercise_versions(id)
        ON DELETE RESTRICT,
    eligibility TEXT NOT NULL CHECK (eligibility IN ('eligible', 'excluded')),
    exclusion_reasons TEXT[] NOT NULL,
    source_pattern TEXT NOT NULL,
    supported_confidence_patterns TEXT[] NOT NULL,
    pattern_distance INTEGER NULL CHECK (pattern_distance BETWEEN 0 AND 2),
    deterministic_rank INTEGER NULL CHECK (deterministic_rank > 0),
    candidate_sha256 TEXT NOT NULL CHECK (candidate_sha256 ~ '^[0-9a-f]{64}$'),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    PRIMARY KEY (offer_id, exercise_version_id),
    FOREIGN KEY (offer_id, acquisition_principal_id)
        REFERENCES public.exercise_service_offers(id, acquisition_principal_id)
        ON DELETE RESTRICT,
    CHECK ((eligibility = 'eligible' AND cardinality(exclusion_reasons) = 0
            AND pattern_distance IS NOT NULL AND deterministic_rank IS NOT NULL)
        OR (eligibility = 'excluded' AND cardinality(exclusion_reasons) > 0
            AND deterministic_rank IS NULL))
);

CREATE TABLE IF NOT EXISTS public.exercise_service_offer_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    offer_id UUID NOT NULL REFERENCES public.exercise_service_offers(id)
        ON DELETE RESTRICT,
    acquisition_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    event_kind TEXT NOT NULL CHECK (event_kind IN (
        'assignment_prepared', 'delivery_prepared', 'render_confirmed',
        'playback_started', 'playback_completed'
    )),
    event_payload JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (
        jsonb_typeof(event_payload) = 'object'
    ),
    event_sha256 TEXT NOT NULL CHECK (event_sha256 ~ '^[0-9a-f]{64}$'),
    idempotency_key TEXT NOT NULL UNIQUE,
    occurred_at TIMESTAMPTZ NOT NULL,
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    FOREIGN KEY (offer_id, acquisition_principal_id)
        REFERENCES public.exercise_service_offers(id, acquisition_principal_id)
        ON DELETE RESTRICT
);

-- The P1 evidence layer may only begin from this fresh service offer.  A dark
-- assignment UUID cannot satisfy this relationship.
ALTER TABLE public.exercise_practice_sessions
    DROP CONSTRAINT IF EXISTS exercise_practice_sessions_source_offer_fk;
ALTER TABLE public.exercise_practice_sessions
    ADD CONSTRAINT exercise_practice_sessions_source_offer_fk
    FOREIGN KEY (source_offer_id, acquisition_principal_id)
    REFERENCES public.exercise_service_offers(id, acquisition_principal_id)
    ON DELETE RESTRICT;

CREATE OR REPLACE FUNCTION public.freeze_synthetic_exercise_service_offer_v1(
    p_feedback_membership_id UUID,
    p_feedback_candidate_id UUID,
    p_n1_candidate_set_id UUID,
    p_authorization_check_id UUID,
    p_idempotency_key TEXT
) RETURNS public.exercise_service_offers
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    membership public.feedback_v3_memberships;
    feedback_item public.feedback_v3_membership_items;
    n1_snapshot public.exercise_n1_pattern_snapshots;
    candidate_set public.exercise_candidate_sets;
    lineage public.exercise_audio_lineages;
    existing public.exercise_service_offers;
    inventory JSONB;
    inventory_hash TEXT;
    offer_hash TEXT;
    chosen UUID;
    total_count INTEGER;
    eligible_count INTEGER;
    item RECORD;
    rank_index INTEGER := 0;
BEGIN
    IF COALESCE(btrim(p_idempotency_key), '') = '' THEN
        RAISE EXCEPTION 'EXERCISE_SERVICE_OFFER_KEY_REQUIRED';
    END IF;
    SELECT * INTO membership
      FROM public.require_synthetic_feedback_v3_membership_live_v1(
          p_feedback_membership_id
      );
    SELECT * INTO STRICT feedback_item FROM public.feedback_v3_membership_items
     WHERE membership_id = membership.id AND candidate_id = p_feedback_candidate_id
       AND feedback_family = 'confident_voice' AND selected
       AND eligibility = 'eligible';
    SELECT * INTO STRICT n1_snapshot FROM public.exercise_n1_pattern_snapshots
     WHERE candidate_set_id = p_n1_candidate_set_id
       AND acquisition_principal_id = membership.acquisition_principal_id;
    SELECT * INTO STRICT candidate_set FROM public.exercise_candidate_sets
     WHERE id = n1_snapshot.candidate_set_id
       AND acquisition_principal_id = membership.acquisition_principal_id;
    SELECT * INTO STRICT lineage FROM public.exercise_audio_lineages
     WHERE id = candidate_set.audio_lineage_id
       AND acquisition_principal_id = membership.acquisition_principal_id
       AND take_id = membership.take_id
       AND snippet_id = feedback_item.snippet_id;
    IF candidate_set.source_candidate_id <> feedback_item.candidate_key
       OR feedback_item.evidence_span_id IS NULL
    THEN RAISE EXCEPTION 'EXERCISE_SERVICE_OFFER_FEEDBACK_LINEAGE_INVALID'; END IF;
    PERFORM public.require_exercise_assignment_authority_v1(
        p_authorization_check_id, membership.acquisition_principal_id
    );

    SELECT COALESCE(jsonb_agg(jsonb_build_object(
        'exercise_version_id', source.exercise_version_id,
        'eligibility', CASE WHEN base.eligibility = 'eligible'
             AND source.compatibility_state = 'rankable' THEN 'eligible' ELSE 'excluded' END,
        'exclusion_reasons', CASE WHEN base.eligibility = 'eligible'
             AND source.compatibility_state = 'rankable' THEN '[]'::jsonb
             ELSE to_jsonb(CASE WHEN source.compatibility_state = 'excluded'
                  THEN array_append(base.exclusion_reasons, source.exclusion_reason)
                  ELSE base.exclusion_reasons END) END,
        'source_pattern', source.source_pattern,
        'supported_confidence_patterns', to_jsonb(source.supported_confidence_patterns),
        'pattern_distance', source.pattern_distance,
        'base_rank', base.deterministic_rank,
        'editorial_priority', COALESCE(profile.editorial_priority, 0)
    ) ORDER BY
        CASE WHEN base.eligibility = 'eligible'
              AND source.compatibility_state = 'rankable' THEN 0 ELSE 1 END,
        source.pattern_distance NULLS LAST,
        base.deterministic_rank NULLS LAST,
        COALESCE(profile.editorial_priority, 0) DESC,
        source.exercise_version_id), '[]'::jsonb)
    INTO inventory
    FROM public.exercise_n1_pattern_candidates source
    JOIN public.exercise_candidates base
      ON base.candidate_set_id = source.candidate_set_id
     AND base.exercise_version_id = source.exercise_version_id
    LEFT JOIN public.exercise_n1_version_compatibility_profiles profile
      ON profile.id = source.compatibility_profile_id
    WHERE source.candidate_set_id = n1_snapshot.candidate_set_id
      AND source.acquisition_principal_id = membership.acquisition_principal_id;
    total_count := jsonb_array_length(inventory);
    IF total_count <> n1_snapshot.candidate_count THEN
        RAISE EXCEPTION 'EXERCISE_SERVICE_OFFER_INVENTORY_INCOMPLETE';
    END IF;
    SELECT count(*) INTO eligible_count
      FROM jsonb_array_elements(inventory) value
     WHERE value->>'eligibility' = 'eligible';
    SELECT (value->>'exercise_version_id')::UUID INTO chosen
      FROM jsonb_array_elements(inventory) value
     WHERE value->>'eligibility' = 'eligible'
     ORDER BY (value->>'pattern_distance')::INTEGER,
              COALESCE((value->>'base_rank')::INTEGER, 2147483647),
              COALESCE((value->>'editorial_priority')::INTEGER, 0) DESC,
              value->>'exercise_version_id'
     LIMIT 1;
    inventory_hash := public.exercise_json_sha256_v1(inventory);
    offer_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'acquisition_principal_id', membership.acquisition_principal_id,
        'project_id', membership.project_id, 'source_take_id', membership.take_id,
        'source_audio_lineage_id', lineage.id,
        'feedback_membership_id', membership.id,
        'feedback_candidate_id', feedback_item.candidate_id,
        'n1_candidate_set_id', n1_snapshot.candidate_set_id,
        'authorization_check_id', p_authorization_check_id,
        'selected_exercise_version_id', chosen,
        'candidate_count', total_count, 'eligible_count', eligible_count,
        'inventory_sha256', inventory_hash,
        'matching_policy_version', 'exercise-proximity-service-v1'));

    PERFORM pg_advisory_xact_lock(hashtextextended(
        'exercise-service-offer:' || p_idempotency_key, 0));
    PERFORM public.require_exercise_assignment_authority_v1(
        p_authorization_check_id, membership.acquisition_principal_id);
    PERFORM public.require_synthetic_feedback_v3_membership_live_v1(
        membership.id);
    IF NOT EXISTS (
        SELECT 1 FROM public.processing_audio_objects object_row
         WHERE object_row.id = lineage.processing_audio_object_id
           AND object_row.acquisition_principal_id = membership.acquisition_principal_id
           AND object_row.deleted_at IS NULL
    ) THEN RAISE EXCEPTION 'EXERCISE_SERVICE_OFFER_SOURCE_NOT_LIVE'; END IF;
    SELECT * INTO existing FROM public.exercise_service_offers
     WHERE idempotency_key = p_idempotency_key;
    IF existing.id IS NOT NULL THEN
        IF existing.offer_sha256 <> offer_hash THEN
            RAISE EXCEPTION 'EXERCISE_SERVICE_OFFER_REPLAY_CONFLICT'; END IF;
        RETURN existing;
    END IF;
    INSERT INTO public.exercise_service_offers (
        acquisition_principal_id, project_id, source_take_id,
        source_audio_lineage_id, feedback_membership_id, feedback_candidate_id,
        n1_candidate_set_id, authorization_check_id,
        selected_exercise_version_id, outcome, candidate_count, eligible_count,
        inventory, inventory_sha256, matching_policy_version, offer_sha256,
        idempotency_key
    ) VALUES (
        membership.acquisition_principal_id, membership.project_id,
        membership.take_id, lineage.id, membership.id, feedback_item.candidate_id,
        n1_snapshot.candidate_set_id, p_authorization_check_id, chosen,
        CASE WHEN chosen IS NULL THEN 'synthetic_no_match' ELSE 'synthetic_matched' END,
        total_count, eligible_count, inventory, inventory_hash,
        'exercise-proximity-service-v1', offer_hash, p_idempotency_key
    ) RETURNING * INTO existing;
    FOR item IN SELECT value FROM jsonb_array_elements(inventory) LOOP
        IF item.value->>'eligibility' = 'eligible' THEN
            rank_index := rank_index + 1;
        END IF;
        INSERT INTO public.exercise_service_offer_candidates (
            offer_id, acquisition_principal_id, exercise_version_id,
            eligibility, exclusion_reasons, source_pattern,
            supported_confidence_patterns, pattern_distance, deterministic_rank,
            candidate_sha256
        ) VALUES (
            existing.id, existing.acquisition_principal_id,
            (item.value->>'exercise_version_id')::UUID,
            item.value->>'eligibility', ARRAY(
                SELECT jsonb_array_elements_text(item.value->'exclusion_reasons')),
            item.value->>'source_pattern', ARRAY(
                SELECT jsonb_array_elements_text(item.value->'supported_confidence_patterns')),
            NULLIF(item.value->>'pattern_distance', '')::INTEGER,
            CASE WHEN item.value->>'eligibility' = 'eligible'
                 THEN rank_index ELSE NULL END,
            public.exercise_json_sha256_v1(item.value)
        );
    END LOOP;
    INSERT INTO public.exercise_service_offer_events (
        offer_id, acquisition_principal_id, event_kind, event_payload,
        event_sha256, idempotency_key, occurred_at
    ) VALUES (
        existing.id, existing.acquisition_principal_id, 'assignment_prepared',
        jsonb_build_object('offer_sha256', existing.offer_sha256),
        public.exercise_json_sha256_v1(jsonb_build_object(
            'offer_id', existing.id, 'event_kind', 'assignment_prepared')),
        p_idempotency_key || ':assignment-prepared', clock_timestamp()
    );
    RETURN existing;
END;
$$;

-- Replace the function above with a straight-line implementation.  The
-- CREATE OR REPLACE keeps the migration re-runnable while avoiding exception-
-- driven control flow around the source check.
CREATE OR REPLACE FUNCTION public.create_synthetic_exercise_practice_session_v1(
    p_offer_id UUID,
    p_authorization_check_id UUID,
    p_exact_passage TEXT,
    p_session_window_version TEXT,
    p_opens_at TIMESTAMPTZ,
    p_closes_at TIMESTAMPTZ,
    p_idempotency_key TEXT
) RETURNS public.exercise_practice_sessions
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE offer public.exercise_service_offers;
    result public.exercise_practice_sessions; passage_hash TEXT;
BEGIN
    IF COALESCE(btrim(p_exact_passage), '') = ''
       OR COALESCE(btrim(p_session_window_version), '') = ''
       OR COALESCE(btrim(p_idempotency_key), '') = ''
       OR p_closes_at <= p_opens_at
    THEN RAISE EXCEPTION 'PRACTICE_SESSION_INVALID'; END IF;
    SELECT * INTO STRICT offer FROM public.exercise_service_offers
     WHERE id = p_offer_id AND outcome = 'synthetic_matched'
       AND serves_user = false AND dataset_eligible = false;
    PERFORM public.require_practice_processing_authority_v1(
        p_authorization_check_id, offer.acquisition_principal_id);
    passage_hash := public.exercise_json_sha256_v1(to_jsonb(p_exact_passage));
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'practice-session:' || p_idempotency_key, 0));
    PERFORM public.require_practice_processing_authority_v1(
        p_authorization_check_id, offer.acquisition_principal_id);
    IF NOT EXISTS (SELECT 1 FROM public.processing_audio_objects object_row
        JOIN public.exercise_audio_lineages lineage
          ON lineage.processing_audio_object_id = object_row.id
       WHERE lineage.id = offer.source_audio_lineage_id
         AND object_row.acquisition_principal_id =
             offer.acquisition_principal_id
         AND object_row.deleted_at IS NULL)
       OR EXISTS (
          SELECT 1 FROM public.data_purge_requests purge
           WHERE purge.acquisition_principal_id =
                 offer.acquisition_principal_id
             AND purge.state <> 'done'
       )
    THEN RAISE EXCEPTION 'PRACTICE_SOURCE_NOT_LIVE'; END IF;
    SELECT * INTO result FROM public.exercise_practice_sessions
     WHERE idempotency_key = p_idempotency_key;
    IF result.id IS NOT NULL THEN
        IF result.source_offer_id <> offer.id
           OR result.exercise_version_id <> offer.selected_exercise_version_id
           OR result.exact_passage_sha256 <> passage_hash
        THEN RAISE EXCEPTION 'PRACTICE_SESSION_REPLAY_CONFLICT'; END IF;
        PERFORM public.require_practice_source_live_v1(
            result.id, result.acquisition_principal_id);
        RETURN result;
    END IF;
    INSERT INTO public.exercise_practice_sessions (
        acquisition_principal_id, project_id, source_take_id,
        source_audio_lineage_id, source_offer_id, exercise_version_id,
        authorization_check_id, exact_passage, exact_passage_sha256,
        session_window_version, opens_at, closes_at, idempotency_key
    ) VALUES (
        offer.acquisition_principal_id, offer.project_id, offer.source_take_id,
        offer.source_audio_lineage_id, offer.id,
        offer.selected_exercise_version_id, p_authorization_check_id,
        p_exact_passage, passage_hash, p_session_window_version,
        p_opens_at, p_closes_at, p_idempotency_key
    ) RETURNING * INTO result;
    PERFORM public.require_practice_source_live_v1(
        result.id, result.acquisition_principal_id);
    RETURN result;
END;
$$;

CREATE TABLE IF NOT EXISTS public.exercise_pair_revisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    acquisition_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    practice_session_id UUID NOT NULL
        REFERENCES public.exercise_practice_sessions(id) ON DELETE RESTRICT,
    source_audio_lineage_id UUID NOT NULL
        REFERENCES public.exercise_audio_lineages(id) ON DELETE RESTRICT,
    selection_revision_id UUID NOT NULL
        REFERENCES public.exercise_practice_selection_revisions(id)
        ON DELETE RESTRICT,
    practice_attempt_id UUID NOT NULL
        REFERENCES public.exercise_practice_attempts(id) ON DELETE RESTRICT,
    comparison_revision INTEGER NOT NULL CHECK (comparison_revision > 0),
    pair_sha256 TEXT NOT NULL CHECK (pair_sha256 ~ '^[0-9a-f]{64}$'),
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    UNIQUE (practice_session_id, comparison_revision),
    UNIQUE (id, acquisition_principal_id)
);

CREATE TABLE IF NOT EXISTS public.exercise_pair_assignments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pair_revision_id UUID NOT NULL REFERENCES public.exercise_pair_revisions(id)
        ON DELETE RESTRICT,
    acquisition_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    reviewer_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    reviewer_role TEXT NOT NULL CHECK (reviewer_role IN ('owner', 'blind_coach')),
    left_clip TEXT NOT NULL CHECK (left_clip IN ('before', 'after')),
    right_clip TEXT NOT NULL CHECK (right_clip IN ('before', 'after')),
    context_state TEXT NOT NULL CHECK (context_state IN (
        'owner_nonblind', 'blind_no_recorded_context', 'known_prior_context'
    )),
    order_policy_version TEXT NOT NULL CHECK (
        order_policy_version = 'paired-preference-order-v1'
    ),
    assignment_sha256 TEXT NOT NULL CHECK (assignment_sha256 ~ '^[0-9a-f]{64}$'),
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    CHECK (left_clip <> right_clip),
    FOREIGN KEY (pair_revision_id, acquisition_principal_id)
        REFERENCES public.exercise_pair_revisions(id, acquisition_principal_id)
        ON DELETE RESTRICT,
    UNIQUE (pair_revision_id, reviewer_principal_id)
);

CREATE TABLE IF NOT EXISTS public.exercise_pair_judgments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pair_assignment_id UUID NOT NULL UNIQUE
        REFERENCES public.exercise_pair_assignments(id) ON DELETE RESTRICT,
    acquisition_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    reviewer_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    answer TEXT NOT NULL CHECK (answer IN (
        'prefer_left', 'prefer_right', 'same', 'not_sure', 'audio_unusable'
    )),
    answer_taxonomy_version TEXT NOT NULL CHECK (
        answer_taxonomy_version = 'paired-listening-preference-five-state-v1'
    ),
    idempotency_key TEXT NOT NULL UNIQUE,
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible)
);

CREATE TABLE IF NOT EXISTS public.exercise_reviewer_context_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    reviewer_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    source_audio_lineage_id UUID NOT NULL
        REFERENCES public.exercise_audio_lineages(id) ON DELETE RESTRICT,
    practice_attempt_id UUID NULL REFERENCES public.exercise_practice_attempts(id)
        ON DELETE RESTRICT,
    event_kind TEXT NOT NULL CHECK (event_kind IN (
        'source_heard', 'practice_heard', 'chronology_revealed'
    )),
    idempotency_key TEXT NOT NULL UNIQUE,
    occurred_at TIMESTAMPTZ NOT NULL,
    event_sha256 TEXT NOT NULL CHECK (event_sha256 ~ '^[0-9a-f]{64}$'),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible)
);

CREATE TABLE IF NOT EXISTS public.exercise_service_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    offer_id UUID NOT NULL UNIQUE REFERENCES public.exercise_service_offers(id)
        ON DELETE RESTRICT,
    acquisition_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    blind_packet_id UUID NOT NULL REFERENCES public.exercise_blind_packets(id)
        ON DELETE RESTRICT,
    judgment_id UUID NOT NULL REFERENCES public.ml_judgments(id) ON DELETE RESTRICT,
    reveal_event_id UUID NOT NULL REFERENCES public.exercise_blind_packet_events(id)
        ON DELETE RESTRICT,
    state TEXT NOT NULL CHECK (state = 'synthetic_post_blind_pending'),
    reason_code TEXT NOT NULL CHECK (reason_code = 'no_eligible_exercise'),
    request_sha256 TEXT NOT NULL CHECK (request_sha256 ~ '^[0-9a-f]{64}$'),
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    FOREIGN KEY (offer_id, acquisition_principal_id)
        REFERENCES public.exercise_service_offers(id, acquisition_principal_id)
        ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS public.exercise_authoring_drafts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id UUID NOT NULL REFERENCES public.exercise_service_requests(id)
        ON DELETE RESTRICT,
    acquisition_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    author_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    instruction_text TEXT NOT NULL CHECK (length(btrim(instruction_text)) > 0),
    target_need_contract_id UUID NOT NULL
        REFERENCES public.exercise_need_contracts(id) ON DELETE RESTRICT,
    state TEXT NOT NULL CHECK (state = 'synthetic_draft'),
    draft_sha256 TEXT NOT NULL CHECK (draft_sha256 ~ '^[0-9a-f]{64}$'),
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible)
);

CREATE OR REPLACE FUNCTION public.freeze_synthetic_exercise_pair_v1(
    p_practice_session_id UUID,
    p_selection_revision_id UUID,
    p_comparison_revision INTEGER,
    p_idempotency_key TEXT
) RETURNS public.exercise_pair_revisions
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE practice public.exercise_practice_sessions;
    selection public.exercise_practice_selection_revisions;
    attempt public.exercise_practice_attempts;
    pair_hash TEXT; existing public.exercise_pair_revisions;
BEGIN
    SELECT * INTO practice FROM public.require_practice_source_live_v1(
        p_practice_session_id, (SELECT acquisition_principal_id
          FROM public.exercise_practice_sessions WHERE id=p_practice_session_id));
    SELECT * INTO STRICT selection FROM public.exercise_practice_selection_revisions
     WHERE id=p_selection_revision_id AND session_id=practice.id
       AND acquisition_principal_id=practice.acquisition_principal_id
       AND baseline_revision=practice.baseline_revision
       AND selection_state='selected_first_valid';
    SELECT * INTO STRICT attempt FROM public.exercise_practice_attempts
     WHERE id=selection.selected_attempt_id AND session_id=practice.id
       AND acquisition_principal_id=practice.acquisition_principal_id;
    IF p_comparison_revision<1 OR COALESCE(btrim(p_idempotency_key),'')=''
    THEN RAISE EXCEPTION 'EXERCISE_PAIR_INVALID'; END IF;
    pair_hash:=public.exercise_json_sha256_v1(jsonb_build_object(
        'practice_session_id',practice.id,
        'source_audio_lineage_id',practice.source_audio_lineage_id,
        'selection_revision_id',selection.id,
        'selection_inventory_sha256',selection.inventory_sha256,
        'practice_attempt_id',attempt.id,
        'practice_audio_sha256',attempt.exact_audio_sha256,
        'comparison_revision',p_comparison_revision));
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'exercise-pair:'||p_idempotency_key,0));
    PERFORM public.require_practice_source_live_v1(
        practice.id,practice.acquisition_principal_id);
    SELECT * INTO existing FROM public.exercise_pair_revisions
     WHERE idempotency_key=p_idempotency_key;
    IF existing.id IS NOT NULL THEN
        IF existing.pair_sha256<>pair_hash THEN
            RAISE EXCEPTION 'EXERCISE_PAIR_REPLAY_CONFLICT'; END IF;
        RETURN existing;
    END IF;
    INSERT INTO public.exercise_pair_revisions(
        acquisition_principal_id,practice_session_id,source_audio_lineage_id,
        selection_revision_id,practice_attempt_id,comparison_revision,
        pair_sha256,idempotency_key)
    VALUES(practice.acquisition_principal_id,practice.id,
        practice.source_audio_lineage_id,selection.id,attempt.id,
        p_comparison_revision,pair_hash,p_idempotency_key)
    RETURNING * INTO existing;
    RETURN existing;
END;
$$;

CREATE OR REPLACE FUNCTION public.assign_synthetic_exercise_pair_v1(
    p_pair_revision_id UUID,
    p_reviewer_principal_id UUID,
    p_reviewer_role TEXT,
    p_idempotency_key TEXT
) RETURNS public.exercise_pair_assignments
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE pair_row public.exercise_pair_revisions; context_state TEXT;
    left_clip TEXT; assignment_hash TEXT;
    existing public.exercise_pair_assignments;
BEGIN
    SELECT * INTO STRICT pair_row FROM public.exercise_pair_revisions
     WHERE id=p_pair_revision_id;
    IF p_reviewer_role NOT IN ('owner','blind_coach')
       OR COALESCE(btrim(p_idempotency_key),'')=''
       OR (p_reviewer_role='owner' AND p_reviewer_principal_id<>
           pair_row.acquisition_principal_id)
    THEN RAISE EXCEPTION 'EXERCISE_PAIR_ASSIGNMENT_INVALID'; END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'exercise-pair-assignment:'||p_idempotency_key,0));
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'exercise-reviewer-context:'||p_reviewer_principal_id::TEXT||':'||
        pair_row.source_audio_lineage_id::TEXT,0));
    PERFORM public.require_practice_source_live_v1(
        (SELECT practice_session_id FROM public.exercise_pair_revisions
          WHERE id=pair_row.id), pair_row.acquisition_principal_id);
    IF p_reviewer_role='owner' THEN
        context_state:='owner_nonblind'; left_clip:='before';
    ELSE
        context_state:=CASE WHEN EXISTS(
            SELECT 1 FROM public.exercise_reviewer_context_events history
             WHERE history.reviewer_principal_id=p_reviewer_principal_id
               AND history.source_audio_lineage_id=pair_row.source_audio_lineage_id
               AND history.event_kind IN ('source_heard','chronology_revealed'))
          THEN 'known_prior_context' ELSE 'blind_no_recorded_context' END;
        left_clip:=CASE WHEN get_byte(extensions.digest(
            convert_to(pair_row.pair_sha256||':'||p_reviewer_principal_id::TEXT,'UTF8'),
            'sha256'),0)%2=0 THEN 'before' ELSE 'after' END;
    END IF;
    assignment_hash:=public.exercise_json_sha256_v1(jsonb_build_object(
        'pair_revision_id',pair_row.id,'pair_sha256',pair_row.pair_sha256,
        'reviewer_principal_id',p_reviewer_principal_id,
        'reviewer_role',p_reviewer_role,'left_clip',left_clip,
        'right_clip',CASE left_clip WHEN 'before' THEN 'after' ELSE 'before' END,
        'context_state',context_state,
        'order_policy_version','paired-preference-order-v1'));
    SELECT * INTO existing FROM public.exercise_pair_assignments
     WHERE idempotency_key=p_idempotency_key;
    IF existing.id IS NOT NULL THEN
        IF existing.assignment_sha256<>assignment_hash THEN
            RAISE EXCEPTION 'EXERCISE_PAIR_ASSIGNMENT_REPLAY_CONFLICT'; END IF;
        RETURN existing;
    END IF;
    INSERT INTO public.exercise_pair_assignments(
        pair_revision_id,acquisition_principal_id,reviewer_principal_id,
        reviewer_role,left_clip,right_clip,context_state,order_policy_version,
        assignment_sha256,idempotency_key)
    VALUES(pair_row.id,pair_row.acquisition_principal_id,p_reviewer_principal_id,
        p_reviewer_role,left_clip,
        CASE left_clip WHEN 'before' THEN 'after' ELSE 'before' END,
        context_state,'paired-preference-order-v1',assignment_hash,p_idempotency_key)
    RETURNING * INTO existing;
    RETURN existing;
END;
$$;

CREATE OR REPLACE FUNCTION public.submit_synthetic_exercise_pair_judgment_v1(
    p_pair_assignment_id UUID,
    p_reviewer_principal_id UUID,
    p_answer TEXT,
    p_idempotency_key TEXT
) RETURNS public.exercise_pair_judgments
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE assignment public.exercise_pair_assignments;
    existing public.exercise_pair_judgments;
BEGIN
    SELECT * INTO STRICT assignment FROM public.exercise_pair_assignments
     WHERE id=p_pair_assignment_id
       AND reviewer_principal_id=p_reviewer_principal_id;
    IF p_answer NOT IN ('prefer_left','prefer_right','same','not_sure','audio_unusable')
       OR COALESCE(btrim(p_idempotency_key),'')=''
    THEN RAISE EXCEPTION 'EXERCISE_PAIR_JUDGMENT_INVALID'; END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'exercise-pair-judgment:'||p_pair_assignment_id::TEXT,0));
    SELECT * INTO existing FROM public.exercise_pair_judgments
     WHERE pair_assignment_id=assignment.id OR idempotency_key=p_idempotency_key;
    IF existing.id IS NOT NULL THEN
        IF existing.pair_assignment_id<>assignment.id
           OR existing.reviewer_principal_id<>p_reviewer_principal_id
           OR existing.answer<>p_answer
           OR existing.idempotency_key<>p_idempotency_key
        THEN RAISE EXCEPTION 'EXERCISE_PAIR_JUDGMENT_REPLAY_CONFLICT'; END IF;
        RETURN existing;
    END IF;
    INSERT INTO public.exercise_pair_judgments(
        pair_assignment_id,acquisition_principal_id,reviewer_principal_id,
        answer,answer_taxonomy_version,idempotency_key)
    VALUES(assignment.id,assignment.acquisition_principal_id,
        p_reviewer_principal_id,p_answer,
        'paired-listening-preference-five-state-v1',p_idempotency_key)
    RETURNING * INTO existing;
    RETURN existing;
END;
$$;

CREATE OR REPLACE FUNCTION public.record_synthetic_exercise_reviewer_context_v1(
    p_pair_assignment_id UUID,
    p_reviewer_principal_id UUID,
    p_event_kind TEXT,
    p_idempotency_key TEXT
) RETURNS public.exercise_reviewer_context_events
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE assignment public.exercise_pair_assignments;
    pair_row public.exercise_pair_revisions;
    existing public.exercise_reviewer_context_events; event_hash TEXT;
BEGIN
    SELECT * INTO STRICT assignment FROM public.exercise_pair_assignments
     WHERE id=p_pair_assignment_id AND reviewer_principal_id=p_reviewer_principal_id;
    SELECT * INTO STRICT pair_row FROM public.exercise_pair_revisions
     WHERE id=assignment.pair_revision_id;
    IF p_event_kind NOT IN ('source_heard','practice_heard','chronology_revealed')
       OR (p_event_kind='chronology_revealed' AND NOT EXISTS(
           SELECT 1 FROM public.exercise_pair_judgments judgment
            WHERE judgment.pair_assignment_id=assignment.id))
    THEN RAISE EXCEPTION 'EXERCISE_REVIEWER_CONTEXT_INVALID'; END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'exercise-reviewer-context:'||p_reviewer_principal_id::TEXT||':'||
        pair_row.source_audio_lineage_id::TEXT,0));
    IF p_event_kind='chronology_revealed' AND NOT EXISTS(
        SELECT 1 FROM public.exercise_pair_judgments judgment
         WHERE judgment.pair_assignment_id=assignment.id)
    THEN RAISE EXCEPTION 'EXERCISE_REVIEWER_CONTEXT_INVALID'; END IF;
    event_hash:=public.exercise_json_sha256_v1(jsonb_build_object(
        'reviewer_principal_id',p_reviewer_principal_id,
        'source_audio_lineage_id',pair_row.source_audio_lineage_id,
        'practice_attempt_id',CASE WHEN p_event_kind='source_heard'
             THEN NULL ELSE pair_row.practice_attempt_id END,
        'event_kind',p_event_kind));
    INSERT INTO public.exercise_reviewer_context_events(
        reviewer_principal_id,source_audio_lineage_id,practice_attempt_id,
        event_kind,idempotency_key,occurred_at,event_sha256)
    VALUES(p_reviewer_principal_id,pair_row.source_audio_lineage_id,
        CASE WHEN p_event_kind='source_heard' THEN NULL ELSE pair_row.practice_attempt_id END,
        p_event_kind,p_idempotency_key,clock_timestamp(),event_hash)
    ON CONFLICT(idempotency_key) DO NOTHING;
    SELECT * INTO STRICT existing FROM public.exercise_reviewer_context_events
     WHERE idempotency_key=p_idempotency_key;
    IF existing.event_sha256<>event_hash THEN
        RAISE EXCEPTION 'EXERCISE_REVIEWER_CONTEXT_REPLAY_CONFLICT'; END IF;
    RETURN existing;
END;
$$;

CREATE OR REPLACE FUNCTION public.register_synthetic_service_no_match_request_v1(
    p_offer_id UUID,
    p_blind_packet_id UUID,
    p_reviewer_principal_id UUID,
    p_idempotency_key TEXT
) RETURNS public.exercise_service_requests
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    offer public.exercise_service_offers;
    packet public.exercise_blind_packets;
    review public.ml_review_assignments;
    judgment public.ml_judgments;
    submission public.exercise_blind_packet_events;
    reveal public.exercise_blind_packet_events;
    result public.exercise_service_requests;
    request_hash TEXT;
    idempotency_lock BIGINT;
    offer_lock BIGINT;
BEGIN
    IF COALESCE(btrim(p_idempotency_key), '') = '' THEN
        RAISE EXCEPTION 'EXERCISE_SERVICE_REQUEST_KEY_REQUIRED';
    END IF;
    SELECT * INTO STRICT offer FROM public.exercise_service_offers
     WHERE id = p_offer_id AND outcome = 'synthetic_no_match'
       AND serves_user = false AND dataset_eligible = false;
    PERFORM public.require_exercise_assignment_authority_v1(
        offer.authorization_check_id, offer.acquisition_principal_id);
    SELECT * INTO STRICT packet FROM public.exercise_blind_packets
     WHERE id = p_blind_packet_id
       AND audio_lineage_id = offer.source_audio_lineage_id
       AND reviewer_principal_id = p_reviewer_principal_id;
    SELECT * INTO STRICT review FROM public.ml_review_assignments
     WHERE id = packet.review_assignment_id
       AND reviewer_principal_id = p_reviewer_principal_id
       AND learning_surface_id = 'confidence_classification';
    SELECT * INTO submission FROM public.exercise_blind_packet_events
     WHERE blind_packet_id = packet.id
       AND review_assignment_id = review.id
       AND event_kind = 'blind_judgment_submitted'
       AND actor_principal_id = p_reviewer_principal_id;
    SELECT * INTO judgment FROM public.ml_judgments
     WHERE id = submission.judgment_id
       AND review_assignment_id = review.id
       AND evidence_span_id = review.evidence_span_id
       AND learning_surface_id = 'confidence_classification'
       AND actor_provenance = 'blind_coach'
       AND actor_principal_id = p_reviewer_principal_id;
    SELECT * INTO reveal FROM public.exercise_blind_packet_events
     WHERE blind_packet_id = packet.id
       AND review_assignment_id = review.id
       AND event_kind = 'post_judgment_reveal_accessed'
       AND actor_principal_id = p_reviewer_principal_id
       AND occurred_at >= submission.occurred_at
       AND created_at >= submission.created_at;
    IF judgment.id IS NULL OR reveal.id IS NULL
       OR NOT public.exercise_evidence_matches_audio_v1(
           judgment.evidence_span_id, offer.source_audio_lineage_id)
    THEN
        RAISE EXCEPTION 'EXERCISE_SERVICE_REQUEST_REQUIRES_EXACT_POST_BLIND_REVEAL';
    END IF;
    request_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'offer_id', offer.id,
        'offer_sha256', offer.offer_sha256,
        'blind_packet_id', packet.id,
        'judgment_id', judgment.id,
        'reveal_event_id', reveal.id,
        'reviewer_principal_id', p_reviewer_principal_id,
        'reason_code', 'no_eligible_exercise'));
    idempotency_lock := hashtextextended(
        'exercise-service-request:' || p_idempotency_key, 0);
    offer_lock := hashtextextended(
        'exercise-service-request-offer:' || offer.id::TEXT, 0);
    PERFORM pg_advisory_xact_lock(LEAST(idempotency_lock, offer_lock));
    IF idempotency_lock <> offer_lock THEN
        PERFORM pg_advisory_xact_lock(GREATEST(idempotency_lock, offer_lock));
    END IF;
    PERFORM public.require_exercise_assignment_authority_v1(
        offer.authorization_check_id, offer.acquisition_principal_id);
    IF NOT EXISTS (
        SELECT 1
          FROM public.processing_audio_objects object_row
          JOIN public.exercise_audio_lineages lineage
            ON lineage.processing_audio_object_id = object_row.id
         WHERE lineage.id = offer.source_audio_lineage_id
           AND lineage.acquisition_principal_id =
               offer.acquisition_principal_id
           AND object_row.acquisition_principal_id =
               offer.acquisition_principal_id
           AND object_row.deleted_at IS NULL
    ) OR EXISTS (
        SELECT 1 FROM public.data_purge_requests purge
         WHERE purge.acquisition_principal_id =
               offer.acquisition_principal_id
           AND purge.state <> 'done'
    ) OR NOT EXISTS (
        SELECT 1
          FROM public.exercise_blind_packet_events event
         WHERE event.id = reveal.id
           AND event.blind_packet_id = packet.id
           AND event.event_kind = 'post_judgment_reveal_accessed'
           AND event.actor_principal_id = p_reviewer_principal_id
    ) THEN
        RAISE EXCEPTION 'EXERCISE_SERVICE_REQUEST_SOURCE_NOT_LIVE';
    END IF;
    SELECT * INTO result FROM public.exercise_service_requests
     WHERE idempotency_key = p_idempotency_key;
    IF result.id IS NOT NULL THEN
        IF result.offer_id <> offer.id
           OR result.blind_packet_id <> packet.id
           OR result.judgment_id <> judgment.id
           OR result.reveal_event_id <> reveal.id
           OR result.request_sha256 <> request_hash
           OR result.idempotency_key <> p_idempotency_key
        THEN RAISE EXCEPTION 'EXERCISE_SERVICE_REQUEST_REPLAY_CONFLICT'; END IF;
        RETURN result;
    END IF;
    SELECT * INTO result FROM public.exercise_service_requests
     WHERE offer_id = offer.id;
    IF result.id IS NOT NULL THEN
        RAISE EXCEPTION 'EXERCISE_SERVICE_REQUEST_REPLAY_CONFLICT';
    END IF;
    INSERT INTO public.exercise_service_requests (
        offer_id, acquisition_principal_id, blind_packet_id, judgment_id,
        reveal_event_id, state, reason_code, request_sha256, idempotency_key
    ) VALUES (
        offer.id, offer.acquisition_principal_id, packet.id, judgment.id,
        reveal.id, 'synthetic_post_blind_pending', 'no_eligible_exercise',
        request_hash, p_idempotency_key
    ) RETURNING * INTO result;
    RETURN result;
END;
$$;

CREATE OR REPLACE FUNCTION public.create_synthetic_exercise_authoring_draft_v1(
    p_request_id UUID,
    p_author_principal_id UUID,
    p_instruction_text TEXT,
    p_idempotency_key TEXT
) RETURNS public.exercise_authoring_drafts
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    request_row public.exercise_service_requests;
    offer public.exercise_service_offers;
    packet public.exercise_blind_packets;
    review public.ml_review_assignments;
    n1_snapshot public.exercise_n1_pattern_snapshots;
    candidate_set public.exercise_candidate_sets;
    result public.exercise_authoring_drafts;
    draft_hash TEXT;
BEGIN
    IF COALESCE(btrim(p_instruction_text), '') = ''
       OR COALESCE(btrim(p_idempotency_key), '') = '' THEN
        RAISE EXCEPTION 'EXERCISE_AUTHORING_DRAFT_INVALID';
    END IF;
    SELECT * INTO STRICT request_row FROM public.exercise_service_requests
     WHERE id = p_request_id AND state = 'synthetic_post_blind_pending';
    SELECT * INTO STRICT offer FROM public.exercise_service_offers
     WHERE id = request_row.offer_id
       AND acquisition_principal_id = request_row.acquisition_principal_id
       AND outcome = 'synthetic_no_match';
    SELECT * INTO STRICT packet FROM public.exercise_blind_packets
     WHERE id = request_row.blind_packet_id
       AND audio_lineage_id = offer.source_audio_lineage_id
       AND reviewer_principal_id = p_author_principal_id;
    SELECT * INTO STRICT review FROM public.ml_review_assignments
     WHERE id = packet.review_assignment_id
       AND reviewer_principal_id = p_author_principal_id
       AND learning_surface_id = 'confidence_classification';
    SELECT * INTO STRICT n1_snapshot FROM public.exercise_n1_pattern_snapshots
     WHERE candidate_set_id = offer.n1_candidate_set_id
       AND acquisition_principal_id = offer.acquisition_principal_id;
    SELECT * INTO STRICT candidate_set FROM public.exercise_candidate_sets
     WHERE id = n1_snapshot.candidate_set_id
       AND acquisition_principal_id = offer.acquisition_principal_id;
    IF NOT EXISTS (
        SELECT 1 FROM public.exercise_blind_packet_events event
         WHERE event.id = request_row.reveal_event_id
           AND event.blind_packet_id = packet.id
           AND event.event_kind = 'post_judgment_reveal_accessed'
           AND event.actor_principal_id = p_author_principal_id
    ) THEN RAISE EXCEPTION 'EXERCISE_AUTHORING_REQUIRES_POST_BLIND_REVEAL'; END IF;
    PERFORM public.require_exercise_assignment_authority_v1(
        offer.authorization_check_id, offer.acquisition_principal_id);
    draft_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'request_id', request_row.id,
        'request_sha256', request_row.request_sha256,
        'author_principal_id', p_author_principal_id,
        'instruction_text', p_instruction_text,
        'target_need_contract_id', candidate_set.need_contract_id,
        'state', 'synthetic_draft'));
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'exercise-authoring-draft:' || p_idempotency_key, 0));
    PERFORM public.require_exercise_assignment_authority_v1(
        offer.authorization_check_id, offer.acquisition_principal_id);
    IF EXISTS (
        SELECT 1 FROM public.data_purge_requests purge
         WHERE purge.acquisition_principal_id =
               offer.acquisition_principal_id
           AND purge.state <> 'done'
    ) OR NOT EXISTS (
        SELECT 1
          FROM public.processing_audio_objects object_row
          JOIN public.exercise_audio_lineages lineage
            ON lineage.processing_audio_object_id = object_row.id
         WHERE lineage.id = offer.source_audio_lineage_id
           AND lineage.acquisition_principal_id =
               offer.acquisition_principal_id
           AND object_row.acquisition_principal_id =
               offer.acquisition_principal_id
           AND object_row.deleted_at IS NULL
    ) THEN RAISE EXCEPTION 'EXERCISE_AUTHORING_SOURCE_NOT_LIVE'; END IF;
    SELECT * INTO result FROM public.exercise_authoring_drafts
     WHERE idempotency_key = p_idempotency_key;
    IF result.id IS NOT NULL THEN
        IF result.request_id <> request_row.id
           OR result.author_principal_id <> p_author_principal_id
           OR result.target_need_contract_id <> candidate_set.need_contract_id
           OR result.draft_sha256 <> draft_hash
        THEN RAISE EXCEPTION 'EXERCISE_AUTHORING_DRAFT_REPLAY_CONFLICT'; END IF;
        RETURN result;
    END IF;
    INSERT INTO public.exercise_authoring_drafts (
        request_id, acquisition_principal_id, author_principal_id,
        instruction_text, target_need_contract_id, state, draft_sha256,
        idempotency_key
    ) VALUES (
        request_row.id, request_row.acquisition_principal_id,
        p_author_principal_id, p_instruction_text,
        candidate_set.need_contract_id, 'synthetic_draft', draft_hash,
        p_idempotency_key
    ) RETURNING * INTO result;
    RETURN result;
END;
$$;

CREATE OR REPLACE FUNCTION public.reject_exercise_service_event_exposure_v1()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path = public AS $$
BEGIN
    IF NEW.event_kind IN ('render_confirmed', 'playback_started', 'playback_completed') THEN
        RAISE EXCEPTION 'EXERCISE_SERVICE_EXPOSURE_DISABLED';
    END IF;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS exercise_service_event_exposure_disabled
    ON public.exercise_service_offer_events;
CREATE TRIGGER exercise_service_event_exposure_disabled
BEFORE INSERT ON public.exercise_service_offer_events FOR EACH ROW
EXECUTE FUNCTION public.reject_exercise_service_event_exposure_v1();

-- Keep these declarations explicit as well as applying the shared policy loop
-- below.  This makes the security boundary auditable by the migration scanner
-- and prevents a newly added table from being mistaken for an implicit RLS
-- dependency.
ALTER TABLE public.exercise_service_offers ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.exercise_service_offer_candidates ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.exercise_service_offer_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.exercise_pair_revisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.exercise_pair_assignments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.exercise_pair_judgments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.exercise_reviewer_context_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.exercise_service_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.exercise_authoring_drafts ENABLE ROW LEVEL SECURITY;

DO $$
DECLARE relation_name TEXT;
BEGIN
    FOREACH relation_name IN ARRAY ARRAY[
        'exercise_service_offers', 'exercise_service_offer_candidates',
        'exercise_service_offer_events', 'exercise_pair_revisions',
        'exercise_pair_assignments', 'exercise_pair_judgments',
        'exercise_reviewer_context_events', 'exercise_service_requests',
        'exercise_authoring_drafts'
    ] LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', relation_name);
        EXECUTE format(
            'REVOKE ALL ON public.%I FROM PUBLIC,anon,authenticated,service_role',
            relation_name);
        EXECUTE format('GRANT SELECT ON public.%I TO service_role', relation_name);
        EXECUTE format('DROP TRIGGER IF EXISTS %I ON public.%I',
            relation_name || '_append_only', relation_name);
        EXECUTE format(
            'CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON public.%I FOR EACH ROW '
            'EXECUTE FUNCTION public.reject_mlc2_immutable_mutation()',
            relation_name || '_append_only', relation_name);
    END LOOP;
END;
$$;

REVOKE ALL ON FUNCTION public.freeze_synthetic_exercise_service_offer_v1(
    UUID,UUID,UUID,UUID,TEXT
) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.freeze_synthetic_exercise_service_offer_v1(
    UUID,UUID,UUID,UUID,TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.create_synthetic_exercise_practice_session_v1(
    UUID,UUID,TEXT,TEXT,TIMESTAMPTZ,TIMESTAMPTZ,TEXT
) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.create_synthetic_exercise_practice_session_v1(
    UUID,UUID,TEXT,TEXT,TIMESTAMPTZ,TIMESTAMPTZ,TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.freeze_synthetic_exercise_pair_v1(
    UUID,UUID,INTEGER,TEXT
) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.freeze_synthetic_exercise_pair_v1(
    UUID,UUID,INTEGER,TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.assign_synthetic_exercise_pair_v1(
    UUID,UUID,TEXT,TEXT
) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.assign_synthetic_exercise_pair_v1(
    UUID,UUID,TEXT,TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.submit_synthetic_exercise_pair_judgment_v1(
    UUID,UUID,TEXT,TEXT
) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.submit_synthetic_exercise_pair_judgment_v1(
    UUID,UUID,TEXT,TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.record_synthetic_exercise_reviewer_context_v1(
    UUID,UUID,TEXT,TEXT
) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.record_synthetic_exercise_reviewer_context_v1(
    UUID,UUID,TEXT,TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.register_synthetic_service_no_match_request_v1(
    UUID,UUID,UUID,TEXT
) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.register_synthetic_service_no_match_request_v1(
    UUID,UUID,UUID,TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.create_synthetic_exercise_authoring_draft_v1(
    UUID,UUID,TEXT,TEXT
) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.create_synthetic_exercise_authoring_draft_v1(
    UUID,UUID,TEXT,TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.reject_exercise_service_event_exposure_v1()
    FROM PUBLIC,anon,authenticated,service_role;

COMMENT ON TABLE public.exercise_service_offers IS
    'Fresh synthetic service offers; never converted from dark assignments and never user-exposed in this release.';
COMMENT ON TABLE public.exercise_pair_judgments IS
    'Independent five-state listening preferences; never confidence or causal-effectiveness labels.';

COMMIT;
