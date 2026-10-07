# Willab canonical product contract

Status: founder-locked on 2026-08-26. Feedback Policy V3 amendment locked on
2026-08-30; it remains inactive until a separately authorized serving cutover.
L1 / helper-words amendment locked by the founder on 2026-09-25 (clauses 8, 9,
12-20, 24e, 29a, 35d): each Take rewrites what was said; the lock keeps the
helper words, not the text. Clause 8 amended 2026-10-03 (N29): the rewrite is
per Slide. Ideal Text redesign amendment locked
by the founder on 2026-09-26 (clauses 13, 16, 20, 24g-1): "Use these helper
words" is the lock; helper words head their own Paragraph and read italic inside
it; the text is never greyed. Closing the Gap amendment by the founder
2026-10-05 (decisions log N48, "go with wave 2"; clauses 4, 8, 20, 24f, 27,
29, 35g-2, 46, 47): each amendment is marked in place, and the text it
replaces is kept.

This document is the product source of truth for the frontend and backend.
Historical prompts, handoffs, schemas, routes, names, and tests are evidence of
past implementations, not competing product definitions. When they conflict
with this contract, this contract wins.

## 1. Project, deck, recording, and Take

1. A Project is the canonical rehearsal container. One Project ID equals one
   Arc ID. Arc is an internal or legacy term, not a second product entity.
2. Project isolation uses immutable Project ID plus authenticated owner ID.
   Display names may repeat and never participate in identity.
3. A Project owns its setup, one slide structure, Takes, Ideal Text, feedback,
   anchors, and journey state.
4. A slide structure is either an uploaded PDF or a project-specific deckless
   structure. It may be replaced before the first completed Take and is
   immutable afterward. A changed deck starts a new Project.
   **Amended 2026-10-05 (founder, decisions log N48.2 Q4 A):** replacing the
   deck inside an existing Project is retired: a new deck is a new setup,
   and so a new Project. The replacement allowed before the first completed
   Take above is no longer offered.
5. A Recording Attempt is the preserved submitted audio. A Take exists and
   counts only after processing succeeds. Retrying processing reuses the same
   Recording Attempt and never increments the Take count.
6. Read, practice, import, and processing-retry sessions do not become Takes.

## 2. Ideal Text and document structure

7. Ideal Text is the sole canonical presentation document. Best Presentation
   as a separate assembled product artifact is retired.
8. Take 1 creates the initial project-specific Ideal Text. Each later Take
   rewrites every Slide it covers from exactly what the speaker said on that
   Slide — the latest Take, never a best-of pick across Takes. A Slide the
   speaker did not speak in a Take keeps its last version. When a Take
   cannot be lined up with the Slides, it follows the Take: a deck recording
   with no slide taps belongs to the Slide on screen when recording started,
   and a document whose Slides cannot be proven is rewritten whole from that
   Take. Nothing is lost, because every version stays in history (clause
   16). (Founder, 2026-09-25, Q4 A; supersedes "later Takes never replace
   it". Amended 2026-10-03, N29: the rewrite is per Slide, as built since
   Q4 A; that a Take which cannot be lined up follows the Take is new, and
   is built in the F1 Repair Plan's Phase 3.) **Amended 2026-10-05
   (founder, decisions log N48.1, Wave 1):** a Slide's last version is the
   words the speaker is reading, so an unspoken Slide keeps the speaker's
   current words, including an owner edit (clause 9) or an accepted rewrite
   (29b), never the earlier Take's machine words; clause 9's "the next Take
   replaces all of these" holds on the Slides that Take spoke.
9. Between Takes, Ideal Text also changes through direct user editing, an
   explicitly accepted proposal, or a practice attempt adopted under 35d. The
   next Take replaces all of these with what was said; nothing is lost,
   because every version stays in the Paragraph's history (clause 16).
10. The document hierarchy is Project -> ordered Slides -> ordered Paragraphs
    -> exact text spans.
11. Paragraph is the canonical unit for identity, editing, protection,
    feedback attachment, and root-phrase generation. Part, chunk, segment, and
    API piece are not alternative product names for an Ideal Text Paragraph.
12. A Paragraph keeps its ID through ordinary wording edits and through a
    Take rewriting its words, so its helper words and history follow it. Split
    and merge operations create new Paragraph IDs; prior IDs remain only in
    history and provenance. **This holds when an owner edit sits between the
    Takes** (founder lock 2026-09-30, B1): the rebuild proves the stored
    Paragraphs by their count against the old document, not by their
    spelling, because an edit rewrites the words of a slot and never the
    slots themselves.

## 3. Decisions, protection, anchors, and roots

13. Resolving Feedback and choosing helper words are separate steps. The
    helper words (root phrase) are words the user taps, **at most four in one
    pick** (founder lock 2026-09-30, B3: a cue is read at a glance while
    recording and found again in the next Take's words; the picker greys the
    words a tap cannot reach and counts "N of 4 words"; phrases saved before
    the cap stay as they are); the one tap on "Use
    these helper words" saves and locks them — there is no separate Lock
    screen, and "lock" is an internal term the user never sees (founder
    2026-09-26). There is no Keep evolving choice: every Paragraph follows
    the speaker (clause 8), and choosing new helper words replaces the old
    ones. **Helper words can be deleted** (founder lock 2026-09-30, B4, D4):
    Delete on the helper words overlay, confirmed once, clears the words and
    the lock, the Paragraph is back in the walk, and the deleted set stays in
    the Paragraph's history with its Take — still the user's act, so L1
    holds. **Helper words can be taken from any earlier Take** (B4, D5): the
    overlay shows one chip per Take that has a version of the Paragraph, that
    Take's text is tappable, and a saved phrase always comes from a single
    Take's text (Q3). Words from an earlier Take that the latest Take did not
    say show as the headline with nothing italic until said again. A user
    whose answer opens the helper-words step (24e) but who closed the sheet
    before choosing may still choose them from the Paragraph's own sheet.
14. A lock keeps the helper words, not the text. Locked helper words persist
    across Takes — including a later Take whose words no longer contain them,
    and a later No answer on that Paragraph — until the user explicitly picks
    new ones. Helper words are stored as their own text on the Paragraph, not
    as a position inside it.
15. Machine proposals (rewrite, restructure, add, cut) and coach corrections
    remain explicit proposals the user accepts or ignores. Nobody silently
    changes a Paragraph's text or its helper words; the only automatic change
    is clause 8, and every version is kept.
16. Every Take rewrite, edit, accepted proposal, adopted practice attempt, and
    helper-word choice appends an immutable Paragraph revision with timestamp
    and provenance. The Paragraph's bookmark opens this history: every version,
    Take by Take, and which helper words were locked when. An exercise shows
    its own history the same way. A bookmark is never an empty screen. Every
    Paragraph opens this sheet, including one that received no Feedback
    (founder 2026-09-26): the current Take on top, with the user's own answer
    said back as a sentence inside it, and earlier Takes folded beneath it.
17. Feedback, Paragraph versions, and helper words are separate layers.
18. Helper words are chosen by tapping exact words from the current Paragraph,
    or from the adopted practice transcript under 35d. Orange styling is never
    inferred from praise or a confidence response.
19. The Ideal Text shows each Paragraph as its latest text with no "changed"
    marker; the history lives behind the bookmark.
20. Presentation Mode, export, and the Ideal Text render helper words as a bold
    orange headline directly above the Paragraph they came from (one headline
    per Paragraph, not one per Slide), with the same words appearing again at
    normal size in the text when they were said — like a newspaper headline
    over its article. Inside the text those words are italic, in the
    Paragraph's own colour and font; the headline is the only orange (founder
    2026-09-26). Recording Mode shows the same helper words as memory
    cues. Only locked helper words are shown. Before Take 3 an uncovered Slide
    has no generated fallback. After Take 3, the Manager may propose at most one
    helper-word phrase for an uncovered Slide, but the user must still tap and
    lock it. **Amended 2026-10-05 (founder, decisions log N48.2 Q5 A):** that
    proposal stays off. An uncovered Slide has no generated helper words on
    any Take; helper words come only from the user's own taps (clause 13).

## 4. Feedback and Manager arbitration

21. The only user-facing feedback families are Confident Voice, Actionable
    Improvement, and Evidence-backed Praise. Moment, star, intervention, lane,
    device, candidate, suggestion kind, and model score are internal terms.
22. Detectors create internal Candidates. The Manager evaluates evidence,
    relevance, quality, collisions, and budget. Only Manager-approved
    Candidates become user-facing Feedback.
23. Machine Feedback appears immediately after processing. Coach review is
    asynchronous and never blocks the next Take.
24. Feedback budgets are versioned Manager policy. Until Feedback Policy V3 is
    separately activated, the live V2 contract remains exactly three items per
    valid Take: the highest-ranked Confident Voice candidate, the highest-ranked
    actionable verbal/structure improvement, and the highest-ranked
    evidence-backed praise. Families never borrow or surrender V2 slots.
    **Cutover decided 2026-09-18 (founder): V3 becomes the served policy.** The
    V2 code is retained but is no longer a fallback — see 24h, which forbids
    substituting it silently. Removing V2 outright is deliberately deferred
    until V3 has run clean; deleting it while V3 still has open defects would
    turn every V3 failure into permanent silence rather than a bad afternoon.
    **Amended 2026-10-06 (founder, Navigation Panel QG3 A, V22a B, V15a A;
    ledger CA01, N29; decisions log N51):** V3 is served today. V4, when built,
    replaces it for every speaker by the founder's switch — no dark run
    (V22a B: "skip the dark run, a few speakers now, then everyone", the
    founder's note "Cause there are no users"). A block V4 is
    very unsure of gets V3's pick for that block, logged as a fallback, never
    silent (V15a A: falling back on more than one block in five fails V4's
    exit gate). V2 stays retained history and is never a fallback for either.
24a. Under Feedback Policy V3, the Manager deterministically partitions each
    contiguous Slide run at persisted snippet/Paragraph boundaries into blocks
    closest to 75 words, normally 60-90 words. It never cuts words, fabricates
    boundaries, reorders chronology, or crosses a Slide boundary. An indivisible
    short or long Paragraph remains intact with a typed partition exception.
24b. **(REPLACED 2026-09-18 — founder. Prior text retained at 24b-prior.)** V3
    surfaces exactly one relative-best Confident Voice item per valid block, on
    **every** Take including Take 1 — see 24e for what every item carries and
    24f for the anchored notes laid on top. There is no whole-Take item
    cap on selection, and no Improvement or Praise exists independently of the
    item it is
    attached to. **Surfacing is windowed** (founder lock 2026-09-30, D8 and
    task 11): of the items still open, at most three reach the page at any
    moment — the highest read above the confident threshold, the lowest read
    below it with a practise, and the next farthest from the threshold on
    either side, never three of one colour. A paragraph saved with helper
    words is done and frees its slot; the next open item appears on the next
    read, without a new Take. Everything answered stays. The window chooses
    what is shown now; it never changes what the Manager selected or froze.

24b-prior. *(superseded, kept so the change is legible)* "V3 Take 1 surfaces
    exactly one relative-best Confident Voice item per valid block and no
    Actionable Improvement or Praise. V3 Take 2+ surfaces exactly one
    relative-best Confident Voice item per valid block, plus zero or one
    globally highest-ranked Actionable Improvement and zero or one globally
    highest-ranked Evidence-backed Praise for the entire Take."

24c. **Coverage ladder.** Of the Slides that yield **at least one valid block**,
    V3 covers at least **70% on Take 1, 80% on Take 2, and 100% from Take 3**. A
    Slide is covered when it carries at least one surfaced Confident Voice item.
    **The denominator is valid blocks, not speech.** A Slide passed over in
    silence is excluded, and so is one whose speech is too short or too
    fragmentary to form a block — for the same reason: it was never assessable,
    so failing to cover it is not a failure. Counting unassessable Slides makes
    the upper rungs unreachable by construction: fourteen Slides of which ten
    can be assessed caps coverage at 71% forever, and Take 3 could never be met.
    With this denominator 100% is reachable, because a valid block always has a
    relative best. Coverage counts the Manager's **selection**, which is
    complete on every Take; the window of three (24b) governs only how many
    of the selected items are on the page at once.

24d. **Coverage is a target on selection, never a floor on output.** V3 attempts
    every spoken Slide and selects the relative best available on each. It never
    invents, pads, or promotes an item to reach a percentage. A Slide with no
    defensible candidate stays uncovered and records a typed reason, and the
    shortfall is a defect to investigate rather than a licence to manufacture.
    This subordinates 24c to clause 25 and to L2, deliberately: a coverage floor
    that could override the evidence rule would be a licence to fabricate.

24e. **Every item carries the judgement; the rooting step follows the
    answer.** A surfaced Confident Voice item always offers its delivery read.
    After **Yes or In-between**, the tap-to-root helper-words step
    and the lock follow the item's feedback. After **No, Not sure or Audio
    unclear**, the
    exercise, praise, or correction still shows, then the sheet closes with no
    helper words — unless the practice loop in 29a turns the answer into Yes
    or In-between. (Founder lock 2026-09-30, B2, narrowing the 2026-09-25
    ruling that opened the step on Not sure: helper words are the words of a
    confident moment, and a Not sure still reaches the coach as an
    ambiguity.) **Emphasis is the helper-words step — it is not a
    Feedback family and carries no budget.** The only Feedback families remain
    Confident Voice, Actionable Improvement and Evidence-backed Praise. No
    bookmark is ever empty, because the judgement and the Paragraph's history
    are always there. (Founder 2026-09-25; supersedes the 2026-09-24 "keep the
    emphasis open for every answer" ruling.)

24e-1. **Judgement after feedback** (founder 2026-10-01, F1; Phase 2 of the
    after-practice paths, served only once `JUDGEMENT_AFTER_FEEDBACK_ENABLED`
    is on): "Opening a bookmark never asks for a judgment first. The
    machine's read chooses the feedback. The speaker judges themselves after
    it: on a confident moment right after the praise, on a moment that
    needed work after each practice attempt. Helper words open on Yes or
    In-between of that judgment." Lock B2 is unchanged. Under it the coach
    request of 35g-2 rises when the moment opens, under the machine's kind
    (praise; error where a problem fired; rewrite where nothing did), and
    the judgement that follows sets the request's answer kind from the same
    matrix: an ambiguity where the speaker and the machine disagree, on the
    moment or on a practice attempt. Nothing rises for an unopened bookmark,
    a clip the machine could not read, or Audio unclear. A practice may
    start before any judgement (29a); a practice that lands, a practice
    dismissed, or a bookmark skipped settles the item without a Path 1
    answer. Until the switch, 24e above is served as written.

24f. **On top of that, each Take carries anchored notes**, each attached to
    the item it concerns and never floating free of a Slide. **The caps are
    lifted** (founder 2026-09-29, evening: "now build it"; until then at most
    two Praise on the two most Confident items and one rewrite per Take): the
    machine's read of each block decides which note it may carry, and clause
    25 decides whether it carries one at all.
    - **Evidence-backed Praise on every item the machine reads confident** —
      one per block, the best defensible praise candidate whose words lie
      inside that block. Read confident means above the neutral delivery
      band; the read chooses and is never surfaced (AC-9). Not every such
      block carries one: a block with no defensible praise in its words
      surfaces none, and inventing one to fill the slot is forbidden. The
      green bar is on every open item the machine read above the confident
      threshold, within the window of three (24b, 24g), and does not decide
      where praise goes (amended 2026-10-05, see 24f-prior);
    - **an exercise on any bookmark** (founder 2026-09-29, superseding the
      2026-09-26 "one exercise, on the weakest item below the neutral band"):
      "they can carry as many exercises as bookmark indicates". Each Confident
      Voice item the machine reads weak gets the library exercise matched to
      its own clip under 35g-1. Which note follows a judgement is the
      **follow-up matrix** (founder 2026-09-29): the speaker's answer crossed
      with the machine's read of the same clip. Read confident: praise now
      (on Yes and In-between as agreement; on No and Not sure as better than
      expected). Read weak with an acoustic problem fired: the library video
      now on In-between, No and Not sure; nothing now on Yes. Read weak with
      nothing acoustic fired: the rewrite now on In-between, No and Not sure;
      nothing now on Yes. Audio unclear: nothing. Praise and rewrites show
      only where the Manager found an evidence-backed one; nothing is ever
      filled in. The read chooses and is never surfaced. An open item read
      below the confident threshold with a practise attached carries the
      orange bar (24g; amended 2026-10-05, see 24f-prior). A rewrite on the same
      Paragraph no longer withholds the video (it did until 2026-09-29): the
      video answers the delivery and the rewrite the words, two findings on
      one moment, and neither silences the other;
    - **an Actionable Improvement (rewrite) on every item the machine reads
      weak** — one per block, the best defensible rewrite whose words lie
      inside that block; a block read confident carries none, because its
      follow-up is praise. Read weak means the neutral delivery band and
      below. A rewrite asserts a finding and can be wrong, the expensive
      error under H.0, which is why the lane was capped at one per Take
      until the founder lifted it; what remains of that caution is clause
      25: only an evidence-backed rewrite, in tentative language where the
      evidence is weak, and none where there is none.
    A Take therefore surfaces one item per valid block, each of which may
    carry an anchored note. **The three-stage shape in 24e is the
    architecture, not a guarantee that every judgement carries a Feedback
    stage** — an item whose block holds nothing defensible carries the
    delivery read and the rooting step alone. Neither the read that places
    the notes nor any ranking among the blocks is ever surfaced (24i).
    **Amended 2026-10-05 (founder, decisions log N48.3 Q12 A, with Q7 A),
    to match the founder lock of 2026-09-30:** what the speaker can do after
    a judgement is the lock's. Practise is the default follow-up for every
    judgement below In-between (29a; lock D1), with Skip as the way out. On
    Yes and In-between the button is Next, and on In-between Practise is
    the plain link under it (lock B5 and its interpretation Q1). On a
    rewrite card the follow-up is 29b's: "Accept and practise" is the one
    primary action and "Keep my words" the way out, which changes nothing.

24f-prior. *(superseded 2026-10-05, N48.3 Q12 A; kept so the change is
    legible)* In the praise lane: "The green bookmark stays on the two most
    Confident items (24g) and no longer decides where praise goes". In the
    exercise lane: "The weakest below-neutral item keeps its bookmark
    colour." Both read the 2026-09-18 ladder of two greens and one orange,
    which the founder lock of 2026-09-30 (B7) replaced with two bar colours
    by the machine's read (24g).

24f-1. **An accepted rewrite re-anchors.** Accepting an Actionable Improvement
    changes the wording of the block it sat in, so its bookmark follows the
    rewritten block rather than the superseded span. A bookmark that cannot
    re-anchor is removed rather than left pointing at text that no longer
    exists.

24g. **Bookmark hierarchy** (founder lock 2026-09-30, B7, replacing the
    2026-09-18 ladder of two greens and one orange). Two bar colours exist
    and nothing else. An open item the machine read **above the confident
    threshold** carries a **green** bar; an open item read **below** it with
    a practise attached carries an **orange, pulsing** bar; every other
    paragraph — read unmeasurable, weak with nothing to practise, settled, or
    saved with helper words — carries **no bar** and reads as plain text at
    full width, still its own tap target. A threshold is a tier name, never a
    position: every green is identical, and the read that places the bar is
    never surfaced (AC-9). At most three open items carry a bar at any time
    (the window of three, task 11 of the lock). Colour is never the sole
    differentiator, and the pulse honours reduced-motion. Coach updates on a
    locked deck render as a plain mark with no pulse, so nothing competes with
    the practise for attention.

24g-1. **Document state** (amended by the founder 2026-09-26). Every block
    renders in the ordinary text colour; the text is never greyed. A block
    holding an unsettled judgement carries one bar in its left margin, green
    or orange by 24g,
    level with the block, and nothing else — no underline, highlight, or badge
    on the text. (Until the founder lock of 2026-09-30 a settled block that
    opened its sheet kept a thin grey bar; it no longer does.) There is no third "done" state: the clean text *is* the
    settled state, and the document empties as the user works rather than
    accumulating marks. The whole block is the bar's tap target; a settled
    block opens its own sheet (clause 16). While Feedback is still arriving, one
    quiet line under the header says so, never a mark per block.

24h. **V3 works or it fails visibly.** V3 never silently substitutes another
    policy version. On failure the client retries once automatically, then shows
    a short notice with a retry control. **A feedback failure never blocks
    recording, transcription, Ideal Text, or the next Take.**
    **Amended 2026-10-06 (founder, Navigation Panel QG3 A, V15a A; ledger
    CA01; decisions log N51):** this clause holds for V4 as it holds for V3. Once V4
    is served (24), a block V4 is very unsure of gets V3's pick for that
    block, logged, never silent; falling back on more than one block in five
    fails V4's exit gate (V15a). Neither policy ever substitutes V2.

24i. **AC-9 applies to everything this section computes.** Coverage
    percentages, delivery bands, PPV estimates, priority values and block counts
    are internal arbitration inputs. None is ever surfaced. "Let's practice"
    carries no number, band name, comparison to other users, or "below average"
    phrasing — it is an invitation to act, never a verdict on the speaker.

24j. **Reasonable confidence — what a Confident Voice item is.** (founder
    2026-09-23, agreed in session.) A moment qualifies when **the words carried
    the point they were meant to carry, and the delivery sounded more assured
    than that speaker's own norm.**

    **The two halves are SEQUENCED, never blended.** Within a block, candidates
    are ordered by what the words did — `covered`, then `partial`, then `not` —
    and the delivery read orders candidates only *within* a tier. There is no
    weight between the halves and no threshold on either: `on_slide_score`
    already returns one of `{1.0, 0.5, 0.0}`, so the three verdicts **are** the
    ordering and there is no new parameter to calibrate.

    **24b is unchanged.** Every valid block still yields exactly one item on
    every Take, because the bottom tier is never empty. A moment that made no
    point wins only when nothing in that block made one — the honest report,
    not a bypass. A candidate with no slide read at all sorts last rather than
    being excluded, so an unmeasured moment can never beat a measured one and
    a block can never be emptied. The item carries `reason_tier`, so the
    wording can say what tier it came from and 24f's exercise can read it.

    **24i covers the tier.** `reason_tier` is an internal arbitration input
    and never rides a client payload: `"not"` is a verdict about what the
    speaker's words did, and it is the ordering input, so a client holding it
    could reconstruct the ranking. The screen is drawn by `bookmark_tier` and
    `why_key` — founder-signed keys — exactly as it is for `candidate_score`.

    **Deleting the weak end was rejected twice over:** 24f's exercise fires on
    the weakest item below the neutral band, and the owner is only ever asked
    about what surfaces — so surfacing one end of the range would collect
    judgements from one end of it, and the validation this rests on needs a
    clean spread across confident, middling and not.

    **The rater's instrument does not move.** `conf-q-v2` still asks about the
    delivery of the clip it is shown, which stays true: the tier chose which
    clip, not what is being judged. Editing it would start a new corpus for no
    gain (SPEC §17, and `services/state_ratings.py` says so itself).

    Implemented in `services/reasonable_confidence.py`, behind
    `REASONABLE_CONFIDENCE_ENABLED`, **default OFF**. With the flag off the
    served order is byte-for-byte unchanged.

25. Each active-policy lane ranks its complete candidate pool and selects its
    best available item, not the first match. Under V3, confidence is relative
    only to the eligible clips inside its block; it is not an objective claim
    that the clip is confident. Improvement and Praise remain Take-level
    comparisons across their complete eligible pools. Weak evidence uses
    tentative language. Feedback never invents words, praise, or certainty.
    When a valid Take has no honest Improvement or Praise candidate, V3 freezes
    `no_defensible_candidate` for that lane and shows no card. Missing or
    unusable source material remains a separate typed exclusion.
    **Amended 2026-09-18:** under 24f, Improvement and Praise are anchored to a
    Confident Voice item rather than being Take-level cards, so "Take-level
    comparison" now governs *which item wins* the single Praise and the single
    Improvement, not whether a standalone card appears. **Amended
    2026-09-29:** the caps are lifted, so the comparison is within the block:
    which candidate inside a block is that block's note.
    `no_defensible_candidate` still applies: when the Take has no honest
    Improvement or Praise candidate, that note is simply absent. An item without
    an anchored note is **not** an empty bookmark — per 24e it still carries the
    delivery read and the rooting step, and it still counts toward coverage.
26. The complete selected set for the active policy version is frozen before
    exposure. Responding to one item never causes a previously hidden
    replacement to appear.
27. Actionable Improvement covers a verbal correction, stronger formulation,
    or material structure improvement. Praise must quote or otherwise identify
    real textual evidence; modest praise is valid when it is the best honest
    candidate. **Amended 2026-10-05 (founder, decisions log N48.2 Q2 B):**
    Actionable Improvement covers verbal correction and stronger formulation
    now. Structure improvement (restructure, add, cut; clause 15) comes
    later and is not built; there is no structure lane.
28. Every surfaced Feedback item references exact Project, Take, Slide,
    Paragraph, and evidence span. Confident Voice additionally requires a
    playable audio interval. Actionable Improvement and Praise do not.

## 5. Confidence, learning provenance, and Voice Album

29. Confident Voice offers primary responses Yes — Confident, In-between, and
    No — Not confident, plus secondary Not sure and Audio unclear. The response
    is an immutable self-report tied to the exact clip and Take.
    **Amended 2026-10-05 (founder, decisions log N48.3 Q8 A):** on the screens
    the answers read "Yes" and "No"; the five responses are unchanged.
29a. **The practice loop.** Practise is the default follow-up for every
    judgement below In-between (founder lock 2026-09-30, D1): the passage is
    the library exercise where one is matched to the clip, else the Manager's
    rewrite as the words to say, else the plain moment said again; the loop
    is the same for all three. After each practice attempt the exact same
    judgement screen appears again, with the same five responses, judging
    that practice attempt. No, Not sure or Audio unclear offers another
    attempt, **as long as the speaker wants — there is no attempt cap**
    (D2; until the lock, three); Yes or In-between ends the loop and opens
    the helper-words step over the attempt's own words, and the lock
    (founder lock 2026-09-30, B2, B6). **A practice never rewrites the
    Paragraph** (B6): the words on the page change only with a Take, or
    with the user's own acceptance of a rewrite (29b). Each
    answer is stored against the practice attempt it judges, never against
    the Take (clause 31).
29b. **Accepting a rewrite** (founder 2026-09-30, the rewrite amendment and
    C11). A rewrite card shows the clearer words as text. The one primary
    action is to accept them and practise: the acceptance is the owner's
    `apply_suggestion` response on that item, which the decision ledger
    bakes into the document (a new version; the Paragraph's history shows
    "Correction accepted" with the accepted words), and the practise
    passage is the accepted text. Keeping one's own words is the way out
    and changes nothing. This is the user accepting a proposal under L1:
    the machine never applies its own rewrite, and the next Take rewrites
    the Paragraph again from what was said (clause 8). Praise (Yes) never
    accepts anything; a Yes shows Next.
29c. **After the practice** (founder 2026-10-01, F5; Phase 3 of the
    after-practice paths, served only once `PRAISE_AFTER_PRACTICE_ENABLED`
    is on): "After a practice the speaker judges Yes or In-between, one
    signed sentence names what measurably changed. If nothing measurably
    changed, a plain 'Good job'. It is practice feedback, not a Feedback
    item, and carries no budget." The sentence comes from a closed,
    founder-signed set and describes the attempt the speaker landed on (the
    scorekeeper reads the first valid attempt, F7, and the two may disagree
    by design). It names the targeted problem that cleared, else the one
    delivery cue that moved, else that the attempt sounded more assured,
    else nothing; a rewrite practice (29b) compares only attempts of the
    same accepted text, never the original. A practice that did not land
    hears an encouragement: a real step between tries, else the effort
    alone. *Bold voices is RETIRED (founder 2026-10-07, Q-B11 A, N62):
    the walk lock (N52) has no such screen; its routes answer 404 whatever
    the switch says and nothing is written to its tables, which are not
    dropped.* It had let the speaker hear, once per Take after the first
    practice ending, their own landed attempt, then a coach's published
    readings, without names; plays only, nothing judged, a heard receipt
    kept. The coach's readings tool stays as it is.
29d. **Lend your ear and the share** *(amended 2026-10-07, founder Q-B11 A,
    N62: "At most 3 other voices per walk, community first, then training
    clips, on the same judgement screen without the slide bar. Lend your
    ear's engine serves them under the per-Take consent only. The Album
    share switch and Bold voices are retired." The Voice Album share switch
    and the per-Take blind set it fed are retired: their routes answer 404
    whatever `PEER_LANE_ENABLED` says, nothing reads the share view, and
    their tables are not dropped. The engine (`services/lend_your_ear.py`)
    now serves the communities' queue (47, N52.4): at most three other
    voices per walk, the community's clips first, then licensed training
    clips for the places left, under the per-Take community share as the
    one consent path; answers are peer ratings, lane `game_peer`, never
    coach labels, owner routing or training labels (L3). The delayed
    measure's pair (29e) rode the retired share and has no door into any
    queue. `PEER_LANE_ENABLED` gates only the coach's licensed-corpus tool.
    What follows is the retired design as it was.)* (founder 2026-10-01, F3,
    F4; Phase 4, served once `PEER_LANE_ENABLED` is on — on from 2026-10-02 after the
    founder's own answers to C1, C2 and C3 (N23) and Privacy 3.3 (N24, N25),
    off again from 2026-10-03 until the share switch and Lend your ear have
    a screen (N29);
    the share switch waits per speaker for `PEER_SHARE_POLICY_VERSION`): "A blind 'Lend your ear' step reopens the
    peer lane. Speakers judge up to three short shared or licensed clips,
    audio only, never their own, at most once per Take after a practice
    that lands. Their answers count toward the coach + peer quorum. The
    retired Game stays retired." "Licensed corpus clips may be played to
    speakers, without names, in 'Lend your ear' and 'Bold voices'." A
    Voice Album moment is lent by a toggle, off by default, per recording,
    revocable; a withdrawal leaves both pools at once, the measure's pair
    included (founder 2026-10-02, Q3-A). The toggle exists only for a
    speaker who accepted the Terms and Privacy version that describes it
    (`PEER_SHARE_TERMS_VERSION`; founder 2026-10-02, Q4-A), and a
    listener's answers are the listener's own data, kept with their
    account and gone with it (Q5-A). The set is a blind
    stratified mix by the machine's read, in random order, never the before
    and the after of one pair in one set nor on the same day. An answer is
    one per person per clip and lands under lane `game_peer` (coach + peer
    settles; a disagreement routes a third rater); owner answers never
    enter (L3). Bold voices then adds others' clips the quorum settled Yes
    and corpus clips a coach labelled Yes, without names.
29e. **The delayed blind human measure** (founder 2026-10-01; Phase 5,
    exercise-human-delayed-v1, `docs/MEASURE-exercise-human-delayed-v1.md`,
    served once `DELAYED_MEASURE_ENABLED` is on — on from 2026-10-02, the
    founder having signed the definition and answered C1 to C3 himself, N24,
    N25; off again from 2026-10-03 with the peer lane, N29): one practice makes
    one pair, the original clip and the first valid attempt (F7), fixed when
    the practice closes; fallbacks and rewrite practices are excluded; the
    clips enter Lend your ear as separate, unlabelled clips seven days
    later, never both in one set; the speaker, the coach who handled the
    moment, and any exposed rater never vote; a pair is better, same or
    worse only once both clips are settled by the quorum. It grades the
    machine's label and never teaches on its own.
30. No blocks orange styling and Voice Album admission for that exact clip and
    suppresses that exact clip from resurfacing. It does not penalize the
    Paragraph, the user's voice, or materially stronger audio in a future Take.
    Yes permits later styling consideration but never applies styling itself.
    Owner answers remain self-reports, not model-training ground truth.
31. Machine prediction, blind human rating, anchored owner route, nonblind
    model review, coach judgment, and detector verdict are separate provenance
    types and are never stored under one semantic label.
32. An exact clip or selected practice attempt enters the Voice Album only
    when Machine Yes, User Yes, and Coach Yes independently refer to that same
    recording. Signals cannot be transferred between recordings. Each leg
    counts only as a real Yes (founder 2026-09-29, Q6): In-between, Not sure,
    Audio unclear, No or a missing answer is never a Yes for any of the three
    legs.
33. Saving a practice attempt never admits it directly. The coach judges the
    selected practice attempt itself.
34. The coach must not see the user label, machine prediction, or other ratings
    before submitting an immutable independent judgment. After submission they
    are revealed for comparison and training analysis. **Amended 2026-10-06
    (founder, Navigation Panel P28 B; ledger A151a; decisions log N51):** the coach
    does not see the machine's read after submitting either; nothing is
    revealed to the coach. The comparison happens off-screen, for analysis
    only. The original coach
    judgment is never editable; reconsideration is a separately timestamped,
    provenance-bearing revision. User Yes / Coach Yes admits silently. User
    No / Coach Yes may later become
    a separate Album disagreement exercise and never enables project styling.
    User Yes / Coach No requires coach re-review and may produce a calm
    explanation after confirmed No. User No / Coach No is silent. Coach review
    never changes project styling already accepted by the user. The Voice
    Album introduction is emitted once per user after the first eligible clip
    and Take 3 completion; it never repeats for later Projects.
35. Blind peer confidence rating is retained exclusively for internal model
    training and evaluation. It has separate provenance, access, and serving
    rules and has zero authority over user Feedback, key moments, Manager
    selection, Ideal Text or presentation ranking, styling, root phrases,
    journey behavior, coach decisions, or Voice Album eligibility. The blind
    peer quorum never appears in the rehearsal or personal coaching loop.

## 5a. Confidence-linked exercise policy

35a. The product may assign an exercise to an exact Confident Voice clip. The
    match is made when the Take's Feedback is built, before any answer exists.
    **Which answers open it is the follow-up matrix (24f, founder 2026-09-29,
    evening ruling "it closes")**: In-between, No and Not sure open the
    library video on a clip read weak; a Yes never does (the moment reaches
    the coach as praise or an ambiguity, and a video the coach shares opens
    on any answer but Audio unclear); **Audio unclear closes the moment and
    moves on**, sends nothing to the coach, and keeps no exercise offered.
    This supersedes the same day's earlier Q2 ruling ("every one of the five
    answers keeps it offered, Audio unclear included"), which is retired.
    Audio the machine cannot rely on is refused by the clip safety gate (35b:
    length, noise and voiced-share checks) whatever the speaker answered. The
    responses remain separate self-reports and never override deterministic
    exercise eligibility.
35b. A deterministic safety and need-compatibility gate runs before ranking.
    A model may rank only eligible exercise versions and may never bypass the
    gate. The complete in-scope catalogue is frozen with every version marked
    eligible or typed-excluded. If none is eligible, the product creates a
    post-blind coach request rather than inventing or forcing an exercise.
35c. 80/20 exploration is an exposure policy, not a dataset split (founder
    2026-09-26: "please do the 80/20 try smth new", superseding the earlier
    "deterministic top until an evaluation contract is approved"). With two or
    more eligible exercises for a moment, the best match is served with
    probability 4/5 and each other eligible one with 1/(5(n-1)); one eligible
    exercise is served with probability 1 and is not a randomized comparison.
    The choice freezes the complete ranked pool, every probability, the seed
    commitment and draw, the policy version and the selected version, once per
    (Take, moment), and never rerandomizes on refresh or retry
    (`exercise-80-20-v1`, migration 0372). Using the outcomes as evaluation
    evidence follows label specification `exercise-adequacy-label-v2`
    (founder 2026-09-28; docs/MLC3-EXERCISE-ADEQUACY-DESIGN.md §3.5): an
    exercise helped when the problems it targeted no longer fire on the first
    valid same-passage attempt (F7, founder 2026-10-01: fixed in advance, so
    when the speaker stops cannot change it; the attempt the speaker landed
    on is stored for reading only); first exposures only; an unattempted exercise
    is excluded, never a failure, with the attempt rate always reported; a
    learned ranking may replace the fixed one only after 300 attempts (30 per
    exercise), a gain of at least 5 points on held-out speakers, an attempt
    rate no more than 5 points lower, and founder approval. An exposure
    exists only once the client confirms the exercise rendered; until that
    event exists, outcomes are raw evidence only, and no dataset, training or
    promotion path reads them.
35d. The user is shown which exact exercise version was assigned and its prior
    use, so the product does not unknowingly repeat it. A practice holds as
    many same-passage Recording Attempts as the speaker records (29a; the
    cap of three is retired, founder lock 2026-09-30, D2). Practice attempts
    are not presentation Takes. When the user answers Yes or In-between
    about a practice attempt (29a), the helper words are tapped from that
    attempt's transcript and stored on the Slide; **no practice outcome
    mutates Ideal Text** (B6). The adoption rule of 2026-09-25 — the
    attempt's transcript replacing the practised passage — is retired; the
    rows it wrote stay in the Paragraph's history. The one thing that
    changes the words between Takes is the user's acceptance of a rewrite
    (29b), which is a decision, not a practice outcome. The next Take
    rewrites the Paragraph again (clause 8).
35f. **The catalogue of signed lines** (founder 2026-09-30, E3, C4). One
    signed sentence per pattern — a praise line per delivery cue, device
    and the confident read, a rewrite move per reason — written by the
    founder or a coach and versioned, never edited. The Manager reads it
    before its fallback: a served praise row carries the line for its
    evidence, a served rewrite row the move for its reason. Where no line
    exists the sheet keeps its constant and the fallback stays tentative;
    nothing is invented (24f). A line is copy, never a score (AC-9), and
    never evidence that a pattern occurred (L3).
35e. Exercise comparison is qualitative. No acoustic score, rank, probability,
    or machine verdict is shown to the user. Opening, skipping, timing out, or
    making no attempt is not an effectiveness label.
35f-1. Coach and peer confidence judgments remain independently blind and may be
    plural. Need evidence, exercise candidates, user answers, and machine output
    remain hidden until that rater submits an immutable confidence judgment.
    Only afterward may a coach choose an eligible exercise, author a versioned
    case-specific exercise, or report no safe match. Sharing with the user is a
    separate explicit action. A coach who later authors an exercise may still
    participate in the confidence quorum when their judgment predates reveal.
35g. Exercise eligibility, exercise assignment, practice outcomes, owner
    self-reports, blind coach/peer confidence judgments, professional authoring,
    and Voice Album admission remain separate provenance. Exercise outcomes
    never train Confidence Classification. A practice recording enters Voice
    Album only through Machine Yes + User Yes + Coach Yes on that exact attempt.
35g-1. **Exercise fit** (founder 2026-09-28, D1/D5/D5a/D6). An exercise is
    offered only when a detected problem fired on that exact clip; a clip's
    confidence level alone never picks one. An exercise names one main target
    and may list secondary targets. **Exact**: its main target fired.
    **Trial**: no exercise's main target fired, but one of its secondary
    targets did; it is shown like any exercise and marked a trial internally so
    its outcomes can show whether it helps. A trial never competes with an
    exact fit, not even in the 80/20 exploration slot. Nothing fired, or
    nothing targets what fired: no exercise, and the item keeps "Let's
    practice" alone. Fit is a category, never a number, and never reaches the
    speaker. Among equal fits, the exercise covering more of what fired wins,
    then the one claiming fewer targets. **The ladder** (founder 2026-10-01,
    F2): "Every moment read weak with an error gets an exercise: the exact
    match, else the closest match, else the general exercise for that error,
    else the warm-up. Fallbacks are traced and never teach the exercise
    ranker." The closest match is the trial tier; the general exercise is the
    catalogue entry flagged for that error and never in the ranked pool; the
    warm-up is `hear-every-word-v1` once a reviewed change activates it. A
    fallback is marked in the match trace and left out of every learning
    read, the delayed human measure included. The coach request still rises
    on the moment, and a coach-shared exercise replaces the rung. Dark behind
    `EXERCISE_FALLBACK_LADDER_ENABLED` until the three general exercises
    and the warm-up exist (switched on 2026-10-02 before they did, off again
    from 2026-10-03, N29).
35g-2. **The coach hears when nothing fits** (founder 2026-09-28; extended
    2026-09-29). When the Take's exercise item gets no exercise under 35g-1,
    one coach request is recorded for that exact moment with why (nothing
    spotted, nothing in the library targets what was, or the library
    matched). **Every judgement reaches the coach** (founder 2026-09-29,
    the follow-up matrix): every answer but Audio unclear sends that
    bookmark to the coach the moment it is saved, tagged with its kind:
    **error** (read weak, a delivery problem named, on In-between or No),
    **praise** (read confident, on Yes or In-between), **rewrite** (read
    weak, nothing acoustic fired, on In-between or No), or **ambiguity**
    (the speaker and the machine disagree: a Yes read weak, a No read
    confident, every Not sure, and a clip the machine could not read). **Amended
    2026-10-06 (founder, Navigation Panel P2 A; ledger A175b; decisions log N51):**
    no coach request is raised for a clip the machine could not read —
    nothing goes to the coach for it, and "a clip the machine could not
    read" leaves the ambiguity list above. This matches 24e-1 ("Nothing
    rises for ... a clip the machine could not read"). The
    coach records a video for errors by default and may for the rest; a
    shared video rides that same moment. On an error with no library match
    the item reads "Your coach is working on your exercise." (founder-signed
    copy, 2026-09-29) until the coach shares one; on the other kinds nothing
    is promised and the video appears when shared. **Amended 2026-10-05
    (founder, decisions log N48.3 Q10 A):** that sentence shows only while a
    coach is active. The coach hears often
    while the library is small; each answer files a reusable exercise. The speaker never waits on it. The coach
    sees it only after their own blind rating of the moment and answers once:
    a library exercise, a new one filed into the library (which must name a
    problem code can detect, and, since 2026-09-30, the one main target it
    is written for, and so becomes reusable for any speaker), **a praise
    line or a clearer version written in words** (founder 2026-09-30, C2 to
    C5), or no safe match. Sharing is a separate act; an exercise, a line
    or a clearer version can be shared, and a shared answer then rides on
    that same item for the speaker (an exercise as `practice_exercise`, words
    as `coach_answer`). A praise line also lands in the catalogue of signed
    lines (35f) as the newest version for the moment's pattern unless the
    coach keeps it to the speaker; a clearer version never does, being one
    speaker's passage. Once the library itself fits the moment, the matched
    exercise is what is served. Under 24e-1 the request rises at the open
    instead, under the machine's kind, and the judgement sets its answer
    kind; the coach reads that side only after their blind rating.
35g-2a. **The draft and the pair** (founder 2026-09-30, C2, C5; build plan
    P2-1, P2-2). On an error, praise or rewrite request the coach may ask
    for one model draft by the request's kind (an exercise script, a praise
    line, a clearer version); an ambiguity has none. The draft is shown to
    the coach only, after their blind rating, and never reaches the speaker
    as drafted. Where a draft was shown and the coach's final differs, one
    (draft, final) pair is recorded on that surface, stamped with the
    model version, the pattern and the moment, with the coach as author and
    the speaker as the passage's owner; the exercise lane records the saved
    instruction and, once it arrives, the video's transcript the same way.
    Three surfaces, never mixed. A pair is provenance for a later,
    separately authorised preference export; it is never a label (L3),
    never a score (AC-9), and never shown. **As built 2026-10-05 (W6):**
    the model's draft a pair stands on is the one the server kept on the
    request, never a text the client calls a draft; the walk's exercise
    answer is paired when the request resolves to the exercise filed for
    it, stamped with the request, the moment, the owner and the model
    version (the transcript pair with the exercise version and the moment);
    a coach answering a moment of their own Take is the owner and leaves no
    pair; the Library, which has no moment and starts from past finals,
    records none. Only pairs the export can release (the speaker's yes, the
    passage, the model version) fill the bar of 200. Naming a pattern on the
    moment itself was retired (N45 Q9); the shadow-cue bar reads the blind
    error audit (35g-3a, N48.5 Q24 A).
35g-3. **Did the practice sound more confident?** (founder 2026-09-28,
    option A; rule `exercise-more-confident-v1`, migration 0388.) For each
    practice session, the attempt the coach judged is recorded as **helped**
    when its voice-confidence composite is higher than the original clip's
    (any increase) **and** the coach heard it get better; **not helped** when
    either says no; **pending** while either is missing. "The coach heard it
    get better" is worked out, never asked (founder 2026-09-29, Q5; rule
    `exercise-more-confident-v2`, migration 0391): the same coach's blind
    rating of the original clip against their answer about the practice, on
    the ladder No < In-between < Yes. Higher is better; the same or lower is
    not; an answer off the ladder (Not sure, Audio unclear) or missing, or
    Yes before and after (already confident), is pending, never "didn't
    help". The speaker's own answer is not part of it. It is internal: never
    shown to a speaker or a coach, and never a label. The machine leg and the
    coach leg keep their own provenance (clause 31). It is a separate reading
    from `exercise-adequacy-label-v2` (the design's §3.5), which stays the
    only label specification and is unchanged; nothing about either feeds
    back into which exercise is shown or how often (35c).
35g-3a. **A pattern is tested silently first** (founder 2026-09-28, D2, D3).
    Between observed (a person named it) and detected (it routes exercises)
    sits shadow: a detector runs on real Takes and its verdicts are logged,
    but it routes nothing, reaches no user and feeds no dataset. The first
    shadow patterns are spoken-word habits: filler clusters, hedging and
    restarts, English only while only English transcripts keep hesitations.
    A clip that cannot be measured honestly gets no verdict, never a false
    "absent". Promotion to detected is a separate, deliberate change, made
    only after the verdicts have been compared with coaches' independent
    judgments against the founder's bar (D3a). **Amended 2026-10-05
    (founder, decisions log N48.5 Q24 A: "coaches' Yes answers in the blind
    error audit are what promote a shadow cue"):** at least 30 coaches' Yes
    answers in the blind error audit (35g-9) for the pattern, on clips
    sampled under the detector version being judged, and the detector fired
    on at least 80% of those moments (the audit's catch rate, each answer
    weighted by its clip's sampling probability). The bar of 30 moments a
    coach named the pattern on is retired with naming on the moment (N45
    Q9); named moments are reported as history only. The audit's No
    answers measure how often it fires falsely. A pattern the audit does
    not sample has no Yes to count and cannot clear the bar.
35g-4. **The speaker's own history breaks ties** (founder 2026-09-28). Among
    exercises of equal fit that cover as much of what was spotted, one for a
    problem this speaker showed on at least two earlier Takes comes first,
    and one they already completed comes after one they have not. An
    exercise done before is ranked later, never withheld: history cannot
    leave a speaker with no exercise. History is read from the frozen records
    of earlier Takes, as of the first draw, and is frozen with it. Shadow
    verdicts are never part of it.

35g-5. **The coach's walk** (founder 2026-09-30, A1 to A8, B10; build plan
    P2-8 to P2-14). The coach's work is one walk over one queue: speakers
    oldest first, each Take's bookmarked moments in slide order, each moment
    with one state word (judge it, answer it, answered, nothing to add,
    judged). The judgement screen is the speaker's own Feedback sheet with
    the one instrument, the five answers in the coach's words, answered
    blind (clause 34) before anything else is revealed. Read follows: the
    passage, the speaker's answer, the coach's answer, the goal, what
    reached the coach and why. An answer is the same three screens for
    every kind, Words, Video, Home; the model draft, where the kind has one
    (35g-2a), sits in the field the coach edits; video is recorded in the
    panel; Home files the answer into the library under its pattern and
    shares it in one tap, sharing staying explicit (35g-2). The walk moves
    on by itself. From 1024 px a rail lists speakers, Takes and moment
    states as words beside the centred sheet; there is no third pane and no
    table. The coach's library is the same screens entered from the
    Library. Every earlier coach surface (the Feedbacks review, the
    take-review overlay and its second instrument, the arc-level publish)
    is retired (clauses 41, 63 to 66).
35g-6. **A word for this Take** (founder 2026-09-30, B3; build plan P2-5,
    P2-12; migration 0403). After the last open moment of a Take the coach
    may leave one optional word for that Take: words, a video, or both,
    saved once per coach and Take and shared as a separate act. The speaker
    reads it as "Your coach" on that Take's page; it is the one Take-level
    coach note (clause 41). It gates nothing, autoplays nothing, carries no
    label, verdict or number, and never edits Ideal Text (clause 40). Every
    per-moment answer reaches the speaker on its own moment the moment it
    is shared (35g-2); the arc-level publish that once held them back is
    retired (clause 65).
35g-7. **The coach's exercise preference** (founder 2026-10-01, F8; Phase 1b
    of the coach panel; migration 0411; served only once
    `COACH_EXERCISE_PREFERENCE_ENABLED` is on). After the blind rating the
    coach sees the exercise the machine served on a moment and may keep it,
    swap it for one of the pool the frozen trace ranked (shuffled, no rank or
    score shown, the served one marked) or make a new one. Keep is explicit;
    silence records nothing. Each explicit choice is appended under
    provenance `coach_preference` with the served exercise and version, the
    draw, the fit, the fired errors and the signal rules of the trace, and
    on a swap the exercise chosen and whether it was in the pool. It may
    propose a ranking (exercise-coach-preferred-v1, dark, graded by the
    same fair test); only outcomes decide whether an exercise helps.
    Coach-chosen exercises never enter the fair test; their outcomes stay in
    their own pile. Never mixed with adequacy labels, detector verdicts,
    audit answers, confidence labels or owner answers (L3).
35g-8. **The coach's words as pair surfaces** (founder 2026-10-01, C5-a;
    Phase 7; migration 0411; `COACH_WORD_PAIRS_ENABLED`). The personal line
    on a moment and the Take word are drafted by the model from the
    transcript and the coach's notes only, after the moment's blind rating
    (the line) or after every moment of the Take is judged (the word); the
    draft sits in the field the coach edits under the label "Drafted from
    this Take · edit every word", is never shown to the speaker as drafted,
    and states nothing about the read. When the coach's final differs, the
    (draft, final) pair is recorded under the C5 rule on its own surface
    (`coach_moment_line`, `coach_take_word`), never mixed with the three
    answer surfaces; a video's transcript is a second final. Pairs are text
    only. Door 2 stays shut for both surfaces until a qualified lawyer's
    written answer and the founder's sentence.
35g-9. **The blind error audit and the detector that can learn** (founder
    2026-10-01, F6; Phase 6; migration 0411; `ERROR_PRESENCE_AUDIT_ENABLED`,
    `DETECTOR_TRAINING_AUTHORISED`, the latter off again from 2026-10-03
    because the fit does not exist and document 02 v1.1 §9 keeps it off
    until counsel confirms, N29). A coach answers Yes, No or Can't tell
    to one error's own question (`speaking_error.asks`, word for word) about
    one clip, never seeing whether the detector fired; clips are sampled
    fired and not fired, stratified per error, practice attempts included,
    one in ten to two coaches, only while the speaker's "Personalised
    practice" choice is on at sampling time (the easy off switch; founder
    2026-10-02, Q1-C; the answers die with the recording, Q2-C), at most
    three per speaker and twenty blind
    answers per coach per week shared with 35g-10. Answers are appended
    under provenance `coach_audit`, never shown to a speaker and never mixed
    with any other label (L3); they give the false-alarm half the shadow
    comparison cannot measure. Every acoustic detector has a version per
    error (off, shadow, live; `LIVE_DETECTOR` names the one in force; a
    change or a rollback is one reviewed line after the founder's yes);
    every version's verdict on every clip is logged insert-once and every
    match trace says which version made its choice. A candidate is
    promoted only after four weeks in shadow, better on one rate and not
    worse on the other on held-out speakers, and never by itself. Fitting a
    learned detector is voice-based training and waits for separate voice
    consent and the AI Act opinion; the tuned thresholds run in shadow
    regardless.
35g-10. **The coach's block pick** (founder 2026-10-01, C5-b; Phase 8;
    migration 0411; `COACH_BLOCK_PICK_ENABLED`, on from 2026-10-02 (N22),
    off again from 2026-10-03 until it samples every speaker's blocks, N29). On a Take the coach is not
    walking, the coach hears up to three candidate moments of one block,
    letters only, and picks the one that sounds most assured or says they
    can't tell; the Manager's pick is stored and never sent. The pick is
    appended under provenance `coach_block_pick`, never changes a bookmark,
    never reaches the speaker, and grades the Manager's choice only.
35g-12. **A student's new Take as a bubble** (founder 2026-10-01, Phase 0c,
    A2; `COACH_TAKE_BUBBLES_ENABLED`). A Take in the coach's queue that this
    coach has not walked yet appears as a bubble in the coach's Lounge chat,
    opening the walk on that Take; it is derived at read and never stored.
    It names the student (the real name only as 0b allows, A3) and the Take,
    and says nothing about the Take's quality or its moments' kinds.
35g-11. **A coach's exposure and the blind rating** (founder 2026-10-01,
    task 4; migration 0411). The first time a coach sees a clip's non-blind
    side (the Read screen, a request, an audit, a block pick) is recorded
    once per coach and clip. A rating by that coach on that clip afterwards
    is stamped not blind by the server, counts for no quorum, no Album leg
    and no measure, and the audit and the block pick never serve that coach
    that clip. Game raters have no exposure record.

## 6. Coach review and learning lineage

35h. Confident Voice, Actionable Improvement, and Praise responses use
    separate schemas and remain separate datasets. Shown is not positive, skip
    is not rejection, and a user response is not a gold label.
35i. Actionable Improvement offers Apply suggestion, Edit myself, and Keep
    wording. Praise offers Useful, Not useful, and Not sure. Praise responses
    never style text.
35j. Every surfaced set writes an immutable exposure ledger containing the
    complete candidate set, evidence and internal scores, selected candidate,
    model and prompt version, user action, and later coach-judgment provenance.
    **Amended 2026-10-06 (founder, Navigation Panel QB16 A; ledger A180b; decisions log N51):**
    the record is *linked to* the speaker's action and the coach's judgement;
    linking is enough, the row need not carry them in its own columns.
35k. Evidence-backed verbal corrections and praise wording/explanations may
    create surface-specific DPO pairs. Praise selection/ranking is not trained
    until the exposure ledger is complete. The three families are never merged
    into one undifferentiated training set.
36. Every Machine Feedback item retains a review lineage. The coach may confirm
    it, refine its explanation, reject it, or materially correct it. The
    original machine output remains in history. **Amended 2026-10-06 (founder,
    Navigation Panel P31 A; ledger A181; decisions log N51):** for rewrite and praise
    items the coach's answer by kind (35g-2) is the review history; the
    answer by kind is enough.
37. Routine agreement is silent. Explanation refinement does not change user
    text. A material correction becomes a new accept/reject proposal if the
    user has seen or acted on the original.
38. Machine-versus-coach outcomes are the learning comparison. Coach actions
    never silently change accepted user text.
39. Coach review and delivery are item-level. Feedback items and clips may
    reach the user independently. Take-level reviewed or finalized state is an
    aggregate summary only and never gates immediate feedback or the next Take.
    Since 2026-09-30 (B2, B3) no such state is shown to the speaker: there is
    no "Reviewed" badge and no arc-level publish; a shared answer reaches its
    moment on its own (35g-2) and the Take word its Take (35g-6).
40. The coach does not own, edit or publish a competing full-document version.
    Ideal Text remains the user's canonical document (L1). The coach's Ideal
    Text edit and approve are retired (founder 2026-09-30, B2; clause 64);
    a coach's wording reaches the speaker only as a clearer version on a
    moment (35g-2), which the speaker may accept (29b) or leave.
41. Per-item breakthrough videos and per-item Star Verdict videos are retired.
    A coach may share only an optional general Take-level note, words or
    video, which is the Take word (35g-6). It is explicitly shared, never
    autoplays, never gates progress, and carries no detector label or
    Feedback verdict. Star Verdict review is retired altogether (founder
    2026-09-30, B1; clause 63); the V2 lane's tables stay as history.

## 7. Lifecycle and journey

42. Recording processing, Take completion, Ideal Text preparation, coach
    delivery, journey progress, and Feedback decisions are independent state
    machines. A UI status may project them but no universal pending, ready, or
    completed state controls them all.
43. Processing is durable when the user leaves the waiting screen. Failure
    preserves the Recording Attempt. Retry uses that same attempt and never
    routes the user to an unrelated Chat.
44. When processing and initial document/feedback preparation succeed, the app
    automatically opens that Project's Ideal Text.
45. Takes 1-3 follow Ideal Text -> See next steps -> stage-specific Chat bubble
    -> return to the next recording action. Refresh and reopening preserve the
    state and never repeat setup.
46. Take 3 completes the guided journey. Take 4+ is optional refinement and
    immediately offers Record again without another See-next-steps loop.
    **Amended 2026-10-05 (founder, decisions log N48.3 Q8 A):** the action
    reads "Record Take N".
47. Accepted anchors persist across Takes and are never automatically
    replaced. First-time Paragraph/Slide coverage precedes replacement
    optimization. Replacement candidates must independently deserve
    attention. Unshown low-priority queues end after Take 3. No changes needed
    is a successful refinement result. **Amended 2026-10-05 (founder,
    decisions log N48.3 Q12 A):** V3 serves every Take (24b to 24d), so
    "Unshown low-priority queues end after Take 3" is superseded: every Take
    is selected in full and surfaced through the window of three (24b).
    **Amended 2026-10-06 (founder, Navigation Panel QG3 A; ledger CA01; decisions log N51):**
    "V3 serves every Take" reads as "the served policy serves every Take":
    V3 today, and V4 for every speaker once built and switched by the
    founder (24, V22a B), with V3's pick on any block V4 is very unsure of,
    logged (V15a).

## 8. Commercial model

48. The free grant occurs once per user. It does not renew monthly.
49. Every purchase is a one-time package of tokens and any included coach
    review credits. Balances remain until consumed and do not renew.
50. There are no subscriptions, billing periods, renewal dates, or monthly
    plans.
51. Exhausted balances may block new paid actions but never remove access to
    existing Projects, Ideal Text, Feedback, exports, or Voice Album entries.

## 9. Legacy retirement

52. Obsolete runtime pipelines, behavioral fallbacks, adapters, and aliases are
    removed rather than retained as degraded paths.
53. Old Project data may be deleted instead of forcing permanent compatibility.
54. Database migration history remains for reproducibility. Obsolete live
    tables are removed only through explicit new migrations.
55. Any route, table, or behavior whose active use remains ambiguous requires
    an individual founder decision before removal.
56. Historical `best_presentation_ready` messages remain readable only as
    compatibility entry points to the live Ideal Text for that Project. They
    never rebuild, cache, or expose a separate Best Presentation document, and
    no new message is created under that legacy kind.
57. Breakthrough Moments is retired as a separate user-facing surface. Useful
    evidence may survive only when it already exists independently under a
    canonical Feedback family or an exact-clip Voice Album decision. It never
    creates a fourth feedback family, library, Chat action, or presentation
    artifact.
58. The former threat-to-challenge breakthrough detector and its labels are
    deleted, not repurposed as hidden Manager evidence.
59. The entire psychological threat/challenge framework is retired. Its
    priming experiment, condition and phrase capture, direction labels,
    classifier and shadow outputs, coach controls, user surfaces, runtime
    fields, and live database storage are deleted. Historical migrations stay
    immutable; an explicit cleanup migration removes the obsolete live schema.
    Pre-recording uses one supportive, non-manipulative framing and records no
    experimental condition.
60. The existing generic Game, its routes, and saved game sessions are retired.
    It is not renamed into Voice Album. Any Voice Album disagreement exercise
    is a purpose-specific personal flow inside Voice Album with its own state
    and the three-signal provenance rules above.
61. The direction-learning subsystem is removed completely, including its live
    `training_labels`, `shadow_predictions`, and `model_versions` tables. A
    future model registry must declare an explicit construct and provenance;
    the generic legacy registry is not retained empty.
62. The legacy Reflection Game and `reflection_clips` experiment are deleted
    completely, including their user and coach routes, decoy pool, agreement
    matrix, database accessors, and live table. They are not a source for the
    canonical Voice Album, which uses the three independent signals in §5.

63. The Feedbacks review (the star-verdict coach overlay, its blind pass, the
    per-arc rows and the backend star lane's coach endpoints) is retired
    (founder 2026-09-30, B1). The V2 lane's tables stay as history and take
    no new writes; the coach's judgement of a moment is the one instrument
    on the walk (35g-5).
64. The coach's Ideal Text edit and approve, the Ideal Text annotation pairs
    they wrote, and the speaker's "Reviewed" badge are retired (founder
    2026-09-30, B2). The approve route answers 410. Pairs come from the
    three answer surfaces (35g-2a).
65. The arc-level delivery (Wrap up, Ideal text, Message, Review and send,
    Delivered), the wrap-up page, the slide-mapping correction control, the
    confidence label chips, the coach note's surface toggle and the
    take-review overlay are retired (founder 2026-09-30, B3 to B6), replaced
    by per-moment Share and the Take word (35g-6). The publish-delivery
    worker job is retired with them. The removal was to wait until the
    ledger had shown a week of walk pairs (L2, build plan ML-5); the founder
    waived that wait on 2026-10-01 ("do P2-19 now", decisions log N17) and
    the removal landed that day: the routes answer 410, the tables stay as
    history, and the Voice Album's coach leg is released by the judgement
    write itself, since a judgement on the walk is final when written
    (35g-5). The speaker's "Your coach" still reads a revision published
    before that day.
66. The coach compare, audit and corpus-summary pages, the /coach/willab
    redirects, the three off-flag composers, the CMS exercise lane, /cms/gaps
    and /cms/jar are retired (founder 2026-09-30, B7, B8); posts stay in
    /cms, and the jar and gaps counts live on the founder's pace panel. The
    MLC-3 exercise service loop is retired (L8): its routes answer 410, its
    monitors are off, its tables stay.

## Non-negotiable provenance walls

- Project identity never derives from display name, topic, deck hash, or
  recency.
- Feedback candidates are not user-facing Feedback until Manager arbitration.
- Owner routing is not blind training ground truth.
- Blind peer labels and quorum are internal corpus evidence, never product
  decision inputs.
- Coach drafts, coach judgments, publication, and notification are distinct.
- Saved, accepted, protected, reviewed, and published are independent states.
- Legacy compatibility cannot silently select a different document,
  processing, feedback, learning, or billing policy.
