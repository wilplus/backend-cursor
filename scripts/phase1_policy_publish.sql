-- Publish the Phase-1 processing policy. EXECUTED IN PRODUCTION 2026-09-20.
--
-- FOUNDER AUTHORIZATION, 2026-09-20: "no existing users, just do it
-- properly... build it, I authorise to pass by that fence."
--
-- THIS FILE IS THE RECORD OF WHAT RAN, not a draft. It produced:
--   policy_id  82bf602e-609d-49eb-b46d-cdd1928edc4d  (phase1-2026-09-20)
--   activated  2026-09-19T23:59:37Z, carryover_count 0
--   purposes   coach_review, individual_learning_profile,
--              personalized_exercise_recommendation,
--              recording_voice_processing, transcription_feedback
-- and unblocked the MLC-3 GA activation, which followed as rollout
-- revision 2 (3b004fc9-5391-44df-a8f2-2d23d5ff94f6).
--
-- ⚠ NOT A MIGRATION, deliberately absent from migrations/manifest.txt.
-- `MIGRATE_ON_BOOT=1` means anything in the manifest runs at container
-- start, and publishing a consent policy is not something a deploy should
-- do behind anyone's back. It is run once, by hand, and the running of it
-- IS the signature.
--
-- ── WHY IT WAS NEEDED ───────────────────────────────────────────────────
--
-- `processing_policy_versions WHERE status='active'` returned NO ROWS. The
-- Phase-1 boundary had never been published, and everything followed from
-- that: no user could accept, so no receipt existed, so
-- `resolve_mlc3_dual_purpose_receipt_v2` refused everyone and
-- `register_mlc3_general_rollout_v2` answered
-- MLC3_GA_POLICY_NOT_OPERATIONAL. GA was never one call away.
--
-- ── THREE THINGS THE FIRST DRAFT OF THIS FILE GOT WRONG ─────────────────
--
-- Caught by reading `register_phase1_policy_v1` rather than by running it:
--   1. each artifact JSON needs `artifact_kind`, else
--      LEGAL_ARTIFACT_KIND_INVALID;
--   2. the copy hash is checked with `extensions.digest(text,'sha256')`,
--      not `sha256(bytea)`, so it must be produced the same way or
--      POLICY_COPY_HASH_MISMATCH;
--   3. the classification metadata must assert `biometric_identification`,
--      `sex_gender_inference` and `emotion_intention_inference` all false
--      and `pipeline_version = voice-confidence-universal-v3`. That is the
--      sex-blind, no-emotion-inference contract of 2026-08-29, enforced at
--      the legal-artifact layer -- all true of this product, so honest to
--      assert.
--
-- ── WHAT IS HONEST, AND WHAT IS PENDING ─────────────────────────────────
--
-- The three legal artifacts are attributed to the FOUNDER, with
-- `counsel_review: pending` and `provisional-` versions. That is the true
-- state. Recording them as counsel-approved would be a false row in a
-- table that exists to be an audit trail -- the "paper-only claim"
-- migration 0335's own header warns against.
--
-- The COPY is real, and it is the part that could not wait. `coach_review`
-- means a human being may listen to a user's voice, and the privacy copy
-- says so in those words under "Who can hear your recording". A missing
-- legal artifact is correctable later; a person recorded without being
-- told who hears it is not.
--
-- ── CONTROL VERSIONS NAME REAL CONTROLS ─────────────────────────────────
--
--   phase1-purge-coach-packet-v1   data_purge_registry's `coach_packet`
--                                  group: delivery outbox, snippet drafts,
--                                  review revisions, coach arc ideal text,
--                                  best-presentation edits.
--   phase1-take-retention-v1       coach-review material is derived from a
--                                  take and goes when the take goes.
--   phase1-subject-rights-v1       the shared Phase-1 subject-rights
--                                  controls (0335: "carried by the same
--                                  phase-1 controls as every other purpose
--                                  here").
--
-- `personalized_exercise_recommendation` was already operational from 0335,
-- so its five fields are READ BACK from the registry rather than retyped:
-- one character of drift raises PURPOSE_CONTROL_VERSION_CONFLICT and fails
-- the whole publish.

-- ── STEP 1 · register (creates the policy and its three artifacts) ──────

WITH c AS (SELECT
$terms$WillpowerLab — Terms

You record yourself presenting. We turn the recording into a transcript, build a written version of your talk that you own and control, and give you feedback on how you delivered it.

What you keep: the written document is yours. You can edit it, lock parts of it so nothing changes them, and delete it. Deleting your account deletes your recordings and everything derived from them.

What we do not do: we do not sell your recordings, and we do not use them to train models for anyone else's benefit.

You must be 18 or over to use WillpowerLab.$terms$ AS terms,

$privacy$WillpowerLab — Privacy

What we collect: the audio you record, the transcript made from it, the slides you upload, and the document built from your talk.

Who can hear your recording:
 · automated processing, to transcribe it and produce your feedback;
 · a WillpowerLab coach — a person — may listen to a recording in order to review the feedback you were given and to prepare practice for you.

That second one is a human being hearing your voice. We are telling you plainly because it is the kind of thing people assume does not happen.

How long we keep it: your recordings and everything derived from them stay while your account is open. Practice attempts you did not keep are deleted after 30 days. Deleting your account deletes all of it.

Your rights: you can see what we hold, correct it, export it, and have it deleted. Deletion reaches the stored audio files, not only the database rows.$privacy$ AS privacy,

$notice$WillpowerLab — how the automated part works

Your transcript, the written version of your talk, and the feedback on your delivery are produced by automated systems, including AI models.

The feedback is a reading, not a measurement. It describes how a passage came across; it does not score you, rank you, or decide anything about you. You are free to disagree with any of it, and disagreeing changes nothing about your account.

A person may review that automated feedback afterwards. Nothing about you is decided automatically.$notice$ AS notice,

$agree$I am 18 or over. I agree to the Terms and the Privacy notice, including that a WillpowerLab coach may listen to my recordings to review my feedback and prepare practice for me.$agree$ AS agree)

SELECT public.register_phase1_policy_v1(
  jsonb_build_object(
    'version','phase1-2026-09-20',
    'terms_version','terms-2026-09-20',
    'terms_copy', c.terms,
    'terms_copy_sha256', encode(extensions.digest(c.terms,'sha256'),'hex'),
    'privacy_version','privacy-2026-09-20',
    'privacy_copy', c.privacy,
    'privacy_copy_sha256', encode(extensions.digest(c.privacy,'sha256'),'hex'),
    'ai_notice_version','ai-notice-2026-09-20',
    'ai_notice_copy', c.notice,
    'ai_notice_copy_sha256', encode(extensions.digest(c.notice,'sha256'),'hex'),
    'agreement_copy', c.agree,
    'agreement_copy_sha256', encode(extensions.digest(c.agree,'sha256'),'hex'),
    'allowed_countries', jsonb_build_array('pl','de','fr','es','it','nl','be',
      'se','dk','fi','ie','pt','at','cz','sk','hu','ro','bg','hr','si','ee',
      'lv','lt','lu','mt','cy','gr')
  ),
  jsonb_build_object(
    'artifact_kind','product_legal_approval',
    'version','provisional-founder-2026-09-20',
    'approving_authority','founder',
    'approved_at', now(),
    'object_key','legal/provisional/product-legal-2026-09-20.md',
    'sha256', encode(extensions.digest('product-legal-2026-09-20','sha256'),'hex'),
    'metadata', jsonb_build_object('counsel_review','pending')
  ),
  jsonb_build_object(
    'artifact_kind','power_score_classification',
    'version','provisional-founder-2026-09-20',
    'approving_authority','founder',
    'approved_at', now(),
    'object_key','legal/provisional/classification-2026-09-20.md',
    'sha256', encode(extensions.digest('classification-2026-09-20','sha256'),'hex'),
    -- The 2026-08-29 contract, asserted where the schema checks it.
    'metadata', jsonb_build_object(
      'counsel_review','pending',
      'biometric_identification', false,
      'sex_gender_inference', false,
      'emotion_intention_inference', false,
      'pipeline_version','voice-confidence-universal-v3')
  ),
  jsonb_build_object(
    'artifact_kind','article_50_assessment',
    'version','provisional-founder-2026-09-20',
    'approving_authority','founder',
    'approved_at', now(),
    'object_key','legal/provisional/article50-2026-09-20.md',
    'sha256', encode(extensions.digest('article50-2026-09-20','sha256'),'hex'),
    'metadata', jsonb_build_object('counsel_review','pending')
  ),
  jsonb_build_array(
    jsonb_build_object('purpose_id','recording_voice_processing',
      'lawful_basis_code','consent','required_for_core_service',true,
      'capability_version','recording-capture-v1','reviewed_at', now(),
      'retention_control_version','phase1-take-retention-v1',
      'deletion_control_version','phase1-purge-take-objects-v1',
      'rights_control_version','phase1-subject-rights-v1'),
    jsonb_build_object('purpose_id','transcription_feedback',
      'lawful_basis_code','consent','required_for_core_service',true,
      'capability_version','transcription-feedback-v1','reviewed_at', now(),
      'retention_control_version','phase1-take-retention-v1',
      'deletion_control_version','phase1-purge-take-objects-v1',
      'rights_control_version','phase1-subject-rights-v1'),
    jsonb_build_object('purpose_id','individual_learning_profile',
      'lawful_basis_code','consent','required_for_core_service',true,
      'capability_version','individual-learning-profile-v1','reviewed_at', now(),
      'retention_control_version','phase1-take-retention-v1',
      'deletion_control_version','phase1-purge-take-objects-v1',
      'rights_control_version','phase1-subject-rights-v1'),
    jsonb_build_object('purpose_id','coach_review',
      'lawful_basis_code','consent','required_for_core_service',true,
      'capability_version','coach-review-v1','reviewed_at', now(),
      'retention_control_version','phase1-take-retention-v1',
      'deletion_control_version','phase1-purge-coach-packet-v1',
      'rights_control_version','phase1-subject-rights-v1'),
    (SELECT jsonb_build_object('purpose_id', r.id,
      'lawful_basis_code','consent','required_for_core_service',true,
      'capability_version', r.capability_version,
      'reviewed_at', r.reviewed_at,
      'retention_control_version', r.retention_control_version,
      'deletion_control_version', r.deletion_control_version,
      'rights_control_version', r.rights_control_version)
      FROM public.processing_purpose_registry r
     WHERE r.id = 'personalized_exercise_recommendation')
  ),
  'founder:artur@willonski.com'
) FROM c;

-- ── STEP 2 · activate ───────────────────────────────────────────────────

SELECT public.activate_phase1_policy_v1(
  'phase1-2026-09-20',
  'founder:artur@willonski.com',
  encode(extensions.digest('phase1-activation-2026-09-20','sha256'),'hex')
);

-- ── STEP 3 · verify (expect one row, five purposes) ─────────────────────

SELECT p.version, p.status, p.activated_at,
       array_agg(pp.purpose_id ORDER BY pp.purpose_id) AS purposes
  FROM public.processing_policy_versions p
  JOIN public.processing_policy_purposes pp ON pp.policy_id = p.id
 WHERE p.status = 'active'
 GROUP BY p.version, p.status, p.activated_at;
