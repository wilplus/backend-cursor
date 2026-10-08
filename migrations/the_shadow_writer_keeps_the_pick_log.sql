-- 0441 · The shadow writer keeps the pick log (V4 Phase 1, B1.1; build
-- plan D-ML-6; ledger B1.1).
--
-- WHY. V4 is measured against V3 before it serves anyone (V4 brief 1.1).
-- That needs, for every Take, every candidate V3 weighed, its chance of
-- being picked, the Take's random seed and the policy version. The dark
-- shadow frame already keeps every candidate; this adds the pick log to it.
-- The code now builds frame schema 'take-feedback-policy-v3-frame-v6' with a
-- `pick_log` object; the writer, last defined by 0431, accepts only -v5, so
-- every new frame would be refused.
--
-- WHAT CHANGES. public.record_take_feedback_policy_v3_shadow_v3 is
-- re-issued exactly as 0431 wrote it, with these changes, all before the
-- Take is read:
--   1. the frame schema literal becomes 'take-feedback-policy-v3-frame-v6';
--   2. the frame must carry `pick_log` (version 'v4-pick-log-v1', seed
--      version 'v4-pick-seed-v1', the frame's own policy version, a decimal
--      seed of at most 16 digits, and a candidates array);
--   3. the inventory has the shape it is read in, checked before anything
--      is expanded, so a malformed frame is refused with a clean exception
--      instead of raising "cannot extract elements" (GPT-0441 review 2):
--      `blocks` is an array or absent, every block an object whose
--      `confidence_candidates` is an array or absent, each verbal lane's
--      `candidates` and `selected_candidate_ids` arrays or absent, and
--      every confidence and verbal inventory candidate an object with a
--      non-empty candidate_id (the code lists only such rows);
--   4. every pick-log entry names a known lane and a candidate (and, for
--      confidence, its block); an eligible entry's chance is a JSON number
--      equal to 1 or 0 as a number (V3 picks deterministically), an
--      excluded one has none;
--   5. the seed is the Take's own (sha256 of 'v4-pick-seed-v1:' and the
--      Take id, its first 13 hex digits as a number);
--   6. the log is the candidate inventory exactly: every confidence and
--      verbal candidate once, under its lane and block, a selected one at
--      chance 1 and every other eligible one at 0. One pass: both sides'
--      rows are grouped by (lane, block, candidate, eligible, chance) and
--      any group whose two counts differ refuses the frame.
-- A -v5 frame, or a -v6 frame without a complete, valid pick log, is
-- refused. The later 0431 checks expand the same arrays; by then their
-- shape is proven, so none of them can raise on a malformed frame.
--
-- WHAT DOES NOT CHANGE. Who gets a frame is the code's gate
-- (`take_feedback_policy_v3.dark_enabled`): still the founder's Takes only.
-- Widening it to every speaker (V1 A) is a separate, founder-confirmed
-- change. The table, its CHECKs (serves_user_feedback and dataset_eligible
-- false), SECURITY DEFINER with search_path = public, and the grants
-- (service_role only) are as 0431 left them. No route reads the pick log;
-- the serving frame drops it (AC-9).
--
-- Idempotent: CREATE OR REPLACE and re-issued grants. No lock on a busy
-- table. Rollback (a new forward migration): re-issue 0431's function.

BEGIN;

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
          IS DISTINCT FROM 'take-feedback-policy-v3-frame-v6'
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
       OR p_frame_hash !~ '^[0-9a-f]{64}$'
       -- V4 B1.1: the pick log travels with the frame.
       OR jsonb_typeof(p_frame -> 'pick_log') IS DISTINCT FROM 'object'
       OR p_frame #>> '{pick_log,version}' IS DISTINCT FROM 'v4-pick-log-v1'
       OR p_frame #>> '{pick_log,seed_version}'
          IS DISTINCT FROM 'v4-pick-seed-v1'
       OR p_frame #>> '{pick_log,policy_version}'
          IS DISTINCT FROM p_policy_version
       OR COALESCE(p_frame #>> '{pick_log,seed}', '') !~ '^[0-9]{1,16}$'
       OR jsonb_typeof(p_frame #> '{pick_log,candidates}')
          IS DISTINCT FROM 'array' THEN
        RAISE EXCEPTION 'invalid universal-v3 dark frame';
    END IF;

    -- The inventory's shape, before anything is expanded (GPT-0441 review
    -- 2). jsonb_array_elements raises on an object or a scalar and `?`
    -- reads an object's keys, so each array is proven an array first. An
    -- absent key (SQL NULL) is an empty list, as 0431 reads it; a JSON null
    -- is refused (0431's COALESCE would not catch it). These run as
    -- separate statements, in order: PL/pgSQL does, SQL does not promise
    -- an order inside one condition.
    IF COALESCE(jsonb_typeof(p_frame -> 'blocks'), 'array') <> 'array'
       OR EXISTS (
           SELECT 1
             FROM (VALUES ('rewrite_clarity'), ('great_formulation'))
                  AS verbal(lane)
            WHERE COALESCE(jsonb_typeof(p_frame #> ARRAY['verbal_lanes',
                      verbal.lane, 'candidates']), 'array') <> 'array'
               OR COALESCE(jsonb_typeof(p_frame #> ARRAY['verbal_lanes',
                      verbal.lane, 'selected_candidate_ids']), 'array')
                  <> 'array'
       ) THEN
        RAISE EXCEPTION 'invalid universal-v3 pick log';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM jsonb_array_elements(COALESCE(
                   p_frame -> 'blocks', '[]'::jsonb)) block
         WHERE jsonb_typeof(block) IS DISTINCT FROM 'object'
            OR COALESCE(jsonb_typeof(block -> 'confidence_candidates'),
                        'array') <> 'array'
    ) THEN
        RAISE EXCEPTION 'invalid universal-v3 pick log';
    END IF;

    -- Every inventory candidate is an object with its id: one without
    -- could never be logged, so it is refused, not left out.
    IF EXISTS (
        SELECT 1
          FROM (
              SELECT candidate
                FROM jsonb_array_elements(COALESCE(
                         p_frame -> 'blocks', '[]'::jsonb)) block
               CROSS JOIN jsonb_array_elements(COALESCE(
                         block -> 'confidence_candidates', '[]'::jsonb))
                         candidate
              UNION ALL
              SELECT candidate
                FROM (VALUES ('rewrite_clarity'), ('great_formulation'))
                     AS verbal(lane)
               CROSS JOIN jsonb_array_elements(COALESCE(
                         p_frame #> ARRAY['verbal_lanes', verbal.lane,
                                          'candidates'],
                         '[]'::jsonb)) candidate
          ) inventory
         WHERE jsonb_typeof(candidate) IS DISTINCT FROM 'object'
            OR length(COALESCE(candidate ->> 'candidate_id', '')) = 0
    ) THEN
        RAISE EXCEPTION 'invalid universal-v3 pick log';
    END IF;

    -- Every pick-log entry is a known lane with a named candidate. V3
    -- picks deterministically: an eligible candidate's chance is a JSON
    -- number equal to 1 or 0 (1, 1.0 and 1e0 alike: compared as numbers,
    -- not as text), an excluded one has none (null). A confidence entry
    -- names its block; a verbal entry names none. Nothing is cast before
    -- its type is known: the CASE makes the type test run first, which a
    -- plain AND does not promise.
    IF EXISTS (
        SELECT 1
          FROM jsonb_array_elements(p_frame #> '{pick_log,candidates}') entry
         WHERE jsonb_typeof(entry) IS DISTINCT FROM 'object'
            OR COALESCE(entry ->> 'lane', '') NOT IN (
                   'confident_voice', 'rewrite_clarity', 'great_formulation')
            OR length(COALESCE(entry ->> 'candidate_id', '')) = 0
            OR jsonb_typeof(entry -> 'eligible') IS DISTINCT FROM 'boolean'
            OR (entry ->> 'lane' = 'confident_voice'
                AND length(COALESCE(entry ->> 'block_id', '')) = 0)
            OR (entry ->> 'lane' <> 'confident_voice'
                AND jsonb_typeof(entry -> 'block_id') IS DISTINCT FROM 'null')
            OR (entry ->> 'eligible' = 'true'
                AND CASE
                        WHEN jsonb_typeof(entry -> 'pick_probability') = 'number'
                        THEN (entry ->> 'pick_probability')::numeric
                             NOT IN (0, 1)
                        ELSE true
                    END)
            OR (entry ->> 'eligible' = 'false'
                AND jsonb_typeof(entry -> 'pick_probability')
                    IS DISTINCT FROM 'null')
    ) THEN
        RAISE EXCEPTION 'invalid universal-v3 pick log';
    END IF;

    -- The seed is the Take's own: sha256('v4-pick-seed-v1:' || take id),
    -- its first 13 hex digits read as a number (pick_seed in
    -- services/take_feedback_policy_v3.py). Leading zeroes vanish in that
    -- numeric conversion, on both sides: bigint::text here and str(int(...))
    -- in the code each give the canonical decimal string, and those two
    -- strings are compared, so a seed written with a leading zero is
    -- refused.
    IF p_frame #>> '{pick_log,seed}' IS DISTINCT FROM (
           ('x' || lpad(substr(encode(extensions.digest(
               'v4-pick-seed-v1:' || p_take_session_id::text, 'sha256'),
               'hex'), 1, 13), 16, '0'))::bit(64)::bigint
       )::text THEN
        RAISE EXCEPTION 'invalid universal-v3 pick log';
    END IF;

    -- The log is the inventory, exactly: every confidence candidate of every
    -- block and every verbal candidate appears once, under its lane and (for
    -- confidence) its block, with its eligibility; a selected candidate has
    -- chance 1 (bound to its block or verbal lane), every other eligible one
    -- 0. Nothing more is logged and nothing is left out. One pass: the
    -- inventory and the log are each expanded once, tagged by side, and
    -- grouped by (lane, block_id, candidate_id, eligible, chance); a group
    -- whose inventory count differs from its log count refuses the frame.
    -- GROUP BY treats NULLs as one value (a verbal block_id, an excluded
    -- chance), which a join on equality would not, and compares chance as
    -- a number. The casts on the log side are safe: the entry check above
    -- already proved each entry's types.
    IF EXISTS (
        WITH inventory AS (
            SELECT 'confident_voice'::text AS lane,
                   block ->> 'block_id' AS block_id,
                   candidate ->> 'candidate_id' AS candidate_id,
                   candidate ->> 'eligibility' = 'eligible' AS eligible,
                   CASE WHEN candidate ->> 'eligibility' = 'eligible' THEN
                       CASE WHEN candidate ->> 'candidate_id'
                                 = block ->> 'selected_candidate_id'
                            THEN 1 ELSE 0 END
                   END::numeric AS chance
              FROM jsonb_array_elements(COALESCE(
                       p_frame -> 'blocks', '[]'::jsonb)) block
              CROSS JOIN jsonb_array_elements(COALESCE(
                       block -> 'confidence_candidates', '[]'::jsonb)) candidate
            UNION ALL
            SELECT verbal.lane, NULL::text,
                   candidate ->> 'candidate_id',
                   candidate ->> 'eligibility' = 'eligible',
                   CASE WHEN candidate ->> 'eligibility' = 'eligible' THEN
                       CASE WHEN COALESCE(p_frame #> ARRAY['verbal_lanes',
                                     verbal.lane, 'selected_candidate_ids'],
                                     '[]'::jsonb)
                                 ? (candidate ->> 'candidate_id')
                            THEN 1 ELSE 0 END
                   END::numeric
              FROM (VALUES ('rewrite_clarity'), ('great_formulation'))
                   AS verbal(lane)
              CROSS JOIN jsonb_array_elements(COALESCE(
                       p_frame #> ARRAY['verbal_lanes', verbal.lane,
                                        'candidates'],
                       '[]'::jsonb)) candidate
        ), logged AS (
            SELECT entry ->> 'lane' AS lane,
                   entry ->> 'block_id' AS block_id,
                   entry ->> 'candidate_id' AS candidate_id,
                   (entry ->> 'eligible')::boolean AS eligible,
                   (entry ->> 'pick_probability')::numeric AS chance
              FROM jsonb_array_elements(p_frame #> '{pick_log,candidates}') entry
        ), sides AS (
            SELECT lane, block_id, candidate_id, eligible, chance,
                   1 AS in_inventory, 0 AS in_log
              FROM inventory
            UNION ALL
            SELECT lane, block_id, candidate_id, eligible, chance, 0, 1
              FROM logged
        )
        SELECT 1
          FROM sides
         GROUP BY lane, block_id, candidate_id, eligible, chance
        HAVING sum(in_inventory) <> sum(in_log)
    ) THEN
        RAISE EXCEPTION 'universal-v3 pick log does not match the inventory';
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
         WHERE (
               candidate ->> 'eligibility' = 'eligible'
               OR (
                   candidate ->> 'machine_version' = 'voice-confidence-v2'
                   AND candidate ->> 'eligibility' = 'excluded'
                   AND candidate ->> 'exclusion_reason' =
                       'incompatible_detector_version'
               )
           )
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

    -- Reconcile per exact old clip. A new frame does not mean that every v2
    -- artifact in the Take was recomputed. Only a matching universal-v3
    -- candidate with the same immutable clip identity creates that fact.
    INSERT INTO public.take_feedback_detector_reconciliation (
        take_session_id, recording_id, snippet_id, candidate_id,
        start_offset_ms, duration_ms, clip_identity_sha256,
        old_policy_version, old_detector_version, outcome, evidence_sha256
    )
    SELECT prior.take_session_id, prior.recording_id, snippet.id,
           old_candidate ->> 'candidate_id', snippet.start_offset_ms,
           snippet.duration_ms,
           old_candidate #>> '{clip_identity,clip_identity_sha256}',
           prior.policy_version, 'voice-confidence-v2',
           'incompatible_detector_version',
           encode(extensions.digest(concat_ws(':',
               prior.take_session_id::text, prior.recording_id::text,
               snippet.id::text, old_candidate ->> 'candidate_id',
               old_candidate #>> '{clip_identity,clip_identity_sha256}',
               prior.policy_version, 'voice-confidence-v2',
               'incompatible_detector_version'
           ), 'sha256'), 'hex')
      FROM public.take_feedback_policy_v3_shadow_frames prior
     CROSS JOIN LATERAL jsonb_array_elements(COALESCE(
                prior.frame -> 'blocks', '[]'::jsonb)) old_block
     CROSS JOIN LATERAL jsonb_array_elements(COALESCE(
                old_block -> 'confidence_candidates', '[]'::jsonb)) old_candidate
      JOIN public.snippets snippet
        ON snippet.id::text = old_candidate ->> 'snippet_id'
       AND snippet.session_id = prior.take_session_id
       AND snippet.recording_id = prior.recording_id
       AND old_candidate #>> '{clip_identity,take_id}' =
           prior.take_session_id::text
       AND old_candidate #>> '{clip_identity,recording_id}' =
           prior.recording_id::text
       AND old_candidate #>> '{clip_identity,snippet_id}' = snippet.id::text
       AND old_candidate #>> '{clip_identity,start_offset_ms}' =
           snippet.start_offset_ms::text
       AND old_candidate #>> '{clip_identity,duration_ms}' =
           snippet.duration_ms::text
     WHERE prior.take_session_id = p_take_session_id
       AND prior.policy_version = 'take-feedback-policy-v3-dark-v2'
       AND prior.frame #>>
           '{implementation_versions,confidence_detector_version}' =
           'voice-confidence-v2'
       AND old_candidate ->> 'machine_version' = 'voice-confidence-v2'
       AND length(COALESCE(old_candidate ->> 'candidate_id', '')) > 0
       AND COALESCE(
            old_candidate #>> '{clip_identity,clip_identity_sha256}', '')
           ~ '^[0-9a-f]{64}$'
    ON CONFLICT DO NOTHING;

    INSERT INTO public.take_feedback_detector_reconciliation (
        take_session_id, recording_id, snippet_id, candidate_id,
        start_offset_ms, duration_ms, clip_identity_sha256,
        old_policy_version, old_detector_version, outcome,
        replacement_policy_version, replacement_detector_version,
        replacement_frame_hash, evidence_sha256
    )
    SELECT incompatible.take_session_id, incompatible.recording_id,
           incompatible.snippet_id, incompatible.candidate_id,
           incompatible.start_offset_ms, incompatible.duration_ms,
           incompatible.clip_identity_sha256, incompatible.old_policy_version,
           incompatible.old_detector_version, 'recomputed', p_policy_version,
           'voice-confidence-universal-v3', p_frame_hash,
           encode(extensions.digest(concat_ws(':',
               incompatible.take_session_id::text,
               incompatible.recording_id::text,
               incompatible.snippet_id::text, incompatible.candidate_id,
               incompatible.clip_identity_sha256,
               incompatible.old_policy_version, p_policy_version,
               p_frame_hash, 'recomputed'
           ), 'sha256'), 'hex')
      FROM public.take_feedback_detector_reconciliation incompatible
     WHERE incompatible.take_session_id = p_take_session_id
       AND incompatible.outcome = 'incompatible_detector_version'
       AND EXISTS (
           SELECT 1
             FROM jsonb_array_elements(COALESCE(
                      p_frame -> 'blocks', '[]'::jsonb)) current_block
            CROSS JOIN jsonb_array_elements(COALESCE(
                      current_block -> 'confidence_candidates', '[]'::jsonb))
                      current_candidate
            WHERE current_candidate ->> 'eligibility' = 'eligible'
              AND current_candidate ->> 'machine_version' =
                  'voice-confidence-universal-v3'
              AND current_candidate ->> 'snippet_id' =
                  incompatible.snippet_id::text
              AND current_candidate #>> '{clip_identity,clip_identity_sha256}' =
                  incompatible.clip_identity_sha256
       )
    ON CONFLICT DO NOTHING;
    RETURN jsonb_build_object(
        'outcome', 'stored', 'take_session_id', existing.take_session_id,
        'policy_version', existing.policy_version,
        'frame_hash', existing.frame_hash
    );
END;
$$;

REVOKE ALL ON FUNCTION public.record_take_feedback_policy_v3_shadow_v3(
    TEXT, UUID, UUID, UUID, UUID, INTEGER, TEXT, JSONB, TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.record_take_feedback_policy_v3_shadow_v3(
    TEXT, UUID, UUID, UUID, UUID, INTEGER, TEXT, JSONB, TEXT
) TO service_role;

COMMIT;
