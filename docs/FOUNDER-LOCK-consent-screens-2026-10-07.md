# Founder lock · the consent screens (7 October 2026)

`LOCKED 2026-10-07 · founder in chat: "the consent screens are great; but right now they are not scrollable like that in the real app; so lock it like that" · decisions log N60`

Clickable prototype (the reference for every screen, phone and desktop):
<https://claude.ai/artifact/TuMKSE2BH364ZQ1Eq4UMdd>, version 2. A copy of
the page as locked is kept in `docs/design/consent-screens-2026-10-07.html`.
The frontend's CLAUDE.md carries the rule ("Design lock — the consent
screens").

## What it covers

1. **First time.** The welcome ("Enter the lab"), the agreement notice with
   the three documents (Terms of Service, Privacy Policy, How AI is used
   here; each "read ✓" once opened), each document's own screen ("Done
   reading" / "Back"), **Where do you live?**, **Three things to confirm**
   (the age tick, the sensitive-information tick, and the Personalised
   practice tick under its own "Optional" label; "Agree and continue" /
   "Do not agree"), and **Nothing was recorded** ("Go back" / "Read the
   documents again").
2. **Data & consent.** Personalised practice, Sensitive information in
   recordings, Help improve WillpowerLab, Your projects, Delete my account
   with its confirm and the 7-day cancel, each with its confirm and its
   outcome line.
3. **Before each Take.** **Turn on the learning?** while the training
   switch is off: Skip is not remembered and it asks again before the next
   Take; Yes turns it on and it is never asked again.

## How it scrolls (the reason for the lock)

- Every step scrolls from its true top to its last button on any phone. A
  step taller than the screen starts at its top (the voice mark and the
  heading are never cut off) and its buttons are reached by scrolling.
- A document's screen keeps its title, its version and its buttons still;
  only the document's text scrolls. "Done reading" is always on screen.

## Words

Today's live words, unchanged, with one change signed by the founder in
chat the same day: the heading **"Two things to confirm"** becomes
**"Three things to confirm"**.

## Not locked (the prototype's stand-ins)

The dashed "Prototype stand-in" boxes (the recording and Ideal Text
screens), the two invented project names, the country list and its order
(the live list comes from the policy), the prototype's pop-up notes, its
"Learning: on/off" chip, and the bar above the phone.

## The rules (as for the other locks)

- Build these screens exactly as the prototype shows. Do not change their
  layout, flow or wording, and add no element or string the prototype
  doesn't show. If a task seems to need one, stop and ask the founder in
  the Navigation Panel, with a clickable prototype of the change.
- The legal documents' text and versions come from the active policy, never
  from the prototype's excerpts.
- These screens are the processing boundary in front of the live loop
  (LIVE LOOP): a change here must keep a person able to agree and record.
