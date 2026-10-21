# Founder lock · the consent screens (7 October 2026)

> **Label: In force** · one of the rules, read in N95's order. Every doc and its label: [`README.md`](../README.md) (N106).

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

## Amended the same day: the settings page (founder, ST1 A, 7 October)

The Data & consent page follows the **settings page prototype**:
<https://claude.ai/artifact/4jDJsvBAquMUgaGkJgHR76> (copy in
`docs/design/settings-page-2026-10-07.html`). From the founder's message:
"remove the support from the hamburger and add it to the settings page with
just an email to contact@willpowerlab.com; remove the community btn; when
you are on the page show it orange text light orange background not only
when you hover over it; when I am on the Privacy policy and terms pages, and
I click back I am brought back to the lounge and I should have been brought
to the settings screen".

- A **Support** card (title and contact@willpowerlab.com) between Your
  projects and Delete my account.
- Privacy Policy and Terms of Service opened from this page show **Back**
  and return here; opened from anywhere else they keep "Back home".
- The ☰ menu has no Support and no Community row; the row for the page you
  are on stays orange on light orange, not only on hover.
- "Support" and "Back" are signed (ST1 A).

## Amended 2026-10-15: the 3.6 consent screens (founder, N73)

Approved on the clickable prototype <https://claude.ai/artifact/YCM8rQKkkwA2HKb4UYajeo>
(version 19; copy in `docs/design/consent-screens-2026-10-15.html`): "this
looks perfect". It replaces the 2026-10-07 prototype as the reference.

- **Documents:** on a computer each opens in its own fixed-height window,
  only the text scrolls; the button is **Continue** (was "Done reading"),
  with **Back** under it.
- **Where do you live?:** Poland, then **United States (California)**, then
  the rest by name.
- **Three things to confirm:** "I am 18 or older. *", "I agree that
  WillpowerLab may process my recordings. *", then **Can we make the product
  so much better for you?** / "We'd train our feedback on your practice."
  with an underlined **Read more** in the same colour / the tick **Yes,
  make it so much better.** (no asterisk, no "Optional" label). **Agree and
  continue** / **Do not agree**; no Back on this step.
- **Before a Take** (only while training is off) and the **Help improve
  WillpowerLab** card: the same question, sentence and Read more.
- **Read more:** Privacy section 4a in a window, **Continue** to close.
- **Data & consent:** the WhatsApp card (Remove, with its confirm) and Stop
  sharing on a shared Take, in the words shown with dashed outlines.

## Amended 2026-10-18: one screen (founder, in chat)

Approved on the clickable prototype "Condensed Consent Screens"
<https://claude.ai/artifact/6v4vEhppupQc9LC2tzbD6H> (version 6; copy in
`docs/design/consent-screens-2026-10-18.html`, the "One screen" flow): "dev
it!". It replaces the first-time walk of 2026-10-07 and 2026-10-15 as the
reference. The founder's words in the same chat, verbatim: "dont ask where
do you live just a choose chountry is neough and make it *", "shorten that
too!" (the sentence above the button), "bring it back to the center",
"so there is no need for the screen that asks you before te take, cause if
you don't agree, you don't enter" and "remove that screen".

- **One screen instead of six.** Welcome, then one acceptance screen: the
  voice mark, the agreement text, the three documents as underlined links in
  one centred row (**Terms of Service · Privacy Policy · How AI is used
  here**, each with "read ✓" once opened), a dropdown reading **Choose your
  country \*** (Poland, then United States (California), then the rest by
  name; nothing preselected except the person's own earlier answer), the one
  tick **"I agree that WillpowerLab may process my recordings. \*"**, then
  **Agree and continue** / **Do not agree**. No heading, no Back.
- **The age and the Terms are accepted by the button**, as the agreement
  text says; the age tick is gone. The recordings tick stays its own tick.
- **The documents open in a window** (the whole screen on a phone, a window
  in the middle on a computer): title, version and **Continue** stay still,
  only the text scrolls. They never gate the button. The AI-notice exposure
  row is written when that window opens.
- **No training question on the screen, and no "Turn on the learning?"
  before a Take.** That screen is removed from the app. The Help improve
  WillpowerLab card on Data & consent stays until the Privacy Policy says
  otherwise (below).
- **Nothing was recorded** is unchanged; "Go back" returns to the screen
  and "Read the documents again" opens the Terms window on it.
- Fits a 390×844 phone and a computer without scrolling; on a 375×667 phone
  it scrolls by under 50 px.

**The words above the button are the policy's `agreement_copy`** and change
only with a policy republish. The founder's approved text, three paragraphs,
is in `legal/phase1-2026.1/copy/agreement-3.2.txt`. Until a policy carrying
it is published the screen shows agreement 3.1 in the same layout. The third
paragraph (anonymised words from practice help improve the feedback for every
speaker) can go live only together with a Privacy Policy and Terms that make
training on anonymised text part of the service (today's 4a makes it a
consent); that is a counsel question (21-counsel-questions-2026-10.md).

Training wording v4's "the third thing to confirm" (amendment of 2026-10-15)
no longer applies to the first-time screen.
