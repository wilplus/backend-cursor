-- ════════════════════════════════════════════════════════════════════════
-- PUBLISH 3.6 — Privacy 3.6, Terms 3.6, AI notice 3.2, training wording v4
-- One block for the Supabase SQL editor. Founder, 15 October 2026.
-- ════════════════════════════════════════════════════════════════════════
--
-- What you signed and approved (decisions log N72 and N73;
-- 25-privacy-terms-3.6-new-features-SIGNED-2026-10-15.md,
-- 27-training-consent-wording-v4-SIGNED-2026-10-15.md). This block does three things in
-- ONE transaction, so either all of it happens or none of it does:
--
--   1. publishes Privacy 3.6, Terms 3.6 and AI notice 3.2 as processing
--      policy phase1-2026-10-15-3.6 (the agreement screen's words are the
--      3.1 bytes), with the United States added to the countries, exactly
--      the way 3.5 was published: register, then activate. From that moment
--      every speaker is asked to accept 3.6.
--   2. at the same instant, retires the training wording in force (v1, or
--      v2 if 3.5 was published) and registers v4 (training-only-v4) with
--      supersede_mlc2_training_consent_policy_v1 (migration 0458). Every
--      earlier yes then reads as off (D1); nothing is deleted.
--   3. shows you a one-row check at the end.
--
-- ── BEFORE YOU RUN IT (all of them, or do not run it) ────────────────────
--
--   a. The frontend PR #790 and the backend branch of 15 October are
--      merged and deployed (the screens, the fixes, the WhatsApp card).
--   b. You signed the PDF of document 27 (PAdES), uploaded it to
--      phase1-2026.1/legal/training-consent-wording-v4.pdf, and its SIGNED
--      hash is in SIGNED-ARTIFACTS.md.
--   c. STEP 4 already holds that signed hash (898e998d…, checked by
--      engineering on 2026-10-15). Nothing to fill in.
--
-- The effective date. The texts say "Effective 15 October 2026". On another
-- day, change the date in legal/phase1-2026.1/copy/privacy-3.6.txt and
-- terms-3.6.txt and ask engineering to regenerate this file.
--
-- If anything fails, Postgres undoes the whole block: nothing is published,
-- nothing is retired. Read the error, stop, and send it to engineering.
--
-- ── STEP 0 · LOOK FIRST (a dry run; changes nothing) ─────────────────────
--
-- Select just this SELECT (down to its semicolon) and press Run on its own.
-- Expect: processing_policy_in_force = phase1-2026-10-08 (3.4) or
-- phase1-2026-10-08-3.5, exactly ONE training wording in force, and
-- the_0458_function_exists = true. people_with_any_yes_now is how many
-- people will be asked to say yes again.

SELECT
  (SELECT string_agg(version, ', ') FROM public.processing_policy_versions
    WHERE status = 'active') AS processing_policy_in_force,
  (SELECT array_agg(version ORDER BY version) FROM public.ml_consent_policies
    WHERE grant_scope = 'training_only' AND active_from <= now()
      AND (retired_at IS NULL OR retired_at > now())) AS training_policies_in_force,
  to_regprocedure('public.supersede_mlc2_training_consent_policy_v1(text, text, '
    || 'text, text, text, text, text, text, timestamptz, text[], text, text, '
    || 'text, timestamptz)') IS NOT NULL AS the_0458_function_exists,
  (SELECT count(*) FROM public.training_consent_active_grants) AS people_with_any_yes_now;

-- ════════════════════════════════════════════════════════════════════════
-- From here on: the publication. Run the whole file (or everything from
-- BEGIN to COMMIT). It is one transaction.
-- ════════════════════════════════════════════════════════════════════════

BEGIN;

-- ── STEP 1 · stop now if anything is not as expected ─────────────────────

DO $$
BEGIN
  IF to_regprocedure('public.supersede_mlc2_training_consent_policy_v1(text, '
       || 'text, text, text, text, text, text, text, timestamptz, text[], '
       || 'text, text, text, timestamptz)') IS NULL THEN
    RAISE EXCEPTION 'STOP: migration 0458 is not applied yet. Merge and deploy it first.';
  END IF;
  IF (SELECT string_agg(version, ',') FROM public.processing_policy_versions
       WHERE status = 'active') NOT IN ('phase1-2026-10-08', 'phase1-2026-10-08-3.5') THEN
    RAISE EXCEPTION 'STOP: the policy in force is neither 3.4 nor 3.5.';
  END IF;
  IF EXISTS (SELECT 1 FROM public.processing_policy_versions
              WHERE version = 'phase1-2026-10-15-3.6') THEN
    RAISE EXCEPTION 'STOP: 3.6 (phase1-2026-10-15-3.6) is already registered.';
  END IF;
  IF (SELECT count(*) FROM public.ml_consent_policies
       WHERE grant_scope = 'training_only'
         AND (retired_at IS NULL OR retired_at > now())) <> 1 THEN
    RAISE EXCEPTION 'STOP: there is not exactly one training wording in force.';
  END IF;
END;
$$;

-- ── STEP 2 · register 3.6 ───────────────────────────────────────────────
-- The four texts, byte for byte, from legal/phase1-2026.1/copy/: Terms 3.6
-- (843fb6a2…), Privacy 3.6 (3e35aec5…), AI notice 3.2
-- (8b85806c…) and the agreement, unchanged since 3.1.

WITH c AS (SELECT
$terms$WillpowerLab — Terms of Service
Version 3.6. Effective 15 October 2026.

These terms are an agreement between you and Artur Willoński, operating under
the name "WillpowerLab" from Poland ("WillpowerLab", "we", "us"). They govern
your use of willpowerlab.com and the WillpowerLab application.

Version 3.6 replaces every earlier version. It adds what the service now
does: the AI version of your voice, Will in the Lounge, WhatsApp messages and
one-to-one lessons (sections 1 and 2); it sets out the plans as they are sold
today (section 2); it opens the service to residents of California (sections
4 and 16); and it asks you again for the training choice (section 8), in
fewer words. Under these terms the sound of
your recordings is processed to deliver your own coaching and is never used
to train models.
Three things are yours to choose, and all are off unless you choose them: your
practice may train the models that give every
WillpowerLab speaker feedback when you turn on Help improve WillpowerLab
(section 8 and the Privacy Policy, section 4a); a short clip of a recording
may be played to other users when you lend that recording (section 8 and the
Privacy Policy, section 4b); and the clips of a take may be played to a
community when you share that take with it (section 8 and the Privacy
Policy, section 4d). A coach may also hear a short clip of a recording to
check our automated listening (section 11). If anything else changes, it
changes in a new version you are asked to accept — see section 15.


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

Your audio is sent to third-party AI providers to be transcribed and, for the
AI version of your voice, to make that voice. The AI notice tells you how the
automated part works, and the Privacy Policy sets out who receives what.

The AI version of your voice. WillpowerLab makes an AI version of your voice
from your recordings, to create practice examples that only you hear.
ElevenLabs, a voice AI company, builds it for us. You can turn it off and
delete it at any time in Data & consent.

Will. In the Lounge you can talk to Will, an AI assistant that knows the app
and your project. Will is not a person and not your coach, and what Will says
can be wrong.

WhatsApp. If you give us your phone number, we tell you on WhatsApp when your
coach's feedback is in. You can remove your number at any time.

Lessons. You can book a one-to-one lesson with a WillpowerLab coach, held by
video call. Section 2 says how lessons are paid for and cancelled.


2. WHAT IT COSTS

There is a free plan and there are paid plans. You can use the free plan for as
long as you like without paying.

Work in the app is measured in tokens. Each plan gives you an allowance of them
for the month. The allowance is SET at the start of each month rather than
added to what you had, so unused tokens do not carry over.

  Free         12,000 tokens a month        no charge
  Starter     150,000 tokens a month        USD 12 a month
  Plus        550,000 tokens a month        USD 39 a month
  Pro       1,400,000 tokens a month        USD 89 a month

Plans differ only in their tokens. A written review by a human coach is paid
for in tokens, like everything else in the app, and the price of each thing
in tokens is shown in the app before you use it.

The price and what it includes are shown before you pay. We will tell you
before any price changes. Payments are taken by our payment provider; we do not
see or store your card details. A paid plan renews each month until you cancel,
and you can cancel at any time.

If you are a consumer in the EU or EEA, you have 14 days to withdraw from a
paid plan. We give you that full 14 days with no questions asked, even once you
have started using it.

A lesson is paid for when you book it, at the price shown on the booking page,
unless the booking page says it is paid later or free. To cancel or move a
lesson, reply to your confirmation email. If you are a consumer in the EU or
EEA, you have 14 days from booking to withdraw from it and be refunded in
full; if you ask for the lesson to take place within those 14 days and it
does, you can no longer withdraw from it.


3. YOU MUST BE 18

The service is for adults. You must be 18 or older to use it. When you accept
these terms you confirm that you are. We do not knowingly provide the service
to anyone under 18, and we will close an account if we learn that its holder is
under 18.


4. WHERE THE SERVICE IS AVAILABLE

We offer the service only in the countries listed on the acceptance screen. If
you are not resident in one of them, you cannot accept these terms and we
cannot provide the service to you.

In the United States, we offer the service only to residents of California.
If you live in any other state, you cannot accept these terms. When you choose
the United States on the acceptance screen, you confirm that you live in
California.


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

Your practice. In these terms and in the Privacy Policy, "your practice"
means the words of the passages you practise, the numbers measured from them,
and what your coach writes and answers about them. It never includes the
sound of your recordings or your conversation with Will.

We do not use the sound of your recordings to train models, and the AI
version of your voice is made for you alone. Your practice is used to train
WillpowerLab's own models, together with other speakers' who said yes, only
if you turn on Help improve WillpowerLab (Privacy Policy, section 4a), and
never for anyone else.

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

If you share a take with a community (Privacy Policy, section 4d), you give
us permission to play the clips of that take to the members of that
community, without your name or your words, for one purpose: letting them
listen to it and say how it sounds. The permission is per take, free of
charge, and ends the moment you stop sharing it.

A coach's video answer is made for you. You may keep it and watch it as
often as you like, but do not publish it.


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
does not depend on your plan. A written review that comes back to you, in
words or as a video, is paid for in tokens (section 2). Not asking for one
does not mean nobody listens; it means no written review is returned to you.
A coach does not see the voice
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

Other users hear a recording of yours only if you lend it or share a take
with a community (Privacy Policy, sections 4b and 4d); nothing in this
section lends or shares anything for you.


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
you may bring proceedings there. If you are a consumer resident in California,
this does not deprive you of any protection of California law that cannot be
waived by agreement, and you may bring proceedings in California.

You may also use the European Commission's online dispute resolution platform.


17. CONTACT

Artur Willoński, operating under the name "WillpowerLab"
Poland, European Union
Contact: contact@willpowerlab.com (a postal address is provided on request to
data subjects and to the supervisory authority)$terms$ AS terms,

$privacy$WillpowerLab — Privacy Policy
Version 3.6. Effective 15 October 2026.

This policy explains what WillpowerLab does with your personal data, who else
receives it, how long we keep it, and how you get it deleted.

Version 3.6 replaces every earlier version. It describes what WillpowerLab
now does that earlier versions did not: the AI version of your voice, made by
ElevenLabs (sections 3 and 5); talking to Will in the Lounge (section 4);
WhatsApp messages when your coach's feedback is in (section 4); one-to-one
lessons you book with a coach (section 4); signing in with Google or
LinkedIn (section 2); sharing a take with a community (section 4d); and
what residents of California should know, now that the service is open to
them (section 14). It
also asks you again for one choice, Help improve WillpowerLab (section 4a),
in fewer words: a yes you gave under an earlier version does not carry over,
so it counts as off until you say yes again. Your conversation with Will is
never used for training. No recording of your voice, and no clip of one, is
ever copied or sent for training.


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
- Your email address and account details. If you sign in with Google or
  LinkedIn, we receive your email address and the name on that account.
- Your slides and presentation materials.
- Audio recordings of you presenting.
- Edits you make to your Ideal Text, and your responses to feedback.
- What you write to Will in the Lounge.
- Your phone number, if you give it to us for WhatsApp messages.
- If you book a lesson: your name, the time zone you choose, the time you
  booked and any note you add.
- Your answers about other people's clips, if you listen to them.

Things produced from your recordings
- Transcripts of what you said.
- Measurements taken from the sound of your voice: how much your pitch varies,
  how loud and how varied your delivery is, how fast you speak, how you pause,
  and how your energy and pitch move across a sentence.
- Your Ideal Text and your feedback.
- Whether a fragment you re-recorded after an exercise came out better.
- The AI version of your voice, and the practice examples made with it
  (section 3).

Things collected automatically
- Technical and security logs: IP address, device and browser information,
  timestamps, and error records.
- The version of the app you used, the country you told us you live in, and the
  language your app was set to, recorded as part of your agreement to this
  policy.
- On the booking page, the time zone your IP address suggests, used only to
  show you times in your own zone first. We do not store it; we store the time
  zone you end up choosing.


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

The AI version of your voice. From the first take you record, we send up to
two and a half minutes of its clearest speech to ElevenLabs, a voice AI
company, which makes an AI version of your voice for us. We use it to say one
of your own sentences back to you the way you could say it, as a practice
example. Only you hear these examples, and every one is labelled "AI version
of your voice". Each example is checked by transcribing it again, and we
measure your next try to see whether the example helped. The AI version of
your voice is made for you alone: it is not used to identify you, not used
for anyone else, and not used to train any model. You can delete it at any
time in Data & consent: we delete it at ElevenLabs and here, with every
example made from it, and we stop making examples. You can turn it on again,
and we make it from your next take.

Other users never hear your voice unless you lend a particular recording to
them yourself (section 4b) or share a take with a community (section 4d).


4. WHAT WE USE IT FOR, AND ON WHAT LEGAL BASIS

To provide the service: to store your recording, transcribe it, generate your
Ideal Text and your feedback, have a WillpowerLab coach review that feedback,
make the AI version of your voice and your practice examples, answer you when
you talk to Will, and keep all of it available to you.
Legal basis: performance of our contract with you (Article 6(1)(b) GDPR). This
processing is what the service is; we cannot provide it without doing this.
WillpowerLab is hybrid coaching — automated work and a human coach together —
so the coach's review sits inside this basis rather than beside it. That basis
covers delivering your coaching and nothing else: it does not cover training
models, analytics about you, or advertising. We do not do analytics or
advertising. Training happens only with the separate choice in section 4a.

Talking to Will. Will is the AI assistant in the Lounge. To answer you, Will
is given what you write, your recent messages, and a short summary of your
project: its title, your slide titles, how many takes you have recorded,
whether your coach's feedback is in, and the beginning of your Ideal Text.
Your conversation is kept in your account so you can come back to it, and
you can clear it at any time.
Your conversation with Will is private. Nobody at WillpowerLab reads it,
except when we must to keep the service safe and working, when the law
requires it, or when you ask us to, for example for help with your account.
It is never used for training.
Legal basis: performance of our contract with you (Article 6(1)(b) GDPR).

WhatsApp messages. If you give us your phone number, we send you a WhatsApp
message when your coach's feedback is in, with a link to it. The message
does not contain your feedback.
Legal basis: your consent (Article 6(1)(a) GDPR), which you give by adding
your number. You can remove it at any time in Data & consent, and we stop.

One-to-one lessons. If you book a lesson with a coach, we use your name, your
email address, the time and time zone you chose and any note you add to
arrange it, to send you and the coach a confirmation with a calendar entry
and the video-call link, and to take payment for it.
Legal basis: performance of our contract with you (Article 6(1)(b) GDPR), and
legal obligation (Article 6(1)(c) GDPR) for the accounting records of a paid
lesson.

To keep the service secure and working: fraud and abuse prevention, debugging,
protecting the service and its users, and answering you when you write to us.
To do this, the person who runs WillpowerLab can see an account's recordings,
transcripts and measurements, and can export the measurements of an account's
takes, without the account's name or email address.
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

If you take a paid plan or pay for a lesson, your payment is handled by
Stripe. We never see or store your card details; we hold the record that a
plan is active or a lesson is paid, and the invoices we are required to keep.

We never use the sound of anyone's recordings to train models: no recording,
and no clip of one, is copied or sent for training. Making the AI version of
your voice is not training: it makes a voice for you alone. What may be used
for training, and only with your yes, is set out in section 4a. Recordings we
import from elsewhere are covered in section 4c.

Do you have to provide this data? For the parts the service is made of, yes.
Recording your voice, having it transcribed, and having a coach able to review
your feedback are what WillpowerLab is; there is no version of it that works
without them, so if you are not willing to provide them you cannot use the
service. Practice is part of the service too, though doing any one exercise
is always up to you. Your phone number, a lesson booking and talking to Will
are up to you.

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

If you turn on Help improve WillpowerLab, we use your practice to train the
models that give feedback to every WillpowerLab speaker. Your practice, as
the Terms define it, is the words of the passages you practise, the numbers
measured from them, and what your coach writes and answers
about them; never the sound of your recordings, and never your conversation
with Will. The screen asks "Can we
make the product so much better for you?", says "We'd train our feedback on
your practice.", and you say yes with "Yes, make it so much better."

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
  endings last, and whether an exercise or a practice example in the AI
  version of your voice helped when you tried again. They tune the same
  software, and the order in which exercises that fit you equally well are
  offered.
- Separate copies. While the switch is on, we keep a separate copy of the
  words of each moment you were shown as feedback, and of a coach's yes or no
  about how assured it sounded, so that training does not depend on your
  project still existing.

Text and numbers only. No recording of your voice, and no clip of one, is ever
copied or sent for training. The AI version of your voice, the examples made
with it, and your coach's videos are not part of it either.

What is used from before you turn it on: the words of passages already in your
account, and your coach's words about them, can be used too. Separate copies are made only from takes you record while the
switch is on.

Legal basis: your consent (Article 6(1)(a) GDPR). You give it on its own
screen, by turning the switch on. It is never on when you sign up, never
pre-ticked, and never a condition of using WillpowerLab. Saying no costs you
nothing. You can turn it off at any time.

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

If you said yes before version 3.6: that yes covered less than this one, so it
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


4d. SHARING A TAKE WITH A COMMUNITY — OPTIONAL, PER TAKE

Before your next take, you can choose to share it with a community: the
general community, which is every WillpowerLab user, or a community you
joined with its pass code, which is only its members. It is not shared
unless you choose a community for that take, and you can choose "Only me".

What others hear and do: the short clips of that take, with no name, no
words on screen and no measurements; listeners see only the community's
name. A listener may answer a question about how a clip sounds. Those
answers are kept with the clip and may help settle, together with a coach's,
whether a moment belongs in your Voice Album. They are never used to train
models on their own.

Legal basis: your explicit consent (Article 9(2)(a) GDPR), given for each
take by choosing a community. You can stop sharing a take at any time:
its clips leave every community at once. Nothing else in your account
changes.


5. WHO ELSE RECEIVES YOUR DATA

AI providers

OpenAI receives:
- the audio of your recording, in order to transcribe it;
- parts of your transcript and related text, in order to generate your Ideal
  Text and your feedback;
- what you write to Will and the summary of your project described in
  section 4, in order to answer you;
- each practice example made in the AI version of your voice, in order to
  check by transcribing it that it says your words.

ElevenLabs receives:
- up to two and a half minutes of audio from one of your takes, in order to
  make the AI version of your voice;
- one of your own sentences at a time, in order to say it in that voice as a
  practice example.

OpenAI and ElevenLabs are the AI providers that receive your audio or your
transcript: OpenAI to transcribe it, check it and write your feedback and
Will's answers, ElevenLabs to make the AI version of your voice. Each
transfer is made under a short-lived internal permit that records which
operation it was for and the minimum data it was allowed to carry. We do not
authorise OpenAI or ElevenLabs to use your content to train their own
models. If you turn on the choice in section 4a, your training copies, which
are text, are processed by OpenAI to train WillpowerLab's models, and by no
one else. OpenAI also transcribes the recordings we import for training
(section 4c).

Infrastructure providers
- Cloudflare (R2): storage of your audio recordings, of your practice
  examples, and of your coach's video answers.
- Supabase: our database, sign-in, and audio storage on a fallback path.
- Railway: hosting of the application. Railway is our processor for what it
  hosts on our behalf, and a controller in its own right for its own account
  and service-usage records about us as its customer.
- Resend: transactional email, including lesson confirmations.
- Vercel: hosting of the website.
- Sentry: error reports, stored in the European Union.

Messaging
- Meta (WhatsApp), if you give us your phone number: your number and the
  message that your coach's feedback is in, with its link. Meta also handles
  that message as a controller for its own service, under WhatsApp's terms.

Signing in
- Google or LinkedIn, if you choose to sign in with them. They tell us your
  email address and name; they decide for themselves, under their own terms,
  what they do with the fact that you signed in.

Payments
- Stripe, if you take a paid plan or pay for a lesson. Stripe is not our
  processor: it decides for itself how it uses payment data, as a controller
  in its own right, under its own terms. We never see or store your card
  details.

Human coaches
A WillpowerLab coach — a person — may listen to your recordings in order to
review the feedback you were given and to prepare practice for you. The review
is part of the service rather than an extra you
switch on, because WillpowerLab is hybrid coaching; the Terms say so in section 1 and section 11, and a written
review that comes back to you is paid for in tokens. A coach who reviews your
recording does not see the voice measurements described in section 3. Coaches
are bound to confidentiality and see only what a review requires.
A coach may answer you in writing or with a video; a video answer is for you.
If you book a lesson, the coach receives your name, your email address, the
time and any note you add.
A coach may also hear a short clip of a recording to check our automated
listening, as section 4 describes, unless you have objected to it. If you turn
on the choice in section 4a, a coach may also hear a moment of yours, and
sometimes read its words, to answer a question that teaches our software, as
section 4a describes.

Other users
If you lend a recording (section 4b) or share a take with a community
(section 4d), other WillpowerLab users hear those clips, without your name
or your words. Nobody else does.

Others
We share data with professional advisers, and with authorities where the law
requires it. We do not sell your personal data and we do not share it for
advertising.


6. TRANSFERS OUTSIDE THE EEA

Some of the providers above process data in the United States. Every one of
those transfers is made under the European Commission's Standard Contractual
Clauses or the EU-US Data Privacy Framework, as each provider's data
processing agreement sets out.

- OpenAI: Standard Contractual Clauses. Its agreement appoints OpenAI Ireland
  Limited to process data from the EEA and Switzerland. Training copies
  (section 4a) are transferred to OpenAI in the United States under the same
  clauses.
- ElevenLabs: the EU-US Data Privacy Framework, and Standard Contractual
  Clauses, which its data processing agreement incorporates.
- Cloudflare: Standard Contractual Clauses. Our storage carries an Eastern
  Europe location hint, which is a preference rather than a guarantee.
- Supabase: Standard Contractual Clauses and a UK addendum. Your data is stored
  in Ireland.
- Railway, Resend, Vercel: Standard Contractual Clauses.
- Meta (WhatsApp): the EU-US Data Privacy Framework, under WhatsApp's Data
  Transfer Addendum, which allows Standard Contractual Clauses instead.
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

Your coach's video answers: kept while your account is open, including
after you delete the take they answer. They are deleted when you ask us or
when you close your account.

The AI version of your voice and the practice examples made with it: kept
until you delete it or close your account, then deleted here and at
ElevenLabs. Whether an example helped you is kept with your practice, like
your other practice attempts.

Your conversation with Will: kept while your account is open, and deleted
when you clear it or close your account.

Your phone number: kept until you remove it or close your account.

A lesson you booked: kept while your account is open, and deleted when you
close it, except the record of a paid lesson, which we keep with our
accounting records for as long as the law requires.

A recording you lent stops being heard by others the moment you turn the
switch off, and is deleted with the recording like everything else.
A take you shared stops being heard by others the moment you stop sharing it,
and is deleted with the take like everything else.
Your answers about other users' clips are kept while your account is open
and deleted when you delete it.

Training copies, if you chose to make them (section 4a) — text only, never
audio: the words of practised passages, what your coach wrote about them, and a
coach's yes or no about a moment. Kept until you turn
the choice off or delete your account, then deleted here and at OpenAI.

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
- Anything we must keep by law, for example accounting records, including the
  record of a paid lesson.

Your training copies, and the answers a coach gave about your moments for
section 4a, do not survive an account deletion: they are deleted with
everything else.

Audio already sent to a provider is deleted at the provider as part of the same
process, and we record the outcome. The AI version of your voice is deleted at
ElevenLabs before anything else.


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
data subjects and to the supervisory authority)


14. IF YOU LIVE IN CALIFORNIA

This section adds to the rest of this policy for residents of California.
Everything above applies to you too, including your rights in section 8.

What we collect, and why: the categories of personal information we collect
are those in section 2: identifiers, such as your email address, your name
and your phone number; audio recordings of your voice, and the AI version of
your voice made from them; what you write, such as your Ideal Text and your
messages to Will; and internet activity, such as technical and security logs.
We collect them from you and from your use of the service, for the purposes
in section 4, and keep each for as long as section 7 says.

Sensitive personal information: the recordings of your voice, and anything
sensitive they happen to reveal. We use it only to provide the service you
asked for, and, if you turn on the choice in section 4a, to train models as
that section describes. You can turn that choice off at any time.

We do not sell your personal information, and we do not share it for
cross-context behavioral advertising. We do not knowingly collect personal
information from anyone under 18.

Your rights: to know what personal information we collect, use and disclose,
and to get a copy of it; to have it deleted; to have it corrected; to limit
our use of your sensitive personal information; and not to be treated
differently for using any of these rights. To use them, write to
contact@willpowerlab.com. Someone you authorise may also write for you. We
confirm who you are before we act on a request, and we answer within 45
days.$privacy$ AS privacy,

$notice$WillpowerLab — how the automated part works

Your transcript, the written version of your talk, and the feedback on your
delivery are produced by automated systems, including AI models.

The feedback is a reading, not a measurement. It describes how a passage came
across; it does not score you, rank you, or decide anything about you. You are
free to disagree with any of it, and disagreeing changes nothing about your
account.

Will, in the Lounge, is an AI assistant, not a person. What Will says can be
wrong.

The AI version of your voice is made by AI from your own recording. Every
practice example made with it is labelled "AI version of your voice", and only
you hear it.

A person may review that automated feedback afterwards. Nothing about you is
decided automatically.$notice$ AS notice,

$agree$I have read the Terms of Service and the Privacy Policy and I agree to them.

I understand that WillpowerLab is hybrid coaching, and that a WillpowerLab coach — a person — may listen to my recordings in order to review my feedback. That is part of the service, not an extra I am switching on.$agree$ AS agree)

SELECT public.register_phase1_policy_v1(
  jsonb_build_object(
    'version','phase1-2026-10-15-3.6',
    'terms_version','terms-3.6-2026-10-15',
    'terms_copy', c.terms,
    'terms_copy_sha256', encode(extensions.digest(c.terms,'sha256'),'hex'),
    'privacy_version','privacy-3.6-2026-10-15',
    'privacy_copy', c.privacy,
    'privacy_copy_sha256', encode(extensions.digest(c.privacy,'sha256'),'hex'),
    'ai_notice_version','ai-notice-3.2-2026-10-15',
    'ai_notice_copy', c.notice,
    'ai_notice_copy_sha256', encode(extensions.digest(c.notice,'sha256'),'hex'),
    'agreement_copy', c.agree,
    'agreement_copy_sha256', encode(extensions.digest(c.agree,'sha256'),'hex'),
    'allowed_countries', jsonb_build_array('pl','de','fr','es','it','nl','be',
      'se','dk','fi','ie','pt','at','cz','sk','hu','ro','bg','hr','si','ee',
      'lv','lt','lu','mt','cy','gr','us')
  ),
  -- The three determinations, provisional as for 3.5: new artifact
  -- versions (the RPC compares every field of an existing version, and
  -- approved_at is now()). Document 02 is now v1.2 (signed 2026-10-08, N68);
  -- its signed PDF is registered by its own hash once uploaded.
  jsonb_build_object(
    'artifact_kind','product_legal_approval',
    'version','provisional-founder-2026-10-15-3.6',
    'approving_authority','founder:artur@willonski.com',
    'approved_at', now(),
    'object_key','legal/phase1-2026.1/01-product-legal-approval-v1.1.pdf',
    'sha256', encode(extensions.digest('provisional-legal-2026-10-15-3.6','sha256'),'hex'),
    'metadata', jsonb_build_object('counsel_review','answered_by_correspondence_2026-10-01',
      'unbundled','true','supersedes','provisional-founder-2026-10-08-3.5',
      'coach_review_basis','contract',
      'practice_basis','contract_6_1_b_N55_WQ3a_B',
      'practice_counsel_review','not_obtained_founder_signed_in_place_2026-10-08',
      'blind_check_basis','legitimate_interest_6_1_f_with_written_objection',
      'lending_basis','explicit_consent_9_2_a_per_recording',
      'training_basis','consent_6_1_a',
      'training_consent_policy','training-only-v4',
      'learning_counsel_review','not_obtained_founder_signed_knowing_2026-10-08',
      'corpus_import_basis','legitimate_interest_6_1_f_D4',
      'founder_ruling','2026-10-15 the 3.6 pack signed in chat (N72), D1 to D8; v4 and the 15 October changes approved (N73)',
      'ai_voice_basis','contract_D3', 'whatsapp_basis','consent_6_1_a_by_adding_the_number_D4',
      'community_sharing_basis','explicit_consent_9_2_a_per_take_D5',
      'us_scope','california_residents_only_D8')),
  jsonb_build_object(
    'artifact_kind','power_score_classification',
    'version','provisional-founder-2026-10-15-3.6',
    'approving_authority','founder:artur@willonski.com',
    'approved_at', now(),
    'object_key','phase1-2026.1/legal/power-score-classification-v1.2.pdf',
    'sha256', encode(extensions.digest('provisional-power-2026-10-15-3.6','sha256'),'hex'),
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
    'version','provisional-founder-2026-10-15-3.6',
    'approving_authority','founder:artur@willonski.com',
    'approved_at', now(),
    'object_key','phase1-2026.1/legal/article-50-assessment-v1.0.pdf',
    'sha256', encode(extensions.digest('provisional-article50-2026-10-15-3.6','sha256'),'hex'),
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

-- ── STEP 3 · activate 3.6 ─────────────────────────────────────────────────
-- Retires the policy in force and writes carryovers for any job in flight.
-- From this moment every speaker is asked to accept 3.6.

SELECT public.activate_phase1_policy_v1(
  'phase1-2026-10-15-3.6',
  'founder:artur@willonski.com',
  encode(extensions.digest('phase1-activation-2026-10-15-3.6','sha256'),'hex')
);

-- ── STEP 4 · the training wording: the one in force retires, v4 starts ───
-- now() is the same moment 3.6 was activated (one transaction). v4 asks for
-- an acceptance of 3.6 before any new yes. The signed PDF hash of document
-- 27 is filled in below.

DO $$
DECLARE
  signed_pdf_sha256 TEXT := lower(btrim('898e998dec4fb9ebcf1f8843572840b7dbf23de051b3ea4613d61804e86a382f'));
  predecessor TEXT;
BEGIN
  IF signed_pdf_sha256 !~ '^[0-9a-f]{64}$' THEN
    RAISE EXCEPTION 'STOP: STEP 4 still holds the placeholder. Put the SIGNED PDF hash of document 27 there.';
  END IF;
  IF signed_pdf_sha256 = '21e249c821de0ce9f1ec1b55a0659fb638b5b26e1601175a1db439ecb72104e7' THEN
    RAISE EXCEPTION 'STOP: that is the UNSIGNED render''s hash. Use the signed PDF''s.';
  END IF;
  SELECT version INTO predecessor FROM public.ml_consent_policies
   WHERE grant_scope = 'training_only' AND (retired_at IS NULL OR retired_at > now());
  PERFORM public.supersede_mlc2_training_consent_policy_v1(
    predecessor,                                          -- the wording that retires (v1 or v2)
    'training-consent-wording-v4',                        -- approval reference
    'ece8d1da2709971302542a490e41cf44d071028918daadc1880d65e339aac286',
    'We''d train our feedback on your practice.',
    'training-only-v4',                                   -- the new wording
    'terms-3.6-2026-10-15',                               -- terms version
    'privacy-3.6-2026-10-15',                             -- privacy version
    'Artur Willoński, founder; wording by the founder on the consent prototype, counsel not consulted',
    TIMESTAMPTZ '2026-10-15 00:00:00+00',                 -- approved in chat that day (N73)
    ARRAY['PL','EU','US-CA'],
    'phase1-2026.1/legal/training-consent-wording-v4.pdf',
    signed_pdf_sha256,
    'phase1-2026-10-15-3.6',                              -- a yes needs 3.6 accepted
    now());                                               -- the switch instant
END;
$$;

-- ── STEP 5 · the last guard before anything is kept ──────────────────────

DO $$
DECLARE
  at TIMESTAMPTZ;
BEGIN
  SELECT activated_at INTO at FROM public.processing_policy_versions
   WHERE version = 'phase1-2026-10-15-3.6' AND status = 'active';
  IF at IS NULL
     OR (SELECT count(*) FROM public.processing_policy_versions WHERE status = 'active') <> 1
     OR (SELECT terms_copy_sha256 FROM public.processing_policy_versions
          WHERE version = 'phase1-2026-10-15-3.6')
        <> '843fb6a273b35f2659f657fcf154d0fe81145a44c383efcf0b32a5e55c17c6fa'
     OR (SELECT privacy_copy_sha256 FROM public.processing_policy_versions
          WHERE version = 'phase1-2026-10-15-3.6')
        <> '3e35aec50e44e950440c697216f94dc108b8e32cb80fe71db654195d666f3626'
     OR NOT EXISTS (SELECT 1 FROM public.processing_policy_versions
          WHERE version = 'phase1-2026-10-15-3.6' AND 'us' = ANY(allowed_countries)) THEN
    RAISE EXCEPTION 'STOP: 3.6 is not in force with the approved bytes and the United States.';
  END IF;
  IF (SELECT active_from FROM public.ml_consent_policies
       WHERE version = 'training-only-v4') IS DISTINCT FROM at
     OR (SELECT array_agg(version) FROM public.ml_consent_policies
          WHERE grant_scope = 'training_only'
            AND (retired_at IS NULL OR retired_at > at))
        IS DISTINCT FROM ARRAY['training-only-v4'] THEN
    RAISE EXCEPTION 'STOP: the training wording did not switch to v4 at the 3.6 instant.';
  END IF;
END;
$$;

COMMIT;

-- ── STEP 6 · the check (this is the result the editor shows you) ─────────
-- Expect ONE row: processing_policy = phase1-2026-10-15-3.6, purposes = 5,
-- required = 5, approved_bytes = true, has_us = true,
-- training_policies_in_force = {training-only-v4}, people_with_a_yes_now = 0
-- (every earlier yes counts as off, D1), v4_sentence_is_signed = true.

SELECT p.version AS processing_policy,
       p.activated_at,
       (SELECT count(*) FROM public.processing_policy_purposes pp
         WHERE pp.policy_id = p.id) AS purposes,
       (SELECT count(*) FROM public.processing_policy_purposes pp
         WHERE pp.policy_id = p.id AND pp.required_for_core_service) AS required,
       (p.terms_copy_sha256 = '843fb6a273b35f2659f657fcf154d0fe81145a44c383efcf0b32a5e55c17c6fa'
        AND p.privacy_copy_sha256 = '3e35aec50e44e950440c697216f94dc108b8e32cb80fe71db654195d666f3626') AS approved_bytes,
       ('us' = ANY(p.allowed_countries)) AS has_us,
       (SELECT array_agg(version) FROM public.ml_consent_policies
         WHERE grant_scope = 'training_only' AND active_from <= now()
           AND (retired_at IS NULL OR retired_at > now())) AS training_policies_in_force,
       (SELECT count(*) FROM public.training_consent_active_grants) AS people_with_a_yes_now,
       (SELECT a.approved_copy_sha256 = 'ece8d1da2709971302542a490e41cf44d071028918daadc1880d65e339aac286'
          FROM public.ml_product_legal_approvals a
          JOIN public.ml_consent_policies cp ON cp.product_legal_approval_id = a.id
         WHERE cp.version = 'training-only-v4') AS v4_sentence_is_signed
  FROM public.processing_policy_versions p
 WHERE p.status = 'active';

-- ── AFTERWARDS ───────────────────────────────────────────────────────────
-- Speakers see "Accept the update" (3.6). On "Three things to confirm" and
-- before a Take they may say yes to v4. Nothing else opens here.
