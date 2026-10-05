# Founder lock — helper words, the paragraph overlay and the practise loop (2026-09-30)

`LOCKED 2026-09-30 · B1 yes · B2 yes · B3 yes · B4 yes · B5 yes · B6 yes · B7 yes · B8 yes · B9 yes · B10 yes · D1 yes · D2 yes · D3 yes · D4 yes · D5 yes · D6 yes · D7 yes · D8 yes · D9 yes · D10 yes · Q1 yes · Q2 yes · Q3 no · Q4 no · Q5 no · closed 2026-09-30: Q1 B · Q2 A · Q3 A · Q4 A · Q5 A`

Locked by the founder on 2026-09-30 from the decisions page, with four overrides. Each item below is the locked outcome and the acceptance criteria to check when it is built. The build list and the mocks: <https://claude.ai/artifact/DQ41tdJqgC21SZGnqn9UYR>. The decisions page: <https://claude.ai/artifact/2Vz1UZVEA997UZpwivWWYh>.

## Signed

The founder signed the lock page as a PDF on 2026-10-01 08:38 UTC with a
qualified seal (PAdES, `ETSI.CAdES.detached`, "ARTUR WILLOŃSKI"), eight
pages, title "Helper Words Lock", rendered from the decisions page on
2026-09-30. sha256 of the signed file as received:
`2024740823dbb58284867ae7d88fc0e93250fc0d42bea5d54bb2a8c5a29e3369`. The
file itself stays with the founder (and in the legal bucket if uploaded,
under `phase1-2026.1/founder/helper-words-lock-2026-09-30.pdf`); this
hash is the record. It is a product lock, not a legal-pack artifact: it
registers nothing in the database.

## Overrides

- **B5** — Next on a Yes or In-between. Practise with Skip on No and Not sure only.
  *Amended 2026-10-05 (founder, decisions log N48.3 Q7 A): on a rewrite card the buttons are contract 29b's, not this rule: "Accept and practise" is the one main action and "Keep my words" is the plain-text way out, which changes nothing.*
- **B7** — Two bar colours only, orange and green. Everything else is plain text with no bar.
- **D6** — The paragraph overlay has exactly two states: the practise state and the helper-words-saved state. Playback in both, never the paragraph text.
  *Amended 2026-10-05 (founder, "keep it as it is today"; decisions log N48.1): on a later Take the helper-words-saved state shows no player. The paragraph text is still never shown.*
- **D8** — Only the most above the threshold is displayed. At any moment the Ideal Text holds at most three open feedbacks, up to two of one colour and up to one of the other. A paragraph saved with helper words is done, frees its slot, and does not count; those are unlimited.

## Interpretations to confirm

The five questions closed on 2026-09-30 (Q1 B · Q2 A · Q3 A · Q4 A · Q5 A).

- **Q2 · D8, the third slot (confirmed A)** — Slots fill from the two ends: the highest read above the threshold takes green, the lowest read below it with a practise takes orange, and the third slot goes to the next candidate farthest from the threshold on either side, never a third of the same colour. When only one side has candidates, at most two show.
- **Q3 · B7, locked paragraphs (confirmed A)** — A paragraph saved with helper words carries no bar. Its orange headline is its mark. This keeps 'at most three bars' true.
- **Q1 · B5 and B6, where Practise stops (confirmed B)** — In-between counts as good enough to lock. On In-between the button reads Next and "Practise" is the plain-text link under it; the practise loop is required only for No and Not sure, and ends on the first In-between or Yes.
  *Amended 2026-10-05 (founder, decisions log N48.3 Q7 A): on a rewrite card the buttons are contract 29b's, not this rule: "Accept and practise" is the one main action and "Keep my words" is the plain-text way out, which changes nothing.*
- **Q4 · the mocks (confirmed A)** — Tasks 4, 5 and 6 are built from the three mocks as they stand; later polish rides the same PRs.
- **Q5 · nothing matched (confirmed A)** — Under "Say it again" the signed sentence "Your coach is working on your exercise." stays; the coach request is still raised.
  *Amended 2026-10-05 (founder, decisions log N48.3 Q10 A): "Your coach is working on your exercise." shows only while a coach is active.*

## The build list

### B1 — The helper words she picked are on the page after every Take, edit or no edit.

Done when:

- [ ] Pick words on Take 1, edit any other paragraph with the pencil, record Take 2: the same words are the headline above the same paragraph on the page.
- [ ] Same result when the edited paragraph is the one that carries the words.
- [ ] The lock survives: the walk shows that paragraph as "Helper words saved".
- [ ] The page, Recording Mode and History show the same words.
- [ ] An end-to-end test for edit-then-Take-2 exists and runs in the gate.

### B2 — The helper words step opens on Yes and In-between only.

Done when:

- [ ] Judging Not sure in the walk: no "Choose your helper words" step; the sheet moves on.
- [ ] Judging Not sure on a practice attempt: same, back to record.
- [ ] The picker is reachable only after a Yes or In-between, or through Edit on saved words.
- [ ] Contract 24e and 29a say Yes and In-between.

### B3 — A helper-word pick stops at four words.

Done when:

- [ ] The fifth tap does nothing and the untapped words grey out; the counter reads "N of 4 words".
- [ ] A phrase saved before this change with more than four words is displayed unchanged.
- [ ] Recording Mode shows the cue on one or two lines at the large size, never as a paragraph.
- [ ] Contract 13 states the limit of four.

### B4 — Helper words have their own overlay.

Done when:

- [ ] Tapping the orange headline on the page opens it; tapping Edit on the "Helper words saved" screen opens the same overlay.
- [ ] Top: the current words with Delete. Under it one chip per Take that has a version of this paragraph, newest first, the current one marked "now".
- [ ] Choosing a chip shows that Take's text as tappable words. There is no playback on this overlay.
- [ ] Tapping updates the top card live and marks it "new"; the button lights only when the selection differs from the saved words.
- [ ] After Delete (confirmed once): no headline on the page, the paragraph is back in the walk, the deleted set is listed in History.

### B5 — The paragraph overlay: playback, a small judgement label, one main practise card, one History row, and the button.

*Override:* Next on a Yes or In-between. Practise with Skip on No and Not sure only.

Done when:

- [ ] Opens from the paragraph. Shows no paragraph text.
- [ ] Order top to bottom: player, judgement label, practise card, History row, button.
- [ ] The judgement label is one line and visibly smaller than the player.
- [ ] The practise card is a rewrite ("Clearer version"), a praise, or an exercise; an exercise with a video shows the video inside the card above its instruction.
- [ ] Judgement Yes: the button reads "Next" and nothing under it.
- [ ] Judgement In-between: the button reads "Next" with "Practise" as plain text under it; tapping it opens the practise screen for the card shown.
- [ ] Judgement No or Not sure: the button reads "Practise" with "Skip" as plain text under it.
- [ ] Audio unclear: grey label, no practise card, "Next".

*Amended 2026-10-05 (founder, decisions log N48.3 Q7 A): on a rewrite card the buttons are contract 29b's, not this rule: "Accept and practise" is the one main action and "Keep my words" is the plain-text way out, which changes nothing.*

### B6 — Practise for every moment judged below In-between, as long as she wants, until In-between or Yes, then helper words and the lock.

Done when:

- [ ] Tapping Practise opens the words to say as the main text of the screen; an exercise shows its video above; one record button; Skip in plain text.
- [ ] The words stay on screen while recording; Stop ends the attempt.
- [ ] After Stop: the five answers with the passage in small print above them.
- [ ] No, Not sure or Audio unclear on an attempt: back to record the next attempt. Attempt 10 works like attempt 1.
- [ ] Yes or In-between on an attempt: the picker over the attempt's own words, four at most; save shows "Helper words saved" and the walk continues.
- [ ] The paragraph text on the page is unchanged by any attempt; only a Take rewrites it.
- [ ] Rewrite, exercise and plain moment all reach these same screens.

### B7 — Two bar colours: green above the confident threshold, orange below and matched to practise. Everything else plain, full width.

*Override:* Two bar colours only, orange and green. Everything else is plain text with no bar.

Done when:

- [ ] Only green and orange bars exist on the page; no grey or black bar anywhere.
- [ ] A paragraph without an open feedback is plain text, flush left, the same width as a barred paragraph. No indent, no empty margin.
- [ ] Green marks an open feedback read above the threshold; orange marks one read below it with a practise attached.
- [ ] A paragraph saved with helper words has no bar; its headline is its mark.
- [ ] Never more than three bars at once.

### B8 — The walk goes top to bottom through the text; a locked paragraph is a Next screen.

Done when:

- [ ] "Review feedback" visits the open feedbacks and the locked paragraphs in text order, across slides.
- [ ] A locked paragraph shows "Helper words saved", the player, the words, History, and Next only. No judgement question, no practise card.
- [ ] A paragraph with neither an open feedback nor saved words is not a screen in the walk; it still opens from the page.
- [ ] The end card follows the last screen.

### B9 — The new words are signed as listed.

Done when:

- [ ] These strings appear exactly: "Your judgement:", "Skip", "Next", "N of 4 words", "Helper words" (eyebrow above the headline), "These replace your Take 1 words. Those stay in Earlier Takes.", "Say it this way", "From your attempt", "History", "This paragraph".
- [ ] No other new user-facing string lands on these screens; the copy file diff shows only these.

*Amended 2026-10-05 (founder, decisions log N48.3 Q9 A): the signed strings also include "Delete helper words", "Tap words from any Take", "Confident" / "Not confident", "Accept and practise", "Keep my words" and "Say it this way · accepted".*

*Amended 2026-10-05 (founder, decisions log N48.3 Q8 A): the words on these screens are: "Next" wherever this lock says Next (the screens' "Done" becomes "Next"); "Record Take N" (not "Record again"); the judgement answers read "Yes" and "No" (not "Yes — Confident" and "No — Not confident"); the header caption reads "AI-generated text · Take N"; the rewrite card is "Clearer version" (not "Small rewrite"); "Edit" (not "Choose different words"); the Take 1 note ("These replace your Take 1 words. Those stay in Earlier Takes.") shows in the paragraph sheet's picker; and the Lounge's door back reads "Practise again" (not "Keep practising").*

### B10 — The page note after a new Take and the automatic pre-selection stay parked.

Done when:

- [ ] No note appears on the page after a Take.
- [ ] The picker opens with the saved words pre-selected and nothing else.

### T11 — The window of three: the backend chooses on every read which open feedbacks are surfaced.

*Override:* Added after the lock, 2026-09-30: the task D8 needs and the list lacked.

Done when:

- [ ] The served Ideal Text carries at most three open feedbacks at any time, chosen by the rule in Q2.
- [ ] Saving helper words on one frees its slot on the next read, without a new Take.
- [ ] Deleting helper words returns that paragraph to the candidate pool.
- [ ] The Manager still evaluates every block; only the surfacing is windowed. Contract 24b and 24c amended.
- [ ] No count, rank or score reaches the client; it receives the open items and the tier colour.


## The divergences

### D1 — Practise is the default follow-up for every judgement below In-between.

Done when:

- [ ] Every No or Not sure shows a practise card; when nothing matched, the card is "Say it again" on the plain moment with "Your coach is working on your exercise." under it.
- [ ] No judgement ends on an overlay with nothing to do.

*Amended 2026-10-05 (founder, decisions log N48.3 Q10 A): "Your coach is working on your exercise." shows only while a coach is active.*

### D2 — No attempt cap.

Done when:

- [ ] No counter of attempts remaining is shown or enforced.
- [ ] Contract 29a says as long as she wants, or until In-between or Yes.

### D3 — Praise follows the same button rule as every card.

Done when:

- [ ] Praise with Yes or In-between: Next.
- [ ] Praise with No or Not sure (the matrix's better-than-expected cells): Practise with Skip, the praise still shown.

### D4 — Helper words can be deleted.

Done when:

- [ ] Delete on the overlay, confirmed once, clears the words and the lock.
- [ ] The deleted set is listed in History with its Take.
- [ ] Contract 13 no longer says there is no way back.

### D5 — Helper words can be taken from any earlier Take.

Done when:

- [ ] Every Take with a version of the paragraph is a chip; its text is tappable.
- [ ] Words taken from Take 1 that Take 2 did not say show as the headline with nothing italic; once said again in a later Take they turn italic.

### D6 — The paragraph overlay has two states and never shows the paragraph text.

*Override:* The paragraph overlay has exactly two states: the practise state and the helper-words-saved state. Playback in both, never the paragraph text.

Done when:

- [ ] State one, practise: player, judgement label, practise card, History, Practise or Next.
- [ ] State two, saved: player, the helper words, History, Next.
- [ ] No third layout exists; no paragraph text in either.

### D7 — The judgement is a small coloured label.

Done when:

- [ ] Green for Yes, blue for In-between, red for No, yellow for Not sure, grey for Audio unclear.
- [ ] Tint behind, full colour on the text, one line, smaller than the player.
- [ ] The machine's read has no colour anywhere on the overlay.

### D8 — At any moment the Ideal Text holds at most three open feedbacks; saved paragraphs are unlimited and free their slot.

*Override:* Only the most above the threshold is displayed. At any moment the Ideal Text holds at most three open feedbacks, up to two of one colour and up to one of the other. A paragraph saved with helper words is done, frees its slot, and does not count; those are unlimited.

Done when:

- [ ] Count the bars on the page: never more than three.
- [ ] Never more than two of one colour.
- [ ] The green ones are the highest reads above the threshold; the orange ones are the lowest reads below it with a practise.
- [ ] Saving helper words on one frees its slot: the next candidate appears on the next page read, without a new Take.
- [ ] When no candidate remains, no bars; "Record Take N" is the main button.
- [ ] Contract 24b and 24c amended: selection stays per block; surfacing is windowed to three.

### D9 — Locked paragraphs send no judgement.

Done when:

- [ ] No answer is stored for a locked paragraph on later Takes.
- [ ] The coach queue receives nothing for it.
- [ ] After Delete, the next Take judges it again.

### D10 — "Skip" and "Next".

Done when:

- [ ] "Skip" is the plain-text link under Practise; "Not now" no longer appears on these screens.
- [ ] "Next" is the button on Yes, In-between, Audio unclear and the saved screen; "Continue" no longer appears on these screens.

*Amended 2026-10-05 (founder, decisions log N48.3 Q7 A): on a rewrite card the buttons are contract 29b's, not this rule: "Accept and practise" is the one main action and "Keep my words" is the plain-text way out, which changes nothing.*


## The open design questions

### Q1 — The paragraph overlay keeps one collapsed History row.

Done when:

- [ ] One full-width row "History ›" at the bottom, the same size as the judgement label.
- [ ] Opening it lists earlier Takes as single rows: Take number, answer, helper words. Nothing else.

### Q2 — Delete asks once.

Done when:

- [ ] One confirmation step; cancel keeps the words.

### Q3 — One Take, one phrase.

Done when:

- [ ] A saved phrase always comes from a single Take's text; switching chips starts a fresh selection.

### Q4 — No judgement label on the practise screen.

Done when:

- [ ] The practise screen shows only the words to say, the video if any, the record button and Skip.

### Q5 — Each attempt starts clean.

Done when:

- [ ] The screen for attempt N shows no earlier attempt's clip.


## Contract clauses this lock amends

13 (four words; delete exists), 24b/24c (surfacing windowed to three), 24e (Yes and In-between open the helper words), 24f (Practise as the default follow-up below In-between; Next on Yes and In-between), 24g (two bar colours; no bar otherwise; locked paragraphs carry no bar), 29a (no attempt cap; the loop ends on In-between or Yes), and the design lock L3 (the two overlay states). The amendments land with the PRs that build them, never before.

*Amended 2026-10-05 (founder, decisions log N48.3 Q12 A): the contract texts are brought in line with this lock and its later amendments: 24f (the stale two-greens and weakest-item text replaced by 24g's two bar colours; Practise below In-between, Next on Yes and In-between, 29b on rewrite cards) and 47 (V3 serves every Take). The design lock's L3 still says "the Take stack"; this lock wins.*
