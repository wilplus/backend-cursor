# SPEC — Parts, Locking, and the Two Intervention Layers

**Status:** design agreed (founder, 2026-08-07). Nothing here is built yet.
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
