# Founder lock · the coach panel, redrawn (6 October 2026)

`LOCKED 2026-10-06 · layout agreed in chat ("rest looks ok", 21:26 UTC) · words signed CP2 A · library and errors to admin CP3 A · corpus switched on CO1 A (21:46 UTC export)`

**Design locked 2026-10-07 (N57):** every coach screen is built to the prototype below exactly, as the speaker's screens are to the Ideal Text Final Screens; the frontend's CLAUDE.md carries the rule.

Clickable prototype (the reference for every screen):
<https://claude.ai/artifact/TEBvGMehRF6wXCvJTEYTUA>. A copy of the page as
locked is kept in `docs/design/coach-panel-redesign-2026-10-06.html`.
Today's panel, for comparison: <https://claude.ai/artifact/DcezJeY9JFsuLkB6jn8asV>.

The coach panel takes the Feedback walk's look and motion
(`FOUNDER-LOCK-feedback-walk-2026-10-06.md`): full-screen overlay, the
grey profile picture, one player, the same moves between screens. Where
this lock and the coach-panel lock of October (`FOUNDER-LOCK-coach-panel-2026-10.md`)
disagree, this one wins.

## The rule

**One action per screen.** Buttons with different jobs never look alike:
in every list of choices the cards shade from white to a darker grey,
one step per card, with black text; no grey text inside a choice.

## The flow

1. **Lounge.** The bubble "N speakers waiting · Open your queue" opens the
   queue. Two buttons pinned above the message box, with icons:
   **Speakers** (every speaker, an orange dot on those waiting) and
   **Training corpus**.
2. **Your queue.** Your speakers only, each with how many moments wait.
   Below: "Also waiting · blind": *Do you hear it?* and *Pick the most
   confident moment* (both built, switched off). The training corpus is
   not in the queue.
3. **A speaker.** Their goal and their Takes. Tapping a Take opens its first
   open moment; ‹ › move between moments; the counter counts moments only
   ("moment 1 of 4").
4. **Judge this moment** (blind): the player, the question, the five
   answers. No orange "Private · training" line. It moves on by itself.
5. **What happened.** The passage with its player; three lines: You,
   the speaker, The machine heard.
6. **Error moments: the diagnosis first.** "What kind of error is it?"
   The errors the machine heard come first, marked "The machine heard
   this". Then the others, then "Something else · Name a new error" (light
   grey card) and "I don't hear an error" (darker grey card). This is also
   where the coach says whether they hear what the machine heard.
   - *Name the error*: one field. The exercise reaches the speaker now; it
     waits in the library under that name until a detector can hear it.
   - *I don't hear an error*: the answer becomes a note.
7. **The cure.** For an error: **Choose exercise**, offering only exercises
   that treat the diagnosed error: Keep it (the served one, with Details),
   Swap it, Make a new one, Nothing to add. For praise, a clearer version
   or a note: What will you do? (Answer, Nothing to add).
   - *Swap it* lists only exercises for that error, each with Details;
     "Make a new one" at the bottom.
   - *Details*: the exercise's video, its instruction, what it treats;
     Use this one.
   - A choice moves on by itself; ‹ comes back to change it.
8. **Your words, as the speaker will see them.** The speaker's passage and
   player on top, the coach's words below with the grey picture, a pencil
   in their top-right corner to edit. (Replaces the white box and the
   green "The passage {p} will say".)
9. **Your video.** Record (one action). An error answered without a video
   goes to the speaker without the library: never stuck.
10. **Praise and clearer version: the kind question.** "What did {p} do
    well?" / "What kind of fix is it?"; Skip shares without the library.
11. **Ready for {p}.** Exactly what the speaker will get; "Share with {p}" or
    "Share without the library". No "Keep it to this speaker" box.
12. **Summary.** An answered moment, reopened from the queue: what happened
    and "Your answer"; "Change my answer".
13. **A word for this Take**, looking like the speaker's first screen, with
    the pencil; then its video step; Send.

## The training corpus (CO1 A)

From its pinned Lounge button: the list of imports; **Import audio**; the
set-up with the corpus page's own fields and words (what the talk is
about, whose voice this is, what language it is in, where it came from,
what to run); an import whose set-up is not finished opens the set-up
before any judging; then its moments are judged blind on the same judging
screen. The machine side is in N56.

## Library and speaking errors (CP3 A)

Both leave the coach's app and move to the founder's admin area, next to
the pace panel. In the moment, coaches already make, choose and name
everything they need.

## The speaker side (locked in the same session)

A paragraph without a bookmark does not open on tap (amends B7's "still
opens its own sheet on tap").

## Words signed (CP2 A)

Signed exactly as listed on the panel (CP2), `{p}` the speaker's name:

- Queue: Your speakers · {n} moments waiting
- A speaker: Goal: … · {n} of {m} moments waiting · All moments answered · Answered · {n} moments
- All speakers: Your speakers
- What happened (title) · The machine heard
- What kind of error is it? · The machine heard this · Something else · Name a new error · I don't hear an error
- Name the error · A few words, as you would say it to another coach · e.g. trailing off · Your exercise goes to {p} now. The library offers it to other speakers once the machine can hear this error; every coach who names it brings that closer.
- Choose exercise (the founder's own title, 21:39 UTC) · What will you do? · Served: {exercise} · {n} more for {error} in the library · Your own words and video · Write your praise · Write a clearer version · Write a note
- Swap it: All treat {error} · shown in random order · Served now · Treats: {error} · Details
- An exercise's details: Treats: {error} · Back to the list
- Your words: As {p} will see it · the pencil edits every word
- Your video: Say the instruction in your own words · under a minute · Optional · under a minute
- What did {p} do well? · What kind of fix is it?
- Ready for {p} · Without a video it goes to {p} only, not to the library. · In the library under “{error}”, waiting until the machine can hear it.
- Summary: Your answer · Change my answer
- A word for this Take: Optional · it opens first in {p}’s feedback · As {p} will see it · Send without a video
- Training corpus: Import audio, label it, then judge its moments blind · {n} imports · {n} moments to judge · {n} of {m} moments to judge · One recording · it is cut into moments you judge blind · Choose a file · Audio or video, up to 30 minutes · Imported · {n} moments
- Training corpus set-up: Finish the set-up · Before its moments can be judged · Set-up not finished · finish it before judging · Set up · {n} moments
- Library (now in admin): One error · the library offers it when the machine hears it · As a speaker will see it · the pencil edits every word · An exercise needs its video · Bring it back · Retire it · Praise lines the library offers when the machine hears this · None yet. · Exercises that treat it

Signed but taken off the screens by later corrections (kept here so they
are not reused unsigned): "Your diagnosis first; the exercise comes next",
"Your diagnosis: {error}", "nothing in the library treats it yet",
"You don't hear an error", "So the library can offer it to the next speaker".
