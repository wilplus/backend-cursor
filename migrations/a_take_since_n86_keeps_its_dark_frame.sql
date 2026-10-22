-- 0489 · A Take since N86 keeps its dark frame, and V4 reads it (the
-- version bump of #1207; V4 Phase 1, B1.1 to B1.6; the pattern of 0431 and
-- 0441).
--
-- WHY. #1207 (N86, merged 2026-10-20 ~19:20 CEST) changed which moments V3
-- shows, and with it the frame's labels: the code builds policy
-- 'take-feedback-policy-v3-universal-dark-v4' and frame schema
-- 'take-feedback-policy-v3-frame-v7'. The writer, last defined by 0441,
-- accepts only dark-v3 and frame-v6, so every frame since was refused
-- ("invalid universal-v3 dark frame"), logged as "take feedback v3 dark
-- frame not stored", and nothing after it ran: no random draw (0447), no
-- moment-to-Paragraph map (0451), no willfidence read (0449), so no V4
-- picks (0452) and no pick outcomes (0451, 0457) for any Take since. The
-- chain below the writer named dark-v3 too: five functions read the frame
-- under that one name and seven tables' CHECKs refuse any other, so
-- accepting the frame alone would store it and draw nothing.
--
-- WHAT CHANGES.
--   1. The writer (record_take_feedback_policy_v3_shadow_v3) is 0441's
--      body with its two labels moved: policy dark-v4, frame schema
--      frame-v7. Every other check is 0441's. A dark-v3 or frame-v6 frame
--      is now refused: no code builds one any more, and 0431 and 0441
--      refused the label before theirs the same way. Stored frames are
--      rows, untouched.
--   2. Eight CHECKs that named dark-v3 alone name dark-v3 or dark-v4:
--      take_feedback_detector_reconciliation (the writer's 'recomputed' row
--      carries the new frame's policy), v4_random_moments,
--      v4_willfidence_reads, v4_willfidence_takes, v4_moment_paragraphs,
--      v4_pick_outcomes, v4_picks and v4_moment_pick_sheets. Each is
--      dropped and re-added under its own name in one ALTER, every other
--      clause as it was; every stored row is dark-v3, so the re-check
--      passes. A postcondition refuses this file if a CHECK on these tables
--      still names dark-v3 without dark-v4 (a constraint named otherwise in
--      production would be left in place in silence).
--   3. A Take's V4 frame. v4_frame_policy_v1(take) is the policy of the
--      frame the Take's random draw was made from and, before the draw, of
--      its newest dark frame (dark-v4 before dark-v3). The draw, the map,
--      the read and the picks of a Take use that one frame;
--      compute_v4_pick_outcomes_v1 uses each Take's own, so Take N from
--      before N86 (dark-v3) and Take N+1 after it (dark-v4) still meet:
--      they are compared by paragraph and slide, never by policy. The five
--      bodies are 0447's, 0449's, 0451's and 0457's with only that changed.
--
-- WHY THE DRAW DECIDES. The writer runs whenever a Take's Ideal Text is
-- built (the speaker's GET and the bake), so a Take drawn under dark-v3 gets
-- a dark-v4 frame beside it the next time it is opened. Its draw is made
-- once (0447), and its map, reads, picks and outcomes hang off the frame the
-- draw used; reading the newer frame would find no draw ('no_draw') and
-- leave Take N's outcomes 'not_ready' for good. The draw depends only on the
-- Take's seed and its block ids, the same under both policies, so staying
-- on the first frame loses nothing. A Take with a frame and no draw (one
-- from before 0441's pick log, which 0447 cannot draw) is drawn from its
-- newest frame.
--
-- WHAT DOES NOT CHANGE. Every served path: the frame is dark, written off
-- the speaker's path, and nothing served reads it (AC-9). Who gets a frame
-- (take_feedback_policy_v3.dark_enabled). Every table's columns, keys,
-- foreign keys and grants. v4_speaker_willfidence_v1, which reads every
-- policy already. No row is written, changed or removed by this file, and
-- no environment variable is read, so no Railway service needs
-- configuration first. Takes since 2026-10-20 that have no frame stay
-- without one until their Ideal Text is built again; a backfill is the
-- founder's call, not this file's. Not here: exercise_candidate_sets (0314,
-- the MLC-3 dark assignments) still names dark-v3 alone; nothing has
-- written it since the MLC-3 loop was retired (L8).
--
-- IDEMPOTENT. CREATE OR REPLACE FUNCTION with the same signatures (the
-- grants are re-stated below); each CHECK is DROP CONSTRAINT IF EXISTS and
-- ADD CONSTRAINT in one statement, so a second run ends the same.
--
-- LOCKS. ACCESS EXCLUSIVE on the eight tables until COMMIT, while each
-- re-check reads its table once. All are dark V4 tables (rows since
-- 2026-10-08) and the detector reconciliation log; none is on the
-- speaker's path, and their writers log a failure and the Take stands.
--
-- Rollback (a new forward migration): re-issue 0441's writer and 0447's,
-- 0449's, 0451's and 0457's bodies; the wider CHECKs may stay.

BEGIN;

-- ── 1. The writer: 0441's body, policy dark-v4 and frame schema v7 ────────
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
    IF p_policy_version <> 'take-feedback-policy-v3-universal-dark-v4'
       OR jsonb_typeof(p_frame) <> 'object'
       OR p_frame->>'frame_hash' IS DISTINCT FROM p_frame_hash
       OR p_frame->>'policy_version' IS DISTINCT FROM p_policy_version
       OR p_frame->>'take_id' IS DISTINCT FROM p_take_session_id::text
       OR p_frame->>'recording_id' IS DISTINCT FROM p_recording_id::text
       OR p_frame->>'frame_schema_version'
          IS DISTINCT FROM 'take-feedback-policy-v3-frame-v7'
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

-- ── 2. The CHECKs name dark-v3 or dark-v4 ─────────────────────────────────
ALTER TABLE public.take_feedback_detector_reconciliation
    DROP CONSTRAINT IF EXISTS detector_reconciliation_replacement_check,
    ADD CONSTRAINT detector_reconciliation_replacement_check CHECK (
        (outcome = 'incompatible_detector_version'
            AND replacement_policy_version IS NULL
            AND replacement_detector_version IS NULL
            AND replacement_frame_hash IS NULL)
        OR (outcome = 'recomputed'
            AND replacement_policy_version IN (
                'take-feedback-policy-v3-universal-dark-v3',
                'take-feedback-policy-v3-universal-dark-v4')
            AND replacement_detector_version =
                'voice-confidence-universal-v3'
            AND replacement_frame_hash IS NOT NULL)
    );

ALTER TABLE public.v4_random_moments
    DROP CONSTRAINT IF EXISTS v4_random_moments_draw_version,
    ADD CONSTRAINT v4_random_moments_draw_version CHECK (
        draw_version = 'v4-random-draw-v1'
        AND policy_version IN ('take-feedback-policy-v3-universal-dark-v3',
                               'take-feedback-policy-v3-universal-dark-v4'));

ALTER TABLE public.v4_willfidence_reads
    DROP CONSTRAINT IF EXISTS v4_willfidence_reads_versions,
    ADD CONSTRAINT v4_willfidence_reads_versions CHECK (
        read_version = 'willfidence-v1-machine'
        AND policy_version IN ('take-feedback-policy-v3-universal-dark-v3',
                               'take-feedback-policy-v3-universal-dark-v4')
        AND roles_version = 'v4-moment-roles-v1'
        AND holding_together_version = 'v4-holding-together-v1');

ALTER TABLE public.v4_willfidence_takes
    DROP CONSTRAINT IF EXISTS v4_willfidence_takes_version,
    ADD CONSTRAINT v4_willfidence_takes_version CHECK (
        read_version = 'willfidence-v1-machine'
        AND policy_version IN ('take-feedback-policy-v3-universal-dark-v3',
                               'take-feedback-policy-v3-universal-dark-v4'));

ALTER TABLE public.v4_moment_paragraphs
    DROP CONSTRAINT IF EXISTS v4_moment_paragraphs_policy,
    ADD CONSTRAINT v4_moment_paragraphs_policy CHECK (
        policy_version IN ('take-feedback-policy-v3-universal-dark-v3',
                           'take-feedback-policy-v3-universal-dark-v4'));

ALTER TABLE public.v4_pick_outcomes
    DROP CONSTRAINT IF EXISTS v4_pick_outcomes_versions,
    ADD CONSTRAINT v4_pick_outcomes_versions CHECK (
        policy_version IN ('take-feedback-policy-v3-universal-dark-v3',
                           'take-feedback-policy-v3-universal-dark-v4')
        AND read_version = 'willfidence-v1-machine'
        AND margin = 0.05 AND margin_version = 'rise-margin-v0-placeholder');

ALTER TABLE public.v4_picks
    DROP CONSTRAINT IF EXISTS v4_picks_versions,
    ADD CONSTRAINT v4_picks_versions CHECK (
        policy_version IN ('take-feedback-policy-v3-universal-dark-v3',
                           'take-feedback-policy-v3-universal-dark-v4')
        AND picker_version = 'v4-picker-v1'
        AND roles_version = 'v4-moment-roles-v1'
        AND cutoff = 0.3 AND cutoff_version = 'sureness-cutoff-v0-placeholder');

ALTER TABLE public.v4_moment_pick_sheets
    DROP CONSTRAINT IF EXISTS v4_moment_pick_sheets_versions,
    ADD CONSTRAINT v4_moment_pick_sheets_versions CHECK (
        sheet_version = 'v4-moment-pick-sheet-v1'
        AND policy_version IN ('take-feedback-policy-v3-universal-dark-v3',
                               'take-feedback-policy-v3-universal-dark-v4')
        AND picker_version = 'v4-picker-v1');

-- The postcondition: no CHECK on the eight tables still names dark-v3
-- without dark-v4, whatever it is called. A table missing here fails the
-- cast, which is right: production has all eight.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
          FROM pg_constraint c
         WHERE c.contype = 'c'
           AND c.conrelid IN (
               'public.take_feedback_detector_reconciliation'::regclass,
               'public.v4_random_moments'::regclass,
               'public.v4_willfidence_reads'::regclass,
               'public.v4_willfidence_takes'::regclass,
               'public.v4_moment_paragraphs'::regclass,
               'public.v4_pick_outcomes'::regclass,
               'public.v4_picks'::regclass,
               'public.v4_moment_pick_sheets'::regclass)
           AND pg_get_constraintdef(c.oid)
               LIKE '%take-feedback-policy-v3-universal-dark-v3%'
           AND pg_get_constraintdef(c.oid)
               NOT LIKE '%take-feedback-policy-v3-universal-dark-v4%'
    ) THEN
        RAISE EXCEPTION '0489: a CHECK still names dark-v3 alone';
    END IF;
END $$;

-- ── 3. A Take's V4 frame ──────────────────────────────────────────────────
-- The policy of the frame the Take's random draw was made from; before the
-- draw, of its newest dark frame (dark-v4 before dark-v3); NULL with no
-- frame. One policy per Take is ever drawn (0447 stores one draw per Take),
-- so the ORDER BY only makes the read deterministic. Mirrored in
-- services/db.py (get_v4_dark_frame).
CREATE OR REPLACE FUNCTION public.v4_frame_policy_v1(p_take_session_id uuid)
RETURNS text
LANGUAGE sql STABLE SET search_path = public
AS $$
    SELECT COALESCE(
        (SELECT d.policy_version
           FROM public.v4_random_moments d
          WHERE d.take_session_id = p_take_session_id
          ORDER BY d.created_at, d.policy_version
          LIMIT 1),
        (SELECT f.policy_version
           FROM public.take_feedback_policy_v3_shadow_frames f
          WHERE f.take_session_id = p_take_session_id
            AND f.policy_version IN (
                'take-feedback-policy-v3-universal-dark-v4',
                'take-feedback-policy-v3-universal-dark-v3')
          ORDER BY f.policy_version
                   = 'take-feedback-policy-v3-universal-dark-v4' DESC
          LIMIT 1));
$$;

COMMENT ON FUNCTION public.v4_frame_policy_v1(uuid) IS
    'The policy of the dark frame V4 reads for one Take (0489): the frame '
    'its random draw was made from; before the draw, its newest (dark-v4 '
    'before dark-v3). Internal (AC-9).';

-- 0447's draw.
CREATE OR REPLACE FUNCTION public.draw_v4_random_moments_v1(
    p_take_session_id uuid
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    v_policy  text;
    v_draw    constant text := 'v4-random-draw-v1';
    v_frame   public.take_feedback_policy_v3_shadow_frames%ROWTYPE;
    v_seed    text;
    v_n       integer;
    v_k       integer;
    v_stored  integer;
BEGIN
    IF p_take_session_id IS NULL THEN
        RAISE EXCEPTION 'V4_RANDOM_MOMENTS_INPUT_INVALID';
    END IF;

    -- One draw per Take at a time: a second caller waits, then finds the
    -- first caller's rows and returns them.
    PERFORM pg_advisory_xact_lock(
        hashtext('v4-random-draw:' || p_take_session_id::text));

    SELECT count(*) INTO v_stored
      FROM public.v4_random_moments
     WHERE take_session_id = p_take_session_id
       AND draw_version = v_draw;
    IF v_stored > 0 THEN
        RETURN jsonb_build_object(
            'outcome', 'stored', 'draw_version', v_draw, 'drawn', v_stored);
    END IF;

    -- 0489: no draw yet, so the Take's newest dark frame
    -- (v4_frame_policy_v1).
    v_policy := public.v4_frame_policy_v1(p_take_session_id);

    SELECT * INTO v_frame
      FROM public.take_feedback_policy_v3_shadow_frames
     WHERE take_session_id = p_take_session_id
       AND policy_version = v_policy;
    IF v_frame.take_session_id IS NULL THEN
        RETURN jsonb_build_object('outcome', 'no_frame');
    END IF;

    -- The frame was checked by its writer (0441); the draw still proves the
    -- two things it reads before it reads them, each its own statement so
    -- nothing is expanded before its type is known.
    v_seed := v_frame.frame #>> '{pick_log,seed}';
    IF COALESCE(v_seed, '') !~ '^[0-9]{1,16}$'
       OR jsonb_typeof(v_frame.frame -> 'blocks') IS DISTINCT FROM 'array'
       OR jsonb_array_length(v_frame.frame -> 'blocks') = 0 THEN
        RAISE EXCEPTION 'V4_RANDOM_MOMENTS_FRAME_INVALID';
    END IF;
    IF EXISTS (
        SELECT 1
          FROM jsonb_array_elements(v_frame.frame -> 'blocks') block
         WHERE jsonb_typeof(block) IS DISTINCT FROM 'object'
            OR jsonb_typeof(block -> 'block_id') IS DISTINCT FROM 'string'
            OR length(block ->> 'block_id') = 0
            OR (block ? 'slide_index'
                AND jsonb_typeof(block -> 'slide_index')
                    NOT IN ('number', 'null'))
    ) THEN
        RAISE EXCEPTION 'V4_RANDOM_MOMENTS_FRAME_INVALID';
    END IF;
    -- A moment is drawn at most once: two blocks with one id refuse the
    -- draw rather than doubling that moment's chance.
    IF EXISTS (
        SELECT 1
          FROM jsonb_array_elements(v_frame.frame -> 'blocks') block
         GROUP BY block ->> 'block_id'
        HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION 'V4_RANDOM_MOMENTS_FRAME_INVALID';
    END IF;

    v_n := jsonb_array_length(v_frame.frame -> 'blocks');
    v_k := (v_n + 4) / 5;  -- ceil(n / 5): 20%, rounded up (V3 A)

    INSERT INTO public.v4_random_moments (
        take_session_id, policy_version, draw_version, block_id,
        slide_index, draw_rank, moments_in_take, drawn_count, seed,
        frame_hash, acquisition_principal_id
    )
    SELECT p_take_session_id, v_policy, v_draw, ranked.block_id,
           ranked.slide_index, ranked.draw_rank, v_n, v_k, v_seed,
           v_frame.frame_hash, v_frame.acquisition_principal_id
      FROM (
          SELECT block ->> 'block_id' AS block_id,
                 CASE WHEN jsonb_typeof(block -> 'slide_index') = 'number'
                      THEN (block ->> 'slide_index')::numeric::integer
                 END AS slide_index,
                 row_number() OVER (
                     ORDER BY encode(extensions.digest(
                                  v_draw || ':' || v_seed || ':'
                                  || (block ->> 'block_id'), 'sha256'),
                                  'hex') COLLATE "C",
                              (block ->> 'block_id') COLLATE "C"
                 ) AS draw_rank
            FROM jsonb_array_elements(v_frame.frame -> 'blocks') block
      ) ranked
     WHERE ranked.draw_rank <= v_k;

    RETURN jsonb_build_object(
        'outcome', 'drawn', 'draw_version', v_draw, 'drawn', v_k,
        'moments', v_n);
END;
$$;

-- 0449's read.
CREATE OR REPLACE FUNCTION public.record_v4_willfidence_reads_v1(
    p_take_session_id uuid,
    p_reads jsonb
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    v_policy  text;
    v_read    constant text := 'willfidence-v1-machine';
    v_frame   public.take_feedback_policy_v3_shadow_frames%ROWTYPE;
    v_n       integer;
    v_random  integer;
    v_rated   integer;
    v_mean    numeric;
    v_status  text;
BEGIN
    IF p_take_session_id IS NULL OR jsonb_typeof(p_reads) IS DISTINCT FROM 'array' THEN
        RAISE EXCEPTION 'V4_WILLFIDENCE_INPUT_INVALID';
    END IF;

    PERFORM pg_advisory_xact_lock(
        hashtext('v4-willfidence:' || p_take_session_id::text));

    IF EXISTS (SELECT 1 FROM public.v4_willfidence_takes
                WHERE take_session_id = p_take_session_id
                  AND read_version = v_read) THEN
        RETURN jsonb_build_object('outcome', 'stored', 'read_version', v_read);
    END IF;

    -- 0489: the Take's own dark frame (v4_frame_policy_v1).
    v_policy := public.v4_frame_policy_v1(p_take_session_id);
    SELECT * INTO v_frame
      FROM public.take_feedback_policy_v3_shadow_frames
     WHERE take_session_id = p_take_session_id AND policy_version = v_policy;
    IF v_frame.take_session_id IS NULL THEN
        RETURN jsonb_build_object('outcome', 'no_frame');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM public.v4_random_moments
                    WHERE take_session_id = p_take_session_id
                      AND policy_version = v_policy) THEN
        RETURN jsonb_build_object('outcome', 'no_draw');
    END IF;
    IF jsonb_typeof(v_frame.frame -> 'blocks') IS DISTINCT FROM 'array' THEN
        RAISE EXCEPTION 'V4_WILLFIDENCE_FRAME_INVALID';
    END IF;

    -- Every read: an object naming a block, its signals in their ranges and
    -- types, its role from the signed list. Checked before anything is cast.
    IF EXISTS (
        SELECT 1 FROM jsonb_array_elements(p_reads) r
         WHERE jsonb_typeof(r) IS DISTINCT FROM 'object'
            OR jsonb_typeof(r -> 'block_id') IS DISTINCT FROM 'string'
            OR EXISTS (
                SELECT 1 FROM unnest(ARRAY['filler', 'hedging', 'slide_fit',
                                           'holding_together']) AS k(key)
                 WHERE jsonb_typeof(r -> k.key) IS NOT NULL
                   AND jsonb_typeof(r -> k.key) NOT IN ('number', 'null'))
            OR (jsonb_typeof(r -> 'role') IS NOT NULL
                AND jsonb_typeof(r -> 'role') NOT IN ('string', 'null'))
    ) THEN
        RAISE EXCEPTION 'V4_WILLFIDENCE_READS_INVALID';
    END IF;
    IF EXISTS (
        SELECT 1 FROM jsonb_array_elements(p_reads) r
         WHERE NOT ((r ->> 'filler') IS NULL
                    OR (r ->> 'filler')::numeric BETWEEN 0 AND 1)
            OR NOT ((r ->> 'hedging') IS NULL
                    OR (r ->> 'hedging')::numeric BETWEEN 0 AND 1)
            OR NOT ((r ->> 'slide_fit') IS NULL
                    OR (r ->> 'slide_fit')::numeric IN (0, 0.5, 1))
            OR NOT ((r ->> 'holding_together') IS NULL
                    OR (r ->> 'holding_together')::numeric IN (0, 0.5, 1))
            OR NOT ((r ->> 'role') IS NULL
                    OR (r ->> 'role') IN ('opening', 'main_point', 'close',
                                          'evidence', 'transition', 'aside'))
    ) THEN
        RAISE EXCEPTION 'V4_WILLFIDENCE_READS_INVALID';
    END IF;

    -- The reads are the frame's moments exactly: each block once, nothing
    -- else.
    IF EXISTS (
        WITH frame_blocks AS (
            SELECT block ->> 'block_id' AS block_id, 1 AS f, 0 AS r
              FROM jsonb_array_elements(v_frame.frame -> 'blocks') block
            UNION ALL
            SELECT r ->> 'block_id', 0, 1 FROM jsonb_array_elements(p_reads) r
        )
        SELECT 1 FROM frame_blocks GROUP BY block_id
        HAVING sum(f) <> 1 OR sum(r) <> 1
    ) THEN
        RAISE EXCEPTION 'V4_WILLFIDENCE_READS_DO_NOT_MATCH_THE_FRAME';
    END IF;

    INSERT INTO public.v4_willfidence_reads (
        take_session_id, policy_version, read_version, block_id, slide_index,
        is_random, sound_clips, s, filler, hedging, slide_fit,
        holding_together, word_signals, w, willfident, hollow, hidden, lost,
        judge_spread, role, roles_version, holding_together_version,
        unrateable_reason, acquisition_principal_id
    )
    SELECT p_take_session_id, v_policy, v_read, m.block_id, m.slide_index,
           m.is_random, m.sound_clips, m.s, m.filler, m.hedging, m.slide_fit,
           m.holding_together, m.word_signals, m.w,
           m.s * m.w, m.s * (1 - m.w), (1 - m.s) * m.w,
           (1 - m.s) * (1 - m.w),
           NULL, m.role, 'v4-moment-roles-v1', 'v4-holding-together-v1',
           CASE WHEN m.s IS NULL THEN 'no_sound_read'
                WHEN m.w IS NULL THEN 'no_word_signal' END,
           v_frame.acquisition_principal_id
      FROM (
          SELECT b.block_id, b.slide_index, b.is_random, b.sound_clips,
                 b.s, b.filler, b.hedging, b.slide_fit, b.holding_together,
                 b.role, b.word_signals,
                 CASE WHEN b.word_signals > 0 THEN
                     (COALESCE(b.filler, 0) + COALESCE(b.hedging, 0)
                      + COALESCE(b.slide_fit, 0)
                      + COALESCE(b.holding_together, 0)) / b.word_signals
                 END AS w
            FROM (
                SELECT block ->> 'block_id' AS block_id,
                       CASE WHEN jsonb_typeof(block -> 'slide_index') = 'number'
                            THEN (block ->> 'slide_index')::numeric::integer
                       END AS slide_index,
                       EXISTS (SELECT 1 FROM public.v4_random_moments d
                                WHERE d.take_session_id = p_take_session_id
                                  AND d.policy_version = v_policy
                                  AND d.block_id = block ->> 'block_id')
                           AS is_random,
                       sound.clips AS sound_clips,
                       CASE WHEN sound.clips > 0
                            THEN (sound.mean + 1) / 2 END AS s,
                       (r ->> 'filler')::numeric AS filler,
                       (r ->> 'hedging')::numeric AS hedging,
                       (r ->> 'slide_fit')::numeric AS slide_fit,
                       (r ->> 'holding_together')::numeric AS holding_together,
                       r ->> 'role' AS role,
                       (r ->> 'filler' IS NOT NULL)::int
                       + (r ->> 'hedging' IS NOT NULL)::int
                       + (r ->> 'slide_fit' IS NOT NULL)::int
                       + (r ->> 'holding_together' IS NOT NULL)::int
                           AS word_signals
                  FROM jsonb_array_elements(v_frame.frame -> 'blocks') block
                  JOIN jsonb_array_elements(p_reads) r
                    ON r ->> 'block_id' = block ->> 'block_id'
                 CROSS JOIN LATERAL (
                     -- The moment's clips, as the frame lists them, that
                     -- belong to this Take and carry a universal-v3 read.
                     SELECT count(*)::int AS clips,
                            avg((snippet.metrics #>>
                                 '{voice_confidence,score}')::numeric) AS mean
                       FROM jsonb_array_elements_text(CASE
                                WHEN jsonb_typeof(block -> 'snippet_ids') = 'array'
                                THEN block -> 'snippet_ids'
                                ELSE '[]'::jsonb END) clip(id)
                       JOIN public.snippets snippet
                         ON snippet.id::text = clip.id
                        AND snippet.session_id = p_take_session_id
                      WHERE snippet.metrics #>> '{voice_confidence,version}'
                            = 'voice-confidence-universal-v3'
                        AND jsonb_typeof(snippet.metrics #>
                            '{voice_confidence,score}') = 'number'
                        AND (snippet.metrics #>> '{voice_confidence,score}')
                            ::numeric BETWEEN -1 AND 1
                 ) sound
            ) b
      ) m;

    SELECT count(*), count(*) FILTER (WHERE s IS NOT NULL AND w IS NOT NULL),
           avg(s * w) FILTER (WHERE s IS NOT NULL AND w IS NOT NULL)
      INTO v_random, v_rated, v_mean
      FROM public.v4_willfidence_reads
     WHERE take_session_id = p_take_session_id AND read_version = v_read
       AND is_random;
    v_n := jsonb_array_length(v_frame.frame -> 'blocks');
    v_status := CASE
        WHEN (v_random - v_rated) * 10 > v_random * 3 THEN 'audio_problem'
        WHEN v_rated < 10 THEN 'not_enough_data'
        ELSE 'measured' END;

    INSERT INTO public.v4_willfidence_takes (
        take_session_id, policy_version, read_version, moments,
        random_moments, rated_random_moments, willfidence, status,
        acquisition_principal_id
    ) VALUES (
        p_take_session_id, v_policy, v_read, v_n, v_random, v_rated, v_mean,
        v_status, v_frame.acquisition_principal_id
    );

    RETURN jsonb_build_object(
        'outcome', 'read', 'read_version', v_read, 'moments', v_n,
        'random_moments', v_random, 'rated_random_moments', v_rated,
        'status', v_status);
END;
$$;

-- 0451's map.
CREATE OR REPLACE FUNCTION public.record_v4_moment_paragraphs_v1(
    p_take_session_id uuid,
    p_map jsonb
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    v_policy text;
    v_frame  public.take_feedback_policy_v3_shadow_frames%ROWTYPE;
BEGIN
    IF p_take_session_id IS NULL
       OR jsonb_typeof(p_map) IS DISTINCT FROM 'array' THEN
        RAISE EXCEPTION 'V4_MOMENT_PARAGRAPHS_INPUT_INVALID';
    END IF;
    PERFORM pg_advisory_xact_lock(
        hashtext('v4-moment-paragraphs:' || p_take_session_id::text));
    -- 0489: the Take's own dark frame (v4_frame_policy_v1).
    v_policy := public.v4_frame_policy_v1(p_take_session_id);
    IF EXISTS (SELECT 1 FROM public.v4_moment_paragraphs
                WHERE take_session_id = p_take_session_id
                  AND policy_version = v_policy) THEN
        RETURN jsonb_build_object('outcome', 'stored');
    END IF;
    SELECT * INTO v_frame FROM public.take_feedback_policy_v3_shadow_frames
     WHERE take_session_id = p_take_session_id AND policy_version = v_policy;
    IF v_frame.take_session_id IS NULL THEN
        RETURN jsonb_build_object('outcome', 'no_frame');
    END IF;
    IF jsonb_typeof(v_frame.frame -> 'blocks') IS DISTINCT FROM 'array'
       OR EXISTS (
           SELECT 1 FROM jsonb_array_elements(p_map) m
            WHERE jsonb_typeof(m) IS DISTINCT FROM 'object'
               OR jsonb_typeof(m -> 'block_id') IS DISTINCT FROM 'string'
               OR NOT (jsonb_typeof(m -> 'paragraph_id') IS NULL
                       OR jsonb_typeof(m -> 'paragraph_id') = 'null'
                       OR (jsonb_typeof(m -> 'paragraph_id') = 'string'
                           AND (m ->> 'paragraph_id') ~*
                    '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'))) THEN
        RAISE EXCEPTION 'V4_MOMENT_PARAGRAPHS_INVALID';
    END IF;
    IF EXISTS (
        WITH sides AS (
            SELECT block ->> 'block_id' AS block_id, 1 AS f, 0 AS m
              FROM jsonb_array_elements(v_frame.frame -> 'blocks') block
            UNION ALL
            SELECT m ->> 'block_id', 0, 1 FROM jsonb_array_elements(p_map) m
        )
        SELECT 1 FROM sides GROUP BY block_id HAVING sum(f) <> 1 OR sum(m) <> 1
    ) THEN
        RAISE EXCEPTION 'V4_MOMENT_PARAGRAPHS_DO_NOT_MATCH_THE_FRAME';
    END IF;
    INSERT INTO public.v4_moment_paragraphs (
        take_session_id, policy_version, block_id, slide_index, paragraph_id,
        acquisition_principal_id)
    SELECT p_take_session_id, v_policy, block ->> 'block_id',
           CASE WHEN jsonb_typeof(block -> 'slide_index') = 'number'
                THEN (block ->> 'slide_index')::numeric::integer END,
           NULLIF(m ->> 'paragraph_id', '')::uuid,
           v_frame.acquisition_principal_id
      FROM jsonb_array_elements(v_frame.frame -> 'blocks') block
      JOIN jsonb_array_elements(p_map) m
        ON m ->> 'block_id' = block ->> 'block_id';
    RETURN jsonb_build_object('outcome', 'mapped');
END;
$$;

-- 0457's picks.
CREATE OR REPLACE FUNCTION public.record_v4_picks_v1(
    p_take_session_id uuid,
    p_rows jsonb
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    v_policy text;
    v_picker constant text := 'v4-picker-v1';
    v_frame  public.take_feedback_policy_v3_shadow_frames%ROWTYPE;
    v_n      integer;
BEGIN
    IF p_take_session_id IS NULL OR jsonb_typeof(p_rows) IS DISTINCT FROM 'array' THEN
        RAISE EXCEPTION 'V4_PICKS_INPUT_INVALID';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtext('v4-picks:' || p_take_session_id::text));
    -- 0489: the Take's own dark frame (v4_frame_policy_v1).
    v_policy := public.v4_frame_policy_v1(p_take_session_id);
    IF EXISTS (SELECT 1 FROM public.v4_pick_takes
                WHERE take_session_id = p_take_session_id
                  AND policy_version = v_policy AND picker_version = v_picker) THEN
        RETURN jsonb_build_object('outcome', 'stored');
    END IF;
    SELECT * INTO v_frame FROM public.take_feedback_policy_v3_shadow_frames
     WHERE take_session_id = p_take_session_id AND policy_version = v_policy;
    IF v_frame.take_session_id IS NULL THEN
        RETURN jsonb_build_object('outcome', 'no_frame');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM public.v4_willfidence_takes
                    WHERE take_session_id = p_take_session_id
                      AND policy_version = v_policy
                      AND read_version = 'willfidence-v1-machine') THEN
        RETURN jsonb_build_object('outcome', 'no_read');
    END IF;

    -- Shape and types first; nothing is cast before its type is known.
    IF EXISTS (
        SELECT 1 FROM jsonb_array_elements(p_rows) r
         WHERE jsonb_typeof(r) IS DISTINCT FROM 'object'
            OR jsonb_typeof(r -> 'block_id') IS DISTINCT FROM 'string'
            OR jsonb_typeof(r -> 'fallback') IS DISTINCT FROM 'boolean'
            OR jsonb_typeof(r -> 'picked') IS DISTINCT FROM 'boolean'
            OR EXISTS (SELECT 1 FROM unnest(ARRAY['strength', 'disagreement', 'sureness'])
                              AS k(key)
                        WHERE jsonb_typeof(r -> k.key) IS DISTINCT FROM 'number')
            OR EXISTS (SELECT 1 FROM unnest(ARRAY['importance', 'willfident', 'gap',
                                                  'rank_score', 'rank_position'])
                              AS k(key)
                        WHERE COALESCE(jsonb_typeof(r -> k.key), 'null')
                              NOT IN ('number', 'null'))
            OR EXISTS (SELECT 1 FROM unnest(ARRAY['role', 'v4_kind', 'v4_snippet_id',
                                                  'v3_kind', 'v3_snippet_id',
                                                  'fallback_reason', 'used_kind',
                                                  'used_snippet_id'])
                              AS k(key)
                        WHERE COALESCE(jsonb_typeof(r -> k.key), 'null')
                              NOT IN ('string', 'null'))
            -- 0457: a rank position is a whole number, never rounded to one.
            --       CASE, so the cast runs only on a number.
            OR (CASE WHEN jsonb_typeof(r -> 'rank_position') = 'number'
                     THEN (r ->> 'rank_position')::numeric
                          <> trunc((r ->> 'rank_position')::numeric)
                     ELSE false END)
    ) THEN
        RAISE EXCEPTION 'V4_PICKS_INVALID';
    END IF;
    -- Exactly the frame's blocks, each once.
    IF EXISTS (
        WITH sides AS (
            SELECT block ->> 'block_id' AS block_id, 1 AS f, 0 AS r
              FROM jsonb_array_elements(v_frame.frame -> 'blocks') block
            UNION ALL
            SELECT r ->> 'block_id', 0, 1 FROM jsonb_array_elements(p_rows) r
        )
        SELECT 1 FROM sides GROUP BY block_id HAVING sum(f) <> 1 OR sum(r) <> 1
    ) THEN
        RAISE EXCEPTION 'V4_PICKS_DO_NOT_MATCH_THE_FRAME';
    END IF;
    -- Allowed first (P1), against the frame's own read of each block; the
    -- role and S*W are the 0449 read's; each moment is one of the block's
    -- clips.
    IF EXISTS (
        SELECT 1
          FROM jsonb_array_elements(p_rows) r
          JOIN jsonb_array_elements(v_frame.frame -> 'blocks') block
            ON block ->> 'block_id' = r ->> 'block_id'
          LEFT JOIN public.v4_willfidence_reads read
            ON read.take_session_id = p_take_session_id
           AND read.policy_version = v_policy
           AND read.read_version = 'willfidence-v1-machine'
           AND read.block_id = r ->> 'block_id'
         WHERE (r ->> 'v4_kind' = 'praise' AND COALESCE(block ->> 'delivery_band', '')
                    NOT IN ('delivery_signal_high', 'delivery_signal_mid_high'))
            OR (r ->> 'v4_kind' IN ('rewrite', 'exercise')
                AND (block ->> 'delivery_band' IS NULL
                     OR block ->> 'delivery_band' IN ('delivery_signal_high',
                                                      'delivery_signal_mid_high')))
            -- 0457: every block has its read row.
            OR read.block_id IS NULL
            OR (r ->> 'role') IS DISTINCT FROM read.role
            -- 0457: a number only where the read has one, and the same one.
            OR (CASE WHEN jsonb_typeof(r -> 'willfident') = 'number'
                     THEN read.willfident IS NULL
                          OR abs((r ->> 'willfident')::numeric - read.willfident) >= 1e-9
                     ELSE read.willfident IS NOT NULL END)
            OR (r ->> 'v4_snippet_id' IS NOT NULL AND NOT (
                    COALESCE(block -> 'snippet_ids', '[]'::jsonb) ? (r ->> 'v4_snippet_id')))
            -- 0457: V3's clip, too, is one of the block's clips.
            OR (r ->> 'v3_snippet_id' IS NOT NULL AND NOT (
                    COALESCE(block -> 'snippet_ids', '[]'::jsonb) ? (r ->> 'v3_snippet_id')))
    ) THEN
        RAISE EXCEPTION 'V4_PICKS_NOT_ALLOWED';
    END IF;

    INSERT INTO public.v4_picks (
        take_session_id, policy_version, picker_version, block_id, role,
        importance, willfident, gap, strength, disagreement, sureness,
        rank_score, rank_position, picked, v4_kind, v4_snippet_id, v3_kind,
        v3_snippet_id, fallback, fallback_reason, used_kind, used_snippet_id,
        roles_version, cutoff, cutoff_version, acquisition_principal_id)
    SELECT p_take_session_id, v_policy, v_picker, r ->> 'block_id', r ->> 'role',
           (r ->> 'importance')::numeric, (r ->> 'willfident')::numeric,
           (r ->> 'gap')::numeric, (r ->> 'strength')::numeric,
           (r ->> 'disagreement')::numeric, (r ->> 'sureness')::numeric,
           (r ->> 'rank_score')::numeric, (r ->> 'rank_position')::numeric::integer,
           (r ->> 'picked')::boolean, r ->> 'v4_kind', r ->> 'v4_snippet_id',
           r ->> 'v3_kind', r ->> 'v3_snippet_id', (r ->> 'fallback')::boolean,
           r ->> 'fallback_reason', r ->> 'used_kind', r ->> 'used_snippet_id',
           'v4-moment-roles-v1', 0.3, 'sureness-cutoff-v0-placeholder',
           v_frame.acquisition_principal_id
      FROM jsonb_array_elements(p_rows) r;

    -- The ranks are a strict order of the improvable blocks by rank_score.
    IF EXISTS (
        SELECT 1 FROM (
            SELECT rank_position,
                   row_number() OVER (ORDER BY rank_score DESC, block_id COLLATE "C") AS expected
              FROM public.v4_picks
             WHERE take_session_id = p_take_session_id AND policy_version = v_policy
               AND picker_version = v_picker
               AND v4_kind IN ('rewrite', 'exercise') AND rank_score IS NOT NULL
        ) ranked WHERE rank_position IS DISTINCT FROM expected
    ) THEN
        RAISE EXCEPTION 'V4_PICKS_RANK_ORDER';
    END IF;

    v_n := jsonb_array_length(p_rows);
    INSERT INTO public.v4_pick_takes (
        take_session_id, policy_version, picker_version, blocks,
        fallback_blocks, acquisition_principal_id)
    SELECT p_take_session_id, v_policy, v_picker, v_n,
           count(*) FILTER (WHERE fallback), v_frame.acquisition_principal_id
      FROM public.v4_picks
     WHERE take_session_id = p_take_session_id AND policy_version = v_policy
       AND picker_version = v_picker;
    RETURN jsonb_build_object('outcome', 'picked', 'blocks', v_n);
END;
$$;

-- 0457's outcomes.
CREATE OR REPLACE FUNCTION public.compute_v4_pick_outcomes_v1(
    p_next_take_session_id uuid
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    v_policy      text;  -- 0489: Take N's own dark frame
    v_next_policy text;  -- 0489: Take N+1's own dark frame
    v_read   constant text := 'willfidence-v1-machine';
    v_next   public.v2_sessions%ROWTYPE;
    v_prev   public.v2_sessions%ROWTYPE;
    v_frame  public.take_feedback_policy_v3_shadow_frames%ROWTYPE;
    v_count  integer;
BEGIN
    IF p_next_take_session_id IS NULL THEN
        RAISE EXCEPTION 'V4_PICK_OUTCOMES_INPUT_INVALID';
    END IF;
    SELECT * INTO v_next FROM public.v2_sessions WHERE id = p_next_take_session_id;
    IF v_next.id IS NULL OR v_next.take_index IS NULL OR v_next.take_index < 2 THEN
        RETURN jsonb_build_object('outcome', 'no_previous_take');
    END IF;
    SELECT * INTO v_prev FROM public.v2_sessions
     WHERE arc_id = v_next.arc_id
       AND owner_principal_id IS NOT DISTINCT FROM v_next.owner_principal_id
       AND take_index = v_next.take_index - 1
       AND COALESCE(recording_kind, 'spoken') = 'spoken'
       AND paired_session_id IS NULL
     ORDER BY id LIMIT 1;
    IF v_prev.id IS NULL THEN
        RETURN jsonb_build_object('outcome', 'no_previous_take');
    END IF;
    PERFORM pg_advisory_xact_lock(hashtext('v4-pick-outcomes:' || v_prev.id::text));
    -- 0489: each Take reads the frame its own draw was made from. Take
    -- N from before N86 is dark-v3 and Take N+1 after it dark-v4; they
    -- meet by paragraph and slide, never by policy.
    v_policy := public.v4_frame_policy_v1(v_prev.id);
    v_next_policy := public.v4_frame_policy_v1(v_next.id);
    IF EXISTS (SELECT 1 FROM public.v4_pick_outcomes
                WHERE take_session_id = v_prev.id AND policy_version = v_policy
                  AND read_version = v_read) THEN
        RETURN jsonb_build_object('outcome', 'stored');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM public.v4_willfidence_takes
                    WHERE take_session_id = v_prev.id AND policy_version = v_policy
                      AND read_version = v_read)
       OR NOT EXISTS (SELECT 1 FROM public.v4_willfidence_takes
                       WHERE take_session_id = v_next.id AND policy_version = v_next_policy
                         AND read_version = v_read) THEN
        RETURN jsonb_build_object('outcome', 'not_ready');
    END IF;
    -- 0457: the slide backs up a moment with no Paragraph, never a Take
    -- with no map. Both Takes' maps, or nothing is written.
    IF NOT EXISTS (SELECT 1 FROM public.v4_moment_paragraphs
                    WHERE take_session_id = v_prev.id AND policy_version = v_policy)
       OR NOT EXISTS (SELECT 1 FROM public.v4_moment_paragraphs
                       WHERE take_session_id = v_next.id AND policy_version = v_next_policy) THEN
        RETURN jsonb_build_object('outcome', 'no_map');
    END IF;
    SELECT * INTO v_frame FROM public.take_feedback_policy_v3_shadow_frames
     WHERE take_session_id = v_prev.id AND policy_version = v_policy;

    INSERT INTO public.v4_pick_outcomes (
        take_session_id, next_take_session_id, policy_version, read_version,
        block_id, slide_index, paragraph_id, match_level, v3_picks,
        willfidence_before, willfidence_after, rise, margin, margin_version,
        outcome, acquisition_principal_id)
    WITH rated AS (
        SELECT r.take_session_id, r.block_id, r.slide_index, mp.paragraph_id,
               r.s * r.w AS sw
          FROM public.v4_willfidence_reads r
          LEFT JOIN public.v4_moment_paragraphs mp
            ON mp.take_session_id = r.take_session_id
           AND mp.policy_version = r.policy_version
           AND mp.block_id = r.block_id
         WHERE ((r.take_session_id = v_prev.id AND r.policy_version = v_policy)
                OR (r.take_session_id = v_next.id
                    AND r.policy_version = v_next_policy))
           AND r.read_version = v_read
           AND r.s IS NOT NULL AND r.w IS NOT NULL
    ), moments AS (
        SELECT r.block_id, r.slide_index, mp.paragraph_id
          FROM public.v4_willfidence_reads r
          LEFT JOIN public.v4_moment_paragraphs mp
            ON mp.take_session_id = r.take_session_id
           AND mp.policy_version = r.policy_version
           AND mp.block_id = r.block_id
         WHERE r.take_session_id = v_prev.id
           AND r.policy_version = v_policy AND r.read_version = v_read
    ), measured AS (
        SELECT m.block_id, m.slide_index, m.paragraph_id,
               (SELECT avg(sw) FROM rated WHERE take_session_id = v_prev.id
                   AND paragraph_id = m.paragraph_id) AS p_before,
               (SELECT avg(sw) FROM rated WHERE take_session_id = v_next.id
                   AND paragraph_id = m.paragraph_id) AS p_after,
               (SELECT avg(sw) FROM rated WHERE take_session_id = v_prev.id
                   AND slide_index = m.slide_index) AS s_before,
               (SELECT avg(sw) FROM rated WHERE take_session_id = v_next.id
                   AND slide_index = m.slide_index) AS s_after
          FROM moments m
    ), leveled AS (
        SELECT *,
               CASE WHEN paragraph_id IS NOT NULL AND p_before IS NOT NULL
                         AND p_after IS NOT NULL THEN 'paragraph'
                    WHEN s_before IS NOT NULL AND s_after IS NOT NULL THEN 'slide'
                    ELSE 'not_measured' END AS level
          FROM measured
    ), valued AS (
        SELECT *,
               CASE level WHEN 'paragraph' THEN p_before
                          WHEN 'slide' THEN s_before END AS before,
               CASE level WHEN 'paragraph' THEN p_after
                          WHEN 'slide' THEN s_after END AS after
          FROM leveled
    )
    SELECT v_prev.id, v_next.id, v_policy, v_read, v.block_id, v.slide_index,
           v.paragraph_id, v.level,
           ARRAY(
               SELECT kind FROM (
                   SELECT 'rewrite'::text AS kind
                    WHERE EXISTS (SELECT 1 FROM jsonb_array_elements(COALESCE(
                              v_frame.frame #> '{verbal_lanes,rewrite_clarity,anchors}',
                              '[]'::jsonb)) a WHERE a ->> 'block_id' = v.block_id)
                   UNION ALL
                   SELECT 'praise'
                    WHERE EXISTS (SELECT 1 FROM jsonb_array_elements(COALESCE(
                              v_frame.frame #> '{verbal_lanes,great_formulation,anchors}',
                              '[]'::jsonb)) a WHERE a ->> 'block_id' = v.block_id)
                   UNION ALL
                   SELECT 'exercise'
                    WHERE EXISTS (SELECT 1 FROM jsonb_array_elements(COALESCE(
                              v_frame.frame -> 'blocks', '[]'::jsonb)) b
                                   WHERE b ->> 'block_id' = v.block_id
                                     AND b -> 'carries_exercise' = 'true'::jsonb)
               ) kinds),
           v.before, v.after, v.after - v.before, 0.05,
           'rise-margin-v0-placeholder',
           CASE WHEN v.after - v.before IS NULL THEN 'not_measured'
                WHEN v.after - v.before > 0.05 THEN 'rose'
                ELSE 'did_not_rise' END,
           v_frame.acquisition_principal_id
      FROM valued v;
    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN jsonb_build_object('outcome', 'computed', 'take_session_id', v_prev.id,
                              'moments', v_count);
END;
$$;

-- ── The door ───────────────────────────────────────────────────────────────
-- Every function keeps its signature, so its grants stand (service_role
-- only); they are re-stated so this file alone shows the door. The new
-- helper is called inside the SECURITY DEFINER functions above and by no
-- one else, so it is granted to no one.
REVOKE ALL ON FUNCTION public.record_take_feedback_policy_v3_shadow_v3(
    TEXT, UUID, UUID, UUID, UUID, INTEGER, TEXT, JSONB, TEXT
) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.v4_frame_policy_v1(uuid)
    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.draw_v4_random_moments_v1(uuid)
    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.record_v4_willfidence_reads_v1(uuid, jsonb)
    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.record_v4_moment_paragraphs_v1(uuid, jsonb)
    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.record_v4_picks_v1(uuid, jsonb)
    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.compute_v4_pick_outcomes_v1(uuid)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.record_take_feedback_policy_v3_shadow_v3(
    TEXT, UUID, UUID, UUID, UUID, INTEGER, TEXT, JSONB, TEXT
) TO service_role;
GRANT EXECUTE ON FUNCTION public.draw_v4_random_moments_v1(uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.record_v4_willfidence_reads_v1(uuid, jsonb) TO service_role;
GRANT EXECUTE ON FUNCTION public.record_v4_moment_paragraphs_v1(uuid, jsonb) TO service_role;
GRANT EXECUTE ON FUNCTION public.record_v4_picks_v1(uuid, jsonb) TO service_role;
GRANT EXECUTE ON FUNCTION public.compute_v4_pick_outcomes_v1(uuid) TO service_role;

COMMIT;
