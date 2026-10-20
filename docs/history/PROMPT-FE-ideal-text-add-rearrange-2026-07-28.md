# PROMPT — FE: add & rearrange text in the ideal-text area while recording (T1 · 1.2)

**For:** the frontend agent/dev. Self-contained — everything you need is in
this file. The BE contract below is live and test-locked today; the ONE
pending BE addition (`prior_edit`) is marked and must be feature-detected.

## What you are building

On the ideal-text screen (the purple bubble, SD flow), during a recording
session:

1. **Add text with a single click** — tap between/after segments → inline
   input → the text appears in the document immediately.
2. **Rearrange segments** — drag a sentence/paragraph to a new position.
3. **Real-time updates** — the edited document renders instantly, persists
   across reloads, and shows on every surface that serves the ideal text.

Segmentation is **presentational**: split the served `text` client-side
(sentence or paragraph granularity — your call). The backend stores plain
text; after any add/rearrange you save the **whole joined document**, not a
delta.

## API contract (live today)

### Read — `GET /api/explore/arc/<arc_id>/ideal-text` (BFF → `/v2/...`)
Fields used here: `text` (the served document — the user's edit when one is
live, else machine/coach text), `version` (int — echo it on every save),
`user_edited` (bool), `can_record_take` (gate for the "record another take"
button — independent of edit state), `take_count`, `key_moments`.

**Pending BE (feature-detect, do not block on it):** `prior_edit:
{text, version}` — present only when a previous edit was superseded by a
newer version. If present, offer one-click "re-apply"; if absent, fall back
to your local edit buffer.

### Write — `PUT /api/explore/arc/<arc_id>/ideal-text/user-edit`
```jsonc
Body: { "text": "<FULL resulting document>", "version": <int from the GET>,
        "reapplied": true }   // reapplied ONLY on a re-apply action (pending BE; harmless today)
200 { "saved": true, "version": N }
400 INVALID_INPUT            // >20000 chars, bad version — surface cleanly, keep local content
404 NOT_FOUND
409 NOTHING_TO_EDIT          // nothing assembled yet — hide the affordance
409 VERSION_SUPERSEDED { "current_version": M }   // see flow step 6
500 V2_ERROR
```
Debounce or save-on-blur — your call. Last write wins. HTML is stripped
server-side.

## The while-recording flow

1. Take N completes → `GET` → render `text` @ `version N` as segments.
2. User adds / rearranges → update locally (instant) → `PUT {text, version: N}`.
3. `200` → the edit is now the served document everywhere (`user_edited: true`).
4. "Record another take" stays available the whole time (`can_record_take`).
5. Take N+1 uploads (`continue_arc_id`, as today) → version bumps server-side.
6. Any in-flight save against version N returns **409 VERSION_SUPERSEDED** →
   refetch, re-render the NEW `text`, and **re-offer the user's pending
   changes on top** (local buffer; `prior_edit` when shipped). Never silently
   drop typing; never silently overwrite the new version.

## Honest persistence semantics — phrase the UX from this table

| The user… | Shows now | Survives reload | Carries into the NEXT version |
|---|---|---|---|
| Rewords existing text | ✅ | ✅ | ✅ (baked server-side) |
| Adds new text | ✅ | ✅ | ❌ — re-offered for one-click re-apply, never silently kept |
| Rearranges segments | ✅ | ✅ | ⚠️ partial — treat like "add": re-offer |
| Deletes text | ✅ | ✅ | ✅ |

Do NOT promise "your additions become part of the next version" anywhere —
that behavior is a parked founder decision (2026-07-28). The re-offer is the
designed affordance.

## Fences (must hold)

- **No AI "improve/rewrite" affordance on this surface** — the document is
  the speaker's own words; machine changes arrive only as stars/tracked
  changes (L1).
- **While `user_edited` is true, stars/moments do not decorate the text**
  (server behavior). Do not re-anchor stars client-side into an edited
  document; they return when the next take supersedes the edit.
- **Never block or gate recording on edit state** — editing is an overlay on
  the record loop, not a step in it.
- **All user-visible copy in this feature is placeholder pending founder
  sign-off.** Build the interactions; hold the strings behind your copy
  constants.
- No scores/numbers anywhere on this surface (AC-9) — `version` renders only
  as the existing "<take_count>.0" badge convention, nothing new.

## QA checklist

- [ ] Add → instant render → PUT 200 → hard reload → still shown, `user_edited: true`.
- [ ] Drag-rearrange → same.
- [ ] Edit while a take is processing → 409 → refetch → pending changes re-offered; nothing lost, nothing clobbered.
- [ ] Next take → fresh machine text; reworded phrases persist in it; additions offered for re-apply (buffer or `prior_edit`).
- [ ] `reapplied: true` sent only on the re-apply action.
- [ ] >20000-char paste → clean error, local content preserved.
- [ ] Stars hidden while edited, back after the next take. Recording affordances never blocked.
