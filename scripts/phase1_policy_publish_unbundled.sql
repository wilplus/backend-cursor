-- Republish the Phase-1 processing policy WITHOUT service-conditional
-- bundled consent. P11. NOT YET RUN.
--
-- ⚠ THE COPY BELOW IS HELD FOR FOUNDER SIGN-OFF. Nothing here runs on merge;
-- this file is deliberately absent from migrations/manifest.txt for the same
-- reason the 2026-09-20 script is. Publishing a consent policy is not
-- something a deploy should do behind anyone's back. It is run once, by hand,
-- and the running of it IS the signature.
--
-- ── REWRITTEN 2026-09-23 AFTER THE FOUNDER'S COACH-REVIEW RULING ────────
--
-- The first draft of this file removed coach_review from the policy entirely
-- and published two purposes on contract. That draft is superseded. The
-- founder ruled, 2026-09-23:
--
--   "Coach review is core to the product. A user who refuses to allow a human
--    to listen to their recordings cannot use WillpowerLab. This reverses the
--    assumption in doc 01 §3 and §6, which placed coach_review on consent and
--    held it out of v1 because it was treated as optional."
--
-- and, on the practice/exercise step, the same day:
--
--   "you can always leave the app and not do it, you can skip it; but it is
--    advisable for the whole experience, just like you can skip the tap to
--    choose rooting phrase or corrections etc."
--
-- Those two rulings settle the two open purposes in OPPOSITE directions, and
-- the running system agrees with both (see "WHAT THE CODE ALREADY SHOWS").
--
-- ── WHAT IS WRONG WITH WHAT IS LIVE ─────────────────────────────────────
--
-- scripts/phase1_policy_publish.sql ran in production on 2026-09-20 and
-- published ALL FIVE purposes with lawful_basis_code 'consent' AND
-- required_for_core_service TRUE. One tick, five purposes, every one of them
-- mandatory, all on consent.
--
-- The COPY is not the problem — it is honest. The live privacy notice says
-- plainly that "a WillpowerLab coach — a person — may listen", and the live
-- agreement tick names coach listening in the tick itself. Nothing published
-- on 09-20 misleads anyone about who hears the recording.
--
-- The LEGAL MACHINERY under that honest copy is the problem. Consent that is
-- a condition of service, for purposes that are not necessary to the service,
-- is not freely given (Art 4(11), Art 7(4), Recital 43). doc 01 §3 assesses
-- that exact structure as invalid.
--
-- Zero non-founder users have accepted. Fixing it now costs nothing.
--
-- ── WHAT THIS PUBLISHES ─────────────────────────────────────────────────
--
--   recording_voice_processing            contract   required
--   transcription_feedback                contract   required
--   coach_review                          contract   required
--   personalized_exercise_recommendation  consent    OPTIONAL
--
--   individual_learning_profile           ABSENT
--
-- Moving the three mandatory purposes from 'consent' to 'contract' dissolves
-- the Art 7(4) problem at the root: consent is no longer the basis for
-- anything compulsory, so there is no compelled consent left to be invalid.
-- The one genuinely separable purpose keeps consent — real consent, refusable
-- without losing the service, which is the only kind worth recording.
--
-- individual_learning_profile stays ABSENT. No ruling covers it, no route
-- reads it, and nothing authorizes it. A purpose nobody has justified does
-- not get published because it happens to be in the registry.
--
-- The Art 9 element stays separate and is NOT folded into coach_review's
-- basis, per the ruling's own third clause.
--
-- ── WHAT THE CODE ALREADY SHOWS (read from main, 2026-09-23) ────────────
--
-- coach_review is load-bearing. routes/v2/coach.py reads every take from the
-- queue and writes two lanes: a user-facing draft (note, tag, surfaced,
-- when_context, examples, transcript_corrected, say-it-stronger, star-text,
-- reference) delivered by publish-analysis, and a blind lane
-- (confidence-label, star-verdict, ab-verdict, the word→slide ground truth)
-- that never surfaces. Remove coach_review and the delivery channel, the
-- corrected transcript and the segmentation ground truth go with it.
--
-- personalized_exercise_recommendation is not. FIVE routes are gated by
-- @operational_purpose_disabled("personalized_exercise_recommendation") and
-- every one of them returns 410 PURPOSE_NOT_OPERATIONAL today:
--
--   POST /coach/sessions/{sid}/snippets/{id}/confident-voice-practice
--   POST /user/snippets/{id}/confidence-practice
--   GET  /user/confidence-practice/{id}
--   POST /user/confidence-practice/{id}/attempts
--   POST /user/confidence-practice/{id}/complete
--
-- The record → transcript → Ideal Text → Feedback loop runs to completion
-- with all five closed. That is the EDPB necessity test answered by the
-- running system rather than by argument: a purpose the service demonstrably
-- operates without cannot be necessary for the performance of the contract.
-- CLAUDE.md states the same rule from the product side — "the loop never
-- waits for a coach or exercise."
--
-- ══════════════════════════════════════════════════════════════════════════
-- ⚠ ORDERING. DO NOT RUN THIS BEFORE accept_v2 IS DEPLOYED.
-- ══════════════════════════════════════════════════════════════════════════
--
-- accept_phase1_processing_authorization_v1 writes receipt purpose rows only
-- `WHERE pp.required_for_core_service`. Under v1, an OPTIONAL purpose can
-- never land in a receipt at all.
--
-- So if this file is published while v1 is still the only acceptance writer:
--
--   * recording, transcription, Ideal Text, Feedback and coach delivery all
--     keep working — the three required purposes are written as today; and
--   * personalized_exercise_recommendation can never be opted into by
--     anybody, so resolve_mlc3_dual_purpose_receipt_v2 never resolves and the
--     MLC-3 general-user service stays dark for every principal.
--
-- That is not a catastrophe — it is the state MLC-3 is already in, since all
-- five practice routes return 410 regardless. But it is a silent one, and it
-- would look like a regression rather than a pending switch.
--
-- The prerequisite is accept_phase1_processing_authorization_v2
-- (migrations/a_receipt_can_record_an_optional_yes.sql), which takes
-- p_optional_purposes TEXT[] and writes
--   WHERE pp.policy_id = policy.id
--     AND (pp.required_for_core_service OR pp.purpose_id = ANY(chosen))
-- refusing any named purpose that is not in the policy or that IS required.
--
-- RUN ORDER, all three before the registry row is flipped:
--   1. deploy accept_v2 (the migration merges, so it runs on boot);
--   2. the acceptance screen sends the optional array it actually ticked;
--   3. run THIS file by hand.
-- Only then is flipping processing_purpose_registry.operational for
-- personalized_exercise_recommendation a meaningful switch.
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
-- ══════════════════════════════════════════════════════════════════════════
-- ⚠ TODO — FOUR COPY DECISIONS THE FOUNDER MUST SIGN OFF BEFORE THIS RUNS.
-- ══════════════════════════════════════════════════════════════════════════
--
-- The copy below starts from the LIVE 2026-09-20 bytes, not from the
-- superseded draft — the live wording on coach listening is honest and well
-- made, and it is reinstated verbatim. Four deltas, each forced by a ruling:
--
--   TODO-1  TERMS gain a coach-review paragraph. The ruling says "the Terms
--           must describe it". Today the Privacy notice and the tick carry the
--           whole disclosure and the Terms are silent on it.
--   TODO-2  TERMS state the plan distinction: a plan with no delivered coach
--           reviews does NOT mean nobody listens. The live Terms page tiers
--           "coach reviews" as a paid feature, which invites exactly that
--           misreading now that listening is universal and compulsory.
--   TODO-3  PRIVACY gains one sentence that coach review is not optional, and
--           one paragraph that practice IS optional and skippable.
--   TODO-4  THE REQUIRED TICK drops "and prepare practice for me". A
--           mandatory tick must not carry an optional purpose — that is the
--           bundling this file exists to remove, in miniature. The optional
--           purpose needs its own separate tick; its string is drafted below
--           as OPTIONAL_TICK and has no home in register_phase1_policy_v1's
--           single agreement_copy, so the acceptance screen must carry it and
--           send the purpose in p_optional_purposes.
--
-- Until these four are signed off, this file does not run. The copy below is
-- a DRAFT for that decision, not an approved string.
--
-- The copy is mirrored byte-for-byte into
-- legal/phase1-2026.1/copy/*-unbundled-2026-09-23.txt so the files and the
-- published bytes agree.

-- ── STEP 1 · register ───────────────────────────────────────────────────

WITH c AS (SELECT
$terms$WillpowerLab — Terms

You record yourself presenting. We turn the recording into a transcript, build a written version of your talk that you own and control, and give you feedback on how you delivered it.

Coach review is part of the service. A WillpowerLab coach — a person — listens to recordings in order to check and correct the feedback you were given. This is not something you can switch off: if you are not willing to have a person hear your recordings, WillpowerLab is not for you. How many coach reviews are sent back to you depends on your plan. A plan that includes no coach reviews does not mean nobody listens.

Practice is optional. After feedback you may be offered a short exercise and the chance to re-record a fragment. You can skip it, and skipping it changes nothing else about your account.

What you keep: the written document is yours. You can edit it, lock parts of it so nothing changes them, and delete it. Deleting your account deletes your recordings and everything derived from them.

What we do not do: we do not sell your recordings, and we do not use them to train models for anyone else's benefit.

You must be 18 or over to use WillpowerLab.$terms$ AS terms,

$privacy$WillpowerLab — Privacy

What we collect: the audio you record, the transcript made from it, the slides you upload, and the document built from your talk.

Who can hear your recording:
 · automated processing, to transcribe it and produce your feedback;
 · a WillpowerLab coach — a person — may listen to a recording in order to review the feedback you were given.

That second one is a human being hearing your voice. We are telling you plainly because it is the kind of thing people assume does not happen. It is part of the service, not an extra: agreeing to the Terms is agreeing to this, and there is no version of WillpowerLab without it.

Practice is separate, and optional. If you turn it on, we use your recording to choose a short exercise that fits it and to keep the fragment you re-record. If you leave it off, nothing is processed for practice and everything else works exactly the same. You can change your mind at any time.

How long we keep it: your recordings and everything derived from them stay while your account is open. Practice attempts you did not keep are deleted after 30 days. Deleting your account deletes all of it.

Your rights: you can see what we hold, correct it, export it, and have it deleted. Deletion reaches the stored audio files, not only the database rows.$privacy$ AS privacy,

$notice$WillpowerLab — how the automated part works

Your transcript, the written version of your talk, and the feedback on your delivery are produced by automated systems, including AI models.

The feedback is a reading, not a measurement. It describes how a passage came across; it does not score you, rank you, or decide anything about you. You are free to disagree with any of it, and disagreeing changes nothing about your account.

A person may review that automated feedback afterwards. Nothing about you is decided automatically.$notice$ AS notice,

$agree$I am 18 or over. I agree to the Terms and the Privacy notice, including that a WillpowerLab coach may listen to my recordings to review my feedback.$agree$ AS agree)

-- TODO-4 · the SEPARATE optional tick. Not part of agreement_copy, which is
-- the mandatory one. The acceptance screen renders this on its own control
-- and, when ticked, sends 'personalized_exercise_recommendation' in
-- accept_phase1_processing_authorization_v2's p_optional_purposes. Unticked
-- sends an empty array and the person keeps the whole service.
--
--   OPTIONAL_TICK:
--   "Optional — practice. Use my recordings to choose short exercises that
--    fit them, and keep the fragments I re-record. I can turn this off at any
--    time and keep using everything else."

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
    'object_key','legal/phase1-2026.1/01-product-legal-approval-v1.1.pdf',
    'sha256', encode(extensions.digest('provisional-legal-2026-09-23','sha256'),'hex'),
    'metadata', jsonb_build_object('counsel_review','pending',
      'unbundled','true','supersedes','provisional-founder-2026-09-20',
      'coach_review_basis','contract',
      'founder_ruling','2026-09-23 coach review is core to the product')),
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
    -- ── REQUIRED, CONTRACT. Art 6(1)(b). ──────────────────────────────
    -- The five control versions are READ BACK from the registry rather than
    -- retyped — one character of drift raises PURPOSE_CONTROL_VERSION_CONFLICT
    -- and fails the whole publish, which is the point.
    --
    -- doc 01 §3 operations 1, 5 and half of 6. Capturing and storing the
    -- recording IS the service the user asked for.
    (SELECT jsonb_build_object('purpose_id', r.id,
      'lawful_basis_code','contract','required_for_core_service',true,
      'capability_version', r.capability_version,
      'reviewed_at', r.reviewed_at,
      'retention_control_version', r.retention_control_version,
      'deletion_control_version', r.deletion_control_version,
      'rights_control_version', r.rights_control_version)
      FROM public.processing_purpose_registry r
     WHERE r.id = 'recording_voice_processing'),
    -- doc 01 §3 operations 2, 3, 4 and the rest of 6.
    (SELECT jsonb_build_object('purpose_id', r.id,
      'lawful_basis_code','contract','required_for_core_service',true,
      'capability_version', r.capability_version,
      'reviewed_at', r.reviewed_at,
      'retention_control_version', r.retention_control_version,
      'deletion_control_version', r.deletion_control_version,
      'rights_control_version', r.rights_control_version)
      FROM public.processing_purpose_registry r
     WHERE r.id = 'transcription_feedback'),
    -- Founder ruling 2026-09-23. Refuse this and there is no service to
    -- give you: no delivery channel, no corrected transcript, no word→slide
    -- ground truth. doc 01 §3 row 8 and §6 are superseded by that ruling and
    -- doc 01 must reach v1.1 before counsel signs.
    (SELECT jsonb_build_object('purpose_id', r.id,
      'lawful_basis_code','contract','required_for_core_service',true,
      'capability_version', r.capability_version,
      'reviewed_at', r.reviewed_at,
      'retention_control_version', r.retention_control_version,
      'deletion_control_version', r.deletion_control_version,
      'rights_control_version', r.rights_control_version)
      FROM public.processing_purpose_registry r
     WHERE r.id = 'coach_review'),
    -- ── OPTIONAL, CONSENT. Art 6(1)(a). ───────────────────────────────
    -- Founder ruling 2026-09-23: skippable, "just like you can skip the tap
    -- to choose rooting phrase or corrections". Five routes return 410 today
    -- and the loop completes without them. Refusing it must cost the person
    -- nothing but practice — that is what makes the consent free, and it is
    -- the corollary doc 01 §3 says must hold or the contract basis fails for
    -- everything else.
    (SELECT jsonb_build_object('purpose_id', r.id,
      'lawful_basis_code','consent','required_for_core_service',false,
      'capability_version', r.capability_version,
      'reviewed_at', r.reviewed_at,
      'retention_control_version', r.retention_control_version,
      'deletion_control_version', r.deletion_control_version,
      'rights_control_version', r.rights_control_version)
      FROM public.processing_purpose_registry r
     WHERE r.id = 'personalized_exercise_recommendation')
    -- individual_learning_profile is ABSENT. No ruling covers it and no route
    -- reads it. It returns only when something actually needs it and a
    -- lawful basis has been decided for it on its own merits.
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

-- ── STEP 3 · verify the shape ───────────────────────────────────────────
--
-- Expect ONE row:
--   purposes  = {coach_review, personalized_exercise_recommendation,
--                recording_voice_processing, transcription_feedback}
--   required  = 3
--   optional  = 1
--   bases     = {consent, contract}

SELECT p.version, p.status, p.activated_at,
       array_agg(pp.purpose_id ORDER BY pp.purpose_id) AS purposes,
       count(*) FILTER (WHERE pp.required_for_core_service) AS required,
       count(*) FILTER (WHERE NOT pp.required_for_core_service) AS optional,
       array_agg(DISTINCT pp.lawful_basis_code) AS bases
  FROM public.processing_policy_versions p
  JOIN public.processing_policy_purposes pp ON pp.policy_id = p.id
 WHERE p.status = 'active'
 GROUP BY p.version, p.status, p.activated_at;

-- ── STEP 4 · verify no CONSENT purpose is a condition of service ────────
--
-- Expect ZERO rows. This is the check the whole file exists for: a row here
-- is compelled consent, which is the Art 7(4) defect. It is deliberately
-- written against the PROPERTY, not against a hard-coded purpose list, so it
-- keeps working when purposes are added later.

SELECT pp.purpose_id, pp.lawful_basis_code, pp.required_for_core_service
  FROM public.processing_policy_versions p
  JOIN public.processing_policy_purposes pp ON pp.policy_id = p.id
 WHERE p.status = 'active'
   AND pp.lawful_basis_code = 'consent'
   AND pp.required_for_core_service;

-- ── STEP 5 · verify the optional purpose is genuinely refusable ─────────
--
-- Expect exactly ONE row: personalized_exercise_recommendation, consent,
-- required_for_core_service = false. If this returns zero rows the optional
-- lane silently vanished, and the acceptance screen would have nothing to
-- offer — which is how an "optional" purpose quietly becomes mandatory.

SELECT pp.purpose_id, pp.lawful_basis_code, pp.required_for_core_service
  FROM public.processing_policy_versions p
  JOIN public.processing_policy_purposes pp ON pp.policy_id = p.id
 WHERE p.status = 'active'
   AND NOT pp.required_for_core_service;

-- ── STEP 6 · verify the acceptance writer can actually record it ────────
--
-- Expect ONE row. accept_phase1_processing_authorization_v2 must exist before
-- this policy is any use: under v1 an optional purpose can never reach a
-- receipt. Zero rows here means STOP — publish nothing until accept_v2 ships.

SELECT p.proname,
       pg_get_function_identity_arguments(p.oid) AS signature
  FROM pg_proc p
  JOIN pg_namespace n ON n.oid = p.pronamespace
 WHERE n.nspname = 'public'
   AND p.proname = 'accept_phase1_processing_authorization_v2';
