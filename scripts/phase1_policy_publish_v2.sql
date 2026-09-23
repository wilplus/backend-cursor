-- Publish the Phase-1 processing policy, v2. NOT YET RUN.
--
-- ⚠ READ THE COPY BEFORE YOU RUN THIS. Four blocks of English below are the
-- words your users agree to, and their SHA-256 is what a receipt names. You do
-- not need to read the SQL. You do need to read the English and decide whether
-- you would be happy for a user to hold you to it.
--
-- ⚠ ONE NUMBER IS MINE, NOT YOURS — CHANGE IT BEFORE RUNNING.
-- The Terms pricing table below gives Free and Practice ONE coach review a
-- month. Founder decision 2026-09-23 was "Free gets coach review too", but the
-- count is a commercial choice I cannot make. Set the two numbers you actually
-- want. The only legal requirement is that every plan is GREATER THAN ZERO —
-- see WHY, below.
--
-- ── WHAT THIS FIXES ─────────────────────────────────────────────────────
--
-- scripts/phase1_policy_publish.sql ran in production on 2026-09-20 and
-- published all five purposes with lawful_basis_code 'consent' AND
-- required_for_core_service TRUE. Consent that is a condition of service is
-- the Art 7(4) defect legal/phase1-2026.1/01-product-legal-approval §3
-- identifies; §6 held coach_review out of v1 for exactly that reason.
--
-- Measured before writing this, in production:
--   SELECT count(*) FROM processing_policy_versions p
--     JOIN processing_policy_purposes pp ON pp.policy_id = p.id
--    WHERE p.status='active' AND pp.lawful_basis_code='consent'
--      AND pp.required_for_core_service IS TRUE;   -->  5
-- After this runs that query must return 0. It is the whole point.
--
-- ── COUNSEL, 2026-09-23 — IMPLEMENTED, NOT RE-ARGUED ────────────────────
--
--   "You sell one service: hybrid coaching. A person listening is how that
--    service is performed, not a clause you added. Users who refuse don't get
--    a lesser app; they don't get WillpowerLab. That is the 2/2019 test. It
--    holds only for coach review to deliver the coaching. Training, analytics,
--    ads stay off 6(1)(b)."
--
--   "[Art 9(2)(a)] Yes. Always. Contract does not unlock special-category
--    data. Keep an explicit yes for incidental sensitive content in sessions.
--    Gate access on that yes. If they withdraw it, stop the service."
--
--   Lead authority: UODO. The exact sentence counsel supplied is in Privacy §1.
--
-- ── WHY EVERY PLAN NEEDS A COACH REVIEW ─────────────────────────────────
--
-- Counsel's opinion rests on hybrid coaching being ONE service. The 2.0 draft
-- of the Terms gave Free and Practice "no coach reviews", which would have made
-- that premise false for two of four plans — a Free user would plainly be
-- getting "a lesser app" without the human half, which is the exact phrase the
-- opinion rules out. A policy claiming coach review is necessary to deliver the
-- service, published beside a pricing table saying two plans never get it, is a
-- contradiction a regulator finds in ninety seconds.
--
-- Founder chose to change the product rather than the argument. Hence a
-- non-zero review allowance on every plan.
--
-- ── WHAT CHANGED FROM legal/phase1-2026.1/copy/ ─────────────────────────
--
-- The two long documents below ARE terms-2.0.txt and privacy-2.0.txt, which
-- were drafted and never published. Surgical edits only, listed so you can
-- check each one rather than re-read 20,000 characters:
--
--   TERMS   §1   names the human coach as part of what the service does
--           §2   every plan now has a coach-review allowance  ← YOUR NUMBERS
--           §11  rewritten: coach review is part of the service, not an
--                optional extra you ask for separately
--           head version/date
--   PRIVACY §1   UODO lead-authority sentence, verbatim from counsel
--           §4   coach review named in the contract-basis paragraph
--           §5   "Human coaches" rewritten to match; Railway gains its
--                independent-controller role (executed DPA §13, 2026-09-23)
--           head version/date
--
-- The AI notice is UNCHANGED from what is live. It meets Art 50(1), surfaces
-- no score, and states the Art 22 position. It did not need touching.
--
-- ── NOT A MIGRATION ─────────────────────────────────────────────────────
--
-- Deliberately absent from migrations/manifest.txt. MIGRATE_ON_BOOT=1 means
-- anything in the manifest runs at container start, and publishing a consent
-- policy is not something a deploy should do behind anyone's back. It is run
-- once, by hand, and the running of it IS the signature.
--
-- ── THE TRAP THIS SCRIPT AVOIDS ─────────────────────────────────────────
--
-- All five purposes are already `operational` in processing_purpose_registry
-- after the 2026-09-20 run. register_phase1_policy_v1 raises
-- PURPOSE_CONTROL_VERSION_CONFLICT if ANY of capability_version, reviewed_at,
-- retention_control_version, deletion_control_version or rights_control_version
-- differs by one character from what is stored — and reviewed_at was written
-- with now(), so it cannot be retyped. Every purpose below therefore READS ITS
-- OWN FIVE FIELDS BACK from the registry, the way the 2026-09-20 script did for
-- personalized_exercise_recommendation alone.
--
-- The lawful basis and the required flag are NOT read back: they are the two
-- things this publish exists to change. POLICY_PURPOSE_CONFLICT only fires when
-- a row already exists for the SAME policy_id, and this is a new version, so
-- changing them here is allowed.
--
-- ── FOUNDER AUTHORIZATION ───────────────────────────────────────────────
--
--   [ FILL THIS IN BEFORE RUNNING — the authorization is yours to give, and
--     this header is the audit trail for why a hand-run script touched prod. ]
--

-- ── STEP 0 · PRE-FLIGHT. Run this FIRST, on its own, and read the answer ─
--
-- The purposes below are built by reading the registry. If any of the five is
-- missing or not phase1, jsonb_agg quietly returns fewer rows and you publish a
-- policy with a hole in it — no error, just a smaller policy. So check first.
--
-- EXPECT EXACTLY 5 ROWS. If you get 4, STOP and say which one is missing.

SELECT id, phase, operational, authorizes_processing, capability_version
  FROM public.processing_purpose_registry
 WHERE phase = 'phase1'
   AND id IN ('recording_voice_processing','transcription_feedback',
              'individual_learning_profile','coach_review',
              'personalized_exercise_recommendation')
 ORDER BY id;

-- And the before-measurement, so the after has something to be compared with.
-- EXPECT 5.

SELECT count(*) AS bundled_consent_rows_before
  FROM public.processing_policy_versions p
  JOIN public.processing_policy_purposes pp ON pp.policy_id = p.id
 WHERE p.status = 'active'
   AND pp.lawful_basis_code = 'consent'
   AND pp.required_for_core_service IS TRUE;


-- ── STEP 1 · register ───────────────────────────────────────────────────

WITH c AS (SELECT
$terms$WillpowerLab — Terms of Service
Version 3.0. Effective 23 September 2026.

These terms are an agreement between you and Artur Willoński, operating under
the name "WillpowerLab" from Poland ("WillpowerLab", "we", "us"). They govern
your use of willpowerlab.com and the WillpowerLab application.

Version 3.0 replaces every earlier version. Earlier versions required you to
agree that your practice data could be used to train models shared with other
users. Version 3.0 does not ask for that and does not permit it. Your
recordings are processed to deliver your own coaching, and for nothing else.


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
Version 3.0. Effective 23 September 2026.

This policy explains what WillpowerLab does with your personal data, who else
receives it, how long we keep it, and how you get it deleted.

Version 3.0 replaces every earlier version. Earlier versions required you to
agree that your practice data could be used to train models shared with other
users. Version 3.0 removes that entirely. Your recordings are used to deliver
your own coaching. They are not pooled with other users' data and they are not
used to train models.


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
Ideal Text and your feedback, have a WillpowerLab coach review that feedback and
prepare practice for you, and keep all of it available to you.
Legal basis: performance of our contract with you (Article 6(1)(b) GDPR). This
processing is what the service is; we cannot provide it without doing this.
WillpowerLab is hybrid coaching — automated work and a human coach together —
so the coach's review sits inside this basis rather than beside it. That basis
covers delivering your coaching and nothing else: it does not cover training
models, analytics about you, or advertising, none of which we do.

To keep the service secure and working: fraud and abuse prevention, debugging,
protecting the service and its users.
Legal basis: our legitimate interests (Article 6(1)(f) GDPR).

To meet our legal obligations: for example accounting records, and responding
to lawful requests.
Legal basis: legal obligation (Article 6(1)(c) GDPR).

If you take a paid plan, your payment is handled by Stripe. We never see or
store your card details; we hold the record that a plan is active and the
invoices we are required to keep. We do not use anyone's recordings to train
models. That one is not a promise we could quietly walk back: our systems
refuse to register any processing policy that would permit it.

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
review the feedback you were given and to prepare practice for you. This is
part of the service rather than an extra you switch on, because WillpowerLab is
hybrid coaching; the Terms say so in section 1 and section 11, and how many
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

I understand that WillpowerLab is hybrid coaching, and that a WillpowerLab coach — a person — may listen to my recordings in order to review my feedback and prepare practice for me. That is part of the service, not an extra I am switching on.$agree$ AS agree)

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
    'version','founder-2026-09-23',
    'approving_authority','founder',
    'approved_at', now(),
    'object_key','legal/provisional/product-legal-2026-09-23.md',
    'sha256', encode(extensions.digest('product-legal-2026-09-23','sha256'),'hex'),
    'metadata', jsonb_build_object(
      'counsel_review','confirmed_by_correspondence_2026-09-23',
      'counsel_signed_letter','pending')
  ),
  jsonb_build_object(
    'artifact_kind','power_score_classification',
    'version','founder-2026-09-23',
    'approving_authority','founder',
    'approved_at', now(),
    'object_key','legal/provisional/classification-2026-09-23.md',
    'sha256', encode(extensions.digest('classification-2026-09-23','sha256'),'hex'),
    -- The 2026-08-29 contract, asserted where the schema checks it. All three
    -- remain honestly false: nothing infers sex, nothing identifies a speaker,
    -- and counsel confirmed on 2026-09-23 that this is not an emotion
    -- recognition system under Art 3(39).
    'metadata', jsonb_build_object(
      'counsel_review','confirmed_by_correspondence_2026-09-23',
      'counsel_signed_letter','pending',
      'biometric_identification', false,
      'sex_gender_inference', false,
      'emotion_intention_inference', false,
      'pipeline_version','voice-confidence-universal-v3')
  ),
  jsonb_build_object(
    'artifact_kind','article_50_assessment',
    'version','founder-2026-09-23',
    'approving_authority','founder',
    'approved_at', now(),
    'object_key','legal/provisional/article50-2026-09-23.md',
    'sha256', encode(extensions.digest('article50-2026-09-23','sha256'),'hex'),
    'metadata', jsonb_build_object(
      'counsel_review','confirmed_by_correspondence_2026-09-23',
      'counsel_signed_letter','pending')
  ),
  -- EVERY purpose reads its five control fields back from the registry. See
  -- "THE TRAP THIS SCRIPT AVOIDS" above: they are all operational since
  -- 2026-09-20, and one character of drift raises
  -- PURPOSE_CONTROL_VERSION_CONFLICT and fails the whole publish.
  --
  -- lawful_basis_code and required_for_core_service are the two fields NOT read
  -- back, because they are what this publish changes: 'consent' becomes
  -- 'contract' on every purpose, which is what takes bundled_consent_rows to 0.
  (SELECT jsonb_agg(jsonb_build_object(
      'purpose_id', r.id,
      'lawful_basis_code','contract',
      'required_for_core_service', true,
      'capability_version', r.capability_version,
      'reviewed_at', r.reviewed_at,
      'retention_control_version', r.retention_control_version,
      'deletion_control_version', r.deletion_control_version,
      'rights_control_version', r.rights_control_version)
      ORDER BY r.id)
     FROM public.processing_purpose_registry r
    WHERE r.phase = 'phase1'
      AND r.id IN ('recording_voice_processing','transcription_feedback',
                   'individual_learning_profile','coach_review',
                   'personalized_exercise_recommendation')),
  'founder:artur@willonski.com'
) FROM c;

-- ── STEP 2 · activate ───────────────────────────────────────────────────

SELECT public.activate_phase1_policy_v1(
  'phase1-2026-09-23',
  'founder:artur@willonski.com',
  encode(extensions.digest('phase1-activation-2026-09-23','sha256'),'hex')
);

-- ── STEP 3 · verify — run all four, read all four ───────────────────────

-- 3a. THE ONE THAT MATTERS. Must return 0. It was 5 before this script.
SELECT count(*) AS bundled_consent_rows
  FROM public.processing_policy_versions p
  JOIN public.processing_policy_purposes pp ON pp.policy_id = p.id
 WHERE p.status = 'active'
   AND pp.lawful_basis_code = 'consent'
   AND pp.required_for_core_service IS TRUE;

-- 3b. Exactly one active policy, and it is the new one.
SELECT version, status, activated_at
  FROM public.processing_policy_versions
 WHERE status = 'active';

-- 3c. EXACTLY FIVE ROWS, every one of them on 'contract'. Four rows here
--     means STEP 0 was skipped and a purpose was dropped.
SELECT pp.purpose_id, pp.lawful_basis_code, pp.required_for_core_service
  FROM public.processing_policy_versions p
  JOIN public.processing_policy_purposes pp ON pp.policy_id = p.id
 WHERE p.status = 'active'
 ORDER BY pp.purpose_id;

-- 3d. The old policy superseded, not deleted. Expect two rows.
SELECT version, status, activated_at
  FROM public.processing_policy_versions
 ORDER BY activated_at;
