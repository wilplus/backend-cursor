-- ════════════════════════════════════════════════════════════════════════
-- PUBLISH 3.9 — Terms 3.8 and Privacy 3.9 (the plan's personal answers,
-- "How do you feel?", WhatsApp sign-in), with AI notice 3.2
-- One block for the Supabase SQL editor. Founder, 28 October 2026.
-- ════════════════════════════════════════════════════════════════════════
--
-- What you signed (decisions log N217; 30-terms-3.8-privacy-3.9-the-plan-
-- feelings-and-whatsapp-sign-in-SIGNED-2026-10-27.md, counsel agrees): Terms
-- 3.8 and Privacy 3.9 are the signed texts word for word, with the date
-- filled in and nothing else. AI notice 3.2 and the agreement are unchanged.
-- This block, in ONE transaction:
--
--   1. publishes them as processing policy phase1-2026-10-28-3.9 (AI notice
--      3.2, the 3.1 agreement, the same countries), exactly as 3.8 was
--      published: register, then activate. From that moment every speaker
--      sees the update prompt and accepts 3.9.
--   2. deletes every "How do you feel?" answer given before 3.9 (question 2
--      A): the rows of recording_feelings, and named_emotion on each Take.
--   3. leaves the training wording alone: training-only-v4 stays in force.
--   4. shows you a one-row check at the end.
--
-- ── BEFORE YOU RUN IT ────────────────────────────────────────────────────
--
--   a. 3.8 is in force (published 2026-10-27 06:34 UTC).
--   b. The backend PR with this file is merged.
--   c. Only AFTER this block has run, on Railway, web and worker:
--      PLAN_CONSENT_ENABLED=true (the plan's own yes, N211). WhatsApp sign-in
--      goes on separately, when Supabase is set up (N214).
--
-- If anything fails, Postgres undoes the whole block: nothing is published
-- and nothing is deleted. Read the error, stop, and send it to engineering.
--
-- ── STEP 0 · LOOK FIRST (a dry run; changes nothing) ─────────────────────
--
-- Select just this SELECT (down to its semicolon) and press Run on its own.
-- Expect: processing_policy_in_force = phase1-2026-10-27-3.8 and
-- training_policies_in_force = {training-only-v4}; feelings_to_delete and
-- takes_with_a_feeling are what STEP 3b deletes.

SELECT
  (SELECT string_agg(version, ', ') FROM public.processing_policy_versions
    WHERE status = 'active') AS processing_policy_in_force,
  (SELECT array_agg(version ORDER BY version) FROM public.ml_consent_policies
    WHERE grant_scope = 'training_only' AND active_from <= now()
      AND (retired_at IS NULL OR retired_at > now())) AS training_policies_in_force,
  (SELECT count(*) FROM public.training_consent_active_grants) AS people_with_a_yes_now,
  (SELECT count(*) FROM public.recording_feelings) AS feelings_to_delete,
  (SELECT count(*) FROM public.v2_sessions
    WHERE intake_context::jsonb ? 'named_emotion') AS takes_with_a_feeling;

-- ════════════════════════════════════════════════════════════════════════
-- From here on: the publication. Run the whole file (or everything from
-- BEGIN to COMMIT). It is one transaction.
-- ════════════════════════════════════════════════════════════════════════

BEGIN;

-- ── STEP 1 · stop now if anything is not as expected ─────────────────────

DO $$
BEGIN
  IF (SELECT string_agg(version, ',') FROM public.processing_policy_versions
       WHERE status = 'active') IS DISTINCT FROM 'phase1-2026-10-27-3.8' THEN
    RAISE EXCEPTION 'STOP: the policy in force is not 3.8.';
  END IF;
  IF EXISTS (SELECT 1 FROM public.processing_policy_versions
              WHERE version = 'phase1-2026-10-28-3.9') THEN
    RAISE EXCEPTION 'STOP: 3.9 (phase1-2026-10-28-3.9) is already registered.';
  END IF;
  IF (SELECT array_agg(version) FROM public.ml_consent_policies
       WHERE grant_scope = 'training_only'
         AND (retired_at IS NULL OR retired_at > now()))
     IS DISTINCT FROM ARRAY['training-only-v4'] THEN
    RAISE EXCEPTION 'STOP: training-only-v4 is not the one training wording in force.';
  END IF;
END;
$$;

-- ── STEP 2 · register 3.9 ───────────────────────────────────────────────
-- The four texts, byte for byte, from legal/phase1-2026.1/copy/: Terms 3.8
-- (3ad7cef6…), Privacy 3.9 (bf659234…), AI notice 3.2 (8b85806c…,
-- unchanged) and the agreement, unchanged since 3.1.

WITH c AS (SELECT
$terms$WillpowerLab — Terms of Service
Version 3.8. Effective 28 October 2026.

These terms are an agreement between you and Artur Willoński, operating under
the name "WillpowerLab" from Poland ("WillpowerLab", "we", "us"). They govern
your use of willpowerlab.com and the WillpowerLab application.

Version 3.8 replaces every earlier version. It adds your plan: a few questions
when you start, a level to work on, practice days and two calls with your
coach (section 1); and signing up and signing in with your WhatsApp number
(section 5). Version 3.7 set out how tokens are sold: free tokens once, when
you join, then packages you buy once, with nothing that renews (section 2). It
said that your coach's answer to a take costs nothing (sections 2 and 11),
that a lesson can be paid for with tokens where the booking page offers it
(section 2), and that WhatsApp also reminds you of a lesson you booked and, if
you ask for it, of your practice days (section 1). It also said what a coach
sees of the one reading the service takes of how sure a moment sounds, which
you are never shown (sections 10 and 11). Version 3.6 added the AI version of
your voice, Will in the Lounge, WhatsApp messages and one-to-one lessons
(sections 1 and 2), and opened the service to residents of California
(sections 4 and 16). Under these terms the sound of your recordings is
processed to deliver your own coaching and is never used to train models.
Four things are yours to choose, and all are off unless you choose them: your
practice may train the models that give every WillpowerLab speaker feedback
when you turn on Help improve WillpowerLab (section 8 and the Privacy Policy,
section 4a); a short clip of a recording may be played to other users when you
lend that recording (section 8 and the Privacy Policy, section 4b); the clips
of a take may be played to a community when you share that take with it
(section 8 and the Privacy Policy, section 4d); and your plan asks its
personal questions only when you say yes to them (section 1 and the Privacy
Policy, section 4e). A coach may also hear a short clip of a recording to
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

WhatsApp. If you give us your phone number, we message you on WhatsApp when
your coach's feedback is in, 10 minutes before a lesson you booked, and, if
you ask for it, on your practice days. You can remove your number at any
time. If you sign up or sign in with WhatsApp, these messages go to that
number.

Lessons. You can book a one-to-one lesson with a WillpowerLab coach, held by
video call. Section 2 says how lessons are paid for and cancelled.

Your plan. When you start, you answer a few questions and get a plan: a level
to work on, practice days and, where you want them, a call with your coach
before you begin and one after your deadline. The calls are booked and paid as
lessons are (section 2). A few of the plan's questions are personal: they are
asked only if you say yes, and you can turn them off at any time (Privacy
Policy, section 4e).


2. WHAT IT COSTS

Work in the app is measured in tokens. The price of each thing in tokens is
shown in the app before you use it.

When you join, you receive free tokens, once. After that, tokens come in
packages. You buy a package once: there is no subscription, nothing renews,
and you are never charged again unless you buy again. The tokens stay in your
account until you spend them; they do not run out at the end of a month. The
packages and their prices are shown before you pay.

Tokens from any package pay for anything the app prices in tokens, including,
where the booking page offers it, a lesson with a coach. Your coach's answer
to a take, in words or as a video, costs nothing.

If your tokens run out, you keep access to everything you have made: your
projects, your Ideal Texts, your feedback and your exports. Things that cost
tokens may wait until you have tokens again.

We will tell you before any price changes. Payments are taken by our payment
provider; we do not see or store your card details.

If you are a consumer in the EU or EEA, you have 14 days to withdraw from a
purchase of tokens. We give you that full 14 days with no questions asked,
even once you have started using them.

A lesson is paid for when you book it, at the price shown on the booking
page, by card or, where the booking page offers it, with tokens, unless the
booking page says it is paid later or free. To cancel or move a lesson, reply
to your confirmation email. If you paid with tokens and cancel at least 12
hours before the lesson starts, your tokens come back. If you are a consumer
in the EU or EEA, you have 14 days from booking to withdraw from it and be
refunded in full; if you ask for the lesson to take place within those 14
days and it does, you can no longer withdraw from it.


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

You can sign in with your email address, with Google or LinkedIn, or with your
WhatsApp number, by a code we send you there. Keep your login details, and the
codes we send you, to yourself. You are responsible for what happens under
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
grade you or produce a verdict about you, and nothing it produces is a
measurement of your ability. The one reading it takes of how sure a moment
sounds, used to choose what to show you, is never shown to you (Privacy
Policy, section 3).


11. HUMAN COACHES

A WillpowerLab coach is a person, and coach review is part of the service
rather than an extra you switch on. Section 1 says why: this is hybrid
coaching, and the human half is not optional to it.

What that means in practice. A coach may listen to your recordings in order to
review the feedback you were given and to prepare practice for you, and may
answer a take in words or with a video. None of this depends on the tokens
you hold, and the answer costs nothing (section 2). A coach does not see the
voice measurements described in section 3 of the Privacy Policy, only, after
answering about a moment, the reading of it that section describes.

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
Version 3.9. Effective 28 October 2026.

This policy explains what WillpowerLab does with your personal data, who else
receives it, how long we keep it, and how you get it deleted.

Version 3.9 replaces every earlier version. It names your plan: the questions
Will asks when you start, what we do with your answers, and the personal ones,
which are asked only if you say yes (sections 2, 4, 4e, 5 and 7). It names the
question "How do you feel?" that may come before a take, which the last
version left out (section 4e). It lets you sign up and sign in with your
WhatsApp number, by a code we send you there (sections 2, 4, 5 and 7). Version
3.8 named two more WhatsApp messages: a reminder 10 minutes before a lesson
you booked and, if you ask for it, a reminder on your practice days (sections
4 and 5). It said that you buy tokens rather than a plan (sections 4 and 5)
and that your coach's answer costs nothing (section 5). It also said five
things the service already did that the version before left out: the one
reading we take of how sure a moment sounds, who sees it, and that you never
do (section 3); Will's note about you and what Will reads of your history
(sections 2, 4, 5 and 7); what you tell Will that reaches your coach or us
(section 4); the card in the Lounge that can ask for the choice in section 4a;
and that clips of recordings we import may be played to you (section 4c).
Version 3.7 said more fully what Will is given to answer you in the Lounge
(sections 4 and 7). Version 3.6 described what WillpowerLab now does that
earlier versions did not: the AI version of your voice, made by ElevenLabs
(sections 3 and 5); talking to Will in the Lounge (section 4); WhatsApp
messages when your coach's feedback is in (section 4); one-to-one lessons you
book with a coach (section 4); signing in with Google or LinkedIn (section 2);
sharing a take with a community (section 4d); and what residents of California
should know, now that the service is open to them (section 14). It also asked
you again for one choice, Help improve WillpowerLab (section 4a), in fewer
words: a yes you gave before version 3.6 does not carry over, so it counts as
off until you say yes again. Your conversation with Will is never used for
training. No recording of your voice, and no clip of one, is ever copied or
sent for training.


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
  LinkedIn, we receive your email address and the name on that account. If you
  sign up with WhatsApp, we ask for your email address only when you book a
  lesson; when you buy tokens, Stripe's payment page asks for it.
- Your slides and presentation materials.
- Audio recordings of you presenting.
- Edits you make to your Ideal Text, and your responses to feedback.
- What you write to Will in the Lounge.
- Your phone number, if you give it to us for WhatsApp messages or to sign up
  and sign in with WhatsApp.
- If you book a lesson: your name, the time zone you choose, the time you
  booked and any note you add.
- Your plan: your deadline; why the event matters to you and what the talk is
  about, and a few answers about the talk, all by voice; the days you pick to
  practise; the times you pick for your calls with your coach.
- If you say yes in section 4e: how stressed and how ready you feel (two taps
  on a scale), what worries you about the talk (by voice), and how it went
  when your plan ends (by voice).
- How you feel before a take, if you answer: one tap, Nervous, Excited, Calm
  or Not sure (section 4e).
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
- Measurements of your plan's voice answers, as section 3 describes, from
  which we choose your level: what your plan works on first. Later levels are
  chosen from your takes.
- A short note about you, at most five lines, on what has helped you and what
  you are working on, written by AI from your answers and your takes
  (section 4).

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

We do not produce a grade or a verdict about you. To choose which of your
moments to show you, we work out for each moment how sure it sounds, from
these measurements, and how plainly it is worded. That reading is a
percentage, and you are never shown it. A coach sees it for a moment only
after giving their own answer about that moment, and the person who runs
WillpowerLab sees it for each take, to check our software. We do not use your voice
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
is given what you write and your recent messages in the Lounge, including the
summary after each take and your coach's word. He is also given your current
project: its title, what each of your slides says, your Ideal Text slide by
slide, how many takes you have recorded, and whether your coach's feedback is
in. If your talk is long, he gets the slides you ask about in full and the
others by their titles. To answer about your past, he is also given the parts
of your own history that fit the question: what you said in earlier takes, in
any of your projects, what your coach sent you, including the words of their
videos, and your own earlier messages. Will only ever sees what is yours. Your
conversation is kept in your account so you can come back to it, and you can
clear it at any time.
Will's note about you. Will keeps a short note about you, at most five lines:
what has helped you and what you are working on. OpenAI rewrites it from your
answers to "Did this help?" and from how each take went. Will reads it before
he answers you and before he writes the summary after a take. The person who
runs WillpowerLab can read it and correct it.
Your conversation with Will is private. A few things you tell Will reach a
person, because your coaching needs them: your coach sees who your talk is
for and what you want your audience to do, and your goal, including when you
change it; the person who runs WillpowerLab sees your answers to "Did this
help?", quotes up to three of them a week, without your name, in a note to
themselves, and can read Will's note about you. Beyond that, nobody at
WillpowerLab reads your conversation, except when we must to keep the service
safe and working, when the law requires it, or when you ask us to, for
example for help with your account. It is never used for training.
Legal basis: performance of our contract with you (Article 6(1)(b) GDPR).

Your plan. When you start, Will asks when your deadline is, why the event
matters to you and what the talk is about, and a few things about the talk.
From your answers and your own voice we choose your level and your practice
days, and we offer you a call with your coach before you start and one after
your deadline. The plan and its answers are kept so that you and your coach
can see where you started and where you are.
Legal basis: performance of our contract with you (Article 6(1)(b) GDPR). The
personal answers in section 4e rest on your consent instead.

WhatsApp messages. If you give us your phone number, we send you a WhatsApp
message when your coach's feedback is in, with a link to it, and 10 minutes
before a lesson you booked, with the link to join it. If you ask for it, we
also remind you on your practice days. No message contains your feedback or
your recordings.
If you sign up or sign in with WhatsApp, we send these messages to that
number.
Legal basis: your consent (Article 6(1)(a) GDPR), which you give by adding
your number, or by signing up with it. You can remove it at any time in Data &
consent, and we stop; if you sign in with it, you still can.

Signing in with WhatsApp. If you sign up or sign in with your WhatsApp number,
Supabase makes a six-digit code, valid for 10 minutes, and we send it to you
on WhatsApp. We do not keep the code ourselves: Supabase keeps it only in
hashed form until it is used or expires, and our message stays in your
WhatsApp chat.
Legal basis: performance of our contract with you (Article 6(1)(b) GDPR).

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

If you buy tokens or pay for a lesson by card, your payment is handled by
Stripe. We never see or store your card details; we hold the record of what
you bought, what you spent your tokens on and which lessons are paid, and
the invoices we are required to keep.

We never use the sound of anyone's recordings to train models: no recording,
and no clip of one, is copied or sent for training. Making the AI version of
your voice is not training: it makes a voice for you alone. What may be used
for training, and only with your yes, is set out in section 4a. Recordings we
import from elsewhere are covered in section 4c.

Do you have to provide this data? For the parts the service is made of, yes.
Recording your voice, having it transcribed, and having a coach able to review
your feedback are what WillpowerLab is; there is no version of it that works
without them, so if you are not willing to provide them you cannot use the
service. Practice is part of the service too, though doing any one exercise is
always up to you. So are your plan's questions about your event. Your phone
number, a lesson booking, talking to Will, your plan's personal answers
(section 4e) and how you feel before a take are up to you.

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
The personal answers of your plan, and how you feel before a take, are asked
only as section 4e says.

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
with it, and your coach's videos are not part of it either. While the switch
is on, OpenAI writes out the words of your coach's videos about your takes;
those words are kept with the take, and Will can read them to answer you, but
they are not used for training.

What is used from before you turn it on: the words of passages already in your
account, and your coach's words about them, can be used too. Separate copies are made only from takes you record while the
switch is on.

Legal basis: your consent (Article 6(1)(a) GDPR). You give it by turning the
switch on, on its own screen, or by answering yes on a card in the Lounge
that asks only this, in the same words. If you answer no, it is not asked
again for at least 30 days. It is never on when you sign up, never
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
by WillpowerLab coaches without a name. Short clips of it may be played to
WillpowerLab users in their feedback, as another speaker's voice to listen
to: sound only, without a name or any words. The person speaking has no
account with us.

What we hold: the recording, its transcript, its measurements, and coaches'
and users' answers about it. Like everything else used for training, it is never sent to
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


4e. YOUR PLAN: PERSONAL ANSWERS — OPTIONAL

Part of your plan is personal. If you say yes, Will also asks how stressed you
feel about the talk and how ready you feel, each as a tap on a scale; what
worries you most about it, which you answer by voice; and, when your plan
ends, how it went, by voice. Before a take you may also be asked how you feel,
with one tap: Nervous, Excited, Calm or Not sure. You can skip it every time.

These answers can say something about your state of mind, so they can count as
sensitive. We use them to shape your plan and to help your coach prepare. You
are never shown a number for them. Your coach and the person who runs
WillpowerLab can see them, and Will reads your voice answers. OpenAI writes
out your voice answers and helps Will reply (section 5). They are never used
to train models, and they are not part of the choice in section 4a.

If you say no, we do not ask them and your plan is built from the rest.
Nothing else changes.

Legal basis: your explicit consent (Article 9(2)(a) GDPR), which you give by
saying yes when Will asks, or by turning the card on in Data & consent. You
can turn it off at any time: we stop asking and delete the personal answers
you gave, and how you felt before your takes. Withdrawing does not affect what
we did lawfully before.

If you have no plan yet. Before a take you may be asked how you feel, with one
tap, and you can skip it every time. Your coach sees your answer. Answering is
your explicit consent to our keeping that one answer (Article 9(2)(a) GDPR);
skipping costs you nothing. To have the answers you gave deleted, write to
contact@willpowerlab.com.


5. WHO ELSE RECEIVES YOUR DATA

AI providers

OpenAI receives:
- the audio of your recording, in order to transcribe it;
- parts of your transcript and related text, in order to generate your Ideal
  Text and your feedback;
- what you write to Will, your recent Lounge messages and your project as
  described in section 4, in order to answer you;
- each practice example made in the AI version of your voice, in order to
  check by transcribing it that it says your words;
- your answers and how your takes went, in order to rewrite Will's note about
  you;
- your plan's voice answers, in order to write them out, choose your next
  question and answer you;
- if you turned on the choice in section 4a, the sound of your coach's videos
  about your takes, in order to write out their words.

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
- Supabase: our database, sign-in, and audio storage on a fallback path. If
  you sign in with WhatsApp, Supabase makes and checks your code.
- Railway: hosting of the application. Railway is our processor for what it
  hosts on our behalf, and a controller in its own right for its own account
  and service-usage records about us as its customer.
- Resend: transactional email, including lesson confirmations.
- Vercel: hosting of the website.
- Sentry: error reports, stored in the European Union.

Messaging
- Meta (WhatsApp), if you give us your phone number: your number and our
  messages to you: that your coach's feedback is in, with its link; that a
  lesson you booked starts in 10 minutes, with the link to join it; and, if
  you ask for them, the reminders on your practice days; and, if you sign up
  or sign in with WhatsApp, the code we send you. Meta also handles those
  messages as a controller for its own service, under WhatsApp's terms.

Signing in
- Google or LinkedIn, if you choose to sign in with them. They tell us your
  email address and name; they decide for themselves, under their own terms,
  what they do with the fact that you signed in.

Payments
- Stripe, if you buy tokens or pay for a lesson by card. Stripe is not our
  processor: it decides for itself how it uses payment data, as a controller
  in its own right, under its own terms. We never see or store your card
  details.

Human coaches
A WillpowerLab coach — a person — may listen to your recordings in order to
review the feedback you were given and to prepare practice for you. The review
is part of the service rather than an extra you
switch on, because WillpowerLab is hybrid coaching; the Terms say so in section 1 and section 11, and an answer
that comes back to you costs nothing. A coach who reviews your
recording does not see the voice measurements described in section 3, only,
after answering about a moment, the reading of it that section describes. Coaches
are bound to confidentiality and see only what a review requires.
A coach may answer you in writing or with a video; a video answer is for you.
If you book a lesson, the coach receives your name, your email address, the
time and any note you add.
A coach sees your plan: your deadline, why the event matters to you, your key
line, your level, your practice days and the time of your calls. If you said
yes in section 4e, a coach also sees how stressed and how ready you feel, and
how you feel before a take. If you have no plan and answer how you feel before
a take, your coach sees that answer.
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

Will's note about you, and the answers and take outcomes it is written from:
kept while your account is open, and deleted when you close it.

Your phone number: kept until you remove it or close your account. If you sign
in with it, removing it stops the messages, and it stays as your way in until
you close your account.

Your plan: your deadline, your voice answers and their recordings, your level
and its history: kept while your account is open, and deleted when you close
it. Deleting a project does not delete them. The personal answers of section
4e are also deleted when you turn them off.

How you feel before a take: kept while your account is open, and deleted when
you ask or when you close it, and, if you have a plan, when you turn off its
personal answers.

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
sensitive they happen to reveal; and the personal answers of your plan and how
you feel before a take, which you give only if you choose (section 4e). We use it only to provide the service you
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
    'version','phase1-2026-10-28-3.9',
    'terms_version','terms-3.8-2026-10-28',
    'terms_copy', c.terms,
    'terms_copy_sha256', encode(extensions.digest(c.terms,'sha256'),'hex'),
    'privacy_version','privacy-3.9-2026-10-28',
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
    'version','provisional-founder-2026-10-28-3.9',
    'approving_authority','founder:artur@willonski.com',
    'approved_at', now(),
    'object_key','legal/phase1-2026.1/01-product-legal-approval-v1.1.pdf',
    'sha256', encode(extensions.digest('provisional-legal-2026-10-28-3.9','sha256'),'hex'),
    'metadata', jsonb_build_object('counsel_review','answered_by_correspondence_2026-10-01',
      'unbundled','true','supersedes','provisional-founder-2026-10-27-3.8',
      'coach_review_basis','contract',
      'practice_basis','contract_6_1_b_N55_WQ3a_B',
      'practice_counsel_review','not_obtained_founder_signed_in_place_2026-10-08',
      'blind_check_basis','legitimate_interest_6_1_f_with_written_objection',
      'lending_basis','explicit_consent_9_2_a_per_recording',
      'training_basis','consent_6_1_a',
      'training_consent_policy','training-only-v4',
      'learning_counsel_review','not_obtained_founder_signed_knowing_2026-10-08',
      'corpus_import_basis','legitimate_interest_6_1_f_D4',
      'founder_ruling','2026-10-15 the 3.6 pack signed in chat (N72), D1 to D8; v4 and the 15 October changes approved (N73); Privacy 3.7, what Will is given, approved in chat: approve all (N74); 2026-10-27 Terms 3.7 and Privacy 3.8 signed in chat (N208); 2026-10-27 Terms 3.8 and Privacy 3.9 signed in chat, question 1 A, question 2 A, counsel agrees (N217)',
      'plan_personal_answers_basis','explicit_consent_9_2_a_own_yes_N211',
      'feelings_without_a_plan_basis','explicit_consent_9_2_a_by_answering_N217',
      'whatsapp_sign_in_basis','contract_6_1_b_N214',
      'ai_voice_basis','contract_D3', 'whatsapp_basis','consent_6_1_a_by_adding_the_number_or_signing_up_with_it_D4_N214',
      'community_sharing_basis','explicit_consent_9_2_a_per_take_D5',
      'us_scope','california_residents_only_D8')),
  jsonb_build_object(
    'artifact_kind','power_score_classification',
    'version','provisional-founder-2026-10-28-3.9',
    'approving_authority','founder:artur@willonski.com',
    'approved_at', now(),
    'object_key','phase1-2026.1/legal/power-score-classification-v1.3.pdf',
    'sha256', encode(extensions.digest('provisional-power-2026-10-28-3.9','sha256'),'hex'),
    'metadata', jsonb_build_object(
      'counsel_review','founder_determination_not_counsel_reviewed',
      'document_version','1.3 note signed 2026-10-27 (N208), on 1.2 signed 2026-10-08 (N68)',
      'biometric_identification', false,
      'sex_gender_inference', false,
      'emotion_intention_inference', false,
      'pipeline_version','voice-confidence-universal-v3',
      'detector_versions', jsonb_build_object('rushing','rules-v1',
        'word_compression','rules-v1','ending_compression','rules-v1'))),
  jsonb_build_object(
    'artifact_kind','article_50_assessment',
    'version','provisional-founder-2026-10-28-3.9',
    'approving_authority','founder:artur@willonski.com',
    'approved_at', now(),
    'object_key','phase1-2026.1/legal/article-50-assessment-v1.0.pdf',
    'sha256', encode(extensions.digest('provisional-article50-2026-10-28-3.9','sha256'),'hex'),
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

-- ── STEP 3 · activate 3.9 ─────────────────────────────────────────────────
-- Retires 3.8 and writes carryovers for any job in flight. From this moment
-- every speaker is asked to accept 3.9 (the update prompt, one tap).

SELECT public.activate_phase1_policy_v1(
  'phase1-2026-10-28-3.9',
  'founder:artur@willonski.com',
  encode(extensions.digest('phase1-activation-2026-10-28-3.9','sha256'),'hex')
);

-- ── STEP 3b · delete the feelings given before 3.9 (N217, question 2 A) ──
-- Every answer to "How do you feel?" so far was given with no text that
-- named it. All of them go: the recording_feelings rows, and named_emotion
-- on each Take's intake_context (the column's JSON type is read first).

DO $$
DECLARE
  v_type TEXT;
BEGIN
  IF to_regclass('public.recording_feelings') IS NOT NULL THEN
    DELETE FROM public.recording_feelings;
  END IF;
  SELECT data_type INTO v_type FROM information_schema.columns
   WHERE table_schema = 'public' AND table_name = 'v2_sessions'
     AND column_name = 'intake_context';
  IF v_type = 'jsonb' THEN
    UPDATE public.v2_sessions SET intake_context = intake_context - 'named_emotion'
     WHERE intake_context ? 'named_emotion';
  ELSIF v_type = 'json' THEN
    UPDATE public.v2_sessions
       SET intake_context = (intake_context::jsonb - 'named_emotion')::json
     WHERE intake_context::jsonb ? 'named_emotion';
  END IF;
END;
$$;

-- ── STEP 4 · the last guard before anything is kept ──────────────────────

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM public.processing_policy_versions
                  WHERE version = 'phase1-2026-10-28-3.9' AND status = 'active')
     OR (SELECT count(*) FROM public.processing_policy_versions WHERE status = 'active') <> 1
     OR (SELECT terms_copy_sha256 FROM public.processing_policy_versions
          WHERE version = 'phase1-2026-10-28-3.9')
        <> '3ad7cef6a2bfaa37eadb8931ab1ef58669e02b3bbc09b309f39eac6cadf55b69'
     OR (SELECT privacy_copy_sha256 FROM public.processing_policy_versions
          WHERE version = 'phase1-2026-10-28-3.9')
        <> 'bf6592344205809241f3eb6075ea8acba14bc3d690d96a7209a2decd8b2a9726'
     OR NOT EXISTS (SELECT 1 FROM public.processing_policy_versions
          WHERE version = 'phase1-2026-10-28-3.9' AND 'us' = ANY(allowed_countries)) THEN
    RAISE EXCEPTION 'STOP: 3.9 is not in force with the approved bytes and the United States.';
  END IF;
  IF (SELECT array_agg(version) FROM public.ml_consent_policies
       WHERE grant_scope = 'training_only'
         AND (retired_at IS NULL OR retired_at > now()))
     IS DISTINCT FROM ARRAY['training-only-v4'] THEN
    RAISE EXCEPTION 'STOP: the training wording changed; it must stay training-only-v4.';
  END IF;
END;
$$;

COMMIT;

-- ── STEP 5 · the check (this is the result the editor shows you) ─────────
-- Expect ONE row: processing_policy = phase1-2026-10-28-3.9, purposes = 5,
-- required = 5, approved_bytes = true, has_us = true,
-- training_policies_in_force = {training-only-v4}; people_with_a_yes_now is
-- the same number STEP 0 showed; feelings_left = 0 and
-- takes_with_a_feeling = 0.

SELECT p.version AS processing_policy,
       p.activated_at,
       (SELECT count(*) FROM public.processing_policy_purposes pp
         WHERE pp.policy_id = p.id) AS purposes,
       (SELECT count(*) FROM public.processing_policy_purposes pp
         WHERE pp.policy_id = p.id AND pp.required_for_core_service) AS required,
       (p.terms_copy_sha256 = '3ad7cef6a2bfaa37eadb8931ab1ef58669e02b3bbc09b309f39eac6cadf55b69'
        AND p.privacy_copy_sha256 = 'bf6592344205809241f3eb6075ea8acba14bc3d690d96a7209a2decd8b2a9726') AS approved_bytes,
       ('us' = ANY(p.allowed_countries)) AS has_us,
       (SELECT array_agg(version) FROM public.ml_consent_policies
         WHERE grant_scope = 'training_only' AND active_from <= now()
           AND (retired_at IS NULL OR retired_at > now())) AS training_policies_in_force,
       (SELECT count(*) FROM public.training_consent_active_grants) AS people_with_a_yes_now,
       (SELECT count(*) FROM public.recording_feelings) AS feelings_left,
       (SELECT count(*) FROM public.v2_sessions
         WHERE intake_context::jsonb ? 'named_emotion') AS takes_with_a_feeling
  FROM public.processing_policy_versions p
 WHERE p.status = 'active';

-- ── AFTERWARDS ───────────────────────────────────────────────────────────
-- Speakers see the update prompt and accept 3.9 in one tap. Then, on
-- Railway, web and worker: PLAN_CONSENT_ENABLED=true (the plan's own yes).
