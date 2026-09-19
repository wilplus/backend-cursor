-- Publish the Phase-1 processing policy, so users can accept it.
--
-- FOUNDER AUTHORIZATION, 2026-09-20: "no existing users, just do it
-- properly... build it, I authorise to pass by that fence."
--
-- ⚠ NOT A MIGRATION. This file is deliberately absent from
-- migrations/manifest.txt. `MIGRATE_ON_BOOT=1` means anything in the
-- manifest runs at container start, and publishing a consent policy is not
-- something a deploy should do behind anyone's back. You run this, once,
-- by hand, and the running of it IS the signature.
--
-- ── WHY THIS FILE EXISTS ────────────────────────────────────────────────
--
-- `SELECT ... FROM processing_policy_versions WHERE status='active'`
-- returns NO ROWS. The Phase-1 boundary has never been published, and
-- everything downstream follows from that one fact:
--
--   * no user can accept anything, so no authorization receipt exists;
--   * `resolve_mlc3_dual_purpose_receipt_v2` needs a receipt carrying BOTH
--     `personalized_exercise_recommendation` and `coach_review`, so it
--     raises MLC3_DUAL_PURPOSE_AUTHORITY_REQUIRED for everyone;
--   * `register_mlc3_general_rollout_v2` needs an active policy carrying
--     both purposes operational, so it raises
--     MLC3_GA_POLICY_NOT_OPERATIONAL -- which is exactly what production
--     answered at 01:20 on 2026-09-20.
--
-- So the GA activation was never one call away. This is the missing step,
-- and the MLC-3 activation runs AFTER it
-- (docs/MLC3-GA-ACTIVATION-RUNBOOK.md).
--
-- ── WHAT IS HONEST HERE, AND WHAT IS PENDING ────────────────────────────
--
-- The three legal artifacts are attributed to the FOUNDER, with
-- `counsel_review: pending` in their metadata and `provisional-` in their
-- version strings. That is the true state: the founder has approved the
-- product's processing description and counsel has not yet reviewed it.
-- Attributing them to counsel would have been a false record in a table
-- whose entire purpose is to be an audit trail, and the founder's own
-- migration 0335 names that failure mode: "Declaring them before they
-- existed would have been the paper-only claim this whole boundary exists
-- to prevent."
--
-- The COPY below is real, and it is the part that matters before anyone
-- records. `coach_review` means a human being may listen to a user's
-- voice. The privacy copy says so in those words. Everything else can be
-- corrected with counsel later; a person being recorded and not told who
-- hears it cannot be corrected later.
--
-- ── CONTROL VERSIONS: WHAT EACH ONE NAMES ───────────────────────────────
--
--   phase1-take-retention-v1        the take's own lifecycle; coach-review
--                                   material is derived from a take and
--                                   goes when it goes.
--   phase1-purge-coach-packet-v1    services/data_purge_registry.py's
--                                   `coach_packet` group -- five real
--                                   dependencies: the delivery outbox,
--                                   snippet drafts, review revisions,
--                                   coach arc ideal text, best-presentation
--                                   edits.
--   phase1-subject-rights-v1        the shared Phase-1 subject-rights
--                                   controls, as 0335 put it: "carried by
--                                   the same phase-1 controls as every
--                                   other purpose here".
--
-- `personalized_exercise_recommendation` is ALREADY operational (0335), and
-- `register_phase1_policy_v1` raises PURPOSE_CONTROL_VERSION_CONFLICT if a
-- single one of its five fields differs. So its row is read back OUT of the
-- registry rather than retyped -- a transcription error there would fail
-- the whole publish for no reason.
--
-- ── AFTER THIS ──────────────────────────────────────────────────────────
--
--   1. verify (bottom of this file)
--   2. accept the policy in the app (Phase1AcceptanceFlow) so your own
--      principal has a receipt carrying all five purposes
--   3. run docs/MLC3-GA-ACTIVATION-RUNBOOK.md call 2 -- call 1 is already
--      recorded (decision a63cc611-1169-4979-83c4-d43cefd68fc7)

BEGIN;

SELECT public.register_phase1_policy_v1(
    -- p_policy
    jsonb_build_object(
        'version', 'phase1-2026-09-20',
        'terms_version', 'terms-2026-09-20',
        'terms_copy', $terms$
WillpowerLab — Terms

You record yourself presenting. We turn the recording into a transcript,
build a written version of your talk that you own and control, and give you
feedback on how you delivered it.

What you keep: the written document is yours. You can edit it, lock parts of
it so nothing changes them, and delete it. Deleting your account deletes your
recordings and everything derived from them.

What we do not do: we do not sell your recordings, and we do not use them to
train models for anyone else's benefit.

You must be 18 or over to use WillpowerLab.
$terms$,
        'terms_copy_sha256', encode(sha256($terms$
WillpowerLab — Terms

You record yourself presenting. We turn the recording into a transcript,
build a written version of your talk that you own and control, and give you
feedback on how you delivered it.

What you keep: the written document is yours. You can edit it, lock parts of
it so nothing changes them, and delete it. Deleting your account deletes your
recordings and everything derived from them.

What we do not do: we do not sell your recordings, and we do not use them to
train models for anyone else's benefit.

You must be 18 or over to use WillpowerLab.
$terms$::bytea), 'hex'),

        'privacy_version', 'privacy-2026-09-20',
        'privacy_copy', $privacy$
WillpowerLab — Privacy

What we collect: the audio you record, the transcript made from it, the
slides you upload, and the document built from your talk.

Who can hear your recording:

  · automated processing, to transcribe it and produce your feedback;
  · a WillpowerLab coach — a person — may listen to a recording in order to
    review the feedback you were given and to prepare practice for you.

That second one is a human being hearing your voice. We are telling you
plainly because it is the kind of thing people assume does not happen.

How long we keep it: your recordings and everything derived from them stay
while your account is open. Practice attempts you did not keep are deleted
after 30 days. Deleting your account deletes all of it.

Your rights: you can see what we hold, correct it, export it, and have it
deleted. Deletion reaches the stored audio files, not only the database rows.

Where: the service is operated from the European Union.
$privacy$,
        'privacy_copy_sha256', encode(sha256($privacy$
WillpowerLab — Privacy

What we collect: the audio you record, the transcript made from it, the
slides you upload, and the document built from your talk.

Who can hear your recording:

  · automated processing, to transcribe it and produce your feedback;
  · a WillpowerLab coach — a person — may listen to a recording in order to
    review the feedback you were given and to prepare practice for you.

That second one is a human being hearing your voice. We are telling you
plainly because it is the kind of thing people assume does not happen.

How long we keep it: your recordings and everything derived from them stay
while your account is open. Practice attempts you did not keep are deleted
after 30 days. Deleting your account deletes all of it.

Your rights: you can see what we hold, correct it, export it, and have it
deleted. Deletion reaches the stored audio files, not only the database rows.

Where: the service is operated from the European Union.
$privacy$::bytea), 'hex'),

        'ai_notice_version', 'ai-notice-2026-09-20',
        'ai_notice_copy', $notice$
WillpowerLab — how the automated part works

Your transcript, the written version of your talk, and the feedback on your
delivery are produced by automated systems, including AI models.

The feedback is a reading, not a measurement. It describes how a passage
came across; it does not score you, rank you, or decide anything about you.
You are free to disagree with any of it, and disagreeing changes nothing
about your account.

A person may review that automated feedback afterwards. Nothing about you is
decided automatically.
$notice$,
        'ai_notice_copy_sha256', encode(sha256($notice$
WillpowerLab — how the automated part works

Your transcript, the written version of your talk, and the feedback on your
delivery are produced by automated systems, including AI models.

The feedback is a reading, not a measurement. It describes how a passage
came across; it does not score you, rank you, or decide anything about you.
You are free to disagree with any of it, and disagreeing changes nothing
about your account.

A person may review that automated feedback afterwards. Nothing about you is
decided automatically.
$notice$::bytea), 'hex'),

        'agreement_copy', $agree$
I am 18 or over. I agree to the Terms and the Privacy notice, including that
a WillpowerLab coach may listen to my recordings to review my feedback and
prepare practice for me.
$agree$,
        'agreement_copy_sha256', encode(sha256($agree$
I am 18 or over. I agree to the Terms and the Privacy notice, including that
a WillpowerLab coach may listen to my recordings to review my feedback and
prepare practice for me.
$agree$::bytea), 'hex'),

        'allowed_countries', jsonb_build_array('pl', 'de', 'fr', 'es', 'it',
            'nl', 'be', 'se', 'dk', 'fi', 'ie', 'pt', 'at', 'cz', 'sk', 'hu',
            'ro', 'bg', 'hr', 'si', 'ee', 'lv', 'lt', 'lu', 'mt', 'cy', 'gr')
    ),
    -- p_product_legal
    jsonb_build_object(
        'version', 'provisional-founder-2026-09-20',
        'approving_authority', 'founder',
        'approved_at', clock_timestamp(),
        'object_key', 'legal/provisional/product-legal-approval-2026-09-20.md',
        'sha256', encode(sha256('product-legal-approval-2026-09-20'::bytea), 'hex'),
        'metadata', jsonb_build_object(
            'counsel_review', 'pending',
            'note', 'Founder-approved provisional record; counsel review to follow.')
    ),
    -- p_power_score_classification
    jsonb_build_object(
        'version', 'provisional-founder-2026-09-20',
        'approving_authority', 'founder',
        'approved_at', clock_timestamp(),
        'object_key', 'legal/provisional/classification-2026-09-20.md',
        'sha256', encode(sha256('classification-2026-09-20'::bytea), 'hex'),
        'metadata', jsonb_build_object(
            'counsel_review', 'pending',
            'note', 'Delivery feedback is qualitative; no score is surfaced (AC-9).')
    ),
    -- p_article50
    jsonb_build_object(
        'version', 'provisional-founder-2026-09-20',
        'approving_authority', 'founder',
        'approved_at', clock_timestamp(),
        'object_key', 'legal/provisional/article50-2026-09-20.md',
        'sha256', encode(sha256('article50-2026-09-20'::bytea), 'hex'),
        'metadata', jsonb_build_object(
            'counsel_review', 'pending',
            'note', 'AI interaction disclosed in the AI notice copy.')
    ),
    -- p_purposes
    jsonb_build_array(
        jsonb_build_object(
            'purpose_id', 'recording_voice_processing',
            'lawful_basis_code', 'consent',
            'required_for_core_service', true,
            'capability_version', 'recording-capture-v1',
            'reviewed_at', clock_timestamp(),
            'retention_control_version', 'phase1-take-retention-v1',
            'deletion_control_version', 'phase1-purge-take-objects-v1',
            'rights_control_version', 'phase1-subject-rights-v1'),
        jsonb_build_object(
            'purpose_id', 'transcription_feedback',
            'lawful_basis_code', 'consent',
            'required_for_core_service', true,
            'capability_version', 'transcription-feedback-v1',
            'reviewed_at', clock_timestamp(),
            'retention_control_version', 'phase1-take-retention-v1',
            'deletion_control_version', 'phase1-purge-take-objects-v1',
            'rights_control_version', 'phase1-subject-rights-v1'),
        jsonb_build_object(
            'purpose_id', 'individual_learning_profile',
            'lawful_basis_code', 'consent',
            'required_for_core_service', true,
            'capability_version', 'individual-learning-profile-v1',
            'reviewed_at', clock_timestamp(),
            'retention_control_version', 'phase1-take-retention-v1',
            'deletion_control_version', 'phase1-purge-take-objects-v1',
            'rights_control_version', 'phase1-subject-rights-v1'),
        jsonb_build_object(
            'purpose_id', 'coach_review',
            'lawful_basis_code', 'consent',
            'required_for_core_service', true,
            'capability_version', 'coach-review-v1',
            'reviewed_at', clock_timestamp(),
            'retention_control_version', 'phase1-take-retention-v1',
            'deletion_control_version', 'phase1-purge-coach-packet-v1',
            'rights_control_version', 'phase1-subject-rights-v1'),
        -- READ BACK, NOT RETYPED. 0335 already made this one operational;
        -- any difference in any of the five fields raises
        -- PURPOSE_CONTROL_VERSION_CONFLICT and fails the whole publish.
        (SELECT jsonb_build_object(
            'purpose_id', r.id,
            'lawful_basis_code', 'consent',
            'required_for_core_service', true,
            'capability_version', r.capability_version,
            'reviewed_at', r.reviewed_at,
            'retention_control_version', r.retention_control_version,
            'deletion_control_version', r.deletion_control_version,
            'rights_control_version', r.rights_control_version)
           FROM public.processing_purpose_registry r
          WHERE r.id = 'personalized_exercise_recommendation')
    ),
    -- p_actor
    'founder:artur@willonski.com'
) AS registered;

SELECT public.activate_phase1_policy_v1(
    'phase1-2026-09-20',
    'founder:artur@willonski.com',
    encode(sha256('phase1-activation-2026-09-20'::bytea), 'hex')
) AS activated;

COMMIT;

-- ── VERIFY ──────────────────────────────────────────────────────────────
-- Expect: one active policy, and five purposes all operational/authorizing.
SELECT p.version, p.status, p.activated_at,
       array_agg(pp.purpose_id ORDER BY pp.purpose_id) AS purposes
  FROM public.processing_policy_versions p
  JOIN public.processing_policy_purposes pp ON pp.policy_id = p.id
 WHERE p.status = 'active'
 GROUP BY p.version, p.status, p.activated_at;

SELECT id, phase, operational, authorizes_processing,
       capability_version, retention_control_version,
       deletion_control_version, rights_control_version
  FROM public.processing_purpose_registry
 WHERE phase = 'phase1'
 ORDER BY id;
