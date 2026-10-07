# Founder lock · the recording screens (7 October 2026)

`LOCKED 2026-10-07 · founder in chat: "Lock the recording screens" · decisions log N59`

Clickable prototype (the reference for every screen, phone and desktop):
<https://claude.ai/artifact/9CFAAP2Ue7pvRdLvdesn9h>, version 7 (version 6
as locked, amended the same day, below). A copy of the
page as locked is kept in `docs/design/recording-screens-2026-10-07.html`.
The frontend's CLAUDE.md carries the rule ("Design lock — the recording
screens"). This lock wins over the Ideal Text lock's line on Recording Mode
for the screens below.

## How the design came about (founder, chat, 7 October)

1. The recording screen for the first Take and for a Take with helper
   words, as a prototype "almost like the live one"; scrolling to the top
   must not reload the page.
2. "It should be scroll down to start; and no slide yet on the screen; it
   should be like a learning screen", without the recording button; on the
   web too, the scroll to the top never reloads the app; scrolls less
   sensitive; a smooth landing that follows the hand; a desktop version
   with its own start screen; the keyboard works without a click first.
3. "Make the slides only change like the rest of the infrastructure should
   stay; the scroll bar or top nav shouldn't move."
4. The drawing: "Recording" crossed out; "Take · Slide" moved up into the
   top bar.
5. "Delete the line right above [the] recording progress bar"; each slide
   one main colour; only a title and at most 1.5 sentences on a slide.
6. The stand-in deck fits any talk: introduce the subject, the main
   points, sum up and what to remember.

## Amended the same day (founder, chat, 7 October, after seeing the live build)

- "Make them orange!": every helper word is orange; the live screen had
  greyed the ones the data marks neutral.
- "Tighten the space below the Take 2 · Slide 2 of 3 and the slide; the
  margin there is too big, at least half that": the gap under the top bar
  is more than halved (about 44px to about 20px on a phone). Prototype
  version 7.

## The flow

1. **First recording (Take 1): the learning screen.** No slide, no clock,
   no Finish take. Phone: **Scroll down to start**, with a bouncing
   chevron. Desktop: the four arrow keys, the down key lit, and **Click
   down to start**. A swipe, a scroll, ↓, Page Down, Space or Enter starts
   the recording; the slide then glides in.
2. **A later Take:** **Getting your mic ready**, then the recording screen
   glides in. No learning screen, and nothing to approve: "Record Take N"
   goes straight here and the Take starts by itself. (Amended the same
   day, founder: the old "Your slides and speaking anchors are ready." /
   orange **Start recording** screen is deleted. The optional training
   question, which is consent, may still ask first.)
3. **The recording screen.**
   - Top bar: **Take N · Slide n of m** on the left (no "Recording"
     label), the close button on the right.
   - The slide, sitting close under the top bar, then the speaker's helper
     words below it, every one of them orange (none on Take 1), the slide
     dots on the right.
   - The strip at the bottom: the recording dot, the clock, the bar,
     **Finish take**. No line above the strip.
4. **Close:** **Discard this take?** / "This recording has not been saved."
   / **Keep recording** / **Discard take**, as today.
5. **Finish take:** the processing wait as today (voice mark, stage label,
   **While you wait** tips), then the Ideal Text page.

## How it moves

- **Only the slide and its helper words move.** The top bar, the "Take ·
  Slide" line, the slide dots and the strip stay exactly where they are and
  are never rebuilt during a move; the content slides under that still
  frame. The dots change which one is current.
- **Touch:** the content follows the finger (a rubber band); a slide moves
  after 90px of travel, a shorter swipe springs back.
- **Wheel and trackpad:** a slide moves after 140 of accumulated scroll, or
  90 if the wheel then rests 220ms; after a move the momentum tail is
  ignored for 450ms, so one flick is one slide.
- **The landing:** out in the direction of travel in 200ms, in from the
  other side in 420ms on `cubic-bezier(.16,1,.3,1)`. Instant with reduce
  motion.
- **Helper words scroll first:** when a slide's helper words are longer
  than the space, the gesture scrolls them; at their edge it moves the
  slide.
- **Keyboard, no click first:** ↓, Page Down, Space forward; ↑, Page Up
  back; Enter starts.
- **Never a reload:** pulling or scrolling at the top never reloads or
  refreshes the page, on a phone or on the web.

## The words

New with this lock (locked with the screens): **Scroll down to start** (the
founder's words), **Click down to start**, **Take N · Slide n of m** in the
top bar. Every other word on these screens is today's, unchanged.

The prototype's three slides are its own stand-in deck ("Introduce your
subject", "Make your main points", "Sum it up", navy, orange and dark
green); the app shows the speaker's own slides, unchanged.

## The rules

- Build these screens exactly as the prototype shows: no layout, flow,
  motion or wording change, and no element or string the prototype doesn't
  show. A task that seems to need one stops and asks the founder in the
  Navigation Panel, with a clickable prototype of the change.
- LIVE LOOP: this is the record → Take surface; every change keeps
  recording, saving and processing working.
