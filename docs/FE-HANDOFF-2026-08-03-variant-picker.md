# FE handoff — the block variant PICKER, revisions & restore (2026-08-03)

**From:** Backend
**Backend state:** merged to `main` (#314), deployed; migration
`add_ideal_text_variant_pool.sql` called out to run
**Flag:** `BLOCK_VARIANTS_ENABLED` — **default OFF**; the founder flips it
when this FE ships. Until then every endpoint below is a plain 404 and no
affordance should render.

```
FILTER: ADVANCE-F1 — cat {F1-SUPPORT} — named in-flight task: the picker FE
        that unblocks BLOCK_VARIANTS_ENABLED — fences {AC-9 rules in §6 are
        load-bearing; ALL copy in §7 is placeholder pending founder sign-off}
```

---

## 1. Why this exists (build the right thing)

Three user fears, each fatal on its own (founder 2026-08-03):

1. *"After I correct my take and record the next one, the previous one is
   lost."*
2. *"I correct the text and record it, and the next text is worse than the
   previous one."*
3. *"I have some things I would want from the previous text and some from
   the new, but no way to put them together."*

The backend now keeps an **append-only pool** of every text each block has
ever had — every take's version of that block (verbatim, take-badged) plus
the student's own edits — and records "my text" as a **composition**: an
ordered list of pointers, one per block, with append-only revisions and a
head. Nothing is ever overwritten. Your job: let the student *see* the pool
per block, *pick* freely (fear 3), and *go back* (fear 2). Fear 1 is already
dead on the backend; the picker is what makes that visible.

**Granularity is BLOCK-LEVEL by founder decision.** No sentence-level mixing
in v1 — the mobile picker stays clean. Do not build piece-level expansion.

## 2. The mental model (three nouns)

* **Variant** — one candidate text for one block. `source: "take"` (verbatim
  recorded speech, badged with its take) or `"user_edit"` (the student's own
  restructuring). Append-only; a new take adds, never replaces.
* **Composition** — the selection: `{block_key → variant}` in block order.
  Every accept / pick / restore appends a revision.
* **Head** — the one live revision. Restore = repoint head (+ write-through).

## 3. Feature detection & gating

`GET /v2/explore/arc/<arc_id>/blocks/variants` → **404 means the feature is
off** (flag down, or the arc predates the master model). Treat 404 as "render
nothing new"; never show an error for it. Everything in this handoff is
additive — no existing surface changes shape when the flag is off.

## 4. Endpoints

All under the existing `/v2` blueprint, all `require_auth`, all owner-scoped
(non-owner → the same 404 as not-found; never distinguishable).

### 4.1 The picker read

`GET /v2/explore/arc/<arc_id>/blocks/variants`

```jsonc
// 200
{
  "arc_id": "…",
  "head_revision": 4,             // int | null (null = pre-migration arc)
  "blocks": [
    {
      "block_key": 10,            // stable int, gaps by design (0,10,20…)
      "label": "Core Message",    // string | null — render when present
      "take_index": 2,            // the CURRENT incumbent's badge (int|null)
      "variants": [
        {
          "variant_id": "6f2c…",  // string | null — see the null rule below
          "source": "take",       // "take" | "user_edit"
          "take_index": 1,        // int | null (null for user_edit)
          "text": "…the block's full text…",
          "is_current": false
        },
        { "variant_id": "9a01…", "source": "take", "take_index": 2,
          "text": "…", "is_current": true },
        { "variant_id": "c377…", "source": "user_edit", "take_index": null,
          "text": "…", "is_current": false }
      ]
    }
  ]
}
```

* **Order is chronological, not ranked** — take variants by take order, then
  the student's latest edit last. §6 makes this a fence, not a style note.
* **At most one `user_edit` entry per block** (the latest). Older edits stay
  restorable through revisions; they are deliberately not in the picker.
* **`variant_id: null`** — a pre-pool incumbent (arc older than the
  migration). It IS the current text: render it, flag it current,
  **never make it tappable-to-select** (there is nothing to select — it is
  already live; the entry exists so the list is never missing its own
  current state). These disappear naturally as the arc gets new activity.
* `500 {"code":"V2_ERROR"}` — read failure; show the existing retry
  affordance, never an empty picker (an empty picker lies).

### 4.2 Select (mix & match — fear 3)

`POST /v2/explore/arc/<arc_id>/blocks/<block_key>/select`
Body: `{"variant_id": "9a01…"}`

| Status | Code | Meaning / FE action |
|---|---|---|
| 200 | `{"saved": true}` | The block flipped. Refetch — see §5. |
| 400 | `INVALID_INPUT` | Missing `variant_id`. FE bug; don't surface. |
| 404 | `NOT_FOUND` | Flag off / not owner / block or variant gone. Refetch the picker. |
| 409 | `NOT_PENDING` | Candidate block (not yet accepted into the document). Unreachable through this payload — candidates are excluded from §4.1; handle by refetching. |
| 500 | `V2_ERROR` | Retry affordance. |

* **Idempotent**: selecting the already-current variant is a 200 no-op.
* **Non-destructive, always**: the displaced text goes back to the pool
  (backend heals it in before repointing) — build the UI with zero
  confirmation-of-loss language; there is no loss to confirm.
* **Silent by design**: select does **not** fire the version-ready bubble
  (the student did it themselves, in place). Update from the refetch; do not
  wait for a notification.
* Selecting clears any pending upgrade offer **on that block** (the offer
  was judged against the text the student just replaced). The refetched
  `changes` lane will reflect it.

### 4.3 The timeline (fear 2, read side)

`GET /v2/explore/arc/<arc_id>/ideal-text/revisions`

```jsonc
// 200 — newest first, max 50
{
  "arc_id": "…",
  "head_revision": 4,
  "revisions": [
    { "revision": 4, "reason": "select",  "created_at": "…", "is_head": true },
    { "revision": 3, "reason": "restore", "created_at": "…", "is_head": false },
    { "revision": 2, "reason": "accept",  "created_at": "…", "is_head": false },
    { "revision": 1, "reason": "seed",    "created_at": "…", "is_head": false }
  ]
}
```

`reason` is a closed enum: `seed | accept | select | restore`. Render it as
qualitative history copy (§7), never as the raw token. An empty list is a
real state (pre-migration arc): hide the timeline entirely.

### 4.4 Restore (fear 2, write side)

`POST /v2/explore/arc/<arc_id>/ideal-text/revisions/<revision>/restore`

* `200 {"restored": true, "head_revision": 5}` — note the head is a **new**
  revision (restore is itself history; it is undoable). Refetch per §5.
* `404 NOT_FOUND` — flag off / not owner / revision unknown.
* Semantics to convey in UX: restore **repoints what that revision
  recorded**. Blocks added to the document *after* that revision stay as
  they are — restore never deletes. Do not present it as "delete everything
  since"; present it as "bring back that version's choices" (§7 copy).

## 5. After every successful write: refetch, in this order

1. The student ideal-text GET (the document text changed; `version` may have
   bumped — the reassembly runs synchronously inside the POST).
2. `blocks/variants` (`is_current` moved; a healed variant may have appeared).
3. `ideal-text/revisions` if the timeline is on screen.

The existing `user-edit` PUT contract is **unchanged** (same
`VERSION_SUPERSEDED` 409 flow you already handle). What changed underneath:
a saved edit now also lands block-level in the pool, so after a PUT the
picker may grow a `user_edit` entry — refetch `blocks/variants` after a
successful PUT too.

## 6. AC-9 fences — load-bearing, not style

These are product fences (see CLAUDE.md); a breach blocks merge.

* **No numbers as judgment.** `take_index` renders as the existing
  provenance badge (the 1.0 / 2.0 convention already on block fragments) —
  never as a score, rank, count of "improvements", or percentage.
* **Chronological ≠ ranked.** Never present variant order as quality order.
  No "best", no sorting toggles by quality, no stars on variants.
* **No better/worse copy anywhere in the picker.** The comparative lane
  (`why_key`: energy/steadiness/coverage/overall) exists ONLY in the offer
  (`changes`, `source: "new_take"`) UI and stays there.
* **The picker is neutral; the offer is the recommendation.** Keep the two
  visually distinct: offers push ("this take beat this block" — existing
  badge flow), the picker pulls (the student browses and chooses). Merging
  them into one ranked list is the exact fence breach to avoid.
* `head_revision` / `revision` are plumbing — fine to *use*, do not
  *feature* them as progress numbers.

## 7. Copy — ALL PLACEHOLDER, founder sign-off required before ship

| Surface | Placeholder (EN) |
|---|---|
| Picker entry (per block) | "Versions" |
| Variant badge, take | "Take 1" / "Take 2" (or the existing 1.0/2.0 badge) |
| Variant badge, user edit | "My edit" |
| Current marker | "Current" |
| Select confirm (if any) | "Use this version" |
| Timeline entry, `seed` | "First assembled" |
| Timeline entry, `accept` | "Suggestion accepted" |
| Timeline entry, `select` | "You chose a version" |
| Timeline entry, `restore` | "Restored an earlier version" |
| Restore action | "Bring back these choices" |
| Restore reassurance | "Nothing is deleted — you can return to any version." |

Per the standing constraint, none of this ships without founder sign-off;
treat the table as intent, not final strings.

## 8. Suggested UX shape (FE owns the final call)

Phone-first (this user presents from their phone). The shape we had in mind:

1. **Per-block picker**: the block's take badge is the entry point → bottom
   sheet listing §4.1's variants, current highlighted, full text readable
   (block texts can be long — the sheet scrolls), tap → select → sheet
   closes → document updates in place.
2. **Timeline**: an overflow/history entry on the notebook → §4.3 list →
   tapping a revision offers §4.4 restore with the reassurance line.
3. **Show the picker affordance only when there is a choice** — a block
   whose list is a single entry (just the current) gets no affordance.

## 9. Edges you must handle

| Case | Behavior |
|---|---|
| 404 on §4.1 | Feature off — render nothing new, no error. |
| `variant_id: null` entry | Display-only current; not selectable. |
| Single-variant block | No picker affordance (§8.3). |
| Select 404 after a fresh GET | Pool changed under you (rare) — refetch the picker, no error toast. |
| New take completes while the picker is open | The list is stale but every id in it stays valid (append-only) — select still works; refetch on sheet re-open rather than live-updating. |
| `is_saved` (save-and-freeze) | Unchanged semantics; a select after a save un-saves exactly like an accepted offer does today (new pending state / version moved). Reuse the existing badge-hiding rules against the refetched state. |
| Guest / unauthenticated | Same as today — these routes never render for guests. |

## 10. QA checklist before flag flip

- [ ] Flag off (staging default): zero visual change anywhere.
- [ ] Pick an older take's block → document text swaps only that block;
      badge updates; revision appears; offer badge on that block (if any)
      clears.
- [ ] Pick "My edit" → same, badge shows the edit provenance, no take badge.
- [ ] Restore revision 1 → early choices return; blocks added since remain;
      a NEW head revision exists; restore of the restore works.
- [ ] Save → picker still opens; selecting after save un-saves per today's
      rules.
- [ ] Airplane-mode select → retry affordance, no half-applied UI state.
- [ ] AC-9 sweep: no numeric scores/ranks anywhere in the new surfaces;
      variant order presented as time, not quality.

## 11. Rollout

FE ships dark → founder runs the migration (if not already run) → founder
flips `BLOCK_VARIANTS_ENABLED=1` → §10 sweep on prod → live. Backend needs
nothing further from FE for this; questions → BE thread as usual.
