-- Republish the Phase-1 processing policy WITHOUT service-conditional
-- bundled consent. P11. NOT YET RUN.
--
-- ⚠ THE COPY BELOW IS HELD FOR FOUNDER SIGN-OFF. Nothing here runs on merge;
-- this file is deliberately absent from migrations/manifest.txt for the same
-- reason the 2026-09-20 script is. Publishing a consent policy is not
-- something a deploy should do behind anyone's back. It is run once, by hand,
-- and the running of it IS the signature.
--
-- ── RECONCILED 2026-09-23 WITH scripts/phase1_policy_publish_v2.sql ─────
--
-- A second session wrote its own publish script on branch
-- claude/compassionate-hamilton-2f4t73, with fuller copy (terms-3.0,
-- privacy-3.0). Two scripts publishing the same policy version is one too
-- many, and the founder asked for one. THIS FILE IS THE RECONCILIATION and
-- the other script should be withdrawn rather than run.
--
-- WHAT CAME FROM THEIRS, because it is better: the hybrid-coaching framing
-- that puts coach review inside the 6(1)(b) basis rather than beside it;
-- Railway's dual role stated more precisely than I had it; the Article 9
-- paragraph, which says outright that the consent "is not bundled with
-- anything else, and a contract can never stand in for it"; §11's solution to
-- the plan-table problem — every plan includes at least one coach review, so
-- "no coach reviews" cannot be read as "nobody listens"; and the Art 56 UODO
-- line, which they had written identically.
--
-- WHAT DID NOT, and why. Their script publishes ALL FIVE purposes as
-- 'contract' + required_for_core_service TRUE, which makes practice and the
-- learning profile compulsory. That contradicts the founder's rulings of the
-- same day — practice "you can always leave the app and not do it, you can
-- skip it", and individual_learning_profile corrected from "NO" to "okok,
-- optional" — and it does not fix the defect it targets. Moving a purpose
-- that is not objectively necessary from 'consent' to 'contract' swaps an
-- invalid consent for an invalid contract basis; Art 6(1)(b) requires
-- necessity, and CLAUDE.md's locked contract says the loop "never waits for a
-- coach or exercise".
--
-- ⚠ AND THEIR VERIFY CANNOT SEE IT. Their check counts rows that are
-- 'consent' AND required, and calls 0 success. An all-contract policy returns
-- 0 because it has no consent rows at all — the counter measures the absence
-- of a symptom, so the very change that recreates the problem is what makes
-- the check pass. STEP 4 below tests the same invariant structurally, per
-- purpose object, and STEP 5 asserts the optional lane is non-empty, which is
-- the half a count can never express.
--
-- ⚠ TODO(founder) — THE PRICING TABLE in Terms §2 carries their placeholder
-- of "1 coach review" on Free and Practice. Set the real numbers. Only
-- "greater than zero on every plan" is load-bearing, because that is what
-- keeps the table from reading as "nobody listens to you".
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
--   individual_learning_profile           consent    OPTIONAL
--
-- All five purposes are published. Nothing is held out.
--
-- Moving the three mandatory purposes from 'consent' to 'contract' dissolves
-- the Art 7(4) problem at the root: consent is no longer the basis for
-- anything compulsory, so there is no compelled consent left to be invalid.
-- The two genuinely separable purposes keep consent — real consent, refusable
-- without losing the service, which is the only kind worth recording.
--
-- individual_learning_profile is OPTIONAL, founder ruling 2026-09-23. Asked
-- what it does, the founder said "it personalises the exercises you get";
-- asked whether a user may refuse it and still use the app, first "NO", then
-- corrected to optional. The correction is the coherent answer: a purpose
-- cannot be more necessary than the only thing it serves, and exercises are
-- themselves refusable. Published as required it would have rebuilt the Art
-- 7(4) defect one purpose to the left.
--
-- It rides the SAME optional tick as practice, because from the user's side
-- it is one choice — "personalised practice" — expressed as two registry
-- rows: the recommendation, and the profile that makes it personal. Granting
-- them separately would offer a choice with no meaning (a profile that
-- personalises nothing, or exercises that cannot be personalised).
-- ⚠ FOR COUNSEL: confirm one tick for both is granular enough under Recital
-- 43, or split it. accept_v2 takes an array, so splitting is a screen change
-- and not a schema one.
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
-- personalized_exercise_recommendation is not necessary, and the basis for
-- saying so is the founder's ruling, NOT the state of the routes.
--
-- ⚠ CORRECTION 2026-09-23. An earlier draft of this header claimed the five
-- practice routes "every one of them returns 410 PURPOSE_NOT_OPERATIONAL
-- today" and rested the necessity test on that. THAT WAS FALSE. The routes
-- are gated by @operational_purpose_disabled(...), which since 0335 ASKS the
-- registry rather than refusing unconditionally, and production answers yes:
--
--   personalized_exercise_recommendation | phase1 | operational=true |
--   authorizes_processing=true | confident-voice-practice-v1 | 2026-09-16
--
-- Their only other guard is @require_auth. Practice is LIVE in production.
-- The claim was made by reading the decorator and assuming its answer — the
-- precise failure 0335 rewrote the guard to prevent.
--
-- Necessity therefore rests where it belongs: on the founder's ruling that
-- the step is skippable ("you can always leave the app and not do it, you can
-- skip it"), and on the locked contract in CLAUDE.md — "the record → process
-- → Ideal Text → next-Take loop never waits for a coach or exercise." A step
-- the product is built never to wait for is not necessary to perform the
-- contract, whether or not its routes happen to be serving.
--
-- ⚠ AND NOTE WHAT THAT MEANS FOR THIS PUBLISH. Practice works today BECAUSE
-- of the defect this file removes: the live policy marks it
-- required_for_core_service, and accept_v1 writes receipt rows only WHERE
-- required_for_core_service, so every receipt carries it and every permit
-- issues. After this file publishes, practice is optional — a new user who
-- does not tick the box genuinely has it off. Receipts already issued stay
-- valid until re-acceptance. This is a real behaviour change, not a no-op,
-- and it is the correct one: it is what "refusable" means.
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
-- ── COUNSEL HAS ANSWERED, AND THE ARTIFACTS SAY SO CAREFULLY ────────────
--
-- Per docs/HANDOFF-2026-09-23.md §0, counsel answered on 2026-09-23: the
-- voice-confidence component is not an emotion recognition system under AI
-- Act Art 3(39); Art 6(1)(b) contract holds for coach review, covering
-- delivery of the coaching only; Art 9(2)(a) survives separately and a
-- contract never unlocks special-category data; UODO is the lead authority
-- under Art 56. An earlier revision of this header said `counsel_review:
-- pending` was "still the true state". It is not, and that is corrected.
--
-- The metadata now records TWO fields rather than one, because they are two
-- different facts:
--
--   counsel_review        confirmed_by_correspondence_2026-09-23
--   counsel_signed_letter pending
--
-- §0 is explicit that getting the answer as a DATED LETTER THAT CAN BE HASHED
-- is still a founder task, because an email thread cannot be a registered
-- artifact. Recording only the first field would let correspondence pass for
-- a signed opinion; recording only the second would deny an answer we have.
-- The versions stay `provisional-` until the letter exists, which is what
-- "provisional" has meant here all along.
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
-- legal/phase1-2026.1/copy/*-3.1.txt so the files and the
-- published bytes agree.

-- ⚠ THE EFFECTIVE DATE IS WRITTEN INTO THE COPY. Both documents say
-- "Version 2.1. Effective 23 September 2026." If you run this on a later day
-- that sentence is wrong on the day it binds. Change the date in the terms and
-- privacy blocks below, re-run the mirror sync, and publish — the
-- sha256s recompute themselves from the text, so only the date needs touching.
-- tests/test_phase1_policy_unbundled.py fails if the mirrors drift.

-- ── STEP 0 · COUNT THE PURPOSES BEFORE PUBLISHING ANYTHING ──────────────
--
-- Handoff trap 4.2: "Purposes built with jsonb_agg fail silently. A missing id
-- publishes a smaller policy with no error. Always count the rows first."
--
-- This file builds each purpose as its own subselect rather than with
-- jsonb_agg, which fails differently but just as quietly: a purpose missing
-- from the registry yields a NULL array element, and the policy publishes
-- short. STEP 3 and STEP 5 below would catch it — AFTERWARDS, and running
-- this file is the signature, so afterwards is the wrong time to find out.
--
-- Run this FIRST, on its own. It must return exactly 5. If it returns 4, STOP
-- and find out which id is missing before anything is published.

SELECT count(*) AS purposes_resolving,
       array_agg(r.id ORDER BY r.id) AS resolved,
       bool_and(r.operational AND r.authorizes_processing) AS all_operational
  FROM public.processing_purpose_registry r
 WHERE r.phase = 'phase1'
   AND r.id IN ('recording_voice_processing','transcription_feedback',
                'coach_review','personalized_exercise_recommendation',
                'individual_learning_profile');

-- Expect: purposes_resolving = 5, all_operational = true.
-- `all_operational` matters because a REQUIRED purpose that is not
-- operational makes every acceptance raise PROCESSING_PURPOSE_NOT_OPERATIONAL
-- — the whole product, not a degraded corner of it.

-- ── STEP 1 · register ───────────────────────────────────────────────────

WITH c AS (SELECT
$terms$WillpowerLab — Terms of Service
Version 3.1. Effective 23 September 2026.

These terms are an agreement between you and Artur Willoński, operating under
the name "WillpowerLab" from Poland ("WillpowerLab", "we", "us"). They govern
your use of willpowerlab.com and the WillpowerLab application.

Version 3.1 replaces every earlier version. Earlier versions required you to
agree that your practice data could be used to train models shared with other
users. This version does not ask for that and does not permit it. Under these
terms your recordings are processed to deliver your own coaching. If that
changes, it changes in a new version you are asked to accept — see section 15.


1. WHAT THE SERVICE DOES

You record yourself presenting. WillpowerLab transcribes the recording, lines
the transcript up with your slides, writes an Ideal Text — a presentation
document built from what you actually said — and gives you feedback after each
attempt.

WillpowerLab is hybrid coaching: automated work and a human coach, together.
The transcription and the written documents are produced by artificial
intelligence, and a WillpowerLab coach — a person — may listen to your
recordings in order to review the feedback you were given and to prepare
practice for you. Both halves are the service. If you are not willing for a
person to hear your recordings, WillpowerLab is not the product for you, and
you should not accept these terms.

Your audio is sent to a third-party AI provider to be transcribed. The AI
notice tells you who receives it and what happens to it, and the Privacy Policy
sets out the detail.


2. WHAT IT COSTS

There is a free plan and there are paid plans. You can use the free plan for as
long as you like without paying.

Work in the app is measured in tokens. Each plan gives you an allowance of them
for the month. The allowance is SET at the start of each month rather than
added to what you had, so unused tokens do not carry over.

  Free         12,000 tokens a month     1 coach review       no charge
  Practice    150,000 tokens a month     1 coach review       USD 12 a month
  Coaching    150,000 tokens a month     3 coach reviews      USD 39 a month
  Intensive   400,000 tokens a month     8 coach reviews      USD 89 a month

Reviews by a human coach are a separate limit from tokens, and the tighter of
the two applies: you can have tokens left and no reviews left.

The price and what it includes are shown before you pay. We will tell you
before any price changes. Payments are taken by our payment provider; we do not
see or store your card details. A paid plan renews each month until you cancel,
and you can cancel at any time.

If you are a consumer in the EU or EEA, you have 14 days to withdraw from a
paid plan. We give you that full 14 days with no questions asked, even once you
have started using it.


3. YOU MUST BE 18

The service is for adults. You must be 18 or older to use it. When you accept
these terms you confirm that you are. We do not knowingly provide the service
to anyone under 18, and we will close an account if we learn that its holder is
under 18.


4. WHERE THE SERVICE IS AVAILABLE

We offer the service only in the countries listed on the acceptance screen. If
you are not resident in one of them, you cannot accept these terms and we
cannot provide the service to you.


5. YOUR ACCOUNT

You may start using the service before creating an account. If you later create
one, the work you have already done moves with you.

Keep your login details to yourself. You are responsible for what happens under
your account. Tell us promptly if you think someone else has access to it.


6. RECORDING OTHER PEOPLE

You may record your own voice. You may not use WillpowerLab to record anyone
else without their knowledge and their agreement.

This matters more here than in most products, because a recording of a person's
voice is their personal data and we process it on your say-so. If you record
someone else, you are the one who must have their permission, and you are
responsible for having it.

If you believe your voice has been recorded and uploaded to WillpowerLab by
somebody else, contact us at contact@willpowerlab.com. We will act on that
report, which includes blocking further processing of the recording and
deleting the audio.


7. WHAT YOU MAY NOT DO

Do not use the service to:

- record a person who has not agreed to it;
- upload material you have no right to upload;
- upload content that is unlawful, or that harasses, threatens or defames
  someone;
- attempt to extract, reverse engineer or retrain any model we use;
- probe, scan or interfere with the service's security, or use it in a way that
  degrades it for other people;
- resell the service or provide it to others as your own;
- deploy it in a workplace or an education institution (see below).


NOT FOR EMPLOYERS OR SCHOOLS

WillpowerLab is for individuals practising on their own account.

You may not use it, or require or encourage anyone else to use it, as part of
employment, recruitment, performance review, or assessment in an education
institution. No employer, school or other organisation may direct, monitor or
require anyone's use of the service, and no organisation receives anything the
service produces about a person.

This is not a formality. The service analyses how a delivery sounds, and the law
treats that kind of analysis very differently inside a workplace or a classroom
than it does for someone practising alone. If you want to use WillpowerLab with
a team, talk to us first.


8. YOUR CONTENT IS YOURS

You keep every right you already have in your recordings, your slides, your
transcripts and the documents the service produces for you.

You give us permission to process that material only so far as it takes to give
you the service: to store it, transcribe it, send the necessary parts to the
providers named in the Privacy Policy, generate your documents and feedback,
have a coach review them, and keep them available to you. That permission is
limited to your own service and ends when your content is deleted.

We do not use your recordings to train models for anyone else, and we do not
pool your material with other users' material.


9. THE IDEAL TEXT IS YOUR DOCUMENT

The Ideal Text is a single, persistent document that belongs to you. Your first
attempt creates it. Later attempts may propose improvements, and you decide
whether to take them. We do not rewrite or replace your Ideal Text behind your
back, and we do not overwrite it with a later transcript.


10. WHAT AI-GENERATED OUTPUT IS AND IS NOT

The transcript, the Ideal Text and the feedback are generated by AI. They can
be wrong. A transcript can mishear a word. A generated document can misstate
something you said. Feedback can be off the mark.

Check anything that matters before you rely on it. You are responsible for what
you present.

The service is practice tooling. It is not professional, medical, psychological
or career advice, and it is not an assessment of you as a person. It does not
score you, rate you, or produce a verdict about you, and nothing it produces is
a measurement of your ability.


11. HUMAN COACHES

A WillpowerLab coach is a person, and coach review is part of the service
rather than an extra you switch on. Section 1 says why: this is hybrid
coaching, and the human half is not optional to it.

What that means in practice. A coach may listen to your recordings in order to
review the feedback you were given and to prepare practice for you. How many
reviews you receive each month depends on your plan, and section 2 sets out the
allowance for each; every plan includes at least one. A coach does not see the
voice measurements described in section 3 of the Privacy Policy.

Practice is optional, and it is the one part of this that you choose. After
your feedback you may be offered a short exercise and the chance to re-record a
fragment. You can turn it on when you accept and off whenever you like;
declining it changes nothing else about your account, and everything in section
1 still works exactly as described.

Your recording and feedback loop never waits for a coach. You record, you get
your transcript, your Ideal Text and your feedback, and you record again — all
of it without a person in the way.

We are stating this plainly because it is the kind of thing people assume does
not happen.


12. AVAILABILITY

We work to keep the service running, but we do not promise it will always be
available or uninterrupted. We may change, suspend or withdraw features. If a
change materially reduces what you get, we will tell you beforehand where we
reasonably can.


13. SUSPENDING OR ENDING YOUR ACCESS

You may stop using the service at any time and ask us to delete your account.

We may suspend or end your access if you break these terms, if we must to
comply with the law, or if keeping your access open would put other people or
the service at risk. Where it is practical and lawful to do so, we will tell
you why.

When your access ends, we handle your content as described in the Privacy
Policy.


14. OUR RESPONSIBILITY TO YOU

We provide the service with reasonable care and skill. We do not exclude or
limit our liability for death or personal injury caused by our negligence, for
fraud, or for anything else that cannot be excluded or limited under the law
that applies to you.

Subject to that: we are not liable for loss that was not reasonably
foreseeable, for lost profits or lost opportunities, or for the consequences of
your relying on AI-generated output without checking it.

If you are a consumer, nothing in these terms affects your statutory rights.


15. CHANGES TO THESE TERMS

We may change these terms. When we do, we publish a new version with a new
version number, and the new text is what you will be asked to agree to.

Because the exact words of each version are fingerprinted, a change means you
are asked to accept the new version before you carry on using the service. Your
acceptance records which exact version you agreed to and when. You can ask us
for that record at any time.


16. LAW AND DISPUTES

These terms are governed by Polish law, and the courts of Warsaw, Poland have
jurisdiction. If you are a consumer resident in the EU, this does not deprive
you of the protection of the mandatory rules of the country where you live, and
you may bring proceedings there.

You may also use the European Commission's online dispute resolution platform.


17. CONTACT

Artur Willoński, operating under the name "WillpowerLab"
Poland, European Union
Contact: contact@willpowerlab.com (a postal address is provided on request to
data subjects and to the supervisory authority)$terms$ AS terms,

$privacy$WillpowerLab — Privacy Policy
Version 3.1. Effective 23 September 2026.

This policy explains what WillpowerLab does with your personal data, who else
receives it, how long we keep it, and how you get it deleted.

Version 3.1 replaces every earlier version. Earlier versions required you to
agree that your practice data could be used to train models shared with other
users. This version does not ask for that. Under this version your recordings
are used to deliver your own coaching: they are not pooled with other users'
data and they are not used to train models. If that ever changes, it changes in
a new version of this policy, which you will be asked to accept before it
applies to you — see section 12.


1. WHO IS RESPONSIBLE FOR YOUR DATA

WillpowerLab is operated by an individual based in Poland. The controller of
the personal data described here is:

Artur Willoński, operating under the name "WillpowerLab"
Poland, European Union
Contact: contact@willpowerlab.com (a postal address is provided on request to
data subjects and to the supervisory authority)

The lead supervisory authority under Article 56 GDPR is the President of the
Personal Data Protection Office (UODO), ul. Stawki 2, 00-193 Warsaw, Poland.

Given the scale of processing we have not appointed a Data Protection Officer,
which GDPR Article 37 does not require of us. Privacy requests are handled
directly at the address above.


2. WHAT WE COLLECT

Things you give us
- Your email address and account details.
- Your slides and presentation materials.
- Audio recordings of you presenting.
- Edits you make to your Ideal Text, and your responses to feedback.

Things produced from your recordings
- Transcripts of what you said.
- Measurements taken from the sound of your voice: how much your pitch varies,
  how loud and how varied your delivery is, how fast you speak, how you pause,
  and how your energy and pitch move across a sentence.
- Your Ideal Text and your feedback.

Things collected automatically
- Technical and security logs: IP address, device and browser information,
  timestamps, and error records.
- The version of the app you used, the country you told us you live in, and the
  language your app was set to, recorded as part of your agreement to this
  policy.


3. THE SOUND OF YOUR VOICE

We take measurements from how your voice sounds and compare them against your
own earlier recordings — never against other people. We use them to help choose
which of your own sentences to show back to you.

We do not produce a score, a rating, a grade or a verdict about you, and no such
thing is shown to you, to a coach, or to anyone else. We do not use your voice
to identify you. We do not infer, record or guess your sex, gender, age, health,
ethnicity, or any other characteristic about you from the sound of your voice.

If the measurements cannot be taken reliably from a recording, we record that
they could not be taken. We do not fill in a value.


4. WHAT WE USE IT FOR, AND ON WHAT LEGAL BASIS

To provide the service: to store your recording, transcribe it, generate your
Ideal Text and your feedback, have a WillpowerLab coach review that feedback,
and keep all of it available to you.
Legal basis: performance of our contract with you (Article 6(1)(b) GDPR). This
processing is what the service is; we cannot provide it without doing this.
WillpowerLab is hybrid coaching — automated work and a human coach together —
so the coach's review sits inside this basis rather than beside it. That basis
covers delivering your coaching and nothing else: it does not cover training
models, analytics about you, or advertising, none of which we do.

To keep the service secure and working: fraud and abuse prevention, debugging,
protecting the service and its users.
Legal basis: our legitimate interests (Article 6(1)(f) GDPR).

Practice, and making it personal — optional: choosing a short exercise that fits
your recording, keeping the fragment you re-record, and remembering what you
have been working on so that later exercises suit you better.
Legal basis: your consent (Article 6(1)(a) GDPR). You choose this separately
when you accept, you can decline it, and declining costs you nothing else in
the service — everything above still works exactly the same. You can withdraw
it at any time, and withdrawing it ends practice, not your account.

To meet our legal obligations: for example accounting records, and responding
to lawful requests.
Legal basis: legal obligation (Article 6(1)(c) GDPR).

If you take a paid plan, your payment is handled by Stripe. We never see or
store your card details; we hold the record that a plan is active and the
invoices we are required to keep. Under this version we do not use
anyone's recordings to train models, and that is enforced rather than merely
stated: while this version is in force our systems refuse to register a
processing policy that would permit it. Changing it would take a new policy
version and your acceptance of it.

Do you have to provide this data? For the parts the service is made of, yes.
Recording your voice, having it transcribed, and having a coach able to review
your feedback are what WillpowerLab is; there is no version of it that works
without them, so if you are not willing to provide them you cannot use the
service. Practice is the exception — it is optional, and refusing it costs you
nothing but practice.

Special categories of data. A recording of you speaking freely may happen to
reveal something sensitive — a health condition audible in your speech, or
something you mention while presenting. We do not look for this and we do not
infer it. Where such information is present, we rely on your explicit consent
(Article 9(2)(a) GDPR), which you give as its own separate agreement on the
acceptance screen. It is not bundled with anything else, and a contract can
never stand in for it. You can withdraw it at any time; because we cannot
process a recording of you speaking freely without it, withdrawing it means we
stop providing the service. Withdrawing does not affect anything we did
lawfully beforehand, and you keep every right in section 8 afterwards — you can
still get a copy of your data and still have it deleted.

We do not make decisions about you by automated means that produce legal effects
or similarly significantly affect you.


5. WHO ELSE RECEIVES YOUR DATA

AI providers

OpenAI receives:
- the audio of your recording, in order to transcribe it;
- parts of your transcript and related text, in order to generate your Ideal
  Text and your feedback.

OpenAI is the only AI provider that receives your audio or your transcript.
Each transfer is made under a short-lived internal permit that records which
operation it was for and the minimum data it was allowed to carry. We do not
authorise OpenAI to use your content to train its models.

Infrastructure providers
- Cloudflare (R2): storage of your audio recordings.
- Supabase: our database, and audio storage on a fallback path.
- Railway: hosting of the application. Railway is our processor for what it
  hosts on our behalf, and a controller in its own right for its own account
  and service-usage records about us as its customer.
- Resend: transactional email.
- Vercel: hosting of the website.
- Sentry: error reports, stored in the European Union.

Payments
- Stripe, if you take a paid plan. Stripe is not our processor: it decides for
  itself how it uses payment data, as a controller in its own right, under its
  own terms. We never see or store your card details.

Human coaches
A WillpowerLab coach — a person — may listen to your recordings in order to
review the feedback you were given, and, if you turned practice on, to prepare
practice for you. The review is part of the service rather than an extra you
switch on, because WillpowerLab is hybrid coaching; the Terms say so in section 1 and section 11, and how many
reviews you receive each month depends on your plan. A coach who reviews your
recording does not see the voice measurements described in section 3. Coaches
are bound to confidentiality and see only what a review requires.

Others
We share data with professional advisers, and with authorities where the law
requires it. We do not sell your personal data and we do not share it for
advertising.


6. TRANSFERS OUTSIDE THE EEA

Some of the providers above process data in the United States. Every one of
those transfers is made under the European Commission's Standard Contractual
Clauses, which each provider's data processing agreement incorporates.

- OpenAI: Standard Contractual Clauses. Its agreement appoints OpenAI Ireland
  Limited to process data from the EEA and Switzerland.
- Cloudflare: Standard Contractual Clauses. Our storage carries an Eastern
  Europe location hint, which is a preference rather than a guarantee.
- Supabase: Standard Contractual Clauses and a UK addendum. Your data is stored
  in Ireland.
- Railway, Resend, Vercel: Standard Contractual Clauses.
- Sentry: error reports are stored in the European Union.

You can ask us for a copy of the safeguards in place.


7. HOW LONG WE KEEP IT

Recordings (audio): 12 months after you last use the recording.
Transcripts, Ideal Text and feedback: until you delete your account.
Voice measurements: deleted together with the recording they came from, never
  kept after it.
Practice attempts: kept while the practice is open; after that we keep only the
  attempt you chose and delete the rest after 30 days.
Uploaded files that never became a recording: deleted after 24 hours.
Security and technical logs: 90 days.
Account records: until you delete your account.
Record of your agreement to this policy: kept for as long as we may need to
  show that your recordings were processed lawfully, and then deleted.

Our full retention and destruction schedule is published at
willpowerlab.com/legal/retention.

What OpenAI holds, separately from us
OpenAI keeps the audio and text sent to its API for up to 30 days, to check for
abuse, and then deletes it. On our current plan that period cannot be switched
off. It is not used to train OpenAI's models.


8. YOUR RIGHTS

You have the right to:
- get a copy of the personal data we hold about you;
- have inaccurate data corrected;
- have your data deleted;
- restrict how we use your data, or object to our using it on the basis of our
  legitimate interests;
- receive your data in a portable format;
- withdraw any consent you have given, at any time, without affecting what we
  did lawfully before you withdrew it.

To exercise any of these, contact contact@willpowerlab.com. We respond within one
month. If we need longer because a request is complex, we will tell you within
that month and explain why.

If you are unhappy with how we handle your data, you can complain to your local
supervisory authority. In Poland that is the President of the Personal Data
Protection Office (Prezes Urzędu Ochrony Danych Osobowych), ul. Stawki 2,
00-193 Warszawa.


9. DELETING YOUR DATA — WHAT ACTUALLY HAPPENS

We want to be precise about this rather than reassuring.

When you ask us to delete your data, we build an inventory of everywhere it is:
database records, stored audio files, transcripts, generated documents, queued
processing jobs, records of what was sent to providers, and coach copies where
they exist. We then delete them and record proof of each deletion.

If our process reaches something it cannot resolve on its own, it stops rather
than guessing, and a person completes it. That is deliberate: it is better for
the process to halt than to report a deletion it did not actually make. It means
some deletions are finished by hand. We finish them within the one-month period
in section 8, and we tell you when it is done.

Two things survive deletion:

- Records that prove your recordings were processed with your agreement. These
  contain identifiers, timestamps and fingerprints — not your recordings, your
  transcripts or anything you said. We keep them because they are the evidence
  that we handled your data lawfully, and we delete them when we no longer need
  them for that.
- Anything we must keep by law, for example accounting records.

Audio already sent to a provider is deleted at the provider as part of the same
process, and we record the outcome.


10. SECURITY

Your recordings are stored with access restricted to the systems that need it.
We verify each stored recording against a fingerprint of its exact bytes so we
can tell that what we hold is what you uploaded and that nothing has been
altered. Internal access is limited and logged. Records that prove how your data
was handled cannot be edited or deleted by the application.

No service is perfectly secure. If a breach affects your rights, we will notify
you and the supervisory authority as the law requires.


11. CHILDREN

The service is for adults aged 18 and over. We do not knowingly collect data
about anyone under 18. If you believe we hold data about a child, contact us and
we will delete it.


12. CHANGES TO THIS POLICY

When we change this policy we publish a new version with a new version number.
The exact words of each version are fingerprinted, so you will be asked to
accept the new version before continuing to use the service, and your record
shows exactly which version you agreed to and when.


13. CONTACT

Artur Willoński, operating under the name "WillpowerLab"
Poland, European Union
Contact: contact@willpowerlab.com (a postal address is provided on request to
data subjects and to the supervisory authority)$privacy$ AS privacy,

$notice$WillpowerLab — how the automated part works

Your transcript, the written version of your talk, and the feedback on your
delivery are produced by automated systems, including AI models.

The feedback is a reading, not a measurement. It describes how a passage came
across; it does not score you, rank you, or decide anything about you. You are
free to disagree with any of it, and disagreeing changes nothing about your
account.

A person may review that automated feedback afterwards. Nothing about you is
decided automatically.$notice$ AS notice,

$agree$I have read the Terms of Service and the Privacy Policy and I agree to them.

I understand that WillpowerLab is hybrid coaching, and that a WillpowerLab coach — a person — may listen to my recordings in order to review my feedback. That is part of the service, not an extra I am switching on.$agree$ AS agree)

-- TODO-4 · the SEPARATE optional tick. Not part of agreement_copy, which is
-- the mandatory one. The acceptance screen renders this on its own control
-- and, when ticked, sends 'personalized_exercise_recommendation' in
-- accept_phase1_processing_authorization_v2's p_optional_purposes. Unticked
-- sends an empty array and the person keeps the whole service.
--
--   OPTIONAL_TICK:
--   "Optional — personalised practice. Use my recordings to choose short
--    exercises that fit them, to keep the fragments I re-record, and to
--    remember what I am working on so the exercises get more personal. I can
--    turn this off at any time and keep using everything else."

SELECT public.register_phase1_policy_v1(
  jsonb_build_object(
    'version','phase1-2026-09-23',
    'terms_version','terms-3.1-2026-09-23',
    'terms_copy', c.terms,
    'terms_copy_sha256', encode(extensions.digest(c.terms,'sha256'),'hex'),
    'privacy_version','privacy-3.1-2026-09-23',
    'privacy_copy', c.privacy,
    'privacy_copy_sha256', encode(extensions.digest(c.privacy,'sha256'),'hex'),
    'ai_notice_version','ai-notice-3.1-2026-09-23',
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
    'metadata', jsonb_build_object('counsel_review','confirmed_by_correspondence_2026-09-23',
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
      'counsel_review','confirmed_by_correspondence_2026-09-23',
      'counsel_signed_letter','pending',
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
    'metadata', jsonb_build_object(
      'counsel_review','confirmed_by_correspondence_2026-09-23',
      'counsel_signed_letter','pending')),
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
     WHERE r.id = 'personalized_exercise_recommendation'),
    -- Founder ruling 2026-09-23, after a correction: "it personalises the
    -- exercises you get", and optional. It serves an optional feature, so it
    -- inherits that status; it cannot outrank what it exists to serve.
    (SELECT jsonb_build_object('purpose_id', r.id,
      'lawful_basis_code','consent','required_for_core_service',false,
      'capability_version', r.capability_version,
      'reviewed_at', r.reviewed_at,
      'retention_control_version', r.retention_control_version,
      'deletion_control_version', r.deletion_control_version,
      'rights_control_version', r.rights_control_version)
      FROM public.processing_purpose_registry r
     WHERE r.id = 'individual_learning_profile')
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
--   purposes  = {coach_review, individual_learning_profile,
--                personalized_exercise_recommendation,
--                recording_voice_processing, transcription_feedback}
--   required  = 3
--   optional  = 2
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
-- Expect exactly TWO rows: personalized_exercise_recommendation and
-- individual_learning_profile, both consent, both
-- required_for_core_service = false. Fewer rows means the optional lane
-- silently shrank and the acceptance screen has less to offer than the
-- policy claims — which is how an "optional" purpose quietly becomes
-- mandatory.

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
