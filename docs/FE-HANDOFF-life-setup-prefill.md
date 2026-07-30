# FE handoff — the setup wizard fills itself from an uploaded document

**Pair:** [PROMPT-life-panel.md](PROMPT-life-panel.md) · [PROMPT-FE-life-panel.md](PROMPT-FE-life-panel.md)
**Date:** 2026-07-30 · **Status:** backend shipped, FE not started
**Founder ask:** *"like a CV you upload and all the forms are filled — create the
goals from the document for each section of the principles onboarding."*

Item 9 already let the user upload their current strategy document and get a flat,
tickable list of drafted rows. This is the rest of it: the same reading, **bucketed
into the wizard's own steps**, so the Weekly step opens with the weekly goals already
in it instead of empty next to a list the user has to re-sort by hand.

---

## The one new call

```
POST /v2/life/setup/prefill-from-document
{ "document_id": null,      // optional — defaults to the newest processed upload
  "save": false }           // optional — see "Saving", below
```

`200` →

```jsonc
{
  "document": { "id": "…", "file_name": "strategy.docx", "status": "processed",
                "char_count": 8123, "created_at": "…" },

  "sections": {                       // ALWAYS all eight keys, in wizard order
    "daily":       [ /* rows */ ],
    "weekly":      [ { "kind": "goal",
                       "title": "Three deep-work blocks",
                       "body": "",
                       "horizon": null,          // the life_items horizon, may be null
                       "due_label": "[Aug]",     // the user's own notation, verbatim
                       "due_at": "2026-08-01",   // parsed only where unambiguous
                       "bet": "company",         // life | company | dream | null
                       "section": "weekly",
                       "external_id": "goal:…",
                       "order_key": 1000.0,
                       "source": "document",     // ← N5: this row is the model's
                       "confirmed": false } ],
    "monthly": [], "quarterly": [], "yearly": [],
    "five_year": [], "ten_year": [], "twenty_year": []
  },

  "unplaced":      [ /* same row shape, section: null */ ],
  "habits":        [ /* kind: "habit" */ ],
  "distractions":  [ /* kind: "distraction"; body IS the environmental response */ ],
  "bets":          [ /* the three, at their locked rank in order_key */ ],

  "counts": { "goals": 12, "placed": 10, "unplaced": 2,
              "habits": 3, "distractions": 1 },
  "setup_sections": ["daily", "weekly", "monthly", "quarterly",
                     "yearly", "five_year", "ten_year", "twenty_year"],
  "saved": false,
  "merged": { "added": {}, "skipped": [] },
  "written": false
}
```

`400 NO_DOCUMENT` when there is no readable upload to draft from (nothing uploaded
yet, or the extraction failed) — show the upload step, not an error toast.

`GET /v2/life/setup` now also returns `setup_sections`, so the step→key mapping comes
from the server rather than a second list on the client that drifts.

---

## How to wire it

1. **Upload step** — unchanged: `POST /v2/life/setup/document` (multipart `file`,
   `.pdf` / `.docx` / `.txt` / `.md`, ≤15 MB).
2. Right after a successful upload, call **prefill-from-document** once and keep the
   payload in form state.
3. Each goal step renders `sections[<its key>]` **already in the list**, above the
   `+ Add a goal` button. The user edits, deletes, adds, and taps Next exactly as
   today — `PUT /v2/life/setup` on every step is unchanged.
4. Show `unplaced` on the **first** goal step (or wherever it reads best) under its
   own heading: these are goals the document did not file under a horizon, and they
   must be visible somewhere or they are lost. One tap should move one into a step.
5. `POST /v2/life/setup/complete` at the end, unchanged.

**Nothing about the existing flow breaks.** `/setup/propose-from-document` (the flat
review list) still works and is untouched — use whichever fits the screen. Both share
one extraction, so calling only the one you render costs one model call, not two.

### Saving

`save: false` (the default) writes **nothing**: the payload is form state and the
user's own Next saves each step.

`save: true` merges the drafted rows into the saved setup answers, so the prefill
survives closing the wizard — which is what the step's own copy ("Saved. You can
close this and come back to it.") already promises. The merge is non-destructive:

- a step the user already answered **keeps what they typed**; drafted rows are
  appended after it, never in place of it;
- a goal whose title is already in the step is not added twice, so re-running the
  prefill converges instead of accumulating;
- a step whose saved value cannot be appended to (it holds a string, say) is left
  **exactly** as it is and named in `merged.skipped`;
- `_step` and every other key you own are carried through untouched.

`merged.added` is `{ "<section>": <how many rows were added> }` — use it if you want
to say "12 goals from your document" after the upload.

The shape written for a step that had no saved answer is `{"goals": [...]}`; a step
already saved as a bare list stays a bare list. If your wizard stores a step under a
different shape, tell the backend and we widen `merge_prefill_answers` — do not
work around it by re-writing the slot on the client.

---

## The rules this has to respect on your side

| | |
|---|---|
| **N5 — nothing appears already accepted** | Every prefilled row carries `source: "document"` and `confirmed: false`. A prefilled goal must be **visually distinct** from one the user typed (a badge, a tint — your call) until they keep or edit it. This is the one non-negotiable in the list. |
| **No scores** | The payload has none, and `counts` is a count of rows, not a rating. Do not render it as progress, completeness, or a percentage (AC-9). |
| **Copy is founder-signed** | The response carries **keys only**, deliberately. Section labels ("Weekly", …) stay yours; any new user-facing string on this screen needs founder sign-off. |
| **The bets are locked** | `bets` comes back at rank 1 The Life · 2 The Company · 3 The Dream (L-2a). The document may word a bet; it can never reorder them, and neither can the client. |
| **The unplaced are not decoration** | `unplaced` is goals the user actually wrote. Dropping them silently is the one failure this feature cannot afford. |

## What the backend does *not* do

- It does **not** create `life_items` rows. A prefilled row becomes a real item only
  through `POST /v2/life/setup/apply-proposed` with exactly the rows the user ticked,
  or through the ordinary `/setup/complete` path. The rows here are already in the
  shape `apply-proposed` accepts — send them back unchanged.
- It does **not** invent goals. The extraction prompt is a transcriber: "never
  invent, never complete, never add an ambition they did not state." If a step comes
  back empty, the document said nothing for that horizon.
- It does **not** guess a step. A goal is placed by what the document filed it under,
  then by its horizon, and otherwise goes to `unplaced`. A "[NOW]" goal is unplaced on
  purpose — daily vs weekly is exactly what the document did not say.

## No migration

Uses `life_setup` and `life_setup_documents` as they are. `add_life_setup_documents.sql`
still needs to have been run (item 9) for the upload step to work at all.
