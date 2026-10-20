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
   the screen with large word buttons, "N of 6 words", "Use these helper
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
                (amended 2026-10-18: the rewrite gate decides; see "Words first, then voice")
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

## Decided after the lock

- **When the coach changes their word** (founder, chat, 2026-10-19, N80;
  prototype <https://claude.ai/artifact/APk56PLZt6o6Cx9qUMKkuk>). Amends
  section 1 and section 3:
  - **One "Later · from your coach" bubble per Take word.** A change moves
    it to the bottom with the latest words and video; it is never stacked.
  - **A removed or replaced coach video no longer plays** anywhere in the
    chat. The file stays stored.
  - **The same words and video again change nothing** for the speaker.
  - **Watching the word anywhere** (the WhatsApp or email link, the dot
    card, the bubble) clears its "new" marks, and the walk writes the
    coach's words into the chat only once. Only "Continue" on the coach's
    step or "Close" on the bubble marks it watched; ✕ keeps the ring.
  - **"See the earlier version"** is the summary from before any coach
    note, however many edits followed; when the first summary already
    heard the coach, it is that first summary.
  - **A video-only change does not rewrite the summary,** but during the
    review a new or removed video with the same words makes the word new
    again: Step 0 shows it again.
  - **Tapping the coach's bubble** opens only the coach's word in the lens,
    with "Close", not the whole finished review.
  - **While the review is open,** the coach's bubble still appears only
    when the walk reaches the coach's step; a later change updates that
    bubble in place.
  - **No new words.** The orange ring says it is new; "Updated with your
    coach's note" stays as signed.

- **Always the two highest willfidence moments** (founder, 2026-10-17:
  "guarantee the best, most confident moment based on the highest scored
  willfidence moment and the second highest scored willfidence moment").
  The highest is the confident moment, praised when it reaches the floor
  and shown with the softer line when it does not; the second highest is
  the one to practise on (clearer version or the voice Exercise with the
  AI clip). Praise is never promised; it follows the score. A Take whose
  clips carry no sound read (nothing stamped: no baseline yet, the measure
  off, or it failed) is no longer a Take with no moments: the picker gives
  such a clip the middle of the sound scale and the words order the clips
  until the sound read is back. Processing logs why nothing was stamped, and the
  picker logs when the words alone picked. On the app side, a review never
  falls back to the 2026-09-30 paragraph sheets or the coach's Step 0
  again: a served moment with nothing attached is the moment said again
  (section 2.4), so the lens always has a step; with no moment at all the
  text shows.

- **The Exercise screen is one thread, and a Good job no longer ends the
  practise** (founder, 2026-10-16; prototype
  <https://claude.ai/artifact/8nGuDXywGDWAZje3EcFMaj>, "Build it").
  Whenever the Exercise screen is open, live or come back to with ‹ ›, it
  shows the whole history at once: the clip, the Exercise, every try and
  the answer it got. Nothing waits behind Next. Under it, while fewer than
  three tries were made, the white outlined "Practise" with the red dot
  sits above a black "Next", after a Good job too; the "Skip" link goes,
  Next is the skip. After the third try only the history and Next remain,
  with the signed move-on line when the third was not praise. This
  replaces section 2.5's "Practise again" and "Skip" under a not yet and
  "Next" alone under a Good job. The three-try limit, every line and the
  AI clip rules stay. On the server a practice the machine closed on a
  praise still takes tries until three in all; a later praise is the try
  it lands on, a later not yet leaves the earlier praise standing. The
  finished walk played again shows the thread and Next only, as before:
  nothing is recorded there.

- **Practise again until the third try or a Good job, then Next**
  (founder, 2026-10-18; prototype
  <https://claude.ai/artifact/URLdtuBvG5rbrzFePfMcUv>, "yes but with the
  same AI video the text feedback slightly changes"). Amends the entry
  above. Under the Exercise thread and under a not yet, the bottom shows
  only the white outlined "Practise" (before the first try) or "Practise
  again" (after one), with the red dot: no Next and no Skip, until a Good
  job or the third try. Then "Next" alone. A Good job ends the practise
  again. A late answer offers "Practise again" while a try is left, the
  late tries counted, so a check that never answers still ends on Next
  after the third. The recorder keeps its Skip. In the Exercise, every not
  yet brings back the same AI clip; above it a not-yet line that changes
  each time (the line for the reading that went the wrong way, else the
  general ones in turn), then L4 and L3 the first time and L5 after. No new
  words. The server still accepts tries after a praise; the app no longer
  offers them.

- **One praise moment and one practise moment per Take** (founder,
  2026-10-14). Praise goes to the strongest moment (section 6's green, now
  one instead of three). Practise goes to the second best: close enough that
  one practise improves it. When that one is too short, the next closest one
  with enough words gets it. Never the praise moment. A Take with one moment
  gets praise only.

- **An old judging bubble in the chat opens "Other speakers" afresh, not a
  read-only replay** (founder, 2026-10-13: "the way it is right now is
  actually better"). The prototype showed the answered moment read-only,
  which would need other speakers' clips saved in each listener's chat.
  Instead the tap opens the "Other speakers" step: while the review is open
  it serves new moments to judge, and no other speaker's recording is ever
  stored in a speaker's thread. Do not build the read-only replay.

- **Walk first** (founder, 2026-10-14, approved on the "Walk First"
  prototype, https://claude.ai/artifact/Bsf3x3HWN2jJVY35edRKw8):
  - **One Ideal Text bubble per Take:** the small card with the first slide,
    the project's name and a version tag ("2.0"), and the coach's "new" dot
    on the project's newest card. The big "Open your ideal text" card is
    gone; a Take whose review has not posted its card shows the same small
    card instead.
  - **The card** opens the Ideal Text page on the text, from the top. Every
    other bubble with › opens that Take's walk on that step.
  - **The walk ends on the Ideal Text page.** Next goes to the next step
    that still waits; when nothing waits, step by step.
  - **✕** goes back where the step was opened from: the chat, or the Ideal
    Text page for a step opened from a paragraph.
  - **Answered steps are read only.** Helper words stay editable on the
    latest Take only (rule 5). An exercise already done plays its tries; a
    new practice comes with the next Take.
  - **Bookmarks are back as the margin line, now black,** on every
    paragraph that opens a step (this amends section 4, "No bookmarks").
    That paragraph, or its orange helper words, opens its step; Next walks
    on from there to the end.
  - An older Take's walk is read only and ends on that Take's Ideal Text.

- **The moment's opening line follows its willfidence** (founder,
  2026-10-14, signed): ten levels, three lines each, all locked and
  rotated, an icon before each; the cue line stays under it. The backend
  sends only the key `level_key` ("W1".."W10"), never the number. Levels by
  willfidence: W1 < 0.30, W2 0.30, W3 0.40, W4 0.50, W5 0.60, W6 0.65,
  W7 0.70, W8 0.80, W9 0.88, W10 0.95 and up. The lines live in the
  frontend's `src/lib/willab/praiseLevels.ts`.

- **The closing summary is cheeky and curious** (founder, 2026-10-14, in
  chat; amends section 3's "how it sounds"). Two to four short sentences,
  playful like a colleague: exclamation marks are fine, one emoji at most.
  It knows the talk's title, its slide topics, what the speaker said and
  their most confident moment. Its praise is one signed line from
  `services/line_bank.py`, varied lightly at most; code checks the line
  is there and falls back to the signed journey copy if not. It gives no
  advice (the walk did) and asks whether the talk matches its title only
  with curiosity. It ends with a question back to the speaker. It speaks
  only to what the Take showed about whether they can do it, never to
  their self-esteem or self-worth. Still no numbers but a signed line's
  Take number, no scores, no verdicts. A speaker with no WhatsApp number
  gets the Lounge's WhatsApp offer right after it.

- **Words first, then voice** (founder, 2026-10-18; prototype
  <https://claude.ai/artifact/Ut2SqvHCoJ1hvH8dp17yQe>, the criteria page
  <https://claude.ai/artifact/Kr97WV8e2PNZwf4FPcsKUW>, "ok, push to prod").
  Amends section 2.4 and section 6's "W < S → Clearer version". The
  practise moment is still the second best. It opens on the Clearer version
  only when both gates pass (`services/rewrite_gate.py`), else on the voice
  Exercise with the AI clip:
  - **The words need help:** fillers at 3 or more per 100 words, hedges at
    3 or more per 100 words, off the slide (slide fit below 0.5), or a
    broken sentence. None of them: the wording is good, the AI clip alone.
  - **The rewrite is good enough:** inside the moment's own clip; backed by
    evidence, never the tentative fallback; a real fix (fillers and hedges
    at least 0.1 better than what they said, or the broken sentence
    mended); still theirs (at least 6 words in 10, no new number or name);
    no longer than what they said and 5 words or more; not turned down
    before on the same words.
  - **After a try of the clearer words** only the voice is checked, on the
    same lanes against the original clip as the voice Exercise. Better is
    the Good job and no AI clip. Not yet brings the AI version of their
    voice saying the accepted words (or their own after "Keep my words"),
    with L4, L3 and L5 as in the Exercise. A try with no sound read is a
    Good job: missing data never forces the AI clip. Three tries and three
    clips at most, as locked.
  - **An answered clearer version stays read only** in the walk and from
    the Lounge (✓ and Next), as the "Walk first" entry says. No new words.

## Still open

- **Self-judgement of your own practice try is off for launch** (founder,
  2026-10-12). The query pack showed 4 speaker answers in total, 21 clips
  with coach answers, and only 1 clip with both: too few to judge. Re-run
  `1-enough-data.sql` once coaches have judged more moments. When
  `clips_with_both` reaches about 50, run the agreement and gap queries and
  decide.
