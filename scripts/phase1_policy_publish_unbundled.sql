-- Republish the Phase-1 processing policy WITHOUT service-conditional
-- bundled consent. P11. NOT YET RUN.
--
-- ⚠ THE COPY BELOW IS HELD FOR FOUNDER SIGN-OFF. Three of the four documents
-- change wording, because the policy they describe changes. Nothing here runs
-- on merge; this file is deliberately absent from migrations/manifest.txt for
-- the same reason the 2026-09-20 script is. Publishing a consent policy is not
-- something a deploy should do behind anyone's back. It is run once, by hand,
-- and the running of it IS the signature.
--
-- ── WHAT IS WRONG WITH WHAT IS LIVE ─────────────────────────────────────
--
-- scripts/phase1_policy_publish.sql ran in production on 2026-09-20 and
-- published all five purposes with lawful_basis_code 'consent' AND
-- required_for_core_service TRUE — including coach_review,
-- individual_learning_profile and personalized_exercise_recommendation. The
-- agreement copy bundles them into a single tick.
--
-- legal/phase1-2026.1/01-product-legal-approval §3 assesses that exact
-- structure as invalid under Art 4(11) and Art 7(4) with Recital 43, and §6
-- states that those three purposes were held out of v1 for this reason. §3
-- proposes Art 6(1)(b) contract — not consent — for operations 1-6.
--
-- Zero non-founder users have accepted. Fixing it now costs nothing.
--
-- ── WHAT THIS PUBLISHES ─────────────────────────────────────────────────
--
--   recording_voice_processing   contract   required
--   transcription_feedback       contract   required
--
-- and nothing else, which is doc 01 §3's operations 1-6 and §6's "v1 carries
-- operations 1-7". Operation 7 (security and abuse logging, 6(1)(f)) is not a
-- registry purpose and needs no row. No optional purpose is present, so no
-- optional purpose can be a condition of service — the corollary §3 says must
-- hold or the contract basis fails.
--
-- ══════════════════════════════════════════════════════════════════════════
-- ⚠ READ THIS BEFORE RUNNING IT. PUBLISHING THIS TAKES MLC-3 DARK.
-- ══════════════════════════════════════════════════════════════════════════
--
-- P11 asked me to report any place the determination and the schema cannot
-- both be satisfied rather than pick one. This is that place.
--
-- `resolve_mlc3_dual_purpose_receipt_v2` (add_mlc3_general_user_service_d4,
-- lines 603-622) gates the whole MLC-3 general-user service on the receipt
-- carrying BOTH `personalized_exercise_recommendation` AND `coach_review`:
--
--     AND NOT EXISTS (
--         SELECT 1 FROM (VALUES
--             ('personalized_exercise_recommendation'::TEXT),
--             ('coach_review'::TEXT)
--         ) required(purpose_id)
--        WHERE NOT EXISTS ( ...receipt_purposes rp... ) )
--
-- And `accept_phase1_processing_authorization_v1` writes receipt purpose rows
-- only `WHERE pp.required_for_core_service` — still true at current main
-- (add_phase1_processing_boundary line 692; enable_practice_phase1_purpose
-- line 152 kept it). Doc 01 §6 predicted exactly this.
--
-- Put together: the ONLY way MLC-3 works today is if those two purposes are
-- marked required — which is the bundling doc 01 calls invalid. The unlawful
-- structure is not a slip in the publish script. The exercise service depends
-- on it.
--
-- So publishing this file, on its own, means:
--   * recording, transcription, Ideal Text and Feedback keep working, on the
--     contract basis, lawfully;                                    [F1 SAFE]
--   * coach delivery is refused — issue_phase1_provider_permit_v1 maps
--     operation_kind 'coach_delivery' to purpose 'coach_review', which is no
--     longer in the receipt;
--   * the MLC-3 general-user service refuses every principal, because the
--     dual-purpose receipt can never resolve.
--
-- Doc 01 §6 names this cost in terms — "under `enforce`, coach review and
-- practice cannot run until v1.1" — and says it is the founder's call, not
-- counsel's. It is still the founder's call. What has changed since §6 was
-- written is that MLC-3 GA now sits behind it too.
--
-- ── THE SCHEMA CHANGE THAT WOULD LET BOTH BE TRUE ───────────────────────
--
-- P11 step 3 said: propose it rather than marking things required to work
-- around it. Proposed, not built, because it changes how consent is recorded
-- for real people and deserves its own review:
--
--   accept_phase1_processing_authorization_v2(..., p_optional_purposes TEXT[])
--     — a NEW function beside v1, never a replacement (the signature differs,
--       and dropping a live consent writer is not something this repo does);
--     — writes receipt purpose rows for every required purpose, as today,
--       PLUS each optional purpose the caller names;
--     — raises if a named purpose is not in the policy, or IS required, so
--       the array can only ever record a real, separable choice;
--     — the acceptance screen sends only what the person actually ticked.
--
-- With that in place, coach_review and personalized_exercise_recommendation
-- return to the policy as `required_for_core_service FALSE` with their own
-- consent, the dual-purpose gate resolves for people who opted in, and
-- someone who declines coach review can still record. That is the v1.1 doc 01
-- §6 describes. This file is its prerequisite, not its replacement.
--
-- ── THE RULES THE 2026-09-20 SCRIPT LEARNED THE HARD WAY ────────────────
--
--   1. every artifact JSON needs `artifact_kind`, else
--      LEGAL_ARTIFACT_KIND_INVALID;
--   2. the copy hash is `extensions.digest(text,'sha256')`, not
--      `sha256(bytea)`, or POLICY_COPY_HASH_MISMATCH;
--   3. the classification metadata must assert `biometric_identification`,
--      `sex_gender_inference` and `emotion_intention_inference` all false and
--      `pipeline_version = voice-confidence-universal-v3`.
--
-- The three legal artifacts stay attributed to the FOUNDER with
-- `counsel_review: pending` and `provisional-` versions, because that is
-- still the true state. Recording them as counsel-approved would be the
-- paper-only claim this boundary exists to prevent.
--
-- The copy below is mirrored byte-for-byte into
-- legal/phase1-2026.1/copy/*-unbundled.txt so the files and the published
-- bytes agree. They did not agree before: agreement-1.0.txt on disk already
-- says a coach is asked for separately, while the bytes published on 09-20
-- bundle it into the tick.

-- ── STEP 1 · register ───────────────────────────────────────────────────

WITH c AS (SELECT
$terms$WillpowerLab — Terms

You record yourself presenting. We turn the recording into a transcript, build a written version of your talk that you own and control, and give you feedback on how you delivered it.

What you keep: the written document is yours. You can edit it, lock parts of it so nothing changes them, and delete it. Deleting your account deletes your recordings and everything derived from them.

What we do not do: we do not sell your recordings, and we do not use them to train models for anyone else's benefit.

You must be 18 or over to use WillpowerLab.$terms$ AS terms,

$privacy$WillpowerLab — Privacy

What we collect: the audio you record, the transcript made from it, the slides you upload, and the document built from your talk.

Who can hear your recording: automated processing only, to transcribe it and produce your feedback. No person at WillpowerLab listens to your recordings as part of the service.

If we ever offer human coach review, we will ask you for that separately, and you will be able to say no and carry on using everything else.

How long we keep it: your recordings and everything derived from them stay while your account is open. Practice attempts you did not keep are deleted after 30 days. Deleting your account deletes all of it.

Your rights: you can see what we hold, correct it, export it, and have it deleted. Deletion reaches the stored audio files, not only the database rows.$privacy$ AS privacy,

$notice$WillpowerLab — how the automated part works

Your transcript, the written version of your talk, and the feedback on your delivery are produced by automated systems, including AI models.

The feedback is a reading, not a measurement. It describes how a passage came across; it does not score you, rank you, or decide anything about you. You are free to disagree with any of it, and disagreeing changes nothing about your account.

Nothing about you is decided automatically.$notice$ AS notice,

$agree$I am 18 or over. I agree to the Terms and the Privacy notice.$agree$ AS agree)

SELECT public.register_phase1_policy_v1(
  jsonb_build_object(
    'version','phase1-2026-09-23',
    'terms_version','terms-2026-09-23',
    'terms_copy', c.terms,
    'terms_copy_sha256', encode(extensions.digest(c.terms,'sha256'),'hex'),
    'privacy_version','privacy-2026-09-23',
    'privacy_copy', c.privacy,
    'privacy_copy_sha256', encode(extensions.digest(c.privacy,'sha256'),'hex'),
    'ai_notice_version','ai-notice-2026-09-23',
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
    'version','provisional-founder-2026-09-23',
    'approving_authority','founder:artur@willonski.com',
    'approved_at', now(),
    'object_key','legal/phase1-2026.1/01-product-legal-approval-v1.0.pdf',
    'sha256', encode(extensions.digest('provisional-legal-2026-09-23','sha256'),'hex'),
    'metadata', jsonb_build_object('counsel_review','pending',
      'unbundled','true','supersedes','provisional-founder-2026-09-20')),
  jsonb_build_object(
    'artifact_kind','power_score_classification',
    'version','provisional-founder-2026-09-23',
    'approving_authority','founder:artur@willonski.com',
    'approved_at', now(),
    'object_key','phase1-2026.1/legal/power-score-classification-v1.0.pdf',
    'sha256', encode(extensions.digest('provisional-power-2026-09-23','sha256'),'hex'),
    'metadata', jsonb_build_object(
      'counsel_review','pending',
      'biometric_identification', false,
      'sex_gender_inference', false,
      'emotion_intention_inference', false,
      'pipeline_version','voice-confidence-universal-v3')),
  jsonb_build_object(
    'artifact_kind','article_50_assessment',
    'version','provisional-founder-2026-09-23',
    'approving_authority','founder:artur@willonski.com',
    'approved_at', now(),
    'object_key','phase1-2026.1/legal/article-50-assessment-v1.0.pdf',
    'sha256', encode(extensions.digest('provisional-article50-2026-09-23','sha256'),'hex'),
    'metadata', jsonb_build_object('counsel_review','pending')),
  jsonb_build_array(
    -- Doc 01 §3 operations 1, 5 and half of 6. Contract, not consent:
    -- capturing and storing the recording IS the service the user asked for.
    -- The five control versions are READ BACK from the registry rather than
    -- retyped — one character of drift raises PURPOSE_CONTROL_VERSION_CONFLICT
    -- and fails the whole publish, which is the point.
    (SELECT jsonb_build_object('purpose_id', r.id,
      'lawful_basis_code','contract','required_for_core_service',true,
      'capability_version', r.capability_version,
      'reviewed_at', r.reviewed_at,
      'retention_control_version', r.retention_control_version,
      'deletion_control_version', r.deletion_control_version,
      'rights_control_version', r.rights_control_version)
      FROM public.processing_purpose_registry r
     WHERE r.id = 'recording_voice_processing'),
    -- Doc 01 §3 operations 2, 3, 4 and the rest of 6.
    (SELECT jsonb_build_object('purpose_id', r.id,
      'lawful_basis_code','contract','required_for_core_service',true,
      'capability_version', r.capability_version,
      'reviewed_at', r.reviewed_at,
      'retention_control_version', r.retention_control_version,
      'deletion_control_version', r.deletion_control_version,
      'rights_control_version', r.rights_control_version)
      FROM public.processing_purpose_registry r
     WHERE r.id = 'transcription_feedback')
    -- coach_review, individual_learning_profile and
    -- personalized_exercise_recommendation are ABSENT, per doc 01 §6. They
    -- return in v1.1, optional, once a receipt can record an optional
    -- purpose. See the header.
  ),
  'founder:artur@willonski.com'
) FROM c;

-- ── STEP 2 · activate ───────────────────────────────────────────────────
--
-- This retires phase1-2026-09-20 and writes carryovers for any job in
-- flight, which activate_phase1_policy_v1 does on its own.

SELECT public.activate_phase1_policy_v1(
  'phase1-2026-09-23',
  'founder:artur@willonski.com',
  encode(extensions.digest('phase1-activation-2026-09-23','sha256'),'hex')
);

-- ── STEP 3 · verify (expect one row, two purposes, both contract) ───────

SELECT p.version, p.status, p.activated_at,
       array_agg(pp.purpose_id ORDER BY pp.purpose_id) AS purposes,
       array_agg(DISTINCT pp.lawful_basis_code) AS bases,
       bool_and(pp.required_for_core_service) AS all_required
  FROM public.processing_policy_versions p
  JOIN public.processing_policy_purposes pp ON pp.policy_id = p.id
 WHERE p.status = 'active'
 GROUP BY p.version, p.status, p.activated_at;

-- ── STEP 4 · verify no optional purpose is a condition of service ───────
--
-- Expect zero rows. A row here means the thing this file exists to prevent.

SELECT pp.purpose_id, pp.lawful_basis_code, pp.required_for_core_service
  FROM public.processing_policy_versions p
  JOIN public.processing_policy_purposes pp ON pp.policy_id = p.id
 WHERE p.status = 'active'
   AND pp.purpose_id IN ('coach_review', 'individual_learning_profile',
                         'personalized_exercise_recommendation');
