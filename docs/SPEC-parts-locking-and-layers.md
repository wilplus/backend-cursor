# SPEC — Parts, Locking, and the Two Intervention Layers

**Status:** design agreed (founder, 2026-08-07). **Step 0 built 2026-08-07**
— see §10 for the two places the build had to diverge from this document and
why. **Locking has since shipped** with the transcript review deck (the lock
icon rides `locked_at`; chunk model in FE `deckChunks.ts`, 2026-08-11).
**§11 (founder spec 2026-08-14) re-grains the chunk** — size cap at the
document builder, nested scroll, two-grain indicator; §11.1/§11.3/§11.4
entered build the same day on founder order. **§12 (founder specs
2026-08-14)** names the three integrity rules — Anchor Rule, Clean Serve
Boundary, Intent Ledger; §12.1 and §12.2 shipped the same day; §12.3
entered build in the next window (founder order).
**Ships in three PRs:** this spec · stable parts (Step 0) · locking.

---

## 0 · The one-paragraph version

The ideal text stops being a string and becomes an ordered list of **parts**
with stable ids. A part can be **locked**. A part's lock state decides which
**layer** of intervention may fire on it: an open part gets *composition*
(change the words), a locked part gets *accentuation* (style what is already
there). The phase is never stored — it is derived from the lock, so it cannot
desync.

---

## 1 · Why this exists

The product loop is: rehearse a chunk until the words are right, declare that
chunk done, move on, and finally rehearse the whole thing for delivery. Two
different kinds of help are needed at those two moments, and offering the wrong
one is worse than offering nothing:

* Suggesting a **rewrite** on text the speaker has already committed to memory
  destroys the memorisation they just paid for.
* Suggesting an **emphasis** on text whose wording is still in flux styles a
  sentence that is about to be replaced.

So the layer is not a preference. It is a function of where the speaker is.

---

## 2 · The distinction already exists, unnamed

This is not a new concept being introduced. It is a load-bearing concept that
is currently implicit in **four separate enums** in `idealText.ts`:

| where | enum |
|---|---|
| suggestion | `kind: "emphasize" \| "replace"` |
| structure marker | `kind: "structure"` |
| delivery marker | `kind: "delivery"` |
| render instruction | `kind: "replace" \| "bold" \| "advice"` |

Sort them and they fall cleanly in two: `replace`/`structure` change words;
`emphasize`/`bold`/`delivery` do not. Nothing names that split, so nothing can
enforce it.

This is the same failure as the six dead metric columns on `charisma_snippets`
(PM-9) and the `unit`/`denominator` overload in `dimension_registry`: a real
distinction with no single home, re-derived slightly differently by each
consumer until they disagree.

---

## 3 · Schema

### 3.1 Parts

```
ideal_text_part
  id          uuid   PK        -- STABLE. never regenerated.
  arc_id      uuid   FK
  ord         int              -- position. changes on reorder; id does not.
  text        text
  locked_at   timestamptz NULL -- NULL = open (composition)
  created_at  timestamptz
```

**`id` is the whole point.** A lock must survive both *reordering* and
*rewording*, and only a persisted id does:

* **array index** — shifts on reorder, and `splitSegments` filters empty
  segments, so it shifts on edits that are not even reorders;
* **content hash** — dies the moment an approved accentuation touches the
  paragraph, and locked text is exactly the text that keeps changing;
* **character offset** — needs re-anchoring on every edit, which is a second
  segmentation problem beside the one F1 already owns.

`ord` is separate from `id` for the same reason `kind` is separate from
`layer` below: position is not identity.

### 3.2 Interventions

Two new columns. **Two, not one.**

```
intervention
  layer   text NOT NULL   -- 'composition' | 'accentuation'   WHEN it may fire
  kind    text NOT NULL   -- 'replace' | 'bold' | 'color' | … HOW it renders
  part_id uuid FK         -- which part it anchors in
```

`layer` is the phase gate. `kind` is the render instruction. They correlate
today and will stop correlating the day a second accentuation kind ships
(colour alongside bold) — at which point a single overloaded column silently
changes the meaning of the phase logic. One column answering two questions is
precisely the bug unpicked in `dimension_registry`.

### 3.3 Decisions

```
intervention_decision
  intervention_id uuid FK
  decision        text     -- 'approved' | 'disregarded'
  decided_at      timestamptz
```

Absence of a row means **undecided**, which is NOT `disregarded`. Collapsing
those two would corrupt the only direct measurement of Manager Engine
precision this product will ever get (see §6).

---

## 4 · The derived phase

```
allowed_layer(part) = part.locked_at IS NULL ? 'composition' : 'accentuation'
```

**Never stored.** A stored `arc.phase` can desync from its parts; a derived one
cannot. Deriving it also buys three behaviours for free rather than as
features:

1. **Progressive locking.** Part 1 locked (accentuation) and part 2 open
   (composition) at the same time, with no special case.
2. **"Rehearse all" is a recording SCOPE, not a mode.** Record the whole text;
   each part gets the layer its own lock state allows. The strict
   composition→accentuation order is preserved *per part* without a global
   gate, so rehearsing everything before everything is locked is coherent
   rather than an edge case.
3. **Voice confidence lands where it belongs.** It is the ranking input for the
   accentuation layer (`services/voice_confidence.py` already exists), and it
   simply never applies to an open part.

---

## 5 · Rules

### R1 · The layer filter runs BEFORE budget selection
Max **3 interventions per take, total, across both layers** — the cognitive
load limit is on the speaker, not per-lane. The Manager Engine filters
candidates by `allowed_layer(part)` *first*, then spends its 3 slots. Filtering
after selection would waste slots proposing rewrites on locked text.

### R2 · Approve ≠ Lock
Different verbs on different objects. **Approve** decides one intervention.
**Lock** promotes one part to the next layer, over a series of already-decided
changes. Lock is not bulk-approve.

### R3 · A part cannot be locked with undecided interventions
Locking a part makes composition illegal there, so any pending composition
suggestion becomes unreachable. The button is **disabled** until every
intervention on that part is decided.

The alternative — auto-disregarding them — writes decisions the user never
made into the exact signal §6 depends on. Same reasoning as R4.

### R4 · Undecided is a real third state
Closing the modal leaves interventions pending. They are not refusals.

### R5 · Unlock is allowed
The cognitive cost of a permanent mistake during practice is too high. Unlock
reverts a part to `composition`, with R3 applying in reverse: a part with
undecided accentuation interventions cannot be unlocked either.

### R6 · Approve applies a span; it does not mint a version
One version per take, composed from that take's approved spans. Otherwise
three taps produce three versions and the history stops being readable.

### R7 · No "something changed" notice
Approving *is* the acknowledgement. The user asked for the change; telling them
it happened is noise. This is what retires the superseded prompt honestly
rather than merely deleting it.

### R8 · A PROPOSAL NEVER PAINTS THE TEXT (founder 2026-08-15)

> *"before it is applied do not fire any stylings — we ripped it out that the
> underlined text was indicating smth; the styling applies to the text only
> after being accepted as a styling suggestion."*

**The document carries the marks of DECISIONS, never of offers.** A pending
suggestion — style or otherwise — is metadata beside the text (`quote`, `span`,
`kind`, `device`, `cue_keys`). It is rendered in the modal that opens on the
chunk, and it changes not one character of the document until the student
accepts it.

This is not a preference about tinting. A talk can arrive as one chunk, and a
single pending note then striped 233 words amber — the page became unreadable
in exactly the state where reading it is the task. Worse than the noise: a
document that paints what was merely *proposed* is telling the student their
words already changed. The accent is the record of a choice they made, so
showing it before the choice is a claim about their intent.

**The chain, and where each link is enforced:**

| Stage | What holds the accent | Enforced by |
|---|---|---|
| proposed | nothing in the text — metadata only | `build_tracked_changes` returns spans and quotes; it never writes into the served document |
| accepted | `{{orange:…}}` baked into the part | `ideal_decision_ledger.bake_piece` filters `decision == "approved"`, and it is the **only** caller of `ideal_text_block.wrap_accent` |
| rendered | the marks present in the text, and nothing else | the deck renders `<RichText text={c.part.text} />`; `deckSurface.test.ts` pins that its source carries no `underline`, no `bg-pending`, no `decoration-`, no `CHUNK_TEXT_CLS` |

**`visual` is a TYPE label, not a paint order.** `intervention_candidates`
maps each C.2 type to `underline` / `bold` / `star`, and the FE parses the
field but no component renders from it. Reviving it as a pre-acceptance
treatment re-creates exactly what was ripped out.

**The two marks are not interchangeable.** `bold` is the *proposed*-accent
label; `{{orange:…}}` is the *accepted* accent, and it is the one accent
colour. A surface that paints bold at the moment of acceptance is showing the
pre-decision state as the result of the decision — which is what the FE's
optimistic apply did between 2026-08-15 (FE #311) and the fix in the same
day's follow-up. The optimistic paint must write **the token the server will
bake**, so the click and the refetch agree.

**The one thing that may paint before the server confirms** is the student's
own tap. Applying a style writes the accepted mark into the draft on the
click — the founder's *"I want it to happen right the moment you click"* — and
rolls it back if the write fails. That is not a proposal painting itself; it
is the decision rendering at the moment it is made.

---

## 6 · What `disregarded` buys

It is the only direct ground truth for Manager Engine precision that this
product will ever collect: *we proposed this, and the person it was for said
no.* `manager_engine.py` carries `PPV_FLOOR = 0.70` and `PPV_TARGET = 0.85` as
**assumptions** today. Decisions turn them into measurements, joined against
the `intervention_arms` rows already migrated in `0253`.

This is why R3 and R4 are not fussiness. A corpus with fabricated refusals in
it cannot be cleaned afterwards, and the fabricated ones are indistinguishable
from the real ones — the same argument that removed the acoustic needle from
the blind labeling card.

---

## 7 · State machine

```
record(scope) ── analysing ── REVIEW(≤3) ── ideal text
                                  │
                                  ├─ approve / disregard   (per intervention)
                                  ├─ lock part   → that part flips to accentuation
                                  ├─ unlock part → that part flips to composition
                                  └─ rehearse all → scope := whole text
```

`scope: { mode: 'chunk' | 'full', from_part_id }` is the only new state. The
existing lifecycle lock still holds: `analysing` blocks both recording and
opening the deliverable (shipped in frontend-cursor#251).

---

## 8 · Fences

* **AC-9** — nothing here surfaces a score. A layer is a phase, not a grade;
  neither `layer` nor `locked_at` is a number about the speaker.
* **LIVE LOOP** — every new user-facing string ("Approve", "Disregard", "Lock
  this part", "Rehearse all") needs founder sign-off before it ships.
* **L1** — accentuation must never rewrite. That is the whole layer boundary,
  and R1's filter is what enforces it mechanically rather than by convention.
* **L2** — locking does not touch ranking. When a later take beats a locked
  part, the LOCK WINS and nothing is surfaced: a lock is a user decision, and
  silently overriding it is the same class of error as the superseded prompt.

---

## 9 · Build order

**PR 1 — this spec.**

**PR 2 — Step 0, stable parts.** Ideal text moves from `text: string` to
`parts: [{id, ord, text}]`, joined text derived for read-only consumers. A
one-time backfill runs the existing `splitBadgeParagraphSpans` over stored
texts to mint ids once (founder confirmed 2026-08-07 that its boundaries are
the paragraph). `DocumentArranger` moves from `part-${i}` keys to ids — which
also fixes a latent React reconciliation bug in drag-reorder, independent of
locking. No behaviour change beyond identity.

**PR 3 — locking.** `locked_at`, `allowed_layer`, R1's filter, R3's gate, and
the FE controls.

Step 0 ships alone because it touches the F1 read path. Reviewing a structural
change to the deliverable *alongside* the interesting new logic is where
mistakes hide.

---

## 10 · What Step 0 actually shipped (2026-08-07)

Two divergences from §3.1 / §9, both forced by reading the serve path. Neither
changes the design; both change where a fact lives.

### 10.1 · The key is `(arc_id, user_id)`, not `arc_id`

§3.1 keys parts on `arc_id`. That is not enough to name a document.

**The served text is DERIVED per request, not stored.** It resolves from up to
four sources — the machine `auto_text`, the coach's `verified_text`, the
student's version-stamped edit in `user_arc_ideal_notes`, plus the fold /
sanitize / strip-moment transforms — so `arc_id` alone identifies an arc, not
the words on screen. `user_arc_ideal_notes` is keyed `(arc_id, user_id)` and is
the row the arranger already writes through, so parts key the same way. With
one owner per arc this is exactly §3.1's semantics; if an arc ever carries two,
parts cannot bleed between them.

**Deliberately NOT version-scoped.** The obvious third key column is the
ideal-text version, and it is wrong: a new take bumps the version, so
version-scoped parts would mint fresh ids on every take and discard every lock
the student had set. §8 says the opposite — when a later take beats a locked
part, the LOCK WINS. Parts outlive versions by construction.

### 10.2 · The backend never splits text; the client mints ids

§9 called for "a one-time backfill [that] runs the existing
`splitBadgeParagraphSpans` over stored texts to mint ids once". Building that
would have contradicted §2's own argument.

`splitBadgeParagraphSpans` is **marker-aware**: it refuses a split point inside
a rich-marker token, because a fold marker may legally contain a blank line and
slicing it leaks raw syntax. It is a stateful scanner, not a regex. A Python
mirror would be a SECOND definition of "paragraph" — a real distinction with no
single home, re-derived slightly differently by each consumer until they
disagree, which is the exact failure §2 names — and the two would drift on
precisely the documents where the split is hard.

So: **the client mints ids and sends them; the backend validates and stores.**
The split stays in one place, where the founder confirmed it lives.

Consequences, all of them acceptable:

* **No backfill.** A document nobody has opened has no parts — fine, because
  nothing can be locked on a document nobody has opened. Identity appears on
  first save, and the FE mints locally from first render either way, so the
  React key fix in §9 lands immediately and does not wait on a save.
* **Ids are validated as real UUIDs**, not accepted as strings. An unvalidated
  id would let a caller mint colliding ids across arcs, surfacing as one
  document's lock on another's paragraph.
* **`text` and `parts` are written together or not at all.** The write path
  refuses a payload whose parts do not join back to its text
  (`agrees_with_text`), and the read path refuses to SERVE parts that no longer
  join to the served text. Stale identity pointing at words that moved is the
  same failure as a mis-anchored tracked change (#219) — except a lock hung on
  it would silently guard the wrong paragraph.
* **`joined()` mirrors `joinSegments`.** That mapping IS mirrored, because it
  is a two-line rule (trim, drop blanks, join on a blank line) rather than a
  scanner. Both sides' tests pin it against the other's, so a drift fails CI
  instead of 400-ing every save in production.

### 10.3 · Reconciliation, which §3.1 did not specify

An id has to survive a rewrite that did NOT come through the arranger — a new
take assembling, a coach verifying. `reconcileParts` matches new paragraphs
against the previous list in **two passes**, and the order is the design:

1. **unique text on both sides → match wherever it moved to.** A paragraph
   appearing exactly once on each side can only be the same part, so this
   survives an arbitrary reorder.
2. **the repeats → first unused with equal text, in reading order.** Two
   identical paragraphs are textually indistinguishable; reading order is the
   only rule that is not a guess, and because the words are identical, which
   copy keeps which id is unobservable.

A single monotonic pass survives rewording but not reordering; a single free
pass survives reordering but lets a repeated paragraph steal an earlier one's
id. §3.1 requires both, so it needs both passes. Anything matching nothing is
genuinely new words and gets a new id — a paragraph the machine rewrote is not
the part the student locked.

### 10.4 · Deferred to PR 3, on purpose

`locked_at` is **not** in the 0255 migration. It lands with the code that reads
it, so the schema never claims a capability the system does not have — the same
distinction `dimension_registry` draws between "switched off by decision" and
"not built yet".

---

## 11 · Chunk grain re-spec: size cap, nested scroll, two-grain indicator (founder, 2026-08-14)

Field report (founder, 2026-08-14, first live decked run through the deck):
one slide's whole text arrived as a single chunk — it did not fit the screen,
could not be read as a unit, and could not be saved. That is not the chunk
model misbehaving; it is the chunk model doing exactly what the 2026-08-11
join fix told it to. `transcript_document` joins a contiguous slide run into
ONE `\n\n` paragraph (within a slide, `" "`; across slides, `"\n\n"`), so a
slide the speaker spent two minutes on is one paragraph, one part, one chunk,
one lock — a wall. The 2026-08-11 fix moved the grain from "whole talk = one
chunk" to "one chunk per slide"; this section moves it once more, and this
time the upper bound is READABILITY, not the slide.

**The founder's three requirements, verbatim in substance:**

1. **Size cap (backend).** Chunks are split at the document builder level.
   No chunk larger than ~4 rendered lines, borrowing the ~200-char logic
   from the deckless path.
2. **Nested scroll (frontend).** Scroll events progress through the chunks
   *within* the active slide first; only when the user reaches the final
   chunk of the current slide does the scroll bubble up and advance to the
   next slide.
3. **Visual indicator (UI).** The scroll track/icon shows macro-progress
   (which slide) AND micro-progress (position within the current slide's
   chunks).

### 11.1 · The size cap lives at the builder, and that is §10.2-legal

§10.2 says "the backend never splits text" — so name precisely why this is
not a contradiction, or someone will cite §10.2 to un-ship it. §10.2 bans a
SECOND definition of "paragraph": a Python mirror of
`splitBadgeParagraphSpans` run over text a user saved, drifting from the
client scanner on exactly the hard documents. The builder is not that. The
builder is the AUTHOR of `\n\n` in machine-assembled text — it decides where
paragraphs begin before the text is ever a document, in the run→paragraph
loop of `services/transcript_document.py` (PASS 2 over `_slide_runs`) and
the master-document assembly's equivalent join. Capping the paragraphs it
emits is the inverse of its own join, not a re-split of anyone's document.
One splitter per document still holds, and it is the same split the FE
chunker already names as the compliant path ("physically split long
paragraphs — one splitter, one identity", `deckChunks.ts` header). The FE
chunk model needs ZERO changes for the cap: a chunk IS a part IS a `\n\n`
paragraph, unchanged — the builder just emits more of them.

**Mechanism.** Within a slide run, consecutive pieces pack greedily into a
paragraph; when appending the next piece would cross the cap, close the
paragraph and open a new one **in the same slide run**. A slide boundary
still forces a break exactly as today. Piece boundaries are the ONLY legal
cut points: a cut between pieces changes a separator (`" "` becomes
`"\n\n"`) and never a word — L1 verbatim holds by construction, every
piece's provenance row stays exact, and no audio span moves.

**The constant has one home.** The cap is the piece cutter's own target —
`_DECKLESS_CHUNK_CHARS = 200` in `services/slide_word_split.py`, the number
already behind `chunk_words_by_chars` (deckless flat cut) and
`chunk_slide_words_by_chars` (decked, within-slide) — imported or pinned by
test, never a second literal. Two numbers named "chunk size" drifting apart
is the exact §2 failure. "~4 lines" is the founder's acceptance criterion
(≈200 chars ≈ 4 lines on the reference mobile viewport); characters are the
mechanism, because the backend cannot measure rendered lines.

**The cap is a target, not a guillotine.** The cutter prefers sentence ends
and may extend a piece up to `_SENTENCE_EXTENSION_CHARS` past target to
reach one, so a single piece can legally exceed 200 chars — and since a
piece is never cut, a one-piece paragraph inherits that. Correct: verbatim
beats the cap. The bound the builder guarantees is "never more than one
cap's worth of pieces PLUS the piece that crossed the line", which in
practice is the ~4-line read the founder asked for.

**Provenance is unchanged in rule, larger in count.** `paragraphs` stays one
row per emitted paragraph (§10's "one row per paragraph" alignment rule);
consecutive paragraphs now share a `slide_index`, which the deck's
`groupChunksBySlide` already folds into one slide section — the FE grouping
was built for exactly this shape and has simply never received it.

### 11.2 · Locks: the cap never re-cuts a locked part (ships WITH fix #5)

Finer paragraphs mean re-minted identity across the transition:
`reconcileParts` cannot match one giant old paragraph to its four new
fragments (no equal text on either pass), so the fragments get fresh ids.
On an OPEN part that is invisible — nothing hangs on the id. On a LOCKED
part it would detach the lock: the machine re-graining text out from under
a student's decision, which is the same failure class as the 2026-08-14
field report #5 (a locked chunk arriving unlocked with a recommendation on
it). So the rule is absolute: **the machine never re-cuts text under a
lock.** `compose_locked` already pins a locked part's text verbatim; the
cap applies to machine-authored regions only. A student who locked a
wall-of-text keeps the wall until they unlock it — their grain, their call.

This section and the lock-identity fix ship TOGETHER, first in the next
window (founder priority, 2026-08-14). Same seam — both are about which
paragraph keeps which id across a rebuild — and the tests that pin one are
the tests that pin the other.

### 11.3 · Nested scroll: the chunk is the step, the slide is the section

A scroll step advances one CHUNK. While the active slide has chunks below
the current one, scroll moves through them and the slide does NOT change;
only from the final chunk of the active slide does the next scroll step
bubble up and advance to the next slide (and symmetrically backwards from a
slide's first chunk). The two grains already exist in the deck's render
model (`DeckSlideGroup`: slide sections containing chunks in order) — this
binds the gesture to them instead of to the page.

### 11.4 · The indicator shows position on both grains — and stays position

The scroll track/icon shows which SLIDE the user is on (macro) and where
within that slide's chunks they are (micro). AC-9 note, so nobody
"improves" this later: the indicator is NAVIGATION — "slide 3, second of
four chunks" is a position, not a measurement. It must never be restyled
into a quality or progress read (a percentage, a completion score, a
per-chunk verdict); the moment it grades rather than locates, it crosses
AC-9 and dies at the fence.

### 11.5 · Lock feedback is immediate (founder, 2026-08-14)

When the user locks a chunk, the UI acknowledges the state change
IMMEDIATELY: the lock icon animates/updates, and the open modal itself
visually transitions into its Locked state. The user must see instant
confirmation that the system registered and applied the change — not a
silent close, not a state that only looks different after the next fetch.
The lock is an optimistic UI transition confirmed by the server, never a
spinner-then-maybe. (A failed server lock must roll the visual state back
and say so; showing a lock the server refused would be the inverse of
field report #5 — a lock the user believes in that does not exist.)

### 11.6 · Smart re-triggering: a locked chunk drops in interruption priority (founder, 2026-08-14)

Locking does not silence a chunk — the 2026-08-11 rule stands (pending
work beats the lock for *display*: new suggestions on a locked chunk are
announced and openable). What changes is the modal's AUTO-OPEN behaviour
on later takes. A locked chunk is a decision already made; the deck should
interrupt for it last:

* **A locked chunk's modal does not aggressively auto-open on subsequent
  takes.** It may auto-open only when the REST of the deck is settled —
  no open chunk is holding an undecided composition-lane (verbal
  correction) suggestion. Open text in flux always outranks revisiting a
  decision.
* **When it does re-open, it opens for accentuation — Styling or Delivery
  (the swap lane) —** the layers a locked part is actually in (§4).
* **A verbal correction on a locked chunk auto-opens ONLY when every
  other verbal correction in the deck is of lower urgency** — i.e. it is
  the top-ranked correction remaining under the served lane precedence
  (Corrections > Swap > Style, the `_collision_rank` ordering already
  wired into the sweep). A mid-pack correction on locked text waits its
  turn behind every correction on open text.

This is an INTERRUPTION policy, not a serving change: candidates are
generated, budgeted and precedence-sorted exactly as today; §11.6 only
governs which chunk's modal the deck opens in the user's face, and when.

---

## 12 · The three integrity rules (founder specs, 2026-08-14 — §12.1 pulled into build the same day; §12.2/§12.3 next)

Three defects from the 2026-08-14 field reports are data-integrity
failures, not polish. Each gets a named rule here so the fix has a spec to
build against and a fence to cite. Build order is founder-set: **lock
survivability (#5) first** — stable part identity is the foundation the
other two (and §11.1's re-grain) stand on.

### 12.1 · The Anchor Rule (field report #5 — lock loss). "Typed words are invincible."

A locked part is a HARD, IMMUTABLE ANCHOR during any alignment,
recomposition, or rebuild. The document builder and composer are strictly
forbidden from re-IDing, editing, or dropping a locked part; the machine
aligns new audio AROUND the locked text, never through it. Concretely:

* No pass may mint a fresh id for a paragraph whose part is locked —
  difflib/reconcile misalignment re-minting a locked part's identity is
  the defect, not an edge case (`reconcileParts`' "a paragraph the
  machine rewrote is not the part the student locked" applies to OPEN
  parts only; a locked part's words cannot have been rewritten, because
  rewriting them is forbidden one clause up).
* A rebuild that cannot place a locked part exactly (verbatim text,
  intact id) is a FAILED rebuild for that document: serve the previous
  composed state rather than a new one that lost a lock. Losing a lock
  silently is strictly worse than serving yesterday's text.
* The staleness guard (`agrees_with_text`) currently protects only the
  KPI fold; the same refusal belongs on every path that would SERVE or
  PERSIST a parts/text pair that no longer joins.

§11.2's builder rule ("the cap never re-cuts a locked part") is a special
case of this rule and ships under it.

### 12.2 · The Clean Serve Boundary (field report #3 — the all-orange save)

The backend serves document text 100% CLEAN of presentation markers.
Baking a paragraph-wide rich-marker (`{{orange:...}}`) into the raw
document text on save is the defect: it violates the no-paint ruling
(2026-08-11: "NOTHING paints the text"; the state lives in the chunk's
icon) and it corrupts the one string every span, part and lock is
anchored to — a marker baked into the text shifts every offset behind it.

* Data and presentation separate at the API boundary: the DOCUMENT is
  words; styling is metadata (spans/ids) the frontend applies dynamically
  — and an approved style renders ONLY where the user explicitly decided
  it, never as a whole-paragraph wash on save.
* The style lane keeps proposing accentuation as designed; what it may
  never do is write its rendering into the served text. A marker the
  backend must persist for its own bookkeeping stays in its own field,
  stripped before the document string leaves the API.

### 12.3 · The Intent Ledger (field report #4 — the phrase-drift bypass). "Never re-litigated."

The decisions ledger exists so a declined suggestion stays declined. It
currently keys on the normalized PHRASE, so the LLM bypasses it by
rewording: decline "try 'X'" on take 1, get "try 'X-prime'" on take 2 —
same intent, new words, served again. The ledger must key on INTENT, not
wording:

* **Key = (location, lane-class), not the phrase.** Location is the part
  (chunk) the suggestion targets — part id where identity exists,
  snippet/piece where it does not. Lane-class is the deterministic class
  the deck already names (the Clarity / Flow / Style / Delivery mapping,
  derived from backend-authored `source`/`kind`/`why` — one mapping, one
  home per side, pinned by contract test, per §2).
* Declining a Clarity suggestion on chunk A blocks EVERY future Clarity
  suggestion on chunk A for that arc, across takes, however the phrasing
  drifts. A re-serve of the same intent in new words is a ledger bypass,
  full stop.
* The phrase key does not disappear — it stays as the JOIN key for
  history display (`historyForChunk`); it just stops being the thing that
  decides whether the machine may ask again.
* Un-blocking is the user's: unlock/re-open of the chunk, or an explicit
  new-take decision surface, may clear the pair — the machine never
  clears it for itself.

### 11.7 · Session backlog (founder, 2026-08-14, post-build field notes — NOT built)

Three amendments logged for the next window, refining §11.5/§11.3/§11.4:

1. **Lock-in closes the modal and the chunk wears the lock.** On a
   successful lock-in the modal CLOSES (or at minimum transitions to a
   distinct Locked state — never keeps showing the just-locked text as if
   still editable), and the chunk on the page shows its locked lock
   immediately. Sharpens §11.5: the confirmation is the closed modal plus
   the locked icon on that chunk, not a state inside an open modal.

2. **A screen is the slide's display unit, and it has its own cap.** The
   per-slide text visible at once must fit ONE screen view: ~9 lines max,
   and those lines arrive as ~3 paragraphs (9 lines → 3 paragraphs,
   6 → 2 — i.e. the §11.1 ~4-line chunk grain, roughly three chunks to a
   screen). The builder's chunk cap (§11.1) already makes the paragraphs;
   this adds the SCREEN grain above them.

3. **A slide longer than one screen CONTINUES on the next screen, and
   the scroll says so.** Overflow chunks of the same slide form a second
   (third, …) screen in the nested scroll — same slide, continued — and
   the indicator (§11.4) makes the continuation visible: the reader can
   see the slide spans multiple screens and where they stand in it.
   Extends the two-grain rail with the screen grain: slide → screen →
   chunk, all position, never a grade (AC-9).
