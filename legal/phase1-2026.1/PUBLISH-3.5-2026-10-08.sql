-- ════════════════════════════════════════════════════════════════════════
-- PUBLISH 3.5 — Privacy 3.5, Terms 3.5, and the training switch wording v2
-- One block for the Supabase SQL editor. Founder, 8 October 2026.
-- ════════════════════════════════════════════════════════════════════════
--
-- What you signed (decisions log N68, SIGN-3.5-2026-10-08.md): Privacy 3.5,
-- Terms 3.5 and training wording v2, with D3: "a v1 yes counts as off until
-- given again". This block does three things in ONE transaction, so either
-- all of it happens or none of it does:
--
--   1. publishes Privacy 3.5 and Terms 3.5 as processing policy
--      phase1-2026-10-08-3.5, exactly the way 3.4 was published
--      (scripts/phase1_policy_publish_3_4.sql): register, then activate.
--      From that moment every speaker is asked to accept 3.5.
--   2. at the same instant, retires training wording v1 (training-only-v1)
--      and registers v2 (training-only-v2), with the function migration 0458
--      added (supersede_mlc2_training_consent_policy_v1). From that instant
--      every yes given under v1 reads as off everywhere; nothing is deleted,
--      the record of every yes stays. A speaker can say yes again after
--      accepting 3.5 (the database refuses a yes before that).
--   3. shows you a one-row check at the end.
--
-- ── BEFORE YOU RUN IT (all four, or do not run it) ───────────────────────
--
--   a. Migration 0458 (a_new_training_wording_retires_the_old.sql) is merged
--      and deployed. The block stops at the start if it is not.
--   b. The frontend PR with the eight signed lines above the switch is
--      deployed. (The switch sentence itself comes from this block; the
--      eight lines come from the frontend. If v2 goes live first, the card
--      shows the new sentence under the old four lines.)
--   c. You signed the PDF of document 23 (PAdES) and uploaded it to
--      phase1-2026.1/legal/training-consent-wording-v2.pdf, and its SIGNED
--      hash is in SIGNED-ARTIFACTS.md.
--   d. You replaced the ONE placeholder below, <SIGNED_PDF_SHA256_OF_23>,
--      with that signed hash: 64 characters, 0-9 and a-f, nothing else.
--      Not the unsigned render's hash (8472440c…): the block refuses that.
--
-- The effective date. Both texts say "Effective 8 October 2026". Run this
-- block on 8 October 2026. On another day, change the date in this file AND
-- in legal/phase1-2026.1/copy/privacy-3.5.txt and terms-3.5.txt first, to
-- the same bytes (engineering does this for you; ask).
--
-- If anything fails, Postgres undoes the whole block: nothing is published,
-- nothing is retired. Read the error, stop, and send it to engineering.
--
-- ── STEP 0 · LOOK FIRST (a dry run; changes nothing) ─────────────────────
--
-- The SQL editor shows only the LAST result of a run. To see this one,
-- select just this SELECT (down to its semicolon) and press Run on its own.
-- Expect: processing_policy_in_force = phase1-2026-10-08 (3.4),
-- training_policies_in_force = {training-only-v1}, the_0458_function_exists
-- = true, active_training_copies_under_v1 = 0 (it counts every copy under a
-- v1 yes not yet purged, as 0458 does). The two "yes" counts tell
-- you how many people will be asked to say yes again.

SELECT
  (SELECT string_agg(version, ', ') FROM public.processing_policy_versions
    WHERE status = 'active') AS processing_policy_in_force,
  (SELECT array_agg(version ORDER BY version) FROM public.ml_consent_policies
    WHERE grant_scope = 'training_only' AND active_from <= now()
      AND (retired_at IS NULL OR retired_at > now())) AS training_policies_in_force,
  to_regprocedure('public.supersede_mlc2_training_consent_policy_v1(text, text, '
    || 'text, text, text, text, text, text, timestamptz, text[], text, text, '
    || 'text, timestamptz)') IS NOT NULL AS the_0458_function_exists,
  (SELECT count(*) FROM public.training_consent_active_grants
    WHERE consent_policy_version = 'training-only-v1') AS people_with_a_v1_yes_now,
  (SELECT count(*) FROM public.training_consent_active_grants) AS people_with_any_yes_now,
  (SELECT count(*) FROM public.training_corpus_items item
     JOIN public.ml_consent_events e ON e.id = item.training_grant_event_id
    WHERE e.consent_policy_version = 'training-only-v1'
      AND item.state <> 'purged') AS active_training_copies_under_v1;

-- ════════════════════════════════════════════════════════════════════════
-- From here on: the publication. Run the whole file (or everything from
-- BEGIN to COMMIT). It is one transaction.
-- ════════════════════════════════════════════════════════════════════════

BEGIN;

-- ── STEP 1 · stop now if anything is not as expected ─────────────────────
-- Plain checks; each one stops the whole block with a message saying why.

DO $$
BEGIN
  IF to_regprocedure('public.supersede_mlc2_training_consent_policy_v1(text, '
       || 'text, text, text, text, text, text, text, timestamptz, text[], '
       || 'text, text, text, timestamptz)') IS NULL THEN
    RAISE EXCEPTION 'STOP: migration 0458 is not applied yet. Merge and deploy it first.';
  END IF;
  IF (SELECT string_agg(version, ',') FROM public.processing_policy_versions
       WHERE status = 'active') IS DISTINCT FROM 'phase1-2026-10-08' THEN
    RAISE EXCEPTION 'STOP: the policy in force is not 3.4 (phase1-2026-10-08).';
  END IF;
  IF EXISTS (SELECT 1 FROM public.processing_policy_versions
              WHERE version = 'phase1-2026-10-08-3.5') THEN
    RAISE EXCEPTION 'STOP: 3.5 (phase1-2026-10-08-3.5) is already registered.';
  END IF;
  IF (SELECT array_agg(version) FROM public.ml_consent_policies
       WHERE grant_scope = 'training_only'
         AND (retired_at IS NULL OR retired_at > now()))
     IS DISTINCT FROM ARRAY['training-only-v1'] THEN
    RAISE EXCEPTION 'STOP: training-only-v1 is not the one training wording in force.';
  END IF;
END;
$$;

-- ── STEP 2 · register 3.5 (as 3.4 was) ───────────────────────────────────
-- The four texts, byte for byte: Terms 3.5 and Privacy 3.5 from
-- legal/phase1-2026.1/copy/ (sha256 38c4b8e4… and 55b8ffe5…, as signed),
-- and the AI notice and the agreement unchanged since 3.1.

WITH c AS (SELECT
$terms$WillpowerLab — Terms of Service
Version 3.5. Effective 8 October 2026.

These terms are an agreement between you and Artur Willoński, operating under
the name "WillpowerLab" from Poland ("WillpowerLab", "we", "us"). They govern
your use of willpowerlab.com and the WillpowerLab application.

Version 3.5 replaces every earlier version. It widens the training choice
(section 8) and asks you for it again. Under these terms the sound of your
recordings is processed to deliver your own coaching and is never used to
train models.
Two things are yours to choose, and both are off unless you choose them: your
practice text, your coach's words and answers about it, and measurements of
your practice may train the models that give every WillpowerLab speaker
feedback when you turn on Help improve WillpowerLab (section 8 and the Privacy
Policy, section 4a), and a short clip of a recording may be played to
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

We do not use the sound of your recordings to train models. Your practice
text, your coach's words and answers about it, and measurements of your
practice are used to train WillpowerLab's own models, together with other
speakers' who said yes, only if you turn on Help improve WillpowerLab (Privacy
Policy, section 4a), and never for anyone else.

If you turn on Help improve WillpowerLab, you give us a licence to reproduce
and adapt the words of the passages you practise, for two purposes only:
training the models that give WillpowerLab's feedback, and using those models
to write feedback for every WillpowerLab speaker. The licence is non-exclusive
and free of charge, it covers no audio, and it ends when you turn the choice
off or delete your account. A model trained while the licence was in force
stays and may still be used, and we test that it does not reproduce your text.
What your coach writes is not yours to license: our agreement with each coach
covers it. Everything else in this section is unchanged: your content stays
yours.

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

If you turn on Help improve WillpowerLab, a coach may also hear a short moment
of a recording and sometimes read its words, without your name, to answer a
question that teaches our software which moments to give feedback on (Privacy
Policy, section 4a). The answer is never shown to you and never changes your
feedback.

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
Version 3.5. Effective 8 October 2026.

This policy explains what WillpowerLab does with your personal data, who else
receives it, how long we keep it, and how you get it deleted.

Version 3.5 replaces every earlier version. It widens one choice, Help
improve WillpowerLab (section 4a), and asks you for it again. With your yes,
everything your coach writes about your practice, including their line on a
moment and their word for a take, joins your practice text in training; the
models trained on it write feedback for every WillpowerLab speaker; and a
coach's answers about your clips, numbers measured from your practice and
whether an exercise helped you may teach the software that spots speaking
patterns, chooses feedback moments and orders exercises. No recording of your
voice, and no clip of one, is ever copied or sent for training. A yes you gave
under an earlier version does not carry over: it covered less, so it counts
as off until you say yes again. Section 4c is new: it is for people whose
voices are in recordings we import for training. Everything else is
unchanged: practice stays part of the service, and lending a recording
(section 4b) happens only if you choose it for that recording.


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
- Whether a fragment you re-recorded after an exercise came out better.

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

If you turn on the choice in section 4a, some of these measurements, taken
from a clip a coach has answered a question about, may also help tune the
software that spots speaking patterns for everyone: your pace, your pauses,
and how long your words and sentence endings last. What the software keeps is
settings learned from many people, not your measurements. Without your yes
your measurements are never used beyond your own recordings.

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
shown to you or used as feedback. If you have turned on the choice in section
4a, the answer may also be used to tune that software, as section 4a says.
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
invoices we are required to keep.

We never use the sound of anyone's recordings to train models: no recording,
and no clip of one, is copied or sent for training. What may be used for
training, and only with your yes, is set out in section 4a. Recordings we
import from elsewhere are covered in section 4c.

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

If you turn on Help improve WillpowerLab, we use your practice text, what your
coach writes and answers about it, and measurements of your practice to train
the models that give feedback to every WillpowerLab speaker. The switch says
exactly that: "Use my practice text, my coach's words and answers about it, and measurements of my practice to train the models that give every WillpowerLab speaker feedback."

What we use, and what for:

- Your practice text and your coach's words. The words of a passage you
  practised, as the transcript holds them, and what your coach wrote about it:
  a praise line, a clearer version, the words of an exercise, your coach's own
  line on one moment of a take, and your coach's word for a whole take. They
  train the models that write those five kinds of feedback.
- A coach's answers about your clips. With your yes, a coach may hear a short
  moment of a recording, sometimes with its words and never with your name,
  to answer one question: which moment of a passage most needs feedback, or
  whether a reworded version of your words sounds surer. Those answers, and
  the answers from the check in section 4 on whether a speaking pattern such
  as rushing is there, teach the software that spots speaking patterns and
  chooses which moments to give feedback on.
- Measurements of your practice. Numbers taken from a clip a coach answered
  about, such as your pace, your pauses and how long your words and sentence
  endings last, and whether an exercise helped when you re-recorded a
  fragment. They tune the same software, and the order in which exercises
  that fit you equally well are offered.
- Separate copies. While the switch is on, we keep a separate copy of the
  words of each moment you were shown as feedback, and of a coach's yes or no
  about how assured it sounded, so that training does not depend on your
  project still existing.

Text and numbers only. No recording of your voice, and no clip of one, is ever
copied or sent for training. Your coach's videos are not part of it either.

What is used from before you turn it on: the words of passages already in your
account, and your coach's words about them, can be used too. Separate copies
are made only from takes you record while the switch is on.

Legal basis: your consent (Article 6(1)(a) GDPR), given as explicit consent
(Article 9(2)(a) GDPR) because what you say in a practice passage may reveal
sensitive information about you. You give it on its own screen, by turning the
switch on. It is never on when you sign up, never pre-ticked, and never a
condition of using WillpowerLab. Saying no costs you nothing. You can turn it
off at any time.

Your coach's words are your coach's too. What a coach writes about your
practice is personal data about you and about your coach. Our agreement with
each coach allows what they write to be used this way; your yes is what allows
it for what they wrote about you.

The trained models. A model trained this way writes feedback for every
WillpowerLab speaker, not only for you. Before a trained model is used we test
it: if it repeats eight words in a row from the text of anyone who has turned
this choice off, it is not used, and it is trained again without that text.
The software tuned on coaches' answers and on measurements keeps settings
learned from many people, not your words or your measurements.

How long we keep the copies: until you turn the switch off or delete your
account. If you delete a project while the switch is on, the training copies
made from that project stay until you turn the switch off.

When you turn it off: your training copies are deleted, here and at the
provider that trains for us, and you are left out of every training that
starts afterwards, including one already waiting to start. A model already
trained stays and may still be used, provided it passes the test above; the
settings our software already learned stay too.

If you said yes before version 3.5: that yes covered less than this one, so it
now counts as off. We treat it as if you had turned the switch off, as the
paragraph above describes, until you say yes again.

The record of your choice: we keep the record of when you turned the switch on
and off, including after you delete your account, for six years after you turn
it off or delete your account, and then delete it. It holds identifiers and
timestamps, not your words.

Who trains, and where: OpenAI trains the models that write feedback for us.
Your training copies, which are text, are sent to OpenAI in the United States,
under the European Commission's standard contractual clauses. They are deleted
there as soon as each training finishes, and when you turn the switch off. The
software that spots speaking patterns, chooses moments and orders exercises is
tuned on our own systems; nothing for it is sent to OpenAI.

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


4c. RECORDINGS WE IMPORT FOR TRAINING

This section is for people whose voices are in recordings we bring in from
elsewhere. They are not WillpowerLab users.

We may import recordings of people speaking that we hold the rights to use,
to build a set of examples on which our coaches judge speaking patterns and
moments, and on which our software is checked and trained. An imported
recording is transcribed by OpenAI, measured as section 3 describes, and heard
by WillpowerLab coaches without a name. It is never shown to WillpowerLab
users, and the person speaking has no account with us.

What we hold: the recording, its transcript, its measurements, and coaches'
answers about it. Like everything else used for training, it is never sent to
anyone for training as audio.

Legal basis: our legitimate interest in coaching software that is accurate and
tested on real speech (Article 6(1)(f) GDPR). We do not look for sensitive
information in an imported recording, we do not infer it, and we do not use
it.

How long we keep it: while we hold the right to use it. It is deleted when
that right ends, or when the person speaking asks us.

Your rights: if your voice may be in a recording we imported, section 8 applies
to you. You can ask us whether we hold a recording of you, ask for a copy, and
ask us to delete it, and you can object to its use at any time by writing to
contact@willpowerlab.com. An objection takes your recording out of training
and checking.


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
choice in section 4a, your training copies, which are text, are processed by
OpenAI to train WillpowerLab's models, and by no one else. OpenAI also
transcribes the recordings we import for training (section 4c).

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
listening, as section 4 describes, unless you have objected to it. If you turn
on the choice in section 4a, a coach may also hear a moment of yours, and
sometimes read its words, to answer a question that teaches our software, as
section 4a describes.

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

Training copies, if you chose to make them (section 4a) — text only, never
audio: the words of practised passages, what your coach wrote about them, and
a coach's yes or no about a moment. Kept until you turn the choice off or
delete your account, then deleted here and at OpenAI.

A coach's answer about a moment of yours given for section 4a, and the two
versions of your words it compared, is deleted with the recording it was
about, and when you turn the choice off.

A trained model, and the settings our software learned from many people's
answers and measurements, are kept until we replace them. They hold no copy of
your text or your measurements, and a model that fails the test in section 4a
is not used.

Recordings we import for training (section 4c): kept while we hold the right
to use them, and deleted when that right ends or when the person speaking asks
us.

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

Your training copies, and the answers a coach gave about your moments for
section 4a, do not survive an account deletion: they are deleted with
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
    'version','phase1-2026-10-08-3.5',
    'terms_version','terms-3.5-2026-10-08',
    'terms_copy', c.terms,
    'terms_copy_sha256', encode(extensions.digest(c.terms,'sha256'),'hex'),
    'privacy_version','privacy-3.5-2026-10-08',
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
  -- The three determinations, provisional as for 3.4: new artifact
  -- versions (the RPC compares every field of an existing version, and
  -- approved_at is now()). Document 02 is now v1.2 (signed 2026-10-08, N68);
  -- its signed PDF is registered by its own hash once uploaded.
  jsonb_build_object(
    'artifact_kind','product_legal_approval',
    'version','provisional-founder-2026-10-08-3.5',
    'approving_authority','founder:artur@willonski.com',
    'approved_at', now(),
    'object_key','legal/phase1-2026.1/01-product-legal-approval-v1.1.pdf',
    'sha256', encode(extensions.digest('provisional-legal-2026-10-08-3.5','sha256'),'hex'),
    'metadata', jsonb_build_object('counsel_review','answered_by_correspondence_2026-10-01',
      'unbundled','true','supersedes','provisional-founder-2026-10-08',
      'coach_review_basis','contract',
      'practice_basis','contract_6_1_b_N55_WQ3a_B',
      'practice_counsel_review','not_obtained_founder_signed_in_place_2026-10-08',
      'blind_check_basis','legitimate_interest_6_1_f_with_written_objection',
      'lending_basis','explicit_consent_9_2_a_per_recording',
      'training_basis','consent_6_1_a_with_9_2_a_in_the_mlc2_ledger',
      'training_consent_policy','training-only-v2',
      'learning_counsel_review','not_obtained_founder_signed_knowing_2026-10-08',
      'corpus_import_basis','legitimate_interest_6_1_f_D4',
      'founder_ruling','2026-10-08 the 3.5 pack signed in chat (N68), D1 to D4 as drafted')),
  jsonb_build_object(
    'artifact_kind','power_score_classification',
    'version','provisional-founder-2026-10-08-3.5',
    'approving_authority','founder:artur@willonski.com',
    'approved_at', now(),
    'object_key','phase1-2026.1/legal/power-score-classification-v1.2.pdf',
    'sha256', encode(extensions.digest('provisional-power-2026-10-08-3.5','sha256'),'hex'),
    'metadata', jsonb_build_object(
      'counsel_review','founder_determination_not_counsel_reviewed',
      'document_version','1.2 signed 2026-10-08 (N68)',
      'biometric_identification', false,
      'sex_gender_inference', false,
      'emotion_intention_inference', false,
      'pipeline_version','voice-confidence-universal-v3',
      'detector_versions', jsonb_build_object('rushing','rules-v1',
        'word_compression','rules-v1','ending_compression','rules-v1'))),
  jsonb_build_object(
    'artifact_kind','article_50_assessment',
    'version','provisional-founder-2026-10-08-3.5',
    'approving_authority','founder:artur@willonski.com',
    'approved_at', now(),
    'object_key','phase1-2026.1/legal/article-50-assessment-v1.0.pdf',
    'sha256', encode(extensions.digest('provisional-article50-2026-10-08-3.5','sha256'),'hex'),
    'metadata', jsonb_build_object(
      'counsel_review','confirmed_by_correspondence_2026-09-23',
      'counsel_signed_letter','pending')),
  jsonb_build_array(
    -- The five purposes exactly as 3.4: all contract, all required. The
    -- control versions are READ BACK from the registry, never retyped.
    (SELECT jsonb_build_object('purpose_id', r.id,
      'lawful_basis_code','contract','required_for_core_service',true,
      'capability_version', r.capability_version,
      'reviewed_at', r.reviewed_at,
      'retention_control_version', r.retention_control_version,
      'deletion_control_version', r.deletion_control_version,
      'rights_control_version', r.rights_control_version)
      FROM public.processing_purpose_registry r
     WHERE r.id = 'recording_voice_processing'),
    (SELECT jsonb_build_object('purpose_id', r.id,
      'lawful_basis_code','contract','required_for_core_service',true,
      'capability_version', r.capability_version,
      'reviewed_at', r.reviewed_at,
      'retention_control_version', r.retention_control_version,
      'deletion_control_version', r.deletion_control_version,
      'rights_control_version', r.rights_control_version)
      FROM public.processing_purpose_registry r
     WHERE r.id = 'transcription_feedback'),
    (SELECT jsonb_build_object('purpose_id', r.id,
      'lawful_basis_code','contract','required_for_core_service',true,
      'capability_version', r.capability_version,
      'reviewed_at', r.reviewed_at,
      'retention_control_version', r.retention_control_version,
      'deletion_control_version', r.deletion_control_version,
      'rights_control_version', r.rights_control_version)
      FROM public.processing_purpose_registry r
     WHERE r.id = 'coach_review'),
    (SELECT jsonb_build_object('purpose_id', r.id,
      'lawful_basis_code','contract','required_for_core_service',true,
      'capability_version', r.capability_version,
      'reviewed_at', r.reviewed_at,
      'retention_control_version', r.retention_control_version,
      'deletion_control_version', r.deletion_control_version,
      'rights_control_version', r.rights_control_version)
      FROM public.processing_purpose_registry r
     WHERE r.id = 'personalized_exercise_recommendation'),
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

-- ── STEP 3 · activate 3.5 ─────────────────────────────────────────────────
-- Retires 3.4 and writes carryovers for any job in flight, on its own.
-- From this moment every speaker is asked to accept 3.5.

SELECT public.activate_phase1_policy_v1(
  'phase1-2026-10-08-3.5',
  'founder:artur@willonski.com',
  encode(extensions.digest('phase1-activation-2026-10-08-3.5','sha256'),'hex')
);

-- ── STEP 4 · the training wording: v1 retires, v2 starts, same instant ───
-- now() is the same moment 3.5 was activated (one transaction). v2 asks
-- for an acceptance of 3.5 before any new yes (C1). The ONE placeholder
-- of this file is on the next line that says <SIGNED_PDF_SHA256_OF_23>.

DO $$
DECLARE
  signed_pdf_sha256 TEXT := lower(btrim('<SIGNED_PDF_SHA256_OF_23>'));
BEGIN
  IF signed_pdf_sha256 !~ '^[0-9a-f]{64}$' THEN
    RAISE EXCEPTION 'STOP: STEP 4 still holds the placeholder. Put the SIGNED PDF hash of document 23 there.';
  END IF;
  IF signed_pdf_sha256 = '8472440c56bbe0a38236d3f14c298ad6a95f4b31d688b8f9c5ee1f4b625b45c0' THEN
    RAISE EXCEPTION 'STOP: that is the UNSIGNED render''s hash. Use the signed PDF''s.';
  END IF;
  PERFORM public.supersede_mlc2_training_consent_policy_v1(
    'training-only-v1',                                   -- the wording that retires
    'training-consent-wording-v2',                        -- approval reference
    '69d3e70205d991b725a55d5a537071358a9fd31b236d5c5049a5273fb521083c',
    'Use my practice text, my coach''s words and answers about it, and measurements of my practice to train the models that give every WillpowerLab speaker feedback.',
    'training-only-v2',                                   -- the new wording
    'terms-3.5-2026-10-08',                               -- terms version
    'privacy-3.5-2026-10-08',                             -- privacy version
    'Artur Willoński, founder; wording drafted by engineering in counsel''s style, counsel not consulted',
    TIMESTAMPTZ '2026-10-08 00:00:00+00',                 -- signed in chat that day (N68)
    ARRAY['PL'],
    'phase1-2026.1/legal/training-consent-wording-v2.pdf',
    signed_pdf_sha256,
    'phase1-2026-10-08-3.5',                              -- a yes needs 3.5 accepted
    now());                                               -- the switch instant
END;
$$;

-- ── STEP 5 · the last guard before anything is kept ──────────────────────
-- If the result is not exactly as intended, this undoes the whole block.

DO $$
DECLARE
  at TIMESTAMPTZ;
BEGIN
  SELECT activated_at INTO at FROM public.processing_policy_versions
   WHERE version = 'phase1-2026-10-08-3.5' AND status = 'active';
  IF at IS NULL
     OR (SELECT count(*) FROM public.processing_policy_versions WHERE status = 'active') <> 1
     OR (SELECT terms_copy_sha256 FROM public.processing_policy_versions
          WHERE version = 'phase1-2026-10-08-3.5')
        <> '38c4b8e42dfe6446f69b64ac0c8b3928357c3210b3b9eefb3a19124cc949e724'
     OR (SELECT privacy_copy_sha256 FROM public.processing_policy_versions
          WHERE version = 'phase1-2026-10-08-3.5')
        <> '55b8ffe5ed62bed7d5a64c885b5ee6cb32f64848e0d862bed39bbda690c5d54f' THEN
    RAISE EXCEPTION 'STOP: 3.5 is not in force with the signed bytes.';
  END IF;
  IF (SELECT retired_at FROM public.ml_consent_policies
       WHERE version = 'training-only-v1') IS DISTINCT FROM at
     OR (SELECT active_from FROM public.ml_consent_policies
          WHERE version = 'training-only-v2') IS DISTINCT FROM at
     OR (SELECT array_agg(version) FROM public.ml_consent_policies
          WHERE grant_scope = 'training_only'
            AND (retired_at IS NULL OR retired_at > at))
        IS DISTINCT FROM ARRAY['training-only-v2'] THEN
    RAISE EXCEPTION 'STOP: the training wording did not switch from v1 to v2 at the 3.5 instant.';
  END IF;
END;
$$;

COMMIT;

-- ── STEP 6 · the check (this is the result the editor shows you) ─────────
-- Expect ONE row:
--   processing_policy = phase1-2026-10-08-3.5, purposes = 5, required = 5,
--   signed_bytes = true, placeholder_left = false,
--   v1_retired_at = v2_active_from = activated_at,
--   training_policies_in_force = {training-only-v2},
--   people_with_a_yes_now = 0 (every v1 yes now counts as off, D3),
--   v2_sentence_is_signed = true.

SELECT p.version AS processing_policy,
       p.activated_at,
       (SELECT count(*) FROM public.processing_policy_purposes pp
         WHERE pp.policy_id = p.id) AS purposes,
       (SELECT count(*) FROM public.processing_policy_purposes pp
         WHERE pp.policy_id = p.id AND pp.required_for_core_service) AS required,
       (p.terms_copy_sha256 = '38c4b8e42dfe6446f69b64ac0c8b3928357c3210b3b9eefb3a19124cc949e724'
        AND p.privacy_copy_sha256 = '55b8ffe5ed62bed7d5a64c885b5ee6cb32f64848e0d862bed39bbda690c5d54f')
         AS signed_bytes,
       (position('[[EFFECTIVE DATE]]' in p.privacy_copy || p.terms_copy) > 0)
         AS placeholder_left,
       (SELECT retired_at FROM public.ml_consent_policies
         WHERE version = 'training-only-v1') AS v1_retired_at,
       (SELECT active_from FROM public.ml_consent_policies
         WHERE version = 'training-only-v2') AS v2_active_from,
       (SELECT array_agg(version) FROM public.ml_consent_policies
         WHERE grant_scope = 'training_only' AND active_from <= now()
           AND (retired_at IS NULL OR retired_at > now())) AS training_policies_in_force,
       (SELECT count(*) FROM public.training_consent_active_grants) AS people_with_a_yes_now,
       (SELECT a.approved_copy_sha256 = '69d3e70205d991b725a55d5a537071358a9fd31b236d5c5049a5273fb521083c'
          FROM public.ml_product_legal_approvals a
          JOIN public.ml_consent_policies cp ON cp.product_legal_approval_id = a.id
         WHERE cp.version = 'training-only-v2') AS v2_sentence_is_signed
  FROM public.processing_policy_versions p
 WHERE p.status = 'active';

-- ── AFTERWARDS ───────────────────────────────────────────────────────────
-- Speakers see "Accept the update" (3.5), then may say yes again on the
-- Help improve WillpowerLab card or at "Turn on the learning?". The next
-- weekly refresh marks every pair of a v1-only speaker not releasable and
-- voids the releases holding one; the door-3 sweep then lists any fine-tune
-- run with such an owner for its provider files to go (22-…, E6). No lane
-- opens here: each waits for its own switch PR (22-…, section 4).
