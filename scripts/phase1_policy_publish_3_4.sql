-- Publish Privacy 3.4 and Terms 3.4: practice becomes part of the service.
-- Founder 2026-10-06 (SPEC-DECISIONS-LOG N55, WQ3a B) and 2026-10-08 (N66.2):
-- "I sign off on it all!", then "text signed" on the exact text, in chat.
-- COUNSEL'S REVIEW WAS NOT OBTAINED: the founder signed in its place, and
-- the product legal artifact's metadata says so
-- (practice_counsel_review = not_obtained_founder_signed_in_place_2026-10-08).
--
-- ⚠ RUN BY HAND, ONCE, IN THE SUPABASE SQL EDITOR (service role), step by
-- step. Nothing here runs on merge: this file is deliberately absent from
-- migrations/manifest.txt, like the four scripts before it. Running it IS
-- the publication. RUN IT ONLY AFTER migration 0451
-- (practice_is_part_of_the_service.sql) is live: without 0451 every practice
-- gate would read practice as off for every speaker on 3.4.
--
-- ── WHAT CHANGES, AND WHAT DOES NOT ─────────────────────────────────────
--
-- The copy: terms-3.4.txt and privacy-3.4.txt (legal/phase1-2026.1/copy/),
-- 3.3 with only the practice passages changed:
--   · both version notes say what changed;
--   · Privacy §4: practice moves from consent (6(1)(a)) to contract
--     (6(1)(b)); skipping any exercise stays free; "Do you have to provide
--     this data?" loses the practice exception;
--   · Privacy §4 and §6, Terms §11: the coach's blind accuracy check, whose
--     only off switch was Personalised practice, now ends on a written
--     objection to contact@willpowerlab.com (recorded by 0451's
--     blind_check_objections);
--   · Terms §11: "Practice is optional" becomes "Practice is part of the
--     service".
-- NOT in 3.4: the packages rewrite of Terms §2 (N44.4), still unsigned.
-- The AI notice and the agreement screen are the 3.1 bytes, unchanged.
--
-- THE FIVE PROCESSING PURPOSES. The three required ones are unchanged. The
-- two practice purposes (personalized_exercise_recommendation,
-- individual_learning_profile) become 'contract' and required, so the policy
-- has no optional purpose: the acceptance screen shows no practice tick
-- (frontend #660) and the accept RPC refuses one. Read back from the
-- registry, never retyped.
--
-- ── THE EFFECTIVE DATE ──────────────────────────────────────────────────
--
-- Both texts say "Effective [[EFFECTIVE DATE]]" until the founder names the
-- day he runs this. STEP 1 registers NOTHING while a placeholder is in either
-- text (its WHERE clause). activate_phase1_policy_v1 stamps activated_at
-- with the moment it runs, so the date must be that day: set it in this
-- file AND in the two copy files, to the same bytes, in a reviewed change.
-- The version id stays phase1-2026-10-08 whatever day it runs.
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
Version 3.4. Effective [[EFFECTIVE DATE]].

These terms are an agreement between you and Artur Willoński, operating under
the name "WillpowerLab" from Poland ("WillpowerLab", "we", "us"). They govern
your use of willpowerlab.com and the WillpowerLab application.

Version 3.4 replaces every earlier version. It makes practice part of the
service rather than a separate choice (section 11). Under these terms your
recordings are processed to deliver your own coaching and are never used to
train models.
Two things are yours to choose, and both are off unless you choose them: the
words you practise and your coach's notes on them may train WillpowerLab's own
feedback models when you turn on Help improve WillpowerLab (section 8 and the
Privacy Policy, section 4a), and a short clip of a recording may be played to
other users when you lend that recording (section 8 and the Privacy Policy,
section 4b). A coach may also hear a short clip of a recording to check our
automated listening (section 11). If anything else changes, it changes in a
new version you are asked to accept — see section 15.


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

If you turn on lending for a recording (Privacy Policy, section 4b), you
give us permission to play a short clip of that recording to other users,
without your name or your words, for one purpose: letting them judge or
listen to how it sounds. The permission is per recording, free of charge,
and ends the moment you turn it off. Everything else in this section is
unchanged: your content stays yours.


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

A coach may also hear a short clip of a recording in order to check our
automated listening, without being told what it found and without seeing
who you are. That check is described in section 4 of the Privacy Policy, and
you can object to it at any time as that section says.

Practice is part of the service. After your feedback you may be offered a
short exercise chosen for your recording and the chance to re-record a
fragment, and the app remembers what you have been working on so that later
exercises suit you better. Doing an exercise is always up to you: you can skip
any of them, and skipping changes nothing else about your account.

Your recording and feedback loop never waits for a coach. You record, you get
your transcript, your Ideal Text and your feedback, and you record again — all
of it without a person in the way.

We are stating this plainly because it is the kind of thing people assume does
not happen.

Other users hear a recording of yours only if you lend it (Privacy Policy,
section 4b); nothing in this section lends anything for you.


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
Version 3.4. Effective [[EFFECTIVE DATE]].

This policy explains what WillpowerLab does with your personal data, who else
receives it, how long we keep it, and how you get it deleted.

Version 3.4 replaces every earlier version. It changes one thing: practice
is now part of the service rather than a separate choice. After your feedback
the app may offer you a short exercise chosen for your recording, and it
remembers what you have been working on so that later exercises suit you
better; section 4 describes it. If you had turned Personalised practice off,
accepting this version turns practice back on for you. Doing an exercise is
still up to you every time: you can skip any of them. Because the switch for
practice goes, the coach's accuracy check in section 4 no longer has a switch
of its own either; you can object to it by writing to us, as section 4 says.
Everything else is unchanged: the training choice in section 4a is off unless
you turn it on, text only, never your voice, and lending a recording (section
4b) happens only if you choose it for that recording.


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

Other users never hear your voice unless you lend a particular recording to
them yourself, as section 4b describes.


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

To check that our automated listening is right: from time to time a
WillpowerLab coach — a person — hears a short clip of a recording and answers
one question about one speaking pattern, for example whether the words sound
rushed, without being told what our software found. The answer is used only
to check and correct the software that chooses your feedback. The coach does
not see your name, your words or anything about you, and the answer is never
shown to you or used as feedback.
Legal basis: our legitimate interest in keeping the tool accurate (Article
6(1)(f) GDPR). You can object to it at any time by writing to
contact@willpowerlab.com: from then on no clip of yours is chosen for a check.
Objecting costs you nothing else.

Practice, and making it personal: choosing a short exercise that fits your
recording, keeping the fragment you re-record, and remembering what you have
been working on so that later exercises suit you better.
Legal basis: performance of our contract with you (Article 6(1)(b) GDPR).
Practice is part of what WillpowerLab is, alongside your feedback, so it is no
longer a separate choice. Doing an exercise is always up to you: you can skip
any exercise, and skipping costs you nothing.

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
service. Practice is part of the service too, though doing any one exercise
is always up to you.

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

4b. LENDING A RECORDING TO OTHER USERS — OPTIONAL, PER RECORDING

You can let other WillpowerLab users hear one short clip of your voice, one
recording at a time. It is off unless you turn it on for that recording, and
you can turn it off again at any time.

What others hear and do: a clip of a few seconds, with no name, no words on
screen and nothing about you. A listener answers one question about how
assured the clip sounds, or simply listens to it as an example. If you
practised that moment, the practised version may be played the same way.
Their answers help settle, together with a coach's, whether that moment
belongs in your Voice Album; no listener learns who you are, and you never
learn who listened.

Legal basis: your explicit consent (Article 9(2)(a) GDPR), given per
recording by the switch itself. Turning it off withdraws it for that
recording: the clip leaves every place it could be heard at once. Nothing
you did before is affected, and nothing else in your account changes.

Your own answers as a listener: when you answer a question about someone
else's clip, that answer is about their voice and it is also your own data.
It stays tied to your account, you can ask us for a copy of it (section 8),
and it is deleted when you delete your account.


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
review the feedback you were given and to prepare practice for you. The review
is part of the service rather than an extra you
switch on, because WillpowerLab is hybrid coaching; the Terms say so in section 1 and section 11, and how many
reviews you receive each month depends on your plan. A coach who reviews your
recording does not see the voice measurements described in section 3. Coaches
are bound to confidentiality and see only what a review requires.
A coach may also hear a short clip of a recording to check our automated
listening, as section 4 describes, unless you have objected to it.

Other users
If you lend a recording (section 4b), other WillpowerLab users hear that
clip, without your name or your words. Nobody else does.

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
A coach's answer in a blind check is deleted together with the recording it
was about, and never kept after it.

A recording you lent stops being heard by others the moment you turn the
switch off, and is deleted with the recording like everything else.
Your answers about other users' clips are kept while your account is open
and deleted when you delete it.

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
    'version','phase1-2026-10-08',
    'terms_version','terms-3.4-2026-10-08',
    'terms_copy', c.terms,
    'terms_copy_sha256', encode(extensions.digest(c.terms,'sha256'),'hex'),
    'privacy_version','privacy-3.4-2026-10-08',
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
  -- The three determinations, provisional as on 2026-10-01: new artifact
  -- versions, because the RPC compares every field of an existing version
  -- and approved_at is now(). Document 02 reached v1.1 on 2026-10-02 (the
  -- speaking-error detectors in scope; the founder's own determination, not
  -- counsel-reviewed); its signed PDF is registered by its own hash under
  -- (power_score_classification, 1.1) once uploaded, never by editing a row.
  jsonb_build_object(
    'artifact_kind','product_legal_approval',
    'version','provisional-founder-2026-10-08',
    'approving_authority','founder:artur@willonski.com',
    'approved_at', now(),
    'object_key','legal/phase1-2026.1/01-product-legal-approval-v1.1.pdf',
    'sha256', encode(extensions.digest('provisional-legal-2026-10-08','sha256'),'hex'),
    'metadata', jsonb_build_object('counsel_review','answered_by_correspondence_2026-10-01',
      'unbundled','true','supersedes','provisional-founder-2026-10-02',
      'coach_review_basis','contract',
      'practice_basis','contract_6_1_b_N55_WQ3a_B',
      'practice_counsel_review','not_obtained_founder_signed_in_place_2026-10-08',
      'blind_check_basis','legitimate_interest_6_1_f_with_written_objection',
      'lending_basis','explicit_consent_9_2_a_per_recording',
      'training_basis','consent_6_1_a_with_9_2_a_in_the_mlc2_ledger',
      'founder_ruling','2026-10-08 Privacy 3.4 and Terms 3.4 signed in chat (N66.2)')),
  jsonb_build_object(
    'artifact_kind','power_score_classification',
    'version','provisional-founder-2026-10-08',
    'approving_authority','founder:artur@willonski.com',
    'approved_at', now(),
    'object_key','phase1-2026.1/legal/power-score-classification-v1.1.pdf',
    'sha256', encode(extensions.digest('provisional-power-2026-10-08','sha256'),'hex'),
    'metadata', jsonb_build_object(
      'counsel_review','founder_determination_not_counsel_reviewed',
      'document_version','1.1 signed 2026-10-02',
      'biometric_identification', false,
      'sex_gender_inference', false,
      'emotion_intention_inference', false,
      'pipeline_version','voice-confidence-universal-v3',
      'detector_versions', jsonb_build_object('rushing','rules-v1',
        'word_compression','rules-v1','ending_compression','rules-v1'))),
  jsonb_build_object(
    'artifact_kind','article_50_assessment',
    'version','provisional-founder-2026-10-08',
    'approving_authority','founder:artur@willonski.com',
    'approved_at', now(),
    'object_key','phase1-2026.1/legal/article-50-assessment-v1.0.pdf',
    'sha256', encode(extensions.digest('provisional-article50-2026-10-08','sha256'),'hex'),
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
    -- ── REQUIRED, CONTRACT, SINCE 3.4. Art 6(1)(b). ──────────────────────
    -- Founder 2026-10-06 (N55, WQ3a B, against Claude's pick) and 2026-10-08
    -- (N66.2): practice is part of what people sign up for, no longer a
    -- consent choice. Counsel's review was not obtained; the founder signed
    -- the text in its place. Skipping any one exercise stays free (Privacy
    -- §4), and the loop never waits for an exercise (LIVE LOOP).
    (SELECT jsonb_build_object('purpose_id', r.id,
      'lawful_basis_code','contract','required_for_core_service',true,
      'capability_version', r.capability_version,
      'reviewed_at', r.reviewed_at,
      'retention_control_version', r.retention_control_version,
      'deletion_control_version', r.deletion_control_version,
      'rights_control_version', r.rights_control_version)
      FROM public.processing_purpose_registry r
     WHERE r.id = 'personalized_exercise_recommendation'),
    -- It personalises the exercises (founder 2026-09-23); it serves practice,
    -- so it shares practice's basis: contract, required, since 3.4.
    (SELECT jsonb_build_object('purpose_id', r.id,
      'lawful_basis_code','contract','required_for_core_service',true,
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
-- Retires phase1-2026-10-02 and writes carryovers for any job in flight,
-- which activate_phase1_policy_v1 does on its own. From this moment every
-- speaker is asked to accept 3.4 ("What's changed since you agreed"). The
-- acceptance screen reads optional_purposes, now empty: no practice tick,
-- "Two things to confirm", and Data & consent shows no practice card
-- (frontend #660). Practice reads as on for every 3.4 receipt (0451). The
-- training switch carries over as for 3.3.

SELECT public.activate_phase1_policy_v1(
  'phase1-2026-10-08',
  'founder:artur@willonski.com',
  encode(extensions.digest('phase1-activation-2026-10-08','sha256'),'hex')
);

-- ── STEP 3 · verify the shape ───────────────────────────────────────────
--
-- Expect ONE row: version phase1-2026-10-08, five purposes, required = 5,
-- optional = 0, bases = {contract}.

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

-- ── STEP 5 · verify practice reads as part of the service ───────────────
--
-- Expect ONE row: practice_in_service = true, optional_purposes = [].
-- (0451 must be applied; it is, once its PR is merged and deployed.)

SELECT public.get_phase1_consent_choices_v1(
         (SELECT id FROM public.owner_principals
           WHERE user_id = (SELECT id FROM auth.users
                             WHERE email = 'artur@willonski.com'))
       ) -> 'practice_in_service' AS practice_in_service,
       public.get_phase1_consent_choices_v1(
         (SELECT id FROM public.owner_principals
           WHERE user_id = (SELECT id FROM auth.users
                             WHERE email = 'artur@willonski.com'))
       ) -> 'optional_purposes' AS optional_purposes;

-- ── STEP 6 · verify the published text carries the change ───────────────
--
-- Expect ONE row with all four counts = 1 and placeholder_left = false.

SELECT p.version,
       (position('Legal basis: performance of our contract with you (Article 6(1)(b) GDPR).
Practice is part of what WillpowerLab is' in p.privacy_copy) > 0)::int AS privacy_practice_is_service,
       (position('You can object to it at any time by writing to' in p.privacy_copy) > 0)::int AS privacy_blind_check_objection,
       (position('Practice is part of the service. After your feedback' in p.terms_copy) > 0)::int AS terms_practice_is_service,
       (position('you can object to it at any time as that section says' in p.terms_copy) > 0)::int AS terms_blind_check_objection,
       (position('[[EFFECTIVE DATE]]' in p.privacy_copy || p.terms_copy) > 0) AS placeholder_left
  FROM public.processing_policy_versions p
 WHERE p.status = 'active';

-- ── STEP 7 · what comes after ────────────────────────────────────────────
--
-- Nothing else flips. PEER_SHARE_POLICY_VERSION, BLIND_CHECK_POLICY_VERSION
-- and COMMUNITY_SHARE_POLICY_VERSION (config.py) name phase1-2026-10-02 and
-- compare `>=`, so a 3.4 receipt satisfies them. Until a speaker accepts 3.4
-- they are asked to, as for every new version. An objection to the blind
-- check is recorded with scripts/record_blind_check_objection.sql.
