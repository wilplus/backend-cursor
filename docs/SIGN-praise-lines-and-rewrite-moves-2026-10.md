# Sign: nine praise lines and three rewrite moves (October 2026)

**For the founder's signature.** Decisions log N48.6, Q29 A: "the nine praise
lines and three rewrite moves are drafted by the session for the founder's
signature." **Status: PROPOSED.** The lines are in
`services/feedback_catalogue.py` (`PROPOSED_LINES`) behind
`PROPOSED_LINES_SIGNED = False`. No speaker sees any of them until you sign
and a reviewed change sets that to True.

**How to answer.** Per line: **A** signs it as written; **B** replaces it with
your words (write them in the row). Strike a line to leave its pattern empty:
the sheet then keeps today's sentence there.

**Where they show.** The paragraph sheet's card (frontend
`ParagraphSheet.tsx`). A praise line sits under "Good job" and the quoted
words, in place of "It was your confident moment." and the cue sentences. A
move sits under the "Clearer version" words, above "Accept and practise" and
"Keep my words".

**Rules for every line.** It says how the voice or the words sounded, not how
you felt (N23 Q7). It compares you only with your own usual delivery, never
with other people. No number (AC-9), no retired construct word. Tentative
evidence gets tentative words.

## Praise (9)

| # | Line | Shows when | A / B | Why these words |
|---|---|---|---|---|
| 1 | It was your confident moment: your voice sounded more assured here than it usually does. | A praise whose own evidence has no line. Today that is a contrast or a list of three on a moment read confident. | A ☐ B ☐ | Your signed lead (24 Sept), then contract 24j's definition: more assured than your own norm. "Assured" is the word of the rating's written definition (conf-q-v2). |
| 2 | Your voice rose and fell more than it usually does, so the words did not sit on one note. | The strongest cue was pitch range. | A ☐ B ☐ | From your line of 29 Sept and the signed "Your voice moved more this time." "Engaging" is left out: it has no written definition, and `delivery_cues.py` says it must not become a state (that is how charisma got in). |
| 3 | You let your volume move, so the words had shape rather than one flat level. | The strongest cue was loudness range. | A ☐ B ☐ | Today's Good job sentence, kept. It was written to your brief and never signed word by word. |
| 4 | You went straight through it, with fewer and shorter pauses than you usually take. | The strongest cue was fewer and shorter pauses. | A ☐ B ☐ | Today's sentence, kept. |
| 5 | Your voice sat lower than it usually does, so it sounded settled. | The strongest cue was a lower pitch than your norm. | A ☐ B ☐ | Today's sentence ends "which is what settled sounds like", a general claim. This one says only what the recording did, and how it sounded. |
| 6 | You kept the pace up here instead of letting it drop. | The strongest cue was pace. | A ☐ B ☐ | Today's sentence compares you with other people ("the way people do when they hedge") and guesses at a state of mind. Cues are measured against your own norm only. |
| 7 | You brought the end down and landed it, instead of letting it drift up. | The strongest cue was a falling ending. | A ☐ B ☐ | Today's sentence, kept. |
| 8 | You opened with energy and eased off after, instead of building up to it. | The strongest cue was energy at the start. | A ☐ B ☐ | Today's sentence, in the words of the signed "You opened stronger this time." |
| 9 | On this take, this was one of your more assured moments — and there is still room to improve. | The Manager's fallback praise: the Take's shortest complete sentence, used only when nothing else in the Take can be praised, and shown only where it falls inside a moment read confident. Always tentative. | A ☐ B ☐ | Your 24 Sept sentence with one change. It said "this landed the most confident". Since the caps were lifted (29 Sept) several moments can be read confident, so "the most" can be untrue, and it ranks moments (24i). This line is tied to the fallback itself, so line 1 can never replace its tentative words. Strike it and sign line 1, and line 1 shows on the fallback too. |

## Rewrite moves (3)

| # | Line | Shows when | A / B | Why these words |
|---|---|---|---|---|
| 10 | Try starting straight on your point, without the filler word in front of it. | The clearer version is your sentence without its opening filler (so, well, actually, basically, literally, you know). This is the Manager's tentative fallback rewrite. | A ☐ B ☐ | Your coach panel's name for the move ("drop the filler"), as an instruction. "Try", because the rewrite is tentative. |
| 11 | Try it as two shorter sentences, with a short pause where the first one ends. | Your sentence is cut in two at a clause near its middle, with the same words. Also the tentative fallback. | A ☐ B ☐ | "Split the clause". The pause says how to say it, not only how to write it. |
| 12 | Say it as one sentence, so the thought does not stop before it is finished. | Two pieces the transcript split ("I don't want. A script…") are joined into one sentence, with the same words. This rewrite is rule-made, not tentative. | A ☐ B ☐ | "Repair the structure". No "Try", because the evidence is exact. |

## What signing changes, and what it does not

- **On signing**, the session puts your B words in place and sets
  `PROPOSED_LINES_SIGNED = True` in one reviewed change, with a decisions-log
  entry. The lines then reach Takes processed after the merge. A page stored
  before the merge keeps its card until its next answer.
- **A line you or a coach later writes** into the catalogue (the coach
  panel's Home, or `POST /coach/catalogue`) wins over these for its pattern.
- **Not drafted.** Contrast and list-of-three praise take line 1 until a line
  is written for them. "Even pitch" is no longer a cue the backend names: it
  was retired with the sex-blind cue contract (29 Aug). A model's clearer
  formulation, which changes the words, carries no move.
- **Not fixed by this sheet** (separate work):
  - The Feedback sheet's Good job step does not read these lines. That is
    the design lock, so it waits for the designer session.
  - The Manager still attaches lines after it chooses, not before its
    fallback (P1-4).

Signed: ______________________  Date: __________
