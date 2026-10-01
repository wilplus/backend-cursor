-- Publish Privacy 3.2 and Terms 3.2: the training choice (door 1).
-- Founder approval 2026-10-01 (SPEC-DECISIONS-LOG N15). NOT YET RUN.
--
-- ⚠ RUN BY HAND, ONCE, IN THE SUPABASE SQL EDITOR (service role), step by
-- step. Nothing here runs on merge: this file is deliberately absent from
-- migrations/manifest.txt, like the two scripts before it. Running it IS the
-- signature. The founder approved the copy in chat on 2026-10-01; counsel
-- still has one number to confirm (the six-year consent record), and if it
-- changes before this runs the copy changes for free; afterwards it costs a
-- 3.3 that everyone re-accepts.
--
-- ── WHAT CHANGES, AND WHAT DOES NOT ─────────────────────────────────────
--
-- The copy: terms-3.2.txt and privacy-3.2.txt (legal/phase1-2026.1/copy/),
-- counsel's five fixes of 2026-10-01 applied to 3.1: a text-only training
-- programme a speaker turns on in Settings (Privacy §4a, Terms §8 licence),
-- explicit consent as the basis, a six-year consent record, "we test that
-- our models do not reproduce your text", OpenAI in the US under the SCCs.
-- The AI notice and the agreement screen are the 3.1 bytes, unchanged.
--
-- THE FIVE PROCESSING PURPOSES ARE UNCHANGED, and that is deliberate: the
-- training yes is NOT a Phase-1 purpose. It is recorded in the MLC-2 consent
-- ledger (ml_consent_events, grant_scope training_only, migration 0373) by
-- its own switch, with its own wording and fingerprint, and
-- 'pooled_model_improvement' stays phase2 in processing_purpose_registry:
-- register_phase1_policy_v1 refuses it (PHASE2_PURPOSE_FORBIDDEN) and must.
-- What this policy version does for training is C1: a training yes is
-- refused for anyone who has not accepted THE VERSION THAT INTRODUCED
-- TRAINING, which is this one. So:
--
--   recording_voice_processing            contract   required
--   transcription_feedback                contract   required
--   coach_review                          contract   required
--   personalized_exercise_recommendation  consent    OPTIONAL
--   individual_learning_profile           consent    OPTIONAL
--
-- exactly as phase1-2026-09-23 published them (required_for_core_service on
-- contract only; the optional two refusable; resolve_mlc3_dual_purpose_receipt_v2
-- and accept_phase1_processing_authorization_v2 unchanged and already live).
--
-- ── THE EFFECTIVE DATE ──────────────────────────────────────────────────
--
-- Both copy blocks say "Effective 1 October 2026": the day the founder ran
-- it (the first run, with the placeholder [[EFFECTIVE DATE]] still in the
-- text, registered nothing and stopped at STEP 2 with POLICY_NOT_APPROVED,
-- as designed). The 2026-09-24 lesson: activate_phase1_policy_v1 stamps
-- activated_at with the moment it runs, so the date in the registered text
-- must be that day. If this runs on ANOTHER day, change the date in both
-- blocks and in the two .txt files first (tests keep them mirrored). STEP 1
-- still registers nothing while a placeholder is in the text (its WHERE
-- clause). The version id stays phase1-2026-10-01 whatever day it runs.
--
-- ── STEP 0 · COUNT THE PURPOSES BEFORE PUBLISHING ANYTHING ──────────────
--
-- Run FIRST, on its own. Expect purposes_resolving = 5, all_operational =
-- true. Anything else: STOP.

SELECT count(*) AS purposes_resolving,
       array_agg(r.id ORDER BY r.id) AS resolved,
       bool_and(r.operational AND r.authorizes_processing) AS all_operational
  FROM public.processing_purpose_registry r
 WHERE r.phase = 'phase1'
   AND r.id IN ('recording_voice_processing','transcription_feedback',
                'coach_review','personalized_exercise_recommendation',
                'individual_learning_profile');

-- ── STEP 1 · register ───────────────────────────────────────────────────

WITH c AS (SELECT
$terms$WillpowerLab — Terms of Service
Version 3.2. Effective 1 October 2026.

These terms are an agreement between you and Artur Willoński, operating under
the name "WillpowerLab" from Poland ("WillpowerLab", "we", "us"). They govern
your use of willpowerlab.com and the WillpowerLab application.

Version 3.2 replaces every earlier version. Under these terms your recordings
are processed to deliver your own coaching and are never used to train models.
One thing is new, and only if you choose it: the words you practise and your
coach's notes on them may train WillpowerLab's own feedback models when you
turn on Help improve WillpowerLab — see section 8 and the Privacy Policy,
section 4a. If anything else changes, it changes in a new version you are
asked to accept — see section 15.


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

  Free         12,000 tokens a month     no coach reviews     no charge
  Practice    150,000 tokens a month     no coach reviews     USD 12 a month
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

We do not use your recordings to train models, and we do not pool your
material with other users' material. The words you practise and your coach's
notes on them are used to train WillpowerLab's own models only if you turn on
Help improve WillpowerLab (Privacy Policy, section 4a), and never for anyone
else.

If you turn on Help improve WillpowerLab, you give us a licence to reproduce
and adapt the words of the passages you practise and your coach's notes on
them, for one purpose only: training the models that write WillpowerLab's
feedback. The licence is non-exclusive and free of charge, it covers no audio,
and it ends when you turn the choice off or delete your account. A model
trained while the licence was in force stays, and we test that it does not
reproduce your text. Everything else in this section is unchanged: your
content stays yours.


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
review the feedback you were given and to prepare practice for you. That part
does not depend on your plan. What your plan sets is how many written reviews
come back to you each month, and section 2 sets out the allowance for each. A
plan with no coach reviews does not mean nobody listens; it means no written
review is returned to you that month. A coach does not see the voice
measurements described in section 3 of the Privacy Policy.

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
Version 3.2. Effective 1 October 2026.

This policy explains what WillpowerLab does with your personal data, who else
receives it, how long we keep it, and how you get it deleted.

Version 3.2 replaces every earlier version. It adds one thing, and only if you
choose it: you can let us use the words you practise and your coach's notes
on them to train the models that write WillpowerLab's feedback. Text only,
never your voice. That choice is off unless you turn it on, it is on its own
screen, and everything else in WillpowerLab works the same without it.
Earlier versions bundled training into the agreement you had to accept; any
yes you gave that way does not count, and nothing recorded under it is used
for training. Section 4a explains the new choice.


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
models, analytics about you, or advertising. We do not do analytics or
advertising. Training happens only with the separate choice in section 4a.

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


4a. HELPING TO IMPROVE WILLPOWERLAB — OPTIONAL

If you turn on Help improve WillpowerLab, we keep separate copies of the words
you practise and of your coach's notes on them, and use them to train the
models that write WillpowerLab's feedback. The switch says exactly that: "Use
my practice text and my coach's notes on it to train the models that write
WillpowerLab's feedback."

What we copy: the words of a passage you practised, as the transcript holds
them, and what your coach wrote about that passage — a praise line, a clearer
version, or the words of an exercise. Text only. Your voice never leaves for
training: no audio is copied, sent or used. Your coach's videos are not part
of it either. Only passages from takes you record while the switch is on are
copied; nothing recorded before you turn it on is.

Legal basis: your consent (Article 6(1)(a) GDPR), given as explicit consent
(Article 9(2)(a) GDPR) because what you say in a practice passage may reveal
sensitive information about you. You give it on its own screen, by turning the
switch on. It is never on when you sign up, never pre-ticked, and never a
condition of using WillpowerLab. Saying no costs you nothing. You can turn it
off at any time.

How long we keep the copies: until you turn the switch off or delete your
account. If you delete a project while the switch is on, the training copies
made from that project stay until you turn the switch off.

When you turn it off: your training copies are deleted, here and at the
provider that trains for us, and you are left out of every training that
starts afterwards. A model already trained stays. We test that our models do
not reproduce your text; a model that fails that test is trained again without
your text.

The record of your choice: we keep the record of when you turned the switch on
and off, including after you delete your account, for six years after you turn
it off or delete your account, and then delete it. It holds identifiers and
timestamps, not your words.

Who trains, and where: OpenAI trains the models for us. Your training copies
are sent to OpenAI in the United States, under the European Commission's
standard contractual clauses, and are deleted there when you turn the switch
off.

5. WHO ELSE RECEIVES YOUR DATA

AI providers

OpenAI receives:
- the audio of your recording, in order to transcribe it;
- parts of your transcript and related text, in order to generate your Ideal
  Text and your feedback.

OpenAI is the only AI provider that receives your audio or your transcript.
Each transfer is made under a short-lived internal permit that records which
operation it was for and the minimum data it was allowed to carry. We do not
authorise OpenAI to use your content to train its models. If you turn on the
choice in section 4a, your training copies are processed by OpenAI to train
WillpowerLab's models, and by no one else.

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
  Limited to process data from the EEA and Switzerland. Training copies
  (section 4a) are transferred to OpenAI in the United States under the same
  clauses.
- Cloudflare: Standard Contractual Clauses. Our storage carries an Eastern
  Europe location hint, which is a preference rather than a guarantee.
- Supabase: Standard Contractual Clauses and a UK addendum. Your data is stored
  in Ireland.
- Railway, Resend, Vercel: Standard Contractual Clauses.
- Sentry: error reports are stored in the European Union.

You can ask us for a copy of the safeguards in place.


7. HOW LONG WE KEEP IT

We keep what you give us for as long as your account is open. When you ask us
to delete something, or when you delete your account, we delete it — section 9
describes what that involves and what survives it.

Recordings, transcripts, Ideal Text, feedback, voice measurements, practice
attempts and account records: kept while your account is open, and deleted
when you ask or when you close it. Voice measurements are deleted together with
the recording they came from and are never kept after it.

Training copies, if you chose to make them (section 4a) — the words of a
practised passage and your coach's notes on it, never audio: kept until you
turn the choice off or delete your account, then deleted here and at OpenAI.

Record of your agreement to this policy: kept for as long as we may need it to
show that your recordings were processed lawfully, and then deleted.

Record of your training choice: kept, including after you delete your account,
for six years after you turn the choice off or delete your account, and then
deleted.

We are not quoting fixed retention periods here. A period in a privacy policy
is a promise that something is deleted on a clock. We would rather tell you
what we actually do than name a number we do not yet enforce. When the
automatic schedule is in place we will publish it, and you will be asked to
accept the version that describes it.

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

Three things survive deletion:

- Records that prove your recordings were processed with your agreement. These
  contain identifiers, timestamps and fingerprints — not your recordings, your
  transcripts or anything you said. We keep them because they are the evidence
  that we handled your data lawfully, and we delete them when we no longer need
  them for that.
- The record of your training choice (section 4a): when you turned it on and
  off. It holds identifiers and timestamps, not your recordings or anything
  you said, and we keep it for six years after you turned it off or deleted
  your account, then delete it.
- Anything we must keep by law, for example accounting records.

Your training copies do not survive an account deletion: they are deleted with
everything else.

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

SELECT public.register_phase1_policy_v1(
  jsonb_build_object(
    'version','phase1-2026-10-01',
    'terms_version','terms-3.2-2026-10-01',
    'terms_copy', c.terms,
    'terms_copy_sha256', encode(extensions.digest(c.terms,'sha256'),'hex'),
    'privacy_version','privacy-3.2-2026-10-01',
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
  -- The three determinations, provisional as on 2026-09-23 (counsel's
  -- signed letters still pending; doc 01 reaches v1.1 with the training
  -- programme before counsel signs). New artifact versions, because the
  -- RPC compares every field of an existing version and approved_at is now().
  jsonb_build_object(
    'artifact_kind','product_legal_approval',
    'version','provisional-founder-2026-10-01',
    'approving_authority','founder:artur@willonski.com',
    'approved_at', now(),
    'object_key','legal/phase1-2026.1/01-product-legal-approval-v1.1.pdf',
    'sha256', encode(extensions.digest('provisional-legal-2026-10-01','sha256'),'hex'),
    'metadata', jsonb_build_object('counsel_review','answered_by_correspondence_2026-10-01',
      'unbundled','true','supersedes','provisional-founder-2026-09-23',
      'coach_review_basis','contract',
      'training_basis','consent_6_1_a_with_9_2_a_in_the_mlc2_ledger',
      'founder_ruling','2026-10-01 Privacy 3.2 and Terms 3.2 approved; door 1 opened')),
  jsonb_build_object(
    'artifact_kind','power_score_classification',
    'version','provisional-founder-2026-10-01',
    'approving_authority','founder:artur@willonski.com',
    'approved_at', now(),
    'object_key','phase1-2026.1/legal/power-score-classification-v1.0.pdf',
    'sha256', encode(extensions.digest('provisional-power-2026-10-01','sha256'),'hex'),
    'metadata', jsonb_build_object(
      'counsel_review','confirmed_by_correspondence_2026-09-23',
      'counsel_signed_letter','pending',
      'biometric_identification', false,
      'sex_gender_inference', false,
      'emotion_intention_inference', false,
      'pipeline_version','voice-confidence-universal-v3')),
  jsonb_build_object(
    'artifact_kind','article_50_assessment',
    'version','provisional-founder-2026-10-01',
    'approving_authority','founder:artur@willonski.com',
    'approved_at', now(),
    'object_key','phase1-2026.1/legal/article-50-assessment-v1.0.pdf',
    'sha256', encode(extensions.digest('provisional-article50-2026-10-01','sha256'),'hex'),
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
) FROM c
 WHERE position('[[EFFECTIVE DATE]]' in c.terms) = 0
   AND position('[[EFFECTIVE DATE]]' in c.privacy) = 0;

-- ── STEP 2 · activate ───────────────────────────────────────────────────
--
-- Retires phase1-2026-09-23 and writes carryovers for any job in flight,
-- which activate_phase1_policy_v1 does on its own. From this moment every
-- speaker is asked to accept 3.2 ("What's changed since you agreed"), and
-- only those who have can turn the training switch on (C1).

SELECT public.activate_phase1_policy_v1(
  'phase1-2026-10-01',
  'founder:artur@willonski.com',
  encode(extensions.digest('phase1-activation-2026-10-01','sha256'),'hex')
);

-- ── STEP 3 · verify the shape ───────────────────────────────────────────
--
-- Expect ONE row: version phase1-2026-10-01, five purposes, required = 3,
-- optional = 2, bases = {consent, contract}.

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
-- Expect ZERO rows.

SELECT pp.purpose_id, pp.lawful_basis_code, pp.required_for_core_service
  FROM public.processing_policy_versions p
  JOIN public.processing_policy_purposes pp ON pp.policy_id = p.id
 WHERE p.status = 'active'
   AND pp.lawful_basis_code = 'consent'
   AND pp.required_for_core_service;

-- ── STEP 5 · verify the optional purposes are genuinely refusable ───────
--
-- Expect exactly TWO rows, both consent, both required_for_core_service =
-- false.

SELECT pp.purpose_id, pp.lawful_basis_code, pp.required_for_core_service
  FROM public.processing_policy_versions p
  JOIN public.processing_policy_purposes pp ON pp.policy_id = p.id
 WHERE p.status = 'active'
   AND NOT pp.required_for_core_service;

-- ── STEP 6 · verify the published text carries the training choice ──────
--
-- Expect ONE row with both counts = 1: the active policy's privacy copy
-- holds section 4a and its terms copy the licence, and neither still holds
-- the placeholder.

SELECT p.version,
       (position('4a. HELPING TO IMPROVE WILLPOWERLAB' in p.privacy_copy) > 0)::int AS privacy_has_4a,
       (position('you give us a licence to reproduce' in p.terms_copy) > 0)::int AS terms_has_licence,
       (position('[[EFFECTIVE DATE]]' in p.privacy_copy || p.terms_copy) > 0) AS placeholder_left
  FROM public.processing_policy_versions p
 WHERE p.status = 'active';

-- ── STEP 7 · the coaching rollout re-point: NO LONGER NEEDED ────────────
--
-- The 3.1 publish needed scripts/mlc3_repoint_rollout_to_active_policy.sql
-- afterwards, because the MLC-3 coaching rollout kept requiring the policy
-- it was registered against. That service loop was retired on 2026-09-30
-- (ML-15, #830): its routes answer 410 and the script is gone. Nothing else
-- binds to a processing policy version; a speaker who re-accepts simply
-- carries on.
--
-- ── STEP 8 · what comes after, on the training side ─────────────────────
--
-- This version is the twelfth argument of the training policy registration
-- (configure_mlc2_training_consent_policy_v1, docs/LEARNING-DOORS.md):
-- 'phase1-2026-10-01'. That registration also needs the signed wording
-- PDF's hash. Once both are in, the Settings card appears for everyone who
-- has accepted 3.2, off, with the four lines above it.
