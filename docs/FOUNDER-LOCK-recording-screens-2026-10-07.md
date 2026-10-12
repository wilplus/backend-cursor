# Founder lock · the recording screens (7 October 2026)

`LOCKED 2026-10-07 · founder in chat: "Lock the recording screens" · decisions log N59`
`RE-LOCKED 2026-10-12 · founder in chat: "that's what i want; please lock it" · decisions log N70`

Clickable prototype (the reference for every screen, phone and desktop),
since 2026-10-12: <https://claude.ai/artifact/4zD6Tjw4MWjooqWq6z4FAL>,
version 4 (its v10 design), copy in
`docs/design/recording-screens-2026-10-12.html`. It replaces the scrolling
navigation of the 2026-10-07 prototype
(<https://claude.ai/artifact/9CFAAP2Ue7pvRdLvdesn9h>, version 7, copy in
`docs/design/recording-screens-2026-10-07.html`), which stays as history.
The flow and motion below are the 2026-10-12 design.
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

1. **First recording (Take 1):** as every Take (amended 2026-10-12, N70:
   the learning screen, **Scroll down to start** / **Click down to start**,
   is deleted).
2. **Every Take:** **Getting your mic ready**, then the recording screen
   glides in. No learning screen, and nothing to approve: "Record Take N"
   goes straight here and the Take starts by itself. (Amended the same
   day, founder: the old "Your slides and speaking anchors are ready." /
   orange **Start recording** screen is deleted. The optional training
   question, which is consent, may still ask first.)
3. **The recording screen.**
   - Top bar: **Take N · Slide n of m** on the left (no "Recording"
     label), the close button on the right.
   - The slide, sitting close under the top bar, then the speaker's helper
     words below it, every one of them orange (none on Take 1), using the
     full width. No slide dots (removed 2026-10-12, N70).
   - The strip at the bottom: the recording dot, the clock, the bar. No
     line above the strip, and no Finish take in it (2026-10-12, N70).
   - Under the strip, two buttons side by side, equal width, in the coach
     panel's pair style (48px tall, 16px corners, 15px semibold): **Back**
     (white, thin border; greyed on the first slide) and **Next slide**
     (black). On the last slide **Next slide** becomes **Finish take**,
     red, with the stop square. Finish take is reached only from the last
     slide; closing asks **Discard this take?** (founder, 2026-10-12: "that's
     what i want").
4. **Close:** **Discard this take?** / "This recording has not been saved."
   / **Keep recording** / **Discard take**, as today.
5. **Finish take:** the processing wait as today (voice mark, stage label,
   **While you wait** tips), then the Ideal Text page.

## How it moves

Since 2026-10-12 (N70; founder: "we are resigning from the scrolling — it
was not practical").

- **Only the buttons change the slide.** A swipe, a scroll, a wheel or a
  trackpad never moves a slide. The helper words still scroll inside their
  own space when they are longer than it.
- **Sideways, like a deck.** **Next slide**: the slide and its helper words
  leave to the left and the next ones come in from the right. **Back**: the
  reverse. Out in 200ms, in from the other side in 420ms on
  `cubic-bezier(.16,1,.3,1)`. Instant with reduce motion.
- **Only the slide and its helper words move.** The top bar, the "Take ·
  Slide" line, the strip and the two buttons stay exactly where they are
  and are never rebuilt during a move.
- **Keyboard, no click first:** ← and → change the slide, exactly like
  Back and Next slide (N70.1); ↓, Page Down, Space forward and ↑, Page Up
  back, after scrolling long helper words. **Keys never end a Take**: on
  the last slide → and Space only give a small bounce; only the red Finish
  take ends it (founder, 2026-10-12). A focused button keeps its own Space
  and Enter; a text field keeps every key; nothing is taken while
  **Discard this take?** is open. Keys prototype:
  <https://claude.ai/artifact/LU1XgQyqY2nPSvDAmsRJFo> (version 2), copy in
  `docs/design/recording-screens-2026-10-12-keys.html`.
- **Never a reload:** pulling or scrolling at the top never reloads or
  refreshes the page, on a phone or on the web.

## The words

New with this lock (locked with the screens): **Take N · Slide n of m** in
the top bar. Signed 2026-10-12 (N70): **Back** and **Next slide**; **Finish
take** keeps its word. **Scroll down to start** and **Click down to start**
are retired with the learning screen. Every other word on these screens is
today's, unchanged.

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

## Amendments

- **2026-10-07 · one close button (Q-B14 A, N63; build plan D-RC-6).** The
  app's one small grey close X (`OverlayCloseButton`) is the close button
  everywhere, the recording screen included; the ⋯ beside it on the text
  page uses the same style.
- **2026-10-07 · the fade (Q-B14 A, N63; build plan D-RC-7).** Recording
  Mode is entered and left with a soft 0.4 s fade into and out of these
  white screens; instant with reduce motion. The fade never delays the
  recording.
- **2026-10-12 · buttons replace the scrolling (N70).** Back and Next slide
  under the strip; Next slide becomes a red Finish take on the last slide;
  no slide dots; slides move sideways; the learning screen is deleted.
  Prototype <https://claude.ai/artifact/4zD6Tjw4MWjooqWq6z4FAL> (version 4),
  copy in `docs/design/recording-screens-2026-10-12.html`.
- **2026-10-12 · the arrow keys (N70.1).** ← → change the slide; keys never
  end a Take; a focused button keeps Space and Enter. Prototype
  <https://claude.ai/artifact/LU1XgQyqY2nPSvDAmsRJFo> (version 2).
