# Will's learning plan (founder, 2026-10-20)

> **Label: Reference** · how something works today; where it differs from the In force docs, they win. Every doc and its label: [`README.md`](../README.md) (N106).

Will learns about each person from what they say and do, without retraining a
model: plain-text notes and kept events that any model can read. This page
holds the founder's decisions from the two question pages (the learning plan
and the voice notebook) and the order they are built in.

Built before this plan: the speaker memory (`docs/SPEAKER-MEMORY.md`): every
answer to "Did this help?" and every Take's outcome is kept, and Will reads a
short private note before it chats and before the summary after a Take.

## Step 1: the voice notebook (built 2026-10-20)

- **Who:** the founder only (ring row `voice_notebook`, ring 6).
- **How:** WhatsApp-like. `+` left of the message box, the mic right of it
  while the box is empty. Tap: it records (trash, the running time, send).
  Up to five minutes; it sends itself at the limit.
- **Typed notes:** a message starting with `#` is a note too. A voice note
  shows in the chat as `#` + its words, so both look the same.
- **Words:** transcribed by the same provider as Takes, under the
  processing-authorization path. Only hesitations and repeated words are
  taken out (`transcript_smoothing.strip_fillers`); every other word is kept.
- **Audio:** kept (a later feature reads how sure the voice sounded, and how
  consistent the founder is with themselves over time). Stored in the
  database next to the note, so account deletion removes it with the notes.
- **Private:** only the person and Will read notes. Never a coach, never the
  Ideal Text. Will reads the newest notes in the chat.
- **Consent:** before the first note: "Your notes are private. Only you and
  Will read them. Keep a voice notebook?" **Yes** / **Not now**. After each
  note: "Noted."
- **Safety:** a note that sounds like a crisis gets the chat's existing
  safety reply at once.
- **Life Panel:** a `#principle`, `#mistake` (and the Life Panel's other tags)
  is kept as a note and still answered by the Life Panel when it is on.

Code: `services/voice_notebook.py`, `routes/v2/voice_notebook.py`, migration
`a_voice_notebook_keeps_the_founders_notes.sql`, test
`tests/test_voice_notebook.py`; frontend `useVoiceNote.ts` and the Lounge
composer.

## Step 2: the Sunday note (built 2026-10-20)

**Locked 2026-10-26 (N158), not built yet:** the Sunday note as a lens,
<https://claude.ai/artifact/Bt2YEZLKhu9fLTA1deWTvo>. On Sunday from 6 pm by itself when there is a pattern, and whenever asked in any words (N170), only from the last seven days of # notes, no Old | New, and with nothing to find Will says so; in the
Lounge "We spotted a pattern!" with Not now | Investigate; in the lens one
step at a time (the bug, the principle held, the reflection, the new
principle with Accept or Edit). The rules are frontend
[`docs/flows/principles.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/principles.md) §1 L. What follows
describes the build of 2026-10-20 until then.

How it works now:

- **When:** Sunday from 6 pm in the founder's time zone (the browser's,
  saved when the chat opens), once a week, from the worker's minute sweep.
  Also whenever the founder types "sunday note", "#sunday" or "case of the
  week".
- **Reads:** the week's notebook, the Lounge thread (their words, Will's
  replies, the summaries after each Take), the talk goal, Will's note on
  them and their active Life Panel principles.
- **Writes:** one bubble in the form below, with only the bug the week
  shows explained. No numbers.
- **Then:** the footer asks **Old | New** (a bug they already knew, or a new
  one). If Will has a new principle, "⚜️ <principle>" follows with
  **Not now | Add principle**. Only Add principle puts it among the Life
  Panel's active principles; the reply is "Noted.".
- **Will remembers:** the last case's bug, and whether it was old or new, is
  in Will's private notebook block in the chat.
- Code: `services/sunday_note.py`, migration
  `will_writes_the_founder_a_sunday_case.sql`, `tests/test_sunday_note.py`.

The plan as decided:


Sunday 6 pm local, and whenever asked, in the chat only. In the founder's
Dalio case form:

```
CASE AT HAND
WHAT ONE OF THOSE WAS IT?
👾 Too much pleasure  👾 Blind spots  👾 Hubris  👾 Wishful thinking
PRINCIPLES I APPLIED AND HOW I WEIGHED THEM
REFLECTIONS
NEW PRINCIPLE ⚜️
ADD PRINCIPLE
```

Each pattern has a button: a bug you already knew (old) or a new one. It reads
the week's notes, Takes and chat, and links helpful and harmful patterns to the
talk goal, the life goals and the principles. Will suggests principles; one is
added only when the founder approves it, and goes to the Life Panel's
principles. Never on the recording screens.

## Step 3: life goals, the Dalio way

**Decided 2026-10-26 (N172):** asked once after the first # note, one goal
per sitting in a lens, drafted only from the speaker's words, worked back
from the horizon to the quarter, the ladder per goal, kept in the Life
Panel, <https://claude.ai/artifact/HaWehtwfg1jzJvGeGM1c24>. The rules are
frontend
[`docs/flows/principles.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/principles.md) §1 M.

Built (M1 to M14), founder only (ring row `life_goals`, ring 6):

- **The ask:** after a # note's "Noted." (typed, voice, or the held note on
  Yes), `life_goals.after_note` writes the two bubbles, the second with the
  offer `life_goals` (Not now | Start). Asked once; after Not now, once more
  after the next note (`life_goal_asks`).
- **Asked for in the chat:** `life_goals.chat_turn`, before the notebook's
  intercept: "#goals", or an ask for a goal in their own words (a keyword
  pre-gate, then a cheap classifier that answers none for the talk's goal).
  The reply carries `life_goals_open` (not an offer), and the Lounge opens
  the lens.
- **The lens** is the frontend's. Each answer is kept on a draft (`PUT
  /v2/life-goals/drafts`). Will's draft and redraft keep only quotes found
  word for word in the answers. A spoken answer is transcribed without
  becoming a note.
- **Set and changed:** `finish` posts the ladder (metadata `life_goal`) and
  "Noted. Your … goal is set." to the Lounge. `change_step` keeps the
  earlier words as a dated row in `life_goal_versions`. The talk goal
  changes the profile goal, with its own history.
- **The clash (M12, N185):** before a new goal is set, `check_clash`
  (`POST /v2/life-goals/<id>/clash/check`) asks the model whether its
  give-up pulls against a kept goal, from their words only, once per pair.
  `answer_clash` (`POST /v2/life-goals/<id>/clash`) keeps the answer on
  both ladders as `clashes`, shown as WHEN THEY CLASH; a changed answer
  keeps the earlier one as a dated version (step `clash`).
- **The quarter comes back (M13, N186):** no clock. The Lounge calls
  `POST /v2/life-goals/quarter/due` when it opens; `quarter_due` writes
  "The quarter ends today." (or "The quarter ended on {date}.") and "{emoji}
  {step}. Did it move?" with the offer `life_goals_quarter`, once per goal
  and quarter (`quarter.asked`). The quarter's last day is `quarter.on`, or
  its "31 December" read from the day the goal was made. `answer_quarter`
  takes Not now | Start; `quarter_notes` returns their own # notes from
  the quarter that say the same obstacle, most often none;
  `review_quarter` keeps the outcome in words on `reviews` and sets the
  next quarter's step, the earlier one kept as a version.
- **A note that sounds like a change (M14, N190):** once a goal is set,
  `after_note` hands the newest # note to `note_change`: the model says
  whether it changes one goal's quarter step, and the new words and the
  quote must be found word for word in the note, else nothing is asked.
  The ask ("Change {emoji} this quarter to “…”?", offer
  `life_goals_change`) keeps a `quarter.proposal`; `answer_change` (`POST
  /v2/life-goals/<id>/change`) writes it through `change_step` on Change,
  or drops it on Not now. Only the quarter step.
- **Will reads** the ladders in the chat (`prompt_lines`, inside the
  notebook block).
- **Not built yet:** a note that changes a step other than the quarter
  (waits for the founder), the ladders in the Life Panel's own screens, and this week's focus on the ladder (no source for it yet).
- Code: `services/life_goals.py`, `routes/v2/life_goals.py`, the store in
  `services/life_store.py`, migration `the_founder_keeps_life_goals`
  (0492), `tests/test_life_goals.py`.

What follows is the plan of 2026-10-20 it grew from.

Seven questions: What do you truly want most? What fits your nature and
strengths? What will you give up for it? Is it a real goal or a desire? What
will actually fulfil you? Is it ambitious enough? What path feels right?

Up to three spaces, each can hold a goal: personal life, career, the greater
good. The goal ladder: life goal → talk goal (the setup answer "What do you
want your audience to do?") → this week's focus (the moment being practised).

## The proverbial 15 minutes (N180, N183)

The app teaches the base; the speaker goes and lives it, away from the
phone, and comes back for a short recap. Personal details go in their own
paper notebook; the voice notebook stays for short # notes for Will.

- When the life goals lens first opens: "📓 Use your notebook!" and its
  explanation (frontend). When a goal is set: "That's the base. Now go and
  live it. Come back for a short recap." (`life_goals.finish`).
- "That's your 15 minutes for today." and "Now go and live it, away from the
  phone." come on a practice day once that day's practice is done, never on
  a clock: they wait for the plan's practice days (frontend
  `docs/flows/the-plan.md`).

## Step 4: later

- Speaking-only thinking patterns: six signed patterns, consent first
  (sensitive information), the person can see and delete them, at most one
  gentle question per conversation, strengths too. "I'm worthless" and the
  like: Will steps out and the founder is quietly flagged.
- A look-back bubble after Take 3, then every few Takes.
- The notebook in four parts (speaking, goals, thinking, what to ask next),
  older lines fading.
- The bridge to life goals, once steps 1 to 3 work.
