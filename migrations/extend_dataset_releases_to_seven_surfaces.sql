-- 0300 · make immutable dataset releases cover all seven isolated surfaces.
--
-- This widens only the closed surface vocabulary. Existing releases and items
-- remain immutable and untouched. Ideal Text is the sole document-level
-- surface, so it may be anchored directly to a canonical Take without a fake
-- transcript evidence span; every other surface still requires exact evidence.

BEGIN;

ALTER TABLE public.dataset_releases
    DROP CONSTRAINT IF EXISTS dataset_releases_learning_surface_check;
ALTER TABLE public.dataset_releases
    ADD CONSTRAINT dataset_releases_learning_surface_check CHECK (
        learning_surface IN (
            'confidence_classification', 'correction_generation',
            'coach_comment_generation', 'praise_generation',
            'praise_selection', 'correction_selection',
            'ideal_text_generation'
        )
    );

ALTER TABLE public.dataset_release_items
    DROP CONSTRAINT IF EXISTS dataset_release_items_learning_surface_check;
ALTER TABLE public.dataset_release_items
    ADD CONSTRAINT dataset_release_items_learning_surface_check CHECK (
        learning_surface IN (
            'confidence_classification', 'correction_generation',
            'coach_comment_generation', 'praise_generation',
            'praise_selection', 'correction_selection',
            'ideal_text_generation'
        )
    );
ALTER TABLE public.dataset_release_items
    ALTER COLUMN evidence_span_id DROP NOT NULL;
ALTER TABLE public.dataset_release_items
    ADD CONSTRAINT dataset_release_items_evidence_boundary_check CHECK (
        learning_surface = 'ideal_text_generation'
        OR evidence_span_id IS NOT NULL
    );

COMMENT ON CONSTRAINT dataset_release_items_evidence_boundary_check
    ON public.dataset_release_items IS
    'Ideal Text is document-level and anchors to a Take; all other learning surfaces require an exact evidence span.';

CREATE OR REPLACE FUNCTION public.create_dataset_release_v1(
    p_manifest JSONB
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_release_id UUID;
    existing public.dataset_releases%ROWTYPE;
    assignment_row JSONB;
    item_row JSONB;
    exclusion_row JSONB;
    stored_assignment public.dataset_split_assignments%ROWTYPE;
    item_count INTEGER;
BEGIN
    IF jsonb_typeof(p_manifest) <> 'object'
       OR jsonb_typeof(p_manifest -> 'split_assignments') <> 'array'
       OR jsonb_typeof(p_manifest -> 'items') <> 'array'
       OR jsonb_typeof(p_manifest -> 'exclusions') <> 'array' THEN
        RAISE EXCEPTION 'dataset release manifest is incomplete';
    END IF;
    SELECT * INTO existing FROM public.dataset_releases
     WHERE release_identifier = p_manifest ->> 'release_identifier';
    IF existing.id IS NOT NULL THEN
        IF existing.manifest_checksum IS DISTINCT FROM
           p_manifest ->> 'manifest_checksum' THEN
            RAISE EXCEPTION 'dataset release identifier conflict';
        END IF;
        RETURN jsonb_build_object('release_id', existing.id,
                                  'replayed', true);
    END IF;

    v_release_id := (p_manifest ->> 'id')::uuid;
    INSERT INTO public.dataset_releases (
        id, release_identifier, learning_surface, source_cutoff_at,
        inclusion_rules, exclusion_rules, taxonomy_versions,
        feature_versions, extraction_code_commit, item_counts,
        manifest_checksum, consent_retention_status,
        split_strategy_version, created_by
    ) VALUES (
        v_release_id, p_manifest ->> 'release_identifier',
        p_manifest ->> 'learning_surface',
        (p_manifest ->> 'source_cutoff_at')::timestamptz,
        p_manifest -> 'inclusion_rules', p_manifest -> 'exclusion_rules',
        p_manifest -> 'taxonomy_versions', p_manifest -> 'feature_versions',
        p_manifest ->> 'extraction_code_commit',
        p_manifest -> 'item_counts', p_manifest ->> 'manifest_checksum',
        p_manifest -> 'consent_retention_status',
        p_manifest ->> 'split_strategy_version',
        (p_manifest ->> 'created_by')::uuid
    );

    FOR assignment_row IN SELECT value FROM jsonb_array_elements(
        p_manifest -> 'split_assignments'
    ) LOOP
        SELECT row.* INTO stored_assignment
          FROM public.dataset_split_assignments row
         WHERE row.owner_principal_id =
               (assignment_row ->> 'owner_principal_id')::uuid;
        IF stored_assignment.id IS NOT NULL THEN
            IF stored_assignment.split IS DISTINCT FROM
               assignment_row ->> 'split'
               OR stored_assignment.strategy_version IS DISTINCT FROM
               assignment_row ->> 'strategy_version' THEN
                RAISE EXCEPTION 'speaker split conflict';
            END IF;
        ELSE
            INSERT INTO public.dataset_split_assignments (
                id, owner_principal_id, split, strategy_version,
                assignment_hash, first_release_id
            ) VALUES (
                (assignment_row ->> 'id')::uuid,
                (assignment_row ->> 'owner_principal_id')::uuid,
                assignment_row ->> 'split',
                assignment_row ->> 'strategy_version',
                assignment_row ->> 'assignment_hash', v_release_id
            );
        END IF;
    END LOOP;

    FOR item_row IN SELECT value FROM jsonb_array_elements(
        p_manifest -> 'items'
    ) LOOP
        IF item_row ->> 'learning_surface' IS DISTINCT FROM
           p_manifest ->> 'learning_surface' THEN
            RAISE EXCEPTION 'dataset release mixes learning surfaces';
        END IF;
        IF item_row ->> 'learning_surface' = 'ideal_text_generation' THEN
            IF NULLIF(item_row -> 'item_payload' ->> 'take_id', '') IS NULL
               OR NOT EXISTS (
                   SELECT 1 FROM public.takes take_row
                    WHERE take_row.id =
                          (item_row -> 'item_payload' ->> 'take_id')::uuid
                      AND take_row.owner_principal_id =
                          (item_row ->> 'owner_principal_id')::uuid
               ) THEN
                RAISE EXCEPTION 'ideal text dataset item Take mismatch';
            END IF;
        ELSIF NOT EXISTS (
            SELECT 1 FROM public.evidence_spans evidence
             WHERE evidence.id = (item_row ->> 'evidence_span_id')::uuid
               AND evidence.owner_principal_id =
                   (item_row ->> 'owner_principal_id')::uuid
        ) THEN
            RAISE EXCEPTION 'dataset item evidence ownership mismatch';
        END IF;
        SELECT row.* INTO stored_assignment
          FROM public.dataset_split_assignments row
         WHERE row.owner_principal_id =
               (item_row ->> 'owner_principal_id')::uuid;
        IF stored_assignment.id IS NULL
           OR stored_assignment.split IS DISTINCT FROM item_row ->> 'split' THEN
            RAISE EXCEPTION 'dataset item split is not speaker-stable';
        END IF;
        INSERT INTO public.dataset_release_items (
            id, release_id, owner_principal_id, split_assignment_id,
            evidence_span_id, learning_surface, item_payload,
            label_provenance, eligibility_decision, item_checksum
        ) VALUES (
            (item_row ->> 'id')::uuid, v_release_id,
            (item_row ->> 'owner_principal_id')::uuid,
            stored_assignment.id,
            NULLIF(item_row ->> 'evidence_span_id', '')::uuid,
            item_row ->> 'learning_surface', item_row -> 'item_payload',
            item_row -> 'label_provenance',
            item_row ->> 'eligibility_decision',
            item_row ->> 'item_checksum'
        );
    END LOOP;

    FOR exclusion_row IN SELECT value FROM jsonb_array_elements(
        p_manifest -> 'exclusions'
    ) LOOP
        IF NULLIF(exclusion_row ->> 'evidence_span_id', '') IS NOT NULL
           AND NOT EXISTS (
               SELECT 1 FROM public.evidence_spans evidence
                WHERE evidence.id =
                      (exclusion_row ->> 'evidence_span_id')::uuid
                  AND evidence.owner_principal_id =
                      (exclusion_row ->> 'owner_principal_id')::uuid
           ) THEN
            RAISE EXCEPTION 'dataset exclusion evidence ownership mismatch';
        END IF;
        INSERT INTO public.dataset_exclusions (
            id, release_id, owner_principal_id, evidence_span_id,
            reason_code, reason_detail, consent_retention_status
        ) VALUES (
            (exclusion_row ->> 'id')::uuid, v_release_id,
            (exclusion_row ->> 'owner_principal_id')::uuid,
            NULLIF(exclusion_row ->> 'evidence_span_id', '')::uuid,
            exclusion_row ->> 'reason_code',
            COALESCE(exclusion_row -> 'reason_detail', '{}'::jsonb),
            exclusion_row -> 'consent_retention_status'
        );
    END LOOP;

    SELECT count(*)::integer INTO item_count
      FROM public.dataset_release_items item
     WHERE item.release_id = v_release_id;
    IF item_count <> jsonb_array_length(p_manifest -> 'items')
       OR item_count <> (p_manifest -> 'item_counts' ->> 'total')::integer THEN
        RAISE EXCEPTION 'dataset release item count mismatch';
    END IF;
    RETURN jsonb_build_object('release_id', v_release_id,
                              'item_count', item_count,
                              'replayed', false);
END;
$$;

REVOKE ALL ON FUNCTION public.create_dataset_release_v1(JSONB)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.create_dataset_release_v1(JSONB)
    TO service_role;

COMMIT;
