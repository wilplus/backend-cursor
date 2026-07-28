# BE → FE handoff — add & rearrange text in the ideal-text area while recording (T1 · 1.2)

**Status:** ready to build, 2026-07-26. **Backend changes required: NONE** — the
entire feature rides two endpoints that already exist and are test-locked.
**Filter stamp:** `FILTER: JUSTIFIED-SCAFFOLDING (founder-directed) — cat scaffold —
fences clear — locks clear (uses the BE-2 user-edit lane; canonical untouched) —
redirect: n/a`.

## What you are building

On the ideal-text screen (the purple bubble), while the user is in a recording
session:

1. **Add text with a single click** — tap between/after segments → type → it
   appears in the document immediately.
2. **Rearrange segments** — drag a sentence/paragraph to a new position.
3. **Real-time updates** — the edited document is what the user sees on this
   and every other surface, instantly and across reloads.

All three are FE interactions over ONE write endpoint. Segmentation for
drag-and-drop is **presentational** — split the served `text` client-side
(sentence or paragraph level, your call); the backend stores plain text.

## The contract (both endpoints live, owner-gated, test-locked)

### Read — `GET /v2/explore/arc/<arc_id>/ideal-text`
Fields you need here (others unchanged): `text` (the served document — the
user's edit when one is live, else machine/coach text), `version` (int — you
MUST echo this on every save), `user_edited` (bool — true when the served text
is the student's own edit of the current version), `can_record_take` (the
record-another-take affordance — independent of edits), `take_count`,
`key_moments`.

### Write — `PUT /v2/explore/arc/<arc_id>/ideal-text/user-edit`
Handler: `v2_explore_put_ideal_user_edit` (`routes/v2_routes.py`).

```jsonc
Body: { "text": "<the FULL resulting document>", "version": <int from the GET> }
200 { "saved": true, "arc_id": "...", "version": N }
400 INVALID_INPUT            // text missing / version not a positive int / >20000 chars
404 NOT_FOUND                // not the caller's arc
409 NOTHING_TO_EDIT          // no ideal text assembled yet
409 VERSION_SUPERSEDED { "current_version": M }   // a new take assembled while editing
500 V2_ERROR
```

Save the **whole document** (after your local add/rearrange), not a delta.
Last write wins per (arc, user). HTML tags are stripped server-side.

## The while-recording loop (the flow to build)

1. User finishes take N → `GET` → render `text` @ `version: N`, split into
   segments.
2. User clicks-to-add or drags-to-rearrange → update locally (instant),
   `PUT {text, version: N}` (debounced or on blur — your call).
3. `200` → done. The GET now serves the edit everywhere (`user_edited: true`).
4. User records take N+1 (`can_record_take` is true regardless of edit state;
   upload with `continue_arc_id` as today).
5. Take N+1 assembles → version bumps to N+1. Two things happen server-side:
   * **word-level replacements** in the edit are decomposed onto the decision
     ledger (`source='user_edit'`, approved) and **baked forward** into
     version N+1 — the student's wording is never reversed by a new take;
   * the wholesale edit itself is **retained but no longer displayed**
     (BE-2 pinned default) — the fresh machine text shows.
6. Any in-flight `PUT` carrying `version: N` now gets **`409
   VERSION_SUPERSEDED`** → refetch, re-render from the new `text`, and
   re-offer the user's pending local changes on top. **Keep your local edit
   buffer** for exactly this re-offer — the stale server copy is not served
   back on the student GET.

## Honest semantics — what persists when (say this in UX, don't oversell)

| The user… | Shows now | Survives reload | Carries into the NEXT version |
|---|---|---|---|
| **Rewords** existing text | ✅ | ✅ | ✅ baked via the ledger |
| **Adds** new text | ✅ | ✅ | ❌ pure insertions don't decompose ("no phrase to key on") — retained as signal, not re-grafted |
| **Rearranges** segments | ✅ | ✅ | ⚠️ partially: difflib reads a move as delete+insert, so the delete side bakes and the move doesn't re-anchor; a heavy rearrange falls below the similarity floor and simply stays the wholesale (superseded-from-display) edit |
| **Deletes** text | ✅ | ✅ | ✅ bakes as an approved deletion |

Mechanics: `services/protected_phrases.py` — `decompose_user_edit` /
`record_user_edit_decisions`. Locked by `test_user_ideal_edit.py`
(`LedgerInheritanceTests`, `StudentGetDisplayPriorityTests`, `UserEditPutTests`).

## Rules the FE must respect (fences)

* **While `user_edited` is true, stars/moments do not decorate the text** —
  the edit wins wholesale and the anchor fold is skipped (existing behavior).
  They return when the next take supersedes the edit. Don't try to re-anchor
  stars into an edited document client-side.
* **Never present an AI "improve/rewrite" affordance in this surface** (L1 —
  the document is the speaker's own words; machine changes arrive only as
  approvable stars/tracked changes).
* **The canonical machine/coach document is never written by this feature** —
  the edit is a separate lane. Nothing you send can or should mutate
  `auto_text`/coach text or master-document blocks.
* **All user-visible copy is placeholder until founder sign-off** (LIVE
  LOOP). Ship the interactions; hold the strings.
* The coach panel already sees the student's edit (keyed on the owner) — no
  FE work needed there.

## Optional follow-up (ask BE if wanted — not built)

Server-side re-offer of a superseded edit (e.g. `prior_edit: {text, version}`
on the GET when a stale edit exists) would let "re-apply your additions"
survive a device switch mid-session. Small additive change; ask and we'll
ship it. Until then the local buffer covers the flow.

## QA checklist

- [ ] Add → instant local render → PUT 200 → hard reload → edit still shown, `user_edited: true`.
- [ ] Rearrange → same.
- [ ] Edit while a take is processing → PUT returns 409 VERSION_SUPERSEDED → FE refetches + re-offers pending changes (no lost typing, no silent overwrite).
- [ ] Record next take → fresh machine text shows; reworded phrases from the edit appear in it; `user_edited: false`.
- [ ] >20000-char paste → clean 400 surfaced, local content preserved.
- [ ] Stars hidden while edited; visible again after the next take.
