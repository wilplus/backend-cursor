# BE prompt — the 2026-07-27 backlog wave

> **STATUS 2026-07-27 — all four BE tasks are IMPLEMENTED on
> `claude/be-fe-prompts-0f4z8j`.** Founder answers are folded in below; where
> the answer changed a task, the task text changed with it (BE-2 is now a
> 10-minute soft caution, not a 5-minute limit; BE-4 ships PDF **and**
> `.docx`). Three deviations from this plan are recorded in §5 — read them.
> This file stays the spec of record; the FE prompt is the live one.

Source: `willpowerlab backlog` (13 user stories, T1 · 1.2 / 1.4 / T4 · 4.3).
Companion: `docs/PROMPT-FE-2026-07-27-backlog-wave.md` — read §0 of that file
for the contract split; **10 of the 13 stories are FE-only** and are listed
there, not here.

Branch off `origin/main`, one PR per numbered task below, CI green, squash-merge.
No table/column drops. Every migration `IF NOT EXISTS`.

---

## 0. Decision-filter verdicts (run before any code — CLAUDE.md §🛂)

| # | Story | CATEGORY | VERDICT | Owner |
|---|---|---|---|---|
| 1 | Ideal text in a clean medium-like format, bold not brackets | **F1-SURFACE** | **ADVANCE-F1-SURFACE** | **BE-1** + FE |
| 2 | Streamlined navbar | SCAFFOLDING | DEFER | FE |
| 3 | Unified hamburger (blog + lab) | SCAFFOLDING | DEFER | FE |
| 4 | "Start your first project" — never prefill a project | **F1-SURFACE** | **ADVANCE-F1-SURFACE** | FE (BE contract already exists) |
| 5 | ~~5-minute key-moments modal~~ → **10-minute long-take caution** | SCAFFOLDING | **ADVANCE (founder 2026-07-27)** | **BE-2** + FE |
| 6 | Progress marker on the recording progress bar | SCAFFOLDING | DEFER | FE |
| 7 | Key sentences highlighted in the text | **F1-SURFACE** | **ADVANCE-F1-SURFACE** | **BE-3** + FE |
| 8 | "Pending verification" badge | SCAFFOLDING | DEFER (already served) | FE |
| 9 | Centre the Full-text / Key-words toggle | SCAFFOLDING | DEFER | FE |
| 10 | Onboarding screen cleanup | SCAFFOLDING | DEFER | FE |
| 11 | Download the life-panel strategy as a document | SCAFFOLDING | ADVANCE — **BE-4**, PDF + `.docx` (founder 2026-07-27) | BE |
| 12 | Scrape 500+ phrases from two blogs | **DRIFT** | **REJECT-DRIFT** — founder-confirmed 2026-07-27 | — |
| 13 | Clickable links in chat | SCAFFOLDING | DEFER | FE |

Verdict blocks for the three that are not a plain DEFER:

```
VERDICT:  ADVANCE-F1-SURFACE
CATEGORY: F1-SURFACE
WHY:      #1/#7 — the ideal text IS the F1 deliverable (best-text-per-slide,
          assembled and served). Serving it with raw `{{orange:` / `**`
          tokens in the body, and serving a one-cue key-words view for a
          single-block document, are correctness defects of an existing F1
          surface (the read path), not new features. No fence, no Lx hit:
          the text stays VERBATIM (L1), nothing numeric reaches the user
          (AC-9), the accent stays a qualitative tint (CONSTRUCT).
REDIRECT: n/a
```

```
VERDICT:  REJECT-DRIFT
CATEGORY: DRIFT
WHY:      #12 — scraping two external blogs into a 1000-phrase corpus for
          the life panel serves a NEW surface no F1/F2 piece needs. Textbook
          R11 ("it's a platform / content foundation"): no in-flight F1 task
          is named or unblocked by it. Independently: bulk-scraping
          third-party blogs is a copyright/ToS decision, not an
          engineering one.
REDIRECT: (3) sharpen the blended best-slide ranking, or (1) tighten
          word→slide bucketing. If the founder re-locks the north star to
          include a phrase corpus, it comes back as its own scoped task
          with a licensing answer attached.
STATUS:   founder-confirmed 2026-07-27 — closed, not parked. Do not
          re-open it as a "small script" or fold it into another task.
```

```
VERDICT:  JUSTIFIED-SCAFFOLDING  (was DEFER pending Q1; founder answered
          2026-07-27 and reshaped the story)
CATEGORY: SCAFFOLDING
WHY:      #5 — the 5-minute LIMIT is dropped entirely (it described nothing
          the server did: `MAX_RECORDING_DURATION_SECONDS = 300` is
          referenced nowhere, and the wizard offers 30/45/60 min and "No
          limit"). What ships instead is a 10-minute SOFT CAUTION: at or
          above 10 min the wizard advises practising the beginning and the
          ending in short takes, and the student proceeds anyway. It passes
          because it now states something TRUE and steers takes toward the
          short, repeatable form the cross-take ranking actually feeds on.
          No fence: the copy describes what the product covers and warns
          that long analysis takes longer — no grade, no verdict on the
          user's speech (AC-9). Founder authored the copy, so it is signed
          off.
REDIRECT: n/a. Note the fence for any future edit: nothing server-side may
          start truncating or rejecting on this number — the moment it
          gates, it stops being a caution and needs its own verdict.
```

---

## BE-1 — a marker may never straddle a newline (story #1)

**The defect, exactly.** The founder's screenshot of *Your ideal text* renders:

```
… realizing how it is important. ☆
{{orange:
How little important it is, what he has just achieved
from the perspective of human integrity. ☆
}} And being, in general, human, …
```

`{{orange:` and `}}` are on their own lines, in the reader's face. This is
**not only** an FE rendering bug (the FE fix is FE-1 in the companion prompt —
its marker parser is flat and single-line, see the note already in
`routes/v2_routes.py:12236`). The BE is producing a marker span that wraps a
paragraph break, which no flat parser can render and which is unreadable in
every plain-text fallback the marker contract promises
(`services/ideal_text_block.py:5-20` — "markers are plain text, degrade
readably anywhere"). A span that crosses `\n` does not degrade readably.

**Root cause.** `services/ideal_decision_ledger.py::bake_piece` (~line 105):

```python
elif r.get("kind") == "emphasize":
    if "{{orange:" in found or text[max(0, lo - 9):lo].endswith("{{orange:"):
        continue
    text = text[:lo] + "{{orange:" + found + "}}" + text[hi:]
```

`_find_phrase` is a literal `str.find`, so when the approved
`display_phrase` itself contains a newline the wrap straddles paragraphs. The
serve-time emphasize fold in `routes/v2_routes.py:12209-12245` has the same
shape.

### Do this

**1. New pure helper in `services/ideal_text_block.py`** (it already owns the
marker contract docstring — the rule belongs next to it):

```python
def wrap_accent(text: str, lo: int, hi: int) -> str:
    """Wrap text[lo:hi] in {{orange:…}} WITHOUT ever crossing a newline.

    The marker contract promises markers degrade readably as plain text; a
    span that straddles a paragraph break does not (it renders as a bare
    `{{orange:` line in the reader's face — founder screenshot 2026-07-27),
    and the FE's flat parser cannot close it. So a multi-line span becomes
    ONE wrap PER LINE: `a\nb` → `{{orange:a}}\n{{orange:b}}`.

    Blank/whitespace-only lines are left unwrapped (no empty `{{orange:}}`).
    Leading/trailing whitespace inside the span stays OUTSIDE the wrap, so
    offsets the caller holds elsewhere still point at the same words. A span
    already inside an accent, or out of bounds, returns `text` unchanged.
    Pure.
    """
```

**2. New pure guard in the same module** — the last line of defence at serve:

```python
def sanitize_markers(text: str) -> str:
    """Drop marker tokens that cannot render, keeping every WORD.

    Removes: an unmatched `{{orange:` (no `}}` before end-of-text or before
    the next `{{orange:`), an unmatched closing `}}`, an odd trailing `**`,
    and any accent open/close pair separated by a blank line. Never reorders,
    never deletes prose, never touches `[[moment:…]]` (MOMENT_RE is the one
    marker the BE parses — leave it to strip_moment_markers). Idempotent:
    sanitize_markers(sanitize_markers(t)) == sanitize_markers(t). Pure.
    """
```

**3. Call sites (three, no others):**
- `services/ideal_decision_ledger.py::bake_piece` — replace the inline
  concatenation with `wrap_accent(text, lo, hi)`. Keep the existing
  already-wrapped guard ahead of it.
- `routes/v2_routes.py` ~12209-12245 (the serve-time emphasize fold) — same
  swap. Keep the existing flat-nesting guard (`"{{orange:" in inner`).
- `routes/v2_routes.py::v2_explore_get_ideal_text` — run `sanitize_markers`
  over `_text` **once**, immediately before it goes into the `jsonify`, after
  every fold/bake has run. Also apply it on the `?version=N` historical
  branch (`_s_text`) so an old snapshot cannot leak either.

**Do not** strip `{{orange:}}`/`**`/`__`/`//` from the payload — the FE renders
them (FE-1). This task removes only the *unrenderable* ones.

### Tests — new file `test_marker_hygiene.py`

1. `wrap_accent` on a single-line span → one wrap, words unchanged.
2. `wrap_accent` on a span containing `\n\n` → two wraps, the blank line
   untouched, `"{{orange:\n"` appears **nowhere** in the output.
3. `wrap_accent` leading/trailing spaces stay outside the braces.
4. `bake_piece` with an approved multi-paragraph `emphasize` row → output has
   balanced `{{orange:`/`}}` counts and no marker adjacent to `\n`.
5. `sanitize_markers` — unmatched open dropped, inner words kept; unmatched
   close dropped; `[[moment:…]]…[[/moment]]` survives byte-identical;
   idempotence.
6. Route test: an arc whose ledger holds a multi-paragraph emphasize →
   `GET /v2/explore/arc/<id>/ideal-text` `text` contains no `{{orange:`
   immediately followed by whitespace-then-newline, and balanced braces.

Regression watch: `test_ideal_decision_ledger.py`, `test_protected_phrases.py`
(its `_MARKERS` strip set must still see balanced pairs),
`test_master_doc_output_guards.py`.

### Acceptance
`text` served by the ideal-text GET never contains a marker token that opens
on one line and closes on another, and never an unbalanced one. Word content
byte-identical to today apart from marker placement. **L1 intact** — no word
is added, removed or rewritten by this task.

---

## BE-2 — the long-take soft caution as a served number (story #5) · **DONE**

Founder 2026-07-27: **the 5-minute rule is dropped.** In its place, a
**10-minute soft caution** — at or above the threshold the setup wizard advises
practising the beginning and the ending in short takes, and **the student may
always proceed and record the long take.** Nothing is limited.

- `config.py` — `LONG_TAKE_CAUTION_SECONDS`, default `600`, env-overridable,
  added next to `MAX_RECORDING_DURATION_SECONDS`. The dead
  `MAX_RECORDING_DURATION_SECONDS` is left in place (deleting it is its own
  cleanup; it is referenced in no code path).
- `GET /v2/config/recording` — the existing "stop the FE hardcoding 60s"
  endpoint, and the number's single home:

```
200 { min_duration_sec, min_voiced_sec, long_take_caution_sec }
```

- **No enforcement anywhere.** Nothing is truncated, rejected or capped on this
  number. The moment it gates something it stops being a caution and needs a
  fresh verdict — `test_wave2_be.py::test_the_caution_threshold_never_becomes_a_gate`
  is the pin that argues.

Founder-authored copy (signed off, FE renders it verbatim):

> *"Preparing for a long workshop? It's often better to practice just the
> beginning and the ending. Consider recording a few 2-3 minute takes to
> practice those vulnerable moments instead of focusing on a long speech.
> Note: Analysis of long speeches might take considerably longer."*

Tests: `test_wave2_be.py::ConfigRecordingRouteTests` — the endpoint carries the
key, and the constant is 600.

---

## BE-3 — the key-words view must have more than one cue (story #7)

**The defect, exactly.** The founder's *Key words* screenshot shows the entire
view as one card: `Identity and human nature is`. That is the whole feature,
for a full-length talk.

**Root cause.** `services/key_points.py::build_key_points` emits **one
milestone per `block_key`**. Blocks come from the master-document skeleton,
which is keyed on slide index — a **deckless / single-block project produces
exactly one block, therefore exactly one cue**. Correct by its own contract,
useless on screen.

Second, `key_points` is served only from inside `_tracked_changes_block`
(`routes/v2_routes.py:13564`), so it requires **both** `LIVING_TRANSCRIPT_ENABLED`
and `KEY_POINTS_ENABLED`. Confirm with the founder which of those is on in
prod before debugging an empty array (Q3).

### Do this

**1. Paragraph-level fallback inside `services/key_points.py`.** Keep the
per-block path exactly as is when a document has ≥ 2 blocks. When it yields
fewer than 2 milestones, fall back to segmenting the served text on paragraph
breaks and emitting one cue per paragraph, via the *same* `_opening_clause`
and the *same* offset arithmetic:

```python
def build_key_points(pieces, served_text=None) -> list:
    """… unchanged contract. New (2026-07-27): a document with fewer than two
    BLOCKS (a deckless project is one block by construction) falls back to one
    milestone per PARAGRAPH of `served_text`, so the key-words view is a cue
    sheet and not a single card. Same `_opening_clause`, same verbatim slice,
    same start/end offsets into the served document — L1-exact either way.
    `block_key`/`block_label` are None on fallback entries."""
```

Rules for the fallback, all deterministic, no LLM anywhere in this file:
- Split `served_text` on `\n\s*\n`; keep each chunk's absolute offset.
- Skip a paragraph shorter than **24 chars** (a stray line is not a milestone).
- `text` is `_opening_clause(chunk)` — the existing verbatim-prefix cutter,
  `_CUE_MAX_CHARS = 48`, unchanged.
- Compute `start` from the chunk's absolute offset + its own leading
  whitespace, exactly as the block path does, and assert
  `served_text[start:end] == text` before appending. **Drop any entry that
  fails that assertion** — a mis-anchored cue is worse than a missing one.
- Cap at **12** milestones (take the first 12 in document order) and log the
  drop count; a 60-slide talk must not return a 60-item wall.
- No `served_text` (the pure/testable path) → return today's block result
  unchanged.

**2. Nothing else.** No new endpoint, no flag, no schema change. `key_points`
keeps its existing shape `{block_key, block_label, text, start, end}` — the FE
already has the contract (FE-7 uses `start`/`end` to tint the same spans in the
*Full text* view).

### Fences to hold while doing it
- **L1** — `text` is a verbatim slice of `served_text`. Never a summary, never
  an LLM call, never a re-order. The existing module docstring says this; keep
  it true.
- **AC-9 / CONSTRUCT** — do **not** add importance, salience, rank, confidence
  or any ordering signal to a milestone. Document order only. The FE renders a
  tint, not a score. If you find yourself wanting to sort cues by anything,
  stop — that is the banned number wearing a new hat.

### Tests — extend `test_key_points.py` (create it if absent)
1. ≥ 2 blocks → today's behaviour byte-identical (regression pin).
2. One block, 5 paragraphs → 5 milestones, each `served_text[start:end] == text`.
3. One block, one paragraph → 1 milestone (no crash, no fabrication).
4. Paragraphs under 24 chars skipped.
5. 40 paragraphs → 12 milestones, document order, first-12.
6. `served_text=None` → block path, unchanged.
7. A milestone never contains `{{orange:`/`**`/`[[moment:` (interacts with
   BE-1 — cues are cut from the served text, so run `sanitize_markers` first
   or assert the served text is already clean).

### Acceptance
A deckless single-block project with a normal-length ideal text returns
**2-12** key points, every one a verbatim, correctly-anchored slice.

---

## BE-4 — the strategy downloads as a real file (story #11) · **DONE**

Today `GET /v2/life/strategy/download` (`routes/life_routes.py:365`) returns
**JSON** — `{body, versions}` — so "download" is the FE writing a `.txt` by
hand. The story asks for PDF or DOC.

- `?format=` on that endpoint: `json` (**default — unchanged**, existing
  callers keep working), `md`, `pdf`, `docx`.
- New module `services/strategy_export.py` (not `life_panel.py` — see §5.3):
  `sections()` / `to_markdown()` / `_render_pdf()` / `_render_docx()` /
  `export(latest, horizons, fmt) -> (bytes, mimetype, filename)`.
- PDF follows `services/dev_tasks.py::_render_pdf`: lazy `reportlab` import,
  A4, `getSampleStyleSheet`, a heading per horizon. Dep already pinned.
- `.docx` **is in scope** (founder 2026-07-27) — `python-docx==1.1.2` added to
  `requirements.txt`, lazy-imported, pure-python, no system libs.
- Either renderer failing or missing **degrades to `md`** with a 200 — the same
  contract `services/dev_tasks.py:206-226` uses. Never a 500 on a download.
- Response carries `Content-Disposition: attachment` and the real
  `Content-Type`; the FE reads the returned type rather than assuming the
  requested one.

Tests: `test_strategy_export.py` — horizon order and empty-skip; markdown;
`%PDF` magic bytes; `PK` zip magic for the .docx; each renderer patched to
raise `ImportError` **and** `RuntimeError` → 200 markdown; unknown format and
an empty strategy both land on markdown.

---

## Explicitly NOT backend in this wave

Stories 2, 3, 4, 6, 8, 9, 10, 13 need **zero** BE change — every field they
render is already served. The companion FE prompt names the exact endpoint and
field for each. If FE asks for a new endpoint for any of them, the answer is
"it already exists"; check §0 of the FE prompt first.

Story 8 in particular: `GET /v2/explore/arc/<id>/ideal-text` has served
`status: "verified" | "unverified"` since 2026-07-17. The badge in the
screenshot is already driven by it. That story is a copy/placement question,
not a backend one.

---

## 5. Deviations from this plan (decided while implementing)

**5.1 — `long_take_caution_sec` is NOT on `GET /explore/arc/<id>/setup`.**
The plan said to echo it there so continuing a project needed one call. It
doesn't ship there. `test_context_aware_setup.py::test_payload_is_exactly_the_setup_fields`
pins that payload to exactly the setup fields, and the route's own docstring
calls it "deliberately MINIMAL". The threshold is a property of the *product*,
not of a *project* — echoing it into a per-project payload would have put the
same number in two places, which is the thing BE-2 exists to prevent.
`GET /v2/config/recording` is its one home; the FE reads it once at boot.

**5.2 — `sanitize_markers` runs BEFORE the anchors are read, not at the
jsonify.** The plan said "once, immediately before it goes into the jsonify".
That would have been a bug: `key_moments[].anchor` and the tracked-change /
key-point offsets are all computed against `_text` earlier in the route, so
sanitizing afterwards would shift the served string out from under every anchor
the FE locates, silently dropping the star layer. It now runs right after the
applied-suggestion fold and before `extract_key_moments`, so every offset in
the payload is measured against the exact string the student receives.

**5.3 — the strategy renderers live in `services/strategy_export.py`, not
`services/life_panel.py`.** Two renderers, two lazy dependencies and a shared
degradation path is a module, not a helper. `life_panel.py` is already 1000+
lines of domain logic.

**5.4 — `sanitize_markers` RE-WRAPS a legacy multi-line accent instead of
deleting it.** The plan said to drop such a pair. Re-wrapping per line keeps
the emphasis the student (or coach) actually chose and only fixes the
placement; dropping it would have silently discarded intent on every document
baked before `wrap_accent` existed. `__`/`//` are deliberately left unbalanced —
`//` occurs in every URL and "fixing" it would corrupt real content.

---

## 6. Closed questions (founder, 2026-07-27)

**Q1 — the duration rule.** *Answered:* drop the 5-minute rule; ship a
**10-minute soft caution** with founder-authored copy, always proceedable. BE-2
rewritten accordingly.

**Q2 — is the one-cue document deckless?** *Superseded.* The fallback triggers
on the observable condition (fewer than two blocks) rather than on a diagnosis,
so it is correct for a deckless project **and** for a decked project whose
skeleton failed to build. If decked projects turn out to show one cue too, that
is still an upstream skeleton bug worth its own ticket — BE-3 stops the student
seeing a single card either way.

**Q3 — prod flags.** *Answered:* `LIVING_TRANSCRIPT_ENABLED`,
`MASTER_DOCUMENT_ENABLED` and `KEY_POINTS_ENABLED` are **all 1 in prod**. So
`key_points` is live on the wire today and BE-3 changes what students see as
soon as it deploys — no flag flip needed, and no flag hides a mistake either.

**Q4 — export formats.** *Answered:* PDF **and** `.docx`; `python-docx` pulled
in. BE-4 updated.

---

## 7. Verification

Full CI-tier suite (the workflow's ignore list): **2328 passed**.
Four failures were present, three of which reproduce **unchanged on `main`**
with these changes stashed (`test_arc_unlock`, `test_coach_breakthrough_video`,
`test_coach_video` — pre-existing, unrelated to this wave). The fourth was
5.1 above and is fixed.

New/extended coverage: `test_marker_hygiene.py` (21 cases),
`test_key_points.py::ParagraphFallbackTests` (11 cases),
`test_strategy_export.py` (12 cases), `test_wave2_be.py` (2 cases).

**Deploy note:** `requirements.txt` gains `python-docx==1.1.2`. No migration.
No flag to flip.
