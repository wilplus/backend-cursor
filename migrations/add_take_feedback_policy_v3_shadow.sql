-- 0309 · Founder-only dark frames for take-feedback-policy-v3.
-- These are non-rendered product-policy evaluations, never training rows.

BEGIN;

CREATE TABLE IF NOT EXISTS public.take_feedback_policy_v3_shadow_frames (
    take_session_id UUID NOT NULL
        REFERENCES public.v2_sessions(id) ON DELETE CASCADE,
    recording_id UUID NOT NULL
        REFERENCES public.recordings(id) ON DELETE RESTRICT,
    policy_version TEXT NOT NULL,
    arc_id TEXT NOT NULL,
    acquisition_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id),
    owner_user_id UUID NOT NULL,
    take_index INTEGER NOT NULL CHECK (take_index >= 1),
    frame JSONB NOT NULL CHECK (jsonb_typeof(frame) = 'object'),
    frame_hash TEXT NOT NULL CHECK (frame_hash ~ '^[0-9a-f]{64}$'),
    rendered_exposure_id UUID NULL CHECK (rendered_exposure_id IS NULL),
    dataset_eligible BOOLEAN NOT NULL DEFAULT FALSE
        CHECK (dataset_eligible = FALSE),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (take_session_id, policy_version)
);

ALTER TABLE public.take_feedback_policy_v3_shadow_frames
    ENABLE ROW LEVEL SECURITY;

DROP TRIGGER IF EXISTS take_feedback_policy_v3_shadow_immutable
    ON public.take_feedback_policy_v3_shadow_frames;
CREATE TRIGGER take_feedback_policy_v3_shadow_immutable
    BEFORE UPDATE OR DELETE ON public.take_feedback_policy_v3_shadow_frames
    FOR EACH ROW EXECUTE FUNCTION public.reject_immutable_feedback_mutation();

CREATE OR REPLACE FUNCTION public.record_take_feedback_policy_v3_shadow_v2(
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
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    take_row public.v2_sessions%ROWTYPE;
    existing public.take_feedback_policy_v3_shadow_frames%ROWTYPE;
BEGIN
    IF p_policy_version <> 'take-feedback-policy-v3-dark-v2'
       OR jsonb_typeof(p_frame) <> 'object'
       OR p_frame->>'frame_hash' IS DISTINCT FROM p_frame_hash
       OR p_frame->>'take_id' IS DISTINCT FROM p_take_session_id::text
       OR p_frame->>'recording_id' IS DISTINCT FROM p_recording_id::text
       OR p_frame->>'frame_schema_version'
          IS DISTINCT FROM 'take-feedback-policy-v3-frame-v2'
       OR p_frame->>'serves_user_feedback' IS DISTINCT FROM 'false'
       OR p_frame->>'dataset_eligible' IS DISTINCT FROM 'false'
       OR p_frame #>> '{implementation_versions,confidence_detector_version}'
          IS DISTINCT FROM 'voice-confidence-v2'
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
        RAISE EXCEPTION 'invalid v3 dark frame';
    END IF;
    SELECT * INTO take_row
      FROM public.v2_sessions
     WHERE id = p_take_session_id
     FOR SHARE;
    IF take_row.id IS NULL
       OR take_row.arc_id::text IS DISTINCT FROM p_arc_id
       OR take_row.owner_principal_id IS DISTINCT FROM p_acquisition_principal_id
       OR take_row.user_id IS DISTINCT FROM p_owner_user_id
       OR take_row.recording_1_id IS DISTINCT FROM p_recording_id
       OR take_row.take_index IS DISTINCT FROM p_take_index
       OR COALESCE(take_row.recording_kind, 'spoken') <> 'spoken'
       OR take_row.paired_session_id IS NOT NULL THEN
        RAISE EXCEPTION 'v3 shadow Take provenance mismatch';
    END IF;

    -- Every confidence candidate remains in the frozen frame. Eligible ones
    -- must resolve to the exact immutable Take/recording/interval coordinates;
    -- excluded ones must carry a typed reason. An audio URL is never proof.
    IF EXISTS (
        SELECT 1
          FROM jsonb_array_elements(COALESCE(
                   p_frame -> 'blocks', '[]'::jsonb)) block,
               jsonb_array_elements(COALESCE(
                   block -> 'confidence_candidates', '[]'::jsonb)) candidate
         WHERE candidate ->> 'eligibility' NOT IN ('eligible', 'excluded')
            OR (candidate ->> 'eligibility' = 'excluded'
                AND length(COALESCE(
                    candidate ->> 'exclusion_reason', '')) = 0)
    ) THEN
        RAISE EXCEPTION 'invalid v3 confidence candidate inventory';
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
                AND length(COALESCE(
                    candidate ->> 'exclusion_reason', '')) = 0)
            OR (candidate ->> 'eligibility' = 'eligible'
                AND jsonb_typeof(candidate -> 'producer_versions')
                    IS DISTINCT FROM 'object')
    ) THEN
        RAISE EXCEPTION 'invalid v3 verbal candidate inventory';
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
        RAISE EXCEPTION 'v3 confidence clip lineage mismatch';
    END IF;

    INSERT INTO public.take_feedback_policy_v3_shadow_frames (
        take_session_id, recording_id, policy_version, arc_id,
        acquisition_principal_id,
        owner_user_id, take_index, frame, frame_hash
    ) VALUES (
        p_take_session_id, p_recording_id, p_policy_version, p_arc_id,
        p_acquisition_principal_id, p_owner_user_id, p_take_index,
        p_frame, p_frame_hash
    ) ON CONFLICT DO NOTHING;

    SELECT * INTO existing
      FROM public.take_feedback_policy_v3_shadow_frames
     WHERE take_session_id = p_take_session_id
       AND policy_version = p_policy_version;
    IF existing.frame_hash IS DISTINCT FROM p_frame_hash THEN
        RETURN jsonb_build_object('outcome', 'conflict');
    END IF;
    RETURN jsonb_build_object(
        'outcome', 'stored',
        'take_session_id', existing.take_session_id,
        'policy_version', existing.policy_version,
        'frame_hash', existing.frame_hash
    );
END;
$$;

REVOKE ALL ON TABLE public.take_feedback_policy_v3_shadow_frames
    FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT ON TABLE public.take_feedback_policy_v3_shadow_frames
    TO service_role;
REVOKE ALL ON FUNCTION public.record_take_feedback_policy_v3_shadow_v2(
    TEXT, UUID, UUID, UUID, UUID, INTEGER, TEXT, JSONB, TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.record_take_feedback_policy_v3_shadow_v2(
    TEXT, UUID, UUID, UUID, UUID, INTEGER, TEXT, JSONB, TEXT
) TO service_role;

COMMIT;
