# Willab canonical product contract

Status: founder-locked on 2026-08-26. Feedback Policy V3 amendment locked on
2026-08-30; it remains inactive until a separately authorized serving cutover.
L1 / helper-words amendment locked by the founder on 2026-09-25 (clauses 8, 9,
12-20, 24e, 29a, 35d): each Take rewrites the Paragraph from what was said; the
lock keeps the helper words, not the text. Ideal Text redesign amendment locked
by the founder on 2026-09-26 (clauses 13, 16, 20, 24g-1): "Use these helper
words" is the lock; helper words head their own Paragraph and read italic inside
it; the text is never greyed.

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
5. A Recording Attempt is the preserved submitted audio. A Take exists and
   counts only after processing succeeds. Retrying processing reuses the same
   Recording Attempt and never increments the Take count.
6. Read, practice, import, and processing-retry sessions do not become Takes.

## 2. Ideal Text and document structure

7. Ideal Text is the sole canonical presentation document. Best Presentation
   as a separate assembled product artifact is retired.
8. Take 1 creates the initial project-specific Ideal Text. Each later Take
   rewrites every Paragraph it covers from exactly what the speaker said in
   that Take — the latest Take, never a best-of pick across Takes. A Paragraph
   the speaker did not say in a Take keeps its last spoken version. (Founder,
   2026-09-25; supersedes "later Takes never replace it".)
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
    2026-09-26). There is no Keep evolving choice and no Unlock action: every
    Paragraph follows the speaker (clause 8), and choosing new helper words
    replaces the old ones. A user whose answer opens the helper-words step
    (24e) but who closed the sheet before choosing may still choose them from
    the Paragraph's own sheet.
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
    lock it.

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
      green bookmark stays on the two most Confident items (24g) and no
      longer decides where praise goes;
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
      filled in. The read chooses and is never surfaced. The weakest
      below-neutral item keeps its bookmark colour. A rewrite on the same
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
    candidate.
28. Every surfaced Feedback item references exact Project, Take, Slide,
    Paragraph, and evidence span. Confident Voice additionally requires a
    playable audio interval. Actionable Improvement and Praise do not.

## 5. Confidence, learning provenance, and Voice Album

29. Confident Voice offers primary responses Yes — Confident, In-between, and
    No — Not confident, plus secondary Not sure and Audio unclear. The response
    is an immutable self-report tied to the exact clip and Take.
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
    Paragraph** (B6): the words on the page change only with a Take. Each
    answer is stored against the practice attempt it judges, never against
    the Take (clause 31).
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
    are revealed for comparison and training analysis. The original coach
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
    evidence follows label specification `exercise-adequacy-label-v1`
    (founder 2026-09-28; docs/MLC3-EXERCISE-ADEQUACY-DESIGN.md §3.5): an
    exercise helped when the problems it targeted no longer fire on the last
    valid same-passage attempt; first exposures only; an unattempted exercise
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
    rows it wrote stay in the Paragraph's history. The next Take rewrites the
    Paragraph again (clause 8).
35e. Exercise comparison is qualitative. No acoustic score, rank, probability,
    or machine verdict is shown to the user. Opening, skipping, timing out, or
    making no attempt is not an effectiveness label.
35f. Coach and peer confidence judgments remain independently blind and may be
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
    then the one claiming fewer targets.
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
    confident, every Not sure, and a clip the machine could not read). The
    coach records a video for errors by default and may for the rest; a
    shared video rides that same moment. On an error with no library match
    the item reads "Your coach is working on your exercise." (founder-signed
    copy, 2026-09-29) until the coach shares one; on the other kinds nothing
    is promised and the video appears when shared. The coach hears often
    while the library is small; each answer files a reusable exercise. The speaker never waits on it. The coach
    sees it only after their own blind rating of the moment and answers once:
    a library exercise, a new one filed into the library (which must name a
    problem code can detect, and so becomes reusable for any speaker), or no
    safe match. Sharing is a separate act and only an exercise can be shared;
    a shared exercise then rides on that same item for the speaker. Once the
    library itself fits the moment, the matched exercise is what is served.
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
    from `exercise-adequacy-label-v1` (the design's §3.5), which stays the
    only label specification and is unchanged; nothing about either feeds
    back into which exercise is shown or how often (35c).
35g-3. **A pattern is tested silently first** (founder 2026-09-28, D2, D3).
    Between observed (a person named it) and detected (it routes exercises)
    sits shadow: a detector runs on real Takes and its verdicts are logged,
    but it routes nothing, reaches no user and feeds no dataset. The first
    shadow patterns are spoken-word habits: filler clusters, hedging and
    restarts, English only while only English transcripts keep hesitations.
    A clip that cannot be measured honestly gets no verdict, never a false
    "absent". Promotion to detected is a separate, deliberate change, made
    only after the verdicts have been compared with coaches' independent
    judgments against the founder's bar (D3a): at least 30 moments a coach
    named the pattern on, and the detector fired on at least 80% of them.
    Coaches record only what is present, so this bar measures what the
    detector catches, not how often it fires falsely.
35g-4. **The speaker's own history breaks ties** (founder 2026-09-28). Among
    exercises of equal fit that cover as much of what was spotted, one for a
    problem this speaker showed on at least two earlier Takes comes first,
    and one they already completed comes after one they have not. An
    exercise done before is ranked later, never withheld: history cannot
    leave a speaker with no exercise. History is read from the frozen records
    of earlier Takes, as of the first draw, and is frozen with it. Shadow
    verdicts are never part of it.

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
35k. Evidence-backed verbal corrections and praise wording/explanations may
    create surface-specific DPO pairs. Praise selection/ranking is not trained
    until the exposure ledger is complete. The three families are never merged
    into one undifferentiated training set.
36. Every Machine Feedback item retains a review lineage. The coach may confirm
    it, refine its explanation, reject it, or materially correct it. The
    original machine output remains in history.
37. Routine agreement is silent. Explanation refinement does not change user
    text. A material correction becomes a new accept/reject proposal if the
    user has seen or acted on the original.
38. Machine-versus-coach outcomes are the learning comparison. Coach actions
    never silently change accepted user text.
39. Coach review and delivery are item-level. Feedback items and clips may
    reach the user independently. Take-level reviewed or finalized state is an
    aggregate summary only and never gates immediate feedback or the next Take.
40. The coach does not own or publish a competing full-document version.
    Ideal Text remains the user's canonical document. Coach wording changes
    are explicit correction proposals with preserved machine lineage and a
    user accept/reject decision.
41. Per-item breakthrough videos and per-item Star Verdict videos are retired.
    A coach may share only an optional general Take-level video note. It is
    explicitly shared, never autoplays, never gates progress, and carries no
    detector label or Feedback verdict. Star Verdict review remains text-based.

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
47. Accepted anchors persist across Takes and are never automatically
    replaced. First-time Paragraph/Slide coverage precedes replacement
    optimization. Replacement candidates must independently deserve
    attention. Unshown low-priority queues end after Take 3. No changes needed
    is a successful refinement result.

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
