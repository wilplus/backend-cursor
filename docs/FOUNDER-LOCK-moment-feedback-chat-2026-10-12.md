# Founder lock — moment and feedback, one chat with a lens (2026-10-12)

`LOCKED 2026-10-12 · flow yes · UI yes · words yes · backend rules yes · learning yes`

Locked by the founder on 2026-10-12 ("approved, lock it and write the lock
file"), from the clickable prototype
<https://claude.ai/artifact/TXbwmupWJio6N1gHqdEa7p> (version 27; version 31 is final: version 28 aligns the practice recorder with the 2026-10-12 recording lock, and versions 29–31 apply the last answers in section 9). The
prototype is the design; this file is its written record and the acceptance
check when it is built. Nothing here is built yet.

**Build it super simple.** The founder said so, in these words: "make the
code super stupid simple! no not necessary tests … bare minimum just to
launch and test". Reuse what exists (the Lounge thread, the walk's screens,
the recorder, `voice_confidence`, `willfidence`, the line bank,
`session_cadence`). Add only the tests the critical path needs.

Where this lock disagrees with an older one, this lock wins. It amends:

- `FOUNDER-LOCK-feedback-walk-2026-10-06.md`: the order, the overlay frame,
  the judging step and sharing.
- `FOUNDER-LOCK-helper-words-2026-09-30.md`: the Ideal Text page, its
  bookmarks and how helper words look.
- `FOUNDER-LOCK-coach-panel-redesign-2026-10-06.md`: the coach's answers
  only.

## 1. One chat, two views

- **One thread, stored once.** It's the Lounge thread (`lounge_messages`).
  Every step of the review is a message in it, and each message has one
  author: the speaker, the app (line bank), the coach, the rewrite (LLM) or
  the summary (GPT-4o). Nothing is copied.
- **Lens on, the walk.** It shows the same messages one step at a time, full
  screen, with large bubbles and built-in buttons and no message box. The
  top bar has ‹ › and ✕. The lens turns on by itself when a Take's
  feedback is ready.
- **Lens off, the Lounge.** ✕ turns the lens off and shows the same steps as
  normal chat bubbles. A step that asks something is a message with
  controls. Once answered, it locks and keeps the answer, and the answer
  also shows as the speaker's own bubble.
- **Turning the lens back on.** Tapping a bubble with › turns the lens on at
  that step. A step still waiting has an orange outline, and "Continue
  review" shows above the message box until every step is answered.
- **Bubbles.** The speaker is orange, on the right. The app and the coach
  are light grey, on the left, with a small avatar (the coach's avatar is
  grey-blue). In the lens the text is 18.5px with 22px corners and a 22px
  avatar. In the chat the text is 15px with 16px corners and a 20px avatar.
  These sizes are the same on every screen.
- **The Lounge has no record button.** Only the message box.
- **While the Take is processing,** the chat shows "Processing your
  recording" with the app's breathing mark. The lens opens when the
  feedback is ready.

## 2. The walk, in order

1. **The coach's note for the Take, if there is one.** A coach bubble with
   the video (or words only), then "Continue".
2. **Green moments.** At most 1 per slide and 3 per Take, in slide order.
   Each shows the speaker's clip as an orange bubble, then "Good job" and one
   signed line from B01–B09, then "Next".
3. **Choose your helper words**, after each green moment. The picker fills
   the screen with large word buttons, "N of 4 words", "Use these helper
   words" and "Skip". Helper words stay editable from the chat. Once a newer
   Take exists, the older Take's words are locked ("🔒 Take N").
4. **One exercise**, on the Take's lowest sentence. It's never called weak.
   - **Words weaker:** the Clearer version, with the signed lines,
     "Accept and practise" and "Keep my words". "Keep my words" practises
     the speaker's own sentence with Line A.
   - **Voice weaker:** Exercise, with the video and the instruction (from
     the coach when there is one, otherwise Line A), then "Practise" and
     "Skip".
5. **Practise.** The recorder is the recording screen as re-locked on
   2026-10-12 (N70, `FOUNDER-LOCK-recording-screens-2026-10-07.md`), without
   the slide card. At the top is the coach's or app's message as a bubble,
   then the words to say. The strip holds only the dot, the clock and the
   bar. Under it is the pair: "Skip" (the Back style) and a red "Stop" (the
   Finish-take style, because a practice is one sentence). ✕ goes back to
   the walk. After Stop the walk returns instantly, with no rise
   animation; the breathing mark shows while the try is checked.
   - Each try comes back as an orange bubble labelled "Practise N". Then:
     - **Not yet:** "Practise" with the signed encouragement, then
       "Practise again" and "Skip".
     - **Better:** "Good job" with "That sounded more assured than the
       first." and "Next".
   - At most 3 tries, then the signed move-on line. Nothing else interrupts
     the practice.
6. **Judge other speakers, once, after practice.** One moment per try, at
   least 1 and at most 3. There's no judging if no shared clips exist yet.
   - The first moment opens with "Now one moment from another speaker."
     (or "Now N moments from other speakers.") and the clip, in one system
     bubble.
   - "Does this sound confident to you?" is regular weight, in that same
     bubble.
   - The answers are large and full width: 👍 Yes, 😐 In-between, 👎 No.
     "Audio unclear" is a small link. "Not sure" is gone.
   - An answer moves on by itself after 0.28s. The top bar reads "Other
     speakers · 1 of N". Answers stay locked once given.
7. **The closing summary,** then "Next", which opens the Ideal Text.

"Judgement time!" and judging your own moments are no longer in the walk.
Judging your own practice try is on hold and off; the self-judgement query
pack decides it.

## 3. The closing summary

- **One plain bubble,** 2–3 sentences, written by GPT-4o (`STRONG_MODEL`)
  through `session_cadence.fire_post_take`, which is built but not yet
  called. Every call goes through the processing-authorization path.
- **What it starts from:** the spirit of the signed journey copy for that
  Take (anchors, not a script; talk to them like a friend).
- **What it adds:** this Take's real progress against the last one, from the
  audio analysis (for example "your endings landed this time"); the practice
  result; the coach's asks; and at most two helper words.
- **How it sounds:** like a coach talking. It uses "you", contractions and
  plain words, never "cue" or metric names. No numbers, scores or verdicts,
  and no cheerleading.
- **After Take 1,** it claims no progress.
- **In the chat,** the review ends with the Ideal Text card ("Q3 Board
  pitch · AI-generated text · Take N", with ›), then the summary as a plain
  bubble that can't be tapped.
- **A coach update** arrives later under "Later · from your coach", outlined
  in orange because it's new. It rewrites the summary in place. The earlier
  version stays one tap away: "Updated with your coach's note · see / hide
  the earlier version".
- **A coach update during a recording** waits in the chat. It never
  interrupts the recording.

## 4. The Ideal Text page

- **It opens from its card,** or after the summary. It's no longer the
  landing screen.
- **No bookmarks and no pencil.** Helper words are simply orange in the
  text. Tapping them opens that slide's helper-words step. Tapping a
  sentence that was a moment or the exercise opens that step. Other text
  does nothing.
- **Buttons:** "Record Take N" is the main button and the grey "Close" goes
  to the chat. History is under ⋯.
- **Rule 5 holds.** An accepted clearer version doesn't change the Ideal
  Text; it gets there when it's said in the next Take.

## 5. Sharing, before the next recording

- It's asked when "Record Take N" is tapped, from Take 2 on, and never
  before Take 1.
- The signed opener and question stay. The options are:
  - **General community.**
  - **Only my community.** Inside it, the speaker's saved communities (a
    passcode is entered once). With one community it's ticked; with several,
    all are ticked by default and any can be unticked. "+ Add a community
    with a passcode" stays at the bottom.
  - **Only me.** It stands alone.
- The choice applies to the Take about to be recorded.

## 6. Backend: how a moment is picked

```
willfidence(sentence) = S × W                 0 … 1
  S = voice_confidence (7 cues vs the speaker's own baseline), 0–1
  W = mean of: few fillers/hedges · fits the slide · holds together
green(slide)  = the best sentence on the slide, if ≥ FLOOR and ≥ 5 words
moments       = the top 3 green, in slide order; none → the single best, softer signed line
exercise      = the lowest sentence; W < S → Clearer version, else voice Exercise
practice try  = Δ willfidence vs the original ≥ +0.05 → better
```

- The unit is the sentence; it used to be a 75-word block.
- FLOOR is 0.6 at launch, then calibrated so that about 7 in 10 blind judges
  say 👍 to green sentences.
- MARGIN is +0.05.
- Only "green" is sent to the app. The exercise target goes out with no
  label.
- At most 1 rewrite per Take.

## 7. Learning

- **Labels come only from blind answers:** the coach, and other speakers
  inside practice. 👍 = 1, 😐 = 0.5, 👎 = 0.
- A label counts once 2 answers match. "Audio unclear" goes to a fresh
  judge; twice, and the clip is quarantined.
- The clips judged are half green and half low sentences.
- The speaker's own answers are never labels (L3).
- Training tunes the willfidence weights against the soft label, once there
  are at least 200 labels, with a speaker-disjoint split. It's checked on
  the sealed golden set, re-sealed under the new question version, and the
  founder promotes it as `willfidence-v2`.
- Coaches move to the same 👍 😐 👎 plus "Audio unclear", and keep the signed
  "Skip". Old answers stay as they are.
- Message relevance is read from behaviour (practised, skipped, retried, and
  whether the next Take rose) as a report for the founder, not as a label.

## 8. Words signed on 2026-10-12

- **Line A:** "Say this one like your confident moment."
- **Line B:** "Now one moment from another speaker." and "Now N moments
  from other speakers."
- **Chat and walk labels:** "Moment N of N", "Other speakers", "Practise N",
  "Continue review", "Close", "Later · from your coach", "Updated with your
  coach's note · see / hide the earlier version".
- **Sharing:** "Only my community", "Only me", "+ Add a community with a
  passcode".
- **The summary:** GPT-4o's text under the rules in section 3.

## 9. Last answers (2026-10-12)

- **Sharing.** The question now reads "Do you agree to share your next take
  with others?" (it changes signed words). "After all, it's about speaking
  publicly!" is regular weight, not bold. The option subtitles stay.
- **The Ideal Text page** has one way out, the grey "Close"; there's no ✕
  at the top. A sentence that opens a step shows a light grey highlight
  while it's pressed.
- **The helper-word picker** uses big plain words with no borders. The
  chosen words turn orange.

- **No bold in any bubble,** in the walk or the chat.
- **Who you judge follows who you share with.**
  - **Only my community:** the moments you judge come from your community
    first, and the general community fills in. The bridge line names it:
    "Now one moment from Invita." / "Now N moments from Invita.", and the
    top bar reads "Invita · 1 of N".
  - **General community:** you judge the general community, and its
    members may hear your Take.
  - **Only me:** nobody but the coach hears your Take, but you still judge
    general-community moments.

## Still open

- **Self-judgement of your own practice try is off for launch** (founder,
  2026-10-12). The query pack showed 4 speaker answers in total, 21 clips
  with coach answers, and only 1 clip with both: too few to judge. Re-run
  `1-enough-data.sql` once coaches have judged more moments. When
  `clips_with_both` reaches about 50, run the agreement and gap queries and
  decide.
