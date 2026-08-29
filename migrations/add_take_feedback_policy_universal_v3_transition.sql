-- 0311 · Versioned transition to the universal, sex-blind confidence detector.
--
-- 0309 and record_take_feedback_policy_v3_shadow_v2 remain immutable legacy
-- contracts. This migration adds a new frame/RPC contract. Old detector
-- artifacts are recorded as incompatible until the exact clip is recomputed;
-- they are never silently ranked as unmeasured evidence.

BEGIN;

CREATE TABLE IF NOT EXISTS public.take_feedback_detector_reconciliation (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    take_session_id UUID NOT NULL REFERENCES public.v2_sessions(id)
        ON DELETE CASCADE,
    old_policy_version TEXT NOT NULL,
    old_detector_version TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN (
        'incompatible_detector_version', 'recomputed'
    )),
    replacement_policy_version TEXT,
    replacement_detector_version TEXT,
    evidence_sha256 TEXT NOT NULL CHECK (evidence_sha256 ~ '^[0-9a-f]{64}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT detector_reconciliation_replacement_check CHECK (
        (outcome = 'incompatible_detector_version'
            AND replacement_policy_version IS NULL
            AND replacement_detector_version IS NULL)
        OR (outcome = 'recomputed'
            AND replacement_policy_version =
                'take-feedback-policy-v3-universal-dark-v3'
            AND replacement_detector_version =
                'voice-confidence-universal-v3')
    ),
    UNIQUE (
        take_session_id, old_policy_version, outcome,
        replacement_policy_version, replacement_detector_version
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS take_feedback_detector_reconciliation_identity_idx
    ON public.take_feedback_detector_reconciliation (
        take_session_id, old_policy_version, outcome,
        COALESCE(replacement_policy_version, ''),
        COALESCE(replacement_detector_version, '')
    );

-- Existing v2 frames keep their bytes and meaning. This append-only marker
-- states only that they are not eligible inputs to the new universal ranker.
INSERT INTO public.take_feedback_detector_reconciliation (
    take_session_id, old_policy_version, old_detector_version, outcome,
    evidence_sha256
)
SELECT frame.take_session_id, frame.policy_version, 'voice-confidence-v2',
       'incompatible_detector_version',
       encode(extensions.digest(concat_ws(':',
           frame.take_session_id::text, frame.policy_version,
           'voice-confidence-v2', 'incompatible_detector_version'
       ), 'sha256'), 'hex')
  FROM public.take_feedback_policy_v3_shadow_frames frame
 WHERE frame.policy_version = 'take-feedback-policy-v3-dark-v2'
   AND frame.frame #>> '{implementation_versions,confidence_detector_version}'
       = 'voice-confidence-v2'
ON CONFLICT DO NOTHING;

CREATE OR REPLACE FUNCTION public.record_take_feedback_policy_v3_shadow_v3(
    p_arc_id TEXT,
    p_take_session_id UUID,
    p_recording_id UUID,
    p_acquisition_principal_id UUID,
    p_owner_user_id UUID,
    p_take_index INTEGER,
    p_policy_version TEXT,
    p_frame JSONB,
    p_frame_hash TEXT
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    take_row public.v2_sessions%ROWTYPE;
    existing public.take_feedback_policy_v3_shadow_frames%ROWTYPE;
BEGIN
    IF p_policy_version <> 'take-feedback-policy-v3-universal-dark-v3'
       OR jsonb_typeof(p_frame) <> 'object'
       OR p_frame->>'frame_hash' IS DISTINCT FROM p_frame_hash
       OR p_frame->>'policy_version' IS DISTINCT FROM p_policy_version
       OR p_frame->>'take_id' IS DISTINCT FROM p_take_session_id::text
       OR p_frame->>'recording_id' IS DISTINCT FROM p_recording_id::text
       OR p_frame->>'frame_schema_version'
          IS DISTINCT FROM 'take-feedback-policy-v3-frame-v3'
       OR p_frame->>'serves_user_feedback' IS DISTINCT FROM 'false'
       OR p_frame->>'dataset_eligible' IS DISTINCT FROM 'false'
       OR p_frame #>> '{implementation_versions,confidence_detector_version}'
          IS DISTINCT FROM 'voice-confidence-universal-v3'
       OR p_frame #>> '{implementation_versions,acoustic_feature_schema_version}'
          IS DISTINCT FROM 'acoustic-feature-schema-v1'
       OR p_frame #>> '{implementation_versions,suggestion_generator_contract_version}'
          IS DISTINCT FROM 'feedback-candidate-generator-v1'
       OR p_frame #>> '{implementation_versions,manager_rules_version}'
          IS DISTINCT FROM 'take-feedback-manager-v2'
       OR p_frame #>> '{implementation_versions,manager_evidence_schema_version}'
          IS DISTINCT FROM 'take-feedback-manager-evidence-v1'
       OR jsonb_typeof(p_frame #>
            '{implementation_versions,observed_suggestion_generator_versions}')
          IS DISTINCT FROM 'array'
       OR COALESCE(
            p_frame #>> '{implementation_versions,source_code_sha256}', '')
          !~ '^[0-9a-f]{64}$'
       OR p_frame_hash !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'invalid universal-v3 dark frame';
    END IF;

    SELECT * INTO take_row FROM public.v2_sessions
     WHERE id = p_take_session_id FOR SHARE;
    IF take_row.id IS NULL
       OR take_row.arc_id::text IS DISTINCT FROM p_arc_id
       OR take_row.owner_principal_id IS DISTINCT FROM p_acquisition_principal_id
       OR take_row.user_id IS DISTINCT FROM p_owner_user_id
       OR take_row.recording_1_id IS DISTINCT FROM p_recording_id
       OR take_row.take_index IS DISTINCT FROM p_take_index
       OR COALESCE(take_row.recording_kind, 'spoken') <> 'spoken'
       OR take_row.paired_session_id IS NOT NULL THEN
        RAISE EXCEPTION 'universal-v3 shadow Take provenance mismatch';
    END IF;

    -- Every considered confidence candidate remains in the frame. Any
    -- non-current detector artifact must be an explicit typed exclusion.
    IF EXISTS (
        SELECT 1
          FROM jsonb_array_elements(COALESCE(
                   p_frame -> 'blocks', '[]'::jsonb)) block
          CROSS JOIN jsonb_array_elements(COALESCE(
                   block -> 'confidence_candidates', '[]'::jsonb)) candidate
         WHERE candidate ->> 'eligibility' NOT IN ('eligible', 'excluded')
            OR (candidate ->> 'eligibility' = 'excluded'
                AND length(COALESCE(candidate ->> 'exclusion_reason', '')) = 0)
            OR (candidate ->> 'eligibility' = 'eligible'
                AND NULLIF(candidate ->> 'machine_version', '') IS NOT NULL
                AND candidate ->> 'machine_version'
                    <> 'voice-confidence-universal-v3')
            OR (candidate ->> 'machine_version' = 'voice-confidence-v2'
                AND (
                    candidate ->> 'eligibility' <> 'excluded'
                    OR candidate ->> 'exclusion_reason'
                        <> 'incompatible_detector_version'
                ))
    ) THEN
        RAISE EXCEPTION 'invalid universal-v3 detector transition inventory';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM (
              SELECT candidate
                FROM jsonb_array_elements(COALESCE(
                    p_frame #> '{verbal_lanes,rewrite_clarity,candidates}',
                    '[]'::jsonb)) candidate
              UNION ALL
              SELECT candidate
                FROM jsonb_array_elements(COALESCE(
                    p_frame #> '{verbal_lanes,great_formulation,candidates}',
                    '[]'::jsonb)) candidate
          ) inventory
         WHERE candidate ->> 'eligibility' NOT IN ('eligible', 'excluded')
            OR (candidate ->> 'eligibility' = 'excluded'
                AND length(COALESCE(candidate ->> 'exclusion_reason', '')) = 0)
            OR (candidate ->> 'eligibility' = 'eligible'
                AND jsonb_typeof(candidate -> 'producer_versions')
                    IS DISTINCT FROM 'object')
    ) THEN
        RAISE EXCEPTION 'invalid universal-v3 verbal candidate inventory';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM jsonb_array_elements(COALESCE(
                   p_frame -> 'blocks', '[]'::jsonb)) block
          CROSS JOIN jsonb_array_elements(COALESCE(
                   block -> 'confidence_candidates', '[]'::jsonb)) candidate
          LEFT JOIN public.snippets snippet
            ON snippet.id::text = candidate ->> 'snippet_id'
         WHERE candidate ->> 'eligibility' = 'eligible'
           AND (
               snippet.id IS NULL
               OR snippet.session_id IS DISTINCT FROM p_take_session_id
               OR snippet.recording_id IS DISTINCT FROM p_recording_id
               OR candidate #>> '{clip_identity,take_id}'
                    IS DISTINCT FROM p_take_session_id::text
               OR candidate #>> '{clip_identity,recording_id}'
                    IS DISTINCT FROM p_recording_id::text
               OR candidate #>> '{clip_identity,snippet_id}'
                    IS DISTINCT FROM snippet.id::text
               OR candidate #>> '{clip_identity,start_offset_ms}'
                    IS DISTINCT FROM snippet.start_offset_ms::text
               OR candidate #>> '{clip_identity,duration_ms}'
                    IS DISTINCT FROM snippet.duration_ms::text
               OR snippet.start_offset_ms < 0
               OR snippet.duration_ms <= 0
               OR COALESCE(
                    candidate #>> '{clip_identity,clip_identity_sha256}', '')
                    !~ '^[0-9a-f]{64}$'
           )
    ) THEN
        RAISE EXCEPTION 'universal-v3 confidence clip lineage mismatch';
    END IF;

    -- Every block with eligible evidence has exactly one selected candidate;
    -- the selected ID must name an eligible candidate in that same block.
    IF EXISTS (
        SELECT 1
          FROM jsonb_array_elements(COALESCE(
                   p_frame -> 'blocks', '[]'::jsonb)) block
         WHERE (
               EXISTS (
                   SELECT 1 FROM jsonb_array_elements(COALESCE(
                       block -> 'confidence_candidates', '[]'::jsonb)) candidate
                    WHERE candidate ->> 'eligibility' = 'eligible'
               )
               AND NULLIF(block ->> 'selected_candidate_id', '') IS NULL
           )
            OR (
               NULLIF(block ->> 'selected_candidate_id', '') IS NOT NULL
               AND NOT EXISTS (
               SELECT 1 FROM jsonb_array_elements(COALESCE(
                   block -> 'confidence_candidates', '[]'::jsonb)) candidate
                WHERE candidate ->> 'candidate_id'
                        = block ->> 'selected_candidate_id'
                  AND candidate ->> 'eligibility' = 'eligible'
               )
           )
    ) THEN
        RAISE EXCEPTION 'universal-v3 selected an ineligible candidate';
    END IF;

    INSERT INTO public.take_feedback_policy_v3_shadow_frames (
        take_session_id, recording_id, policy_version, arc_id,
        acquisition_principal_id, owner_user_id, take_index, frame, frame_hash
    ) VALUES (
        p_take_session_id, p_recording_id, p_policy_version, p_arc_id,
        p_acquisition_principal_id, p_owner_user_id, p_take_index,
        p_frame, p_frame_hash
    ) ON CONFLICT DO NOTHING;

    SELECT * INTO existing FROM public.take_feedback_policy_v3_shadow_frames
     WHERE take_session_id = p_take_session_id
       AND policy_version = p_policy_version;
    IF existing.frame_hash IS DISTINCT FROM p_frame_hash THEN
        RETURN jsonb_build_object('outcome', 'conflict');
    END IF;

    IF EXISTS (
        SELECT 1 FROM public.take_feedback_policy_v3_shadow_frames prior
         WHERE prior.take_session_id = p_take_session_id
           AND prior.policy_version = 'take-feedback-policy-v3-dark-v2'
           AND prior.frame #>>
               '{implementation_versions,confidence_detector_version}'
               = 'voice-confidence-v2'
    ) THEN
        INSERT INTO public.take_feedback_detector_reconciliation (
            take_session_id, old_policy_version, old_detector_version,
            outcome, evidence_sha256
        ) VALUES (
            p_take_session_id, 'take-feedback-policy-v3-dark-v2',
            'voice-confidence-v2', 'incompatible_detector_version',
            encode(extensions.digest(concat_ws(':',
                p_take_session_id::text, 'take-feedback-policy-v3-dark-v2',
                'voice-confidence-v2', 'incompatible_detector_version'
            ), 'sha256'), 'hex')
        ) ON CONFLICT DO NOTHING;
        INSERT INTO public.take_feedback_detector_reconciliation (
            take_session_id, old_policy_version, old_detector_version,
            outcome, replacement_policy_version,
            replacement_detector_version, evidence_sha256
        ) VALUES (
            p_take_session_id, 'take-feedback-policy-v3-dark-v2',
            'voice-confidence-v2', 'recomputed', p_policy_version,
            'voice-confidence-universal-v3',
            encode(extensions.digest(concat_ws(':',
                p_take_session_id::text, 'take-feedback-policy-v3-dark-v2',
                p_policy_version, p_frame_hash, 'recomputed'
            ), 'sha256'), 'hex')
        ) ON CONFLICT DO NOTHING;
    END IF;
    RETURN jsonb_build_object(
        'outcome', 'stored', 'take_session_id', existing.take_session_id,
        'policy_version', existing.policy_version,
        'frame_hash', existing.frame_hash
    );
END;
$$;

ALTER TABLE public.take_feedback_detector_reconciliation ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.take_feedback_detector_reconciliation
    FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT ON TABLE public.take_feedback_detector_reconciliation
    TO service_role;

DROP TRIGGER IF EXISTS take_feedback_detector_reconciliation_immutable
    ON public.take_feedback_detector_reconciliation;
CREATE TRIGGER take_feedback_detector_reconciliation_immutable
    BEFORE UPDATE OR DELETE ON public.take_feedback_detector_reconciliation
    FOR EACH ROW EXECUTE FUNCTION public.reject_immutable_feedback_mutation();

REVOKE ALL ON FUNCTION public.record_take_feedback_policy_v3_shadow_v3(
    TEXT, UUID, UUID, UUID, UUID, INTEGER, TEXT, JSONB, TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.record_take_feedback_policy_v3_shadow_v3(
    TEXT, UUID, UUID, UUID, UUID, INTEGER, TEXT, JSONB, TEXT
) TO service_role;

COMMIT;
