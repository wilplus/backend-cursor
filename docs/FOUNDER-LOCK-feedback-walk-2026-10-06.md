# Founder lock — the Feedback walk, its look and its motion (2026-10-06)

`LOCKED 2026-10-06 · flow yes · UI and UX yes · motion yes · engines yes · open: CM1 · CM2 · CM3 · B01–B14 · Journal post · sharing words`

Locked by the founder on 2026-10-06 from the clickable prototype ("once done,
please lock the user flow we have defined here, the design we have now is
good! it should be unified everywhere across the app", and "please lock in
also the small interactions, the smoothing, how the screens change from one
to another"). The prototype is the design; this file is its written record
and the acceptance criteria to check when it is built:
<https://claude.ai/artifact/C2CTBmU1bfSSDQgJUHTKkE> (version 10, "Locked with
motion"; the same summary sits beside the screens).

Nothing here is built yet. Where this file disagrees with an older design
lock, this one wins; the amendments are listed below. Every user-facing
string named here is founder-signed; any other string still needs the
founder's sign-off.

## The flow

1. **Lounge.** When new feedback from the coach arrives, the Ideal Text
   bubble in the Lounge gets the orange outline and a "new" tag. The
   paragraph on the page keeps only its bar, never an outline.
2. **Ideal Text page.** "Review feedback" starts the walk; tapping a
   paragraph opens that paragraph's feedback.
3. **The coach's note for the Take** comes first: the coach's video, then
   their words.
4. **Praise first.** All the praise moments, then the moments to practise.
5. **Helper words** come right after a praise, or after a practise that
   ended in praise: "Choose your helper words", at most four.
6. **Clearer version.** The speaker's words with the changed words crossed
   out, then the coach's message: "Here is a slightly more polished
   option:", the new text with the new words in orange, and "Do you accept
   and want to practise it?". Buttons: "Accept and practise", "Keep my
   words".
7. **Practising** records at once, on the Take's own recording bar, with no
   title and no slide bar. The machine checks each try (the app's loading
   mark while it does). Praise ends the loop; otherwise "It was better, and
   I have yet another practice for you to try!" and another practise, until
   praise or Skip.
8. **Exercise.** The coach's video with "Practise", then the instruction and
   the words to say.
9. **"Judgement time!"** after the practising: "If you are honest when
   judging others, it will help you find your confident voice and calm the
   inner critic 😌", the grey link "More about self-modeling theory" (opens
   the Journal post inside the flow), the black "I am going to judge them
   honestly" and a grey "Skip".
10. **The judgements.** "Does this sound confident to you?" with the
    speaker's voice only, no words. Yes, In-between, No, with "Not sure"
    and "Audio unclear" smaller below. An answer moves on by itself with a
    small toast.
11. **Sharing.** "After all, it's about speaking publicly!" / "Do you agree
    to share this take with others?" after every finished review. Several
    choices may be ticked (general community, only my community with a pass
    code, set up my own community with a name and a pass code); "None"
    stands alone.
12. **End.** "Record Take N" and "Back to the text".

## UI and UX, everywhere in the app

- Minimal: black, white, grey and one orange. No comic or handwritten fonts.
- Feedback opens as a full-screen overlay; nothing of the page shows behind
  it.
- One player and one judgement screen design across the app. "Not sure" and
  "Audio unclear" are smaller than the three main answers.
- The speaker's part is a plain white box with their voice. Their words show
  only where the feedback is about the words (the clearer version).
- Every message is plain black text with a small grey profile picture beside
  it: the coach's photo for the coach, the app's picture for the app. Both
  are the same grey style.
- No sender labels such as "Your coach" or "What you said".
- One loading animation: the app's breathing voice mark (`VoiceMark`).
- The slide and moment bar (‹ Slide 2 · moment 1 of 4 ›) on every feedback
  screen; none on the recording screen.
- Recording uses the Take's own recording bar.
- Orange marks only new words and the Lounge's "new". *(Amended 2026-10-07,
  Q-B9 A, N63: this rule applies inside the walk only. Outside it, the
  bars, the helper-word headlines on the page, in Presentation Mode, in the
  export and in Recording Mode, and the coach panel's "Something else" stay
  orange.)*

## How screens move, everywhere in the app

- Nothing blinks: every change of screen moves. What arrives eases out
  (`cubic-bezier(.2,.8,.2,1)`); what leaves eases in
  (`cubic-bezier(.4,0,1,1)`).
- **Opening feedback:** the overlay rises from the bottom over the page,
  0.38 s. **Closing** (✕ or the end): it sinks back down, 0.28 s, with the
  page already underneath.
- **Next and back** (‹ ›, Next, Continue, Practise, an answer): the top bar
  stays still; the old content slips 22 px away and fades in 0.14 s; the new
  content slides in from the side being headed to, 0.3 s after a 0.1 s
  pause. Back mirrors it.
- **Soft cross-fade** (0.34 s with a slight lift) for the screens that stand
  apart ("Judgement time!", sharing) and for one moment changing state
  (recording, then checking, then praise or encouragement).
- **Lounge and the text:** a short sideways push. **Recording Mode:** fades
  to dark, 0.4 s. *(Amended 2026-10-07, Q-B14 A, N63: a soft 0.4 s fade
  into and out of the white Recording Mode screens, as the recording lock
  draws them; instant with reduce motion, and the fade never delays the
  recording.)*
- **End card:** the page dims and the card rises; leaving, the card sinks and
  the dim fades.
- **Small touches:** a pressed button gives way slightly (scale 0.98); a
  chosen answer fills black, holds 0.28 s, then moves on with the toast;
  ticks, helper words and colour changes fade in 0.16 s; extra fields rise
  in; redrawing the same screen (a tick, a word) does not move.
- With the phone's reduce-motion setting on, every move is instant.

## The engines

- **Practise check.** A practise never asks the speaker "did it sound
  confident?". The machine compares the try with the moment and decides
  improvement or not. Never a score, number or verdict on screen (AC-9).
- **Line bank.** Every praise and rewrite message comes from a
  founder-signed bank (B01 to B14, three phrasings each): rotated, never the
  same line twice in a row; "later" lines name the speaker's own progress
  only when it is true. Learning which phrasing helps may choose only from
  the signed bank; pooled learning uses only Takes with the training yes.
  Until the bank is signed, only the already-signed lines ship.
- **Helper words** come from a moment that sounded confident.
- **Judgements** remain the speaker's own Voice Album answer, kept apart from
  the coach's and the machine's (L3).
- **Communities.** Shared Takes are judged by the community the speaker
  chose. With "None", only the coach judges their Takes. When judging:
  the community's Takes first, then the speaker's own mixed with
  machine-picked training clips. Community ratings are peer ratings, a
  separate provenance (L3).
- **Sharing consent** is per Take; taking it back removes that Take from
  every community queue.

## Communities will work

Founder, 6 October: "the community will be working". The sharing question,
the four choices and the judging order in the flow and engines above are
part of the product, not an experiment. Community answers are peer
ratings, kept apart from the coach's, the speaker's own and the machine's
(L3). The sharing screen asks for consent, so its words go to counsel
before it goes live, and they never rotate. CM1 and CM2 below are the
parts still to decide. Decisions log N52.4.

## Words signed in this round

Written by the founder in chat, signed (decisions log N52.5):

- "It was better, and I have yet another practice for you to try!"
- "Judgement time!"
- "If you are honest when judging others, it will help you find your
  confident voice and calm the inner critic 😌"
- "More about self-modeling theory"
- "I am going to judge them honestly"
- "Skip"
- "Here is a slightly more polished option:"
- "Do you accept and want to practise it?"
- "Practise" (the exercise video's button)
- "After all, it's about speaking publicly!"
- "Do you agree to share this take with others?"

Every other word on these screens is already in the signed copy
(`CHUNK_SHEET_COPY`). Not yet signed: the line bank B01 to B14, the
community options' words (held for counsel) and the Journal post.

## Amendments to older locks

- **Helper-words lock (2026-09-30), B2 and the walk order:** the
  helper-words step now follows a praise, or a practise that ended in
  praise, instead of following a Yes or In-between judgement; the
  judgements come after the practising, under "Judgement time!".
- **Practise self-judgement (contract 24e, 29a):** the speaker is no longer
  asked to judge a practise; the machine's check ends or continues the
  loop. The canonical contract is updated when this is built.
- **Sender labels (design lock, N48.3 Q8/Q10):** messages carry a grey
  profile picture and no "Your coach" label. Q10's status line is
  untouched.
- **Practise screen:** no title, no slide bar and no helper text; the
  exercise video is its own screen before it.
- **Lounge:** the "new" marker sits on the Ideal Text bubble, not on the
  paragraph; the Lounge still never opens the text by itself (journey
  question 2).

## Still open

*Updated 2026-10-07 (build plan D-OP-3).* Settled since this lock was
written:

- **CM1 A** (N53.2): only the voices of people who agreed to share reach
  others; the training clips mixed into judging are the licensed corpus.
- **CM2 B** (N53.2): sharing is built and switches on with the sharing
  screen, under the founder's own words for it, without waiting for
  counsel; the consent stays per Take, revocable, and stamped with the
  version of the words the speaker saw.
- **CM3 A, CM3a A, CM3b A** (N53.2, N54.2, N55): up to three tries; after
  the third try that is not praise, a signed thank-you line and on to
  "Judgement time!".
- **B01 to B14** (N54.1): the line bank is signed
  (`docs/SIGNED-line-bank-2026-10-06.md`).
- **The Journal post** (N53.4, JP1 A): signed as drafted; publishing it is
  build plan D-OP-2.
- **The sharing screen's words** (N54.3, WQ5 A, WQ6 A): signed.
- **Q-B3, Q-B5, Q-B9, Q-B10, Q-B14** (N63): how a tap on a paragraph opens,
  the connected helper-word phrase, orange inside the walk only, the bars
  and buttons after the walk, and five small look choices.

Still open:

- **"None"** on the sharing screen (Q-B6 A): to sign; on the panel as S-B6.
