-- 0318: Feedback Policy V3 service contract restoration.
-- The schema is executable only through synthetic RPCs and structurally
-- cannot serve or create learning-eligible records in this release.

BEGIN;

CREATE TABLE IF NOT EXISTS public.feedback_v3_memberships (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    acquisition_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    project_id UUID NOT NULL REFERENCES public.projects(id) ON DELETE RESTRICT,
    take_id UUID NOT NULL REFERENCES public.v2_sessions(id) ON DELETE RESTRICT,
    candidate_set_id UUID NOT NULL REFERENCES public.candidate_sets(id)
        ON DELETE RESTRICT,
    document_snapshot_id UUID NOT NULL
        REFERENCES public.ideal_text_document_snapshots(id) ON DELETE RESTRICT,
    document_snapshot_sha256 TEXT NOT NULL CHECK (
        document_snapshot_sha256 ~ '^[0-9a-f]{64}$'
    ),
    content_identity_sha256 TEXT NOT NULL CHECK (
        content_identity_sha256 ~ '^[0-9a-f]{64}$'
    ),
    policy_version TEXT NOT NULL CHECK (
        policy_version = 'take-feedback-policy-v3-serving-v1'
    ),
    block_partition_version TEXT NOT NULL,
    take_index INTEGER NOT NULL CHECK (take_index > 0),
    item_count INTEGER NOT NULL CHECK (item_count >= 0),
    selected_count INTEGER NOT NULL CHECK (selected_count >= 0),
    membership_sha256 TEXT NOT NULL CHECK (membership_sha256 ~ '^[0-9a-f]{64}$'),
    idempotency_key TEXT NOT NULL UNIQUE,
    frozen_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    UNIQUE (take_id, policy_version, document_snapshot_id),
    UNIQUE (id, acquisition_principal_id)
);

CREATE TABLE IF NOT EXISTS public.feedback_v3_membership_items (
    membership_id UUID NOT NULL REFERENCES public.feedback_v3_memberships(id)
        ON DELETE RESTRICT,
    acquisition_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    candidate_id UUID NOT NULL REFERENCES public.feedback_candidates(id)
        ON DELETE RESTRICT,
    evidence_span_id UUID NOT NULL REFERENCES public.evidence_spans(id)
        ON DELETE RESTRICT,
    candidate_key TEXT NOT NULL,
    feedback_family TEXT NOT NULL CHECK (feedback_family IN (
        'confident_voice', 'rewrite_clarity', 'great_formulation'
    )),
    slide_index INTEGER NOT NULL CHECK (slide_index >= 0),
    block_key INTEGER NOT NULL CHECK (block_key >= 0),
    source_ideal_part_id UUID NOT NULL,
    snippet_id UUID NOT NULL REFERENCES public.snippets(id) ON DELETE RESTRICT,
    eligibility TEXT NOT NULL CHECK (eligibility IN ('eligible', 'excluded')),
    exclusion_reason TEXT NULL,
    selected BOOLEAN NOT NULL,
    position_shown INTEGER NULL CHECK (position_shown > 0),
    item_sha256 TEXT NOT NULL CHECK (item_sha256 ~ '^[0-9a-f]{64}$'),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    PRIMARY KEY (membership_id, candidate_id),
    UNIQUE (membership_id, candidate_key),
    FOREIGN KEY (membership_id, acquisition_principal_id)
        REFERENCES public.feedback_v3_memberships(id, acquisition_principal_id)
        ON DELETE RESTRICT,
    CHECK ((eligibility = 'eligible' AND exclusion_reason IS NULL)
        OR (eligibility = 'excluded' AND exclusion_reason IS NOT NULL)),
    CHECK ((selected AND eligibility = 'eligible' AND position_shown IS NOT NULL)
        OR (NOT selected AND position_shown IS NULL))
);

CREATE TABLE IF NOT EXISTS public.feedback_v3_owner_responses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    membership_id UUID NOT NULL REFERENCES public.feedback_v3_memberships(id)
        ON DELETE RESTRICT,
    candidate_id UUID NOT NULL,
    acquisition_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    owner_user_id UUID NOT NULL,
    response TEXT NOT NULL CHECK (response IN (
        'confident_yes', 'confident_in_between', 'confident_no',
        'confident_not_sure', 'confident_audio_unclear'
    )),
    response_taxonomy_version TEXT NOT NULL
        CHECK (response_taxonomy_version = 'confidence-owner-five-state-v1'),
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    UNIQUE (membership_id, candidate_id, owner_user_id),
    FOREIGN KEY (membership_id, candidate_id)
        REFERENCES public.feedback_v3_membership_items(membership_id, candidate_id)
        ON DELETE RESTRICT
);

CREATE UNIQUE INDEX IF NOT EXISTS feedback_v3_selected_position_unique
    ON public.feedback_v3_membership_items(membership_id, position_shown)
    WHERE selected;

CREATE OR REPLACE FUNCTION public.feedback_v3_content_identity_v1(p_payload JSONB)
RETURNS TEXT LANGUAGE sql IMMUTABLE SET search_path = public AS $$
    SELECT public.exercise_json_sha256_v1(
        COALESCE((SELECT jsonb_agg(jsonb_build_object(
            'id', part->>'id', 'text', part->>'text'
        ) ORDER BY ordinal)
        FROM jsonb_array_elements(COALESCE(p_payload->'parts', '[]'::jsonb))
            WITH ORDINALITY AS value(part, ordinal)), '[]'::jsonb)
    )
$$;

CREATE OR REPLACE FUNCTION public.validate_feedback_v3_membership_v1()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE membership public.feedback_v3_memberships;
BEGIN
    SELECT * INTO STRICT membership FROM public.feedback_v3_memberships
     WHERE id = NEW.id;
    IF membership.item_count <> (
        SELECT count(*) FROM public.feedback_v3_membership_items item
         WHERE item.membership_id = membership.id
    ) OR membership.selected_count <> (
        SELECT count(*) FROM public.feedback_v3_membership_items item
         WHERE item.membership_id = membership.id AND item.selected
    ) OR EXISTS (
        SELECT 1 FROM public.feedback_v3_membership_items item
         WHERE item.membership_id = membership.id
           AND item.acquisition_principal_id <> membership.acquisition_principal_id
    ) THEN RAISE EXCEPTION 'FEEDBACK_V3_MEMBERSHIP_INCOMPLETE'; END IF;

    -- One relative-best Confident Voice item for every applicable valid block.
    IF EXISTS (
        SELECT item.slide_index, item.block_key
          FROM public.feedback_v3_membership_items item
         WHERE item.membership_id = membership.id
           AND item.feedback_family = 'confident_voice'
           AND item.eligibility = 'eligible'
         GROUP BY item.slide_index, item.block_key
        HAVING count(*) FILTER (WHERE item.selected) <> 1
    ) THEN RAISE EXCEPTION 'FEEDBACK_V3_CONFIDENCE_BUDGET_INVALID'; END IF;
    IF EXISTS (
        SELECT 1 FROM public.feedback_v3_membership_items item
         WHERE item.membership_id = membership.id AND item.selected
           AND item.feedback_family <> 'confident_voice'
           AND (membership.take_index = 1 OR item.feedback_family NOT IN (
               'rewrite_clarity', 'great_formulation'
           ))
    ) OR (
        SELECT count(*) FROM public.feedback_v3_membership_items item
         WHERE item.membership_id = membership.id AND item.selected
           AND item.feedback_family = 'rewrite_clarity'
    ) > (CASE WHEN membership.take_index = 1 THEN 0 ELSE 1 END)
      OR (
        SELECT count(*) FROM public.feedback_v3_membership_items item
         WHERE item.membership_id = membership.id AND item.selected
           AND item.feedback_family = 'great_formulation'
    ) > (CASE WHEN membership.take_index = 1 THEN 0 ELSE 1 END)
    THEN RAISE EXCEPTION 'FEEDBACK_V3_TAKE_BUDGET_INVALID'; END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.freeze_synthetic_feedback_v3_membership_v1(
    p_acquisition_principal_id UUID,
    p_project_id UUID,
    p_take_id UUID,
    p_candidate_set_id UUID,
    p_document_snapshot_id UUID,
    p_block_partition_version TEXT,
    p_items JSONB,
    p_membership_sha256 TEXT,
    p_idempotency_key TEXT
) RETURNS public.feedback_v3_memberships
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    take_row public.v2_sessions;
    candidate_set public.candidate_sets;
    snapshot public.ideal_text_document_snapshots;
    result public.feedback_v3_memberships;
    item JSONB;
    candidate public.feedback_candidates;
    evidence public.evidence_spans;
    snippet public.snippets;
    part JSONB;
    piece JSONB;
    content_hash TEXT;
    item_count INTEGER;
    selected_count INTEGER;
    derived_membership_hash TEXT;
BEGIN
    IF jsonb_typeof(p_items) <> 'array'
       OR COALESCE(btrim(p_block_partition_version), '') = ''
       OR p_membership_sha256 !~ '^[0-9a-f]{64}$'
       OR COALESCE(btrim(p_idempotency_key), '') = ''
    THEN RAISE EXCEPTION 'FEEDBACK_V3_MEMBERSHIP_INVALID'; END IF;
    SELECT * INTO STRICT take_row FROM public.v2_sessions
     WHERE id = p_take_id AND project_id = p_project_id
       AND owner_principal_id = p_acquisition_principal_id
       AND COALESCE(recording_kind, 'spoken') = 'spoken'
       AND paired_session_id IS NULL;
    SELECT * INTO STRICT candidate_set FROM public.candidate_sets
     WHERE id = p_candidate_set_id AND take_id = p_take_id
       AND project_id = p_project_id
       AND owner_principal_id = p_acquisition_principal_id
       AND manager_rules_version LIKE 'take-feedback-policy-v3%';
    SELECT * INTO STRICT snapshot FROM public.ideal_text_document_snapshots
     WHERE id = p_document_snapshot_id AND project_id = p_project_id
       AND acquisition_principal_id = p_acquisition_principal_id
       AND source_take_session_id = p_take_id;
    IF NOT EXISTS (
        SELECT 1 FROM public.ideal_text_document_heads head
        JOIN public.ideal_text_document_generations generation
          ON generation.arc_id = head.arc_id
       WHERE head.snapshot_id = snapshot.id
         AND generation.generation = snapshot.source_generation
    ) THEN RAISE EXCEPTION 'FEEDBACK_V3_DOCUMENT_STALE'; END IF;
    content_hash := public.feedback_v3_content_identity_v1(snapshot.payload);
    item_count := jsonb_array_length(p_items);
    IF item_count <> (SELECT count(*) FROM public.feedback_candidates row
                       WHERE row.candidate_set_id = candidate_set.id)
       OR item_count <> (SELECT count(DISTINCT value->>'candidate_id')
                           FROM jsonb_array_elements(p_items) value)
    THEN RAISE EXCEPTION 'FEEDBACK_V3_INVENTORY_INCOMPLETE'; END IF;
    SELECT count(*) INTO selected_count FROM jsonb_array_elements(p_items) value
     WHERE COALESCE((value->>'selected')::boolean, false);
    derived_membership_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'acquisition_principal_id', p_acquisition_principal_id,
        'project_id', p_project_id, 'take_id', p_take_id,
        'candidate_set_id', p_candidate_set_id,
        'document_snapshot_id', p_document_snapshot_id,
        'document_snapshot_sha256', snapshot.payload_sha256,
        'content_identity_sha256', content_hash,
        'policy_version', 'take-feedback-policy-v3-serving-v1',
        'block_partition_version', p_block_partition_version,
        'items', p_items));
    IF lower(p_membership_sha256) <> derived_membership_hash THEN
        RAISE EXCEPTION 'FEEDBACK_V3_MEMBERSHIP_HASH_MISMATCH'; END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'feedback-v3-membership:' || p_idempotency_key, 0
    ));
    -- A lock wait cannot turn a stale document or recording into a frozen set.
    IF NOT EXISTS (SELECT 1 FROM public.ideal_text_document_heads head
                    WHERE head.snapshot_id = snapshot.id)
       OR NOT EXISTS (
          SELECT 1 FROM public.processing_recording_attempts attempt
           JOIN public.processing_audio_objects object_row
             ON object_row.recording_attempt_id = attempt.id
          WHERE attempt.id = take_row.id
            AND attempt.acquisition_principal_id = p_acquisition_principal_id
            AND attempt.project_id = p_project_id
            AND attempt.recording_id = take_row.recording_1_id
            AND object_row.deleted_at IS NULL)
    THEN RAISE EXCEPTION 'FEEDBACK_V3_SOURCE_STALE'; END IF;
    SELECT * INTO result FROM public.feedback_v3_memberships
     WHERE idempotency_key = p_idempotency_key;
    IF result.id IS NOT NULL THEN
        IF result.candidate_set_id <> p_candidate_set_id
           OR result.document_snapshot_id <> p_document_snapshot_id
           OR result.membership_sha256 <> lower(p_membership_sha256)
        THEN RAISE EXCEPTION 'FEEDBACK_V3_MEMBERSHIP_REPLAY_CONFLICT'; END IF;
        RETURN result;
    END IF;
    INSERT INTO public.feedback_v3_memberships (
        acquisition_principal_id, project_id, take_id, candidate_set_id,
        document_snapshot_id, document_snapshot_sha256,
        content_identity_sha256, policy_version, block_partition_version,
        take_index, item_count, selected_count, membership_sha256,
        idempotency_key
    ) VALUES (
        p_acquisition_principal_id, p_project_id, p_take_id,
        p_candidate_set_id, snapshot.id, snapshot.payload_sha256, content_hash,
        'take-feedback-policy-v3-serving-v1', p_block_partition_version,
        take_row.take_index, item_count, selected_count,
        derived_membership_hash, p_idempotency_key
    ) RETURNING * INTO result;
    FOR item IN SELECT value FROM jsonb_array_elements(p_items) LOOP
        SELECT * INTO STRICT candidate FROM public.feedback_candidates
         WHERE id = (item->>'candidate_id')::uuid
           AND candidate_set_id = candidate_set.id
           AND candidate_key = item->>'candidate_key'
           AND feedback_family = item->>'feedback_family';
        SELECT * INTO STRICT evidence FROM public.evidence_spans
         WHERE id = candidate.evidence_span_id AND take_id = p_take_id
           AND project_id = p_project_id
           AND owner_principal_id = p_acquisition_principal_id;
        SELECT * INTO STRICT snippet FROM public.snippets
         WHERE id = evidence.legacy_piece_id AND session_id = p_take_id
           AND recording_id = evidence.recording_id
           AND recording_id = take_row.recording_1_id
           AND start_offset_ms = evidence.start_ms
           AND duration_ms = evidence.end_ms - evidence.start_ms;
        SELECT value INTO part
          FROM jsonb_array_elements(snapshot.payload->'parts') value
         WHERE value->>'id' = item->>'source_ideal_part_id' LIMIT 1;
        SELECT value INTO piece
          FROM jsonb_array_elements(snapshot.payload->'pieces') value
         WHERE value->>'part_id' = item->>'source_ideal_part_id' LIMIT 1;
        IF part IS NULL OR piece IS NULL
           OR (piece->>'slide_index')::integer <> (item->>'slide_index')::integer
           OR item->>'eligibility' NOT IN ('eligible', 'excluded')
           OR (COALESCE((item->>'selected')::boolean, false)
              AND item->>'eligibility' <> 'eligible')
        THEN RAISE EXCEPTION 'FEEDBACK_V3_ITEM_LINEAGE_INVALID'; END IF;
        INSERT INTO public.feedback_v3_membership_items (
            membership_id, acquisition_principal_id, candidate_id,
            evidence_span_id, candidate_key, feedback_family, slide_index,
            block_key, source_ideal_part_id, snippet_id, eligibility,
            exclusion_reason, selected, position_shown, item_sha256
        ) VALUES (
            result.id, p_acquisition_principal_id, candidate.id, evidence.id,
            candidate.candidate_key, candidate.feedback_family,
            (item->>'slide_index')::integer, (item->>'block_key')::integer,
            (item->>'source_ideal_part_id')::uuid, snippet.id,
            item->>'eligibility', NULLIF(item->>'exclusion_reason', ''),
            COALESCE((item->>'selected')::boolean, false),
            NULLIF(item->>'position_shown', '')::integer,
            public.exercise_json_sha256_v1(item)
        );
    END LOOP;
    SET CONSTRAINTS feedback_v3_membership_complete IMMEDIATE;
    RETURN result;
END;
$$;

DROP TRIGGER IF EXISTS feedback_v3_membership_complete
    ON public.feedback_v3_memberships;
CREATE CONSTRAINT TRIGGER feedback_v3_membership_complete
AFTER INSERT ON public.feedback_v3_memberships
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
EXECUTE FUNCTION public.validate_feedback_v3_membership_v1();

CREATE OR REPLACE FUNCTION public.require_synthetic_feedback_v3_membership_live_v1(
    p_membership_id UUID
) RETURNS public.feedback_v3_memberships
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    membership public.feedback_v3_memberships;
    snapshot public.ideal_text_document_snapshots;
    take_row public.v2_sessions;
    invalid_item_count INTEGER;
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'FEEDBACK_V3_REQUIRES_READ_COMMITTED';
    END IF;
    SELECT * INTO STRICT membership FROM public.feedback_v3_memberships
     WHERE id = p_membership_id;
    SELECT * INTO STRICT snapshot FROM public.ideal_text_document_snapshots
     WHERE id = membership.document_snapshot_id
       AND project_id = membership.project_id
       AND acquisition_principal_id = membership.acquisition_principal_id
       AND source_take_session_id = membership.take_id;
    SELECT * INTO STRICT take_row FROM public.v2_sessions
     WHERE id = membership.take_id
       AND project_id = membership.project_id
       AND owner_principal_id = membership.acquisition_principal_id;
    IF NOT EXISTS (
        SELECT 1
          FROM public.ideal_text_document_heads head
          JOIN public.ideal_text_document_generations generation
            ON generation.arc_id = head.arc_id
         WHERE head.snapshot_id = snapshot.id
           AND generation.generation = snapshot.source_generation
    ) OR membership.document_snapshot_sha256 <> snapshot.payload_sha256
       OR membership.content_identity_sha256 <>
          public.feedback_v3_content_identity_v1(snapshot.payload)
       OR EXISTS (
          SELECT 1 FROM public.data_purge_requests purge
           WHERE purge.acquisition_principal_id =
                 membership.acquisition_principal_id
             AND purge.state <> 'done'
       )
    THEN RAISE EXCEPTION 'FEEDBACK_V3_SOURCE_STALE'; END IF;
    SELECT count(*) INTO invalid_item_count
      FROM public.feedback_v3_membership_items item
      LEFT JOIN public.evidence_spans evidence
        ON evidence.id = item.evidence_span_id
       AND evidence.owner_principal_id = membership.acquisition_principal_id
       AND evidence.project_id = membership.project_id
       AND evidence.take_id = membership.take_id
       AND evidence.recording_id = take_row.recording_1_id
      LEFT JOIN public.snippets snippet
        ON snippet.id = item.snippet_id
       AND snippet.id = evidence.legacy_piece_id
       AND snippet.session_id = membership.take_id
       AND snippet.recording_id = take_row.recording_1_id
       AND snippet.start_offset_ms = evidence.start_ms
       AND snippet.duration_ms = evidence.end_ms - evidence.start_ms
     WHERE item.membership_id = membership.id
       AND (evidence.id IS NULL OR snippet.id IS NULL);
    IF invalid_item_count <> 0 OR NOT EXISTS (
        SELECT 1
          FROM public.processing_recording_attempts attempt
          JOIN public.processing_audio_objects object_row
            ON object_row.recording_attempt_id = attempt.id
           AND object_row.acquisition_principal_id =
               membership.acquisition_principal_id
           AND object_row.deleted_at IS NULL
         WHERE attempt.id = membership.take_id
           AND attempt.acquisition_principal_id =
               membership.acquisition_principal_id
           AND attempt.project_id = membership.project_id
           AND attempt.recording_id = take_row.recording_1_id
    ) THEN RAISE EXCEPTION 'FEEDBACK_V3_SOURCE_STALE'; END IF;
    RETURN membership;
END;
$$;

CREATE OR REPLACE FUNCTION public.record_synthetic_feedback_v3_confidence_response_v1(
    p_membership_id UUID,
    p_candidate_id UUID,
    p_owner_user_id UUID,
    p_response TEXT,
    p_idempotency_key TEXT
) RETURNS public.feedback_v3_owner_responses
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE membership public.feedback_v3_memberships;
    item public.feedback_v3_membership_items;
    result public.feedback_v3_owner_responses;
BEGIN
    IF COALESCE(btrim(p_idempotency_key), '') = '' THEN
        RAISE EXCEPTION 'FEEDBACK_V3_RESPONSE_KEY_REQUIRED'; END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'feedback-v3-response:' || p_idempotency_key, 0));
    SELECT * INTO membership
      FROM public.require_synthetic_feedback_v3_membership_live_v1(
          p_membership_id
      );
    SELECT * INTO STRICT item FROM public.feedback_v3_membership_items
     WHERE membership_id = membership.id AND candidate_id = p_candidate_id
       AND feedback_family = 'confident_voice' AND selected;
    IF p_response NOT IN (
        'confident_yes', 'confident_in_between', 'confident_no',
        'confident_not_sure', 'confident_audio_unclear'
    ) OR NOT EXISTS (
        SELECT 1 FROM public.owner_principals owner
         WHERE owner.id = membership.acquisition_principal_id
           AND owner.user_id = p_owner_user_id
    ) THEN RAISE EXCEPTION 'FEEDBACK_V3_RESPONSE_INVALID'; END IF;
    INSERT INTO public.feedback_v3_owner_responses (
        membership_id, candidate_id, acquisition_principal_id,
        owner_user_id, response, response_taxonomy_version, idempotency_key
    ) VALUES (
        membership.id, item.candidate_id, membership.acquisition_principal_id,
        p_owner_user_id, p_response, 'confidence-owner-five-state-v1',
        p_idempotency_key
    ) ON CONFLICT (idempotency_key) DO NOTHING;
    SELECT * INTO STRICT result FROM public.feedback_v3_owner_responses
     WHERE idempotency_key = p_idempotency_key;
    IF result.membership_id <> membership.id
       OR result.candidate_id <> item.candidate_id
       OR result.owner_user_id <> p_owner_user_id
       OR result.response <> p_response
    THEN RAISE EXCEPTION 'FEEDBACK_V3_RESPONSE_REPLAY_CONFLICT'; END IF;
    PERFORM public.require_synthetic_feedback_v3_membership_live_v1(
        membership.id
    );
    RETURN result;
END;
$$;

ALTER TABLE public.feedback_v3_memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.feedback_v3_membership_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.feedback_v3_owner_responses ENABLE ROW LEVEL SECURITY;
DO $$
DECLARE relation_name TEXT;
BEGIN
    FOREACH relation_name IN ARRAY ARRAY[
        'feedback_v3_memberships', 'feedback_v3_membership_items',
        'feedback_v3_owner_responses'
    ] LOOP
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
REVOKE ALL ON FUNCTION public.feedback_v3_content_identity_v1(JSONB)
    FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION public.validate_feedback_v3_membership_v1()
    FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION public.require_synthetic_feedback_v3_membership_live_v1(UUID)
    FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION public.freeze_synthetic_feedback_v3_membership_v1(
    UUID,UUID,UUID,UUID,UUID,TEXT,JSONB,TEXT,TEXT
) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.freeze_synthetic_feedback_v3_membership_v1(
    UUID,UUID,UUID,UUID,UUID,TEXT,JSONB,TEXT,TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.record_synthetic_feedback_v3_confidence_response_v1(
    UUID,UUID,UUID,TEXT,TEXT
) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.record_synthetic_feedback_v3_confidence_response_v1(
    UUID,UUID,UUID,TEXT,TEXT
) TO service_role;

COMMENT ON TABLE public.feedback_v3_memberships IS
    'Synthetic-only complete Feedback V3 inventory. Root coverage never reduces its one-confidence-item-per-valid-block budget.';

COMMIT;
