# BE → FE handoff — slide linkage on the ideal-text GET (answers FE PR #222)

**Status:** SHIPPED — merged to `main` 2026-08-03 (PR #313, squash `3904d16`).
No migration, no flag: live on the next BE deploy, nothing else to run. No FE
deploy needed — your feature-detection picks both fields up the moment the BE
ships. **Filter stamp:** `ADVANCE-F1-SURFACE — cat {F1-SURFACE} — fences
{clear: no scores (AC-9), no construct exposure} — locks {clear: text stays
verbatim-selected (L1), ranking untouched (L2)}`.

## What's on the wire now

`GET /v2/explore/arc/<arc_id>/ideal-text` (the SD payload, both
`status: unverified` and `verified`) gained two additive fields:

```jsonc
{
  "status": "unverified",
  "text": "First slide's words.\n\nSecond slide's words.",
  "version": 3,
  "presentation_ref": "https://…/willab_presentations/abc.pdf",  // or null
  "pieces": [
    { "piece_key": 0, "text": "First slide's words.",  "slide_index": 0,
      "snippet_id": "s1", "take_session_id": "t1", "take_index": 1,
      "status": "settled", "challenger": null },
    { "piece_key": 1, "text": "Second slide's words.", "slide_index": 1,
      "snippet_id": "s2", "take_session_id": "t2", "take_index": 2,
      "status": "settled", "challenger": null }
  ]
}
```

**One correction to your handoff's assumptions, worth knowing:** `pieces[]`
was described in earlier contract docs but had never actually been served —
your explicit-mapping path could never have fired before this. It exists now,
whole-array additive. (Also: the coach ideal-text GET does not echo
`presentation_ref` today — the canonical value lives in the best-presentation
resolution, and this field carries exactly that.)

## `presentation_ref` — semantics

* The FIRST non-null `intake_context.presentation_ref` across the arc's
  **spoken takes in take order** — the same never-clobbered resolution
  `build_best_presentation` uses for its canonical deck ref. A later retake
  recorded without the deck does NOT null it; paired re-reads never resolve it.
* Deckless arc → `null` (we serve the key with `null`, never `""`).
* Your resolution chain: step 1 (this field) now fires; keep your
  localStorage + `/best-presentation` fallbacks for sessions pinned to a
  pre-#313 BE, then delete them at leisure.

## `pieces[]` — semantics

One entry per `"\n\n"`-paragraph of the **exact served `text`** (after every
server-side fold/sanitize pass — what you split is what we indexed).
`piece_key` is the paragraph ordinal. `pieces` is `[]` when `text` is empty.

* **`slide_index` is all-or-nothing per payload.** It attaches only when the
  machine assembly's piece list aligns 1:1 with the served paragraphs — the
  same provability bar you apply. When anything is unprovable, EVERY entry's
  `slide_index` is `null` (never a mixed payload), so your "any piece lacks it
  → exact-count zip" fallback always triggers as a whole.
* `slide_index` is an int ≥ 0 or `null` — never a string, never negative, and
  never attached on a deckless arc (the deckless compose keys picks by
  SECTION, which is not a deck page).
* Intentionally `null` (your fallback chain is the design, not a bug): user
  edit or coach restructure reshaped the paragraph count; the compose cache is
  absent/stale (we NEVER run the composer — or its LLM pass — on this GET);
  master-document/living-transcript texts, whose single-paragraph join can't
  map paragraph-wise (a single-block master doc still attaches).
* We serve the segmentation's bucket verbatim and do not know the PDF's true
  page count — your out-of-range → hide-all check remains the authority, as
  designed.
* Provenance riders, safe to ignore: `snippet_id` / `take_session_id`
  (strings or null), `take_index` (int or null), `status`
  (`"settled" | "pending_upgrade"`), `challenger` (the offering take's number,
  or null). No scores ride this payload (AC-9).

## Unchanged, on purpose

* Every pre-existing field on this GET is byte-identical; older FE builds
  ignore the additions.
* The historical `?version=N` payload does NOT carry the new fields.
* The coach lane, `/best-presentation`, and the recording POST readout are
  untouched.

## Contract locks

`test_ideal_text_slide_linkage.py` (10 tests): deck resolution (incl.
deckless-retake never clobbers; reads never resolve), aligned attach,
misaligned degrade-to-null, composer-never-runs guard, deckless gating,
master-block provenance (incl. honest `pending_upgrade`).

## QA checklist (against a deployed BE)

- [ ] Decked arc, machine text → `presentation_ref` set, every piece carries
      `slide_index`, slides interleave exactly.
- [ ] Same arc after an in-place user edit that merges two paragraphs →
      all `slide_index` null → your zip/hide fallback, no mis-attached slide.
- [ ] Deckless arc → `presentation_ref: null`, text-only view, no regression.
- [ ] Retake recorded without the deck → deck still resolves (no clobber).
- [ ] Old FE build against new BE → renders exactly as before (fields ignored).
