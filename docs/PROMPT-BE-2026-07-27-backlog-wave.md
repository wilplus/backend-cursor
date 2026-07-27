# BE prompt — the 2026-07-27 backlog wave

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
| 5 | 5-minute key-moments modal | SCAFFOLDING | **BLOCKED — see Q1** | **BE-2** + FE |
| 6 | Progress marker on the recording progress bar | SCAFFOLDING | DEFER | FE |
| 7 | Key sentences highlighted in the text | **F1-SURFACE** | **ADVANCE-F1-SURFACE** | **BE-3** + FE |
| 8 | "Pending verification" badge | SCAFFOLDING | DEFER (already served) | FE |
| 9 | Centre the Full-text / Key-words toggle | SCAFFOLDING | DEFER | FE |
| 10 | Onboarding screen cleanup | SCAFFOLDING | DEFER | FE |
| 11 | Download the life-panel strategy as a document | SCAFFOLDING | DEFER (cheap — **BE-4**, ship only if 1/4/7 are done) | BE |
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
VERDICT:  DEFER (pending Q1)
CATEGORY: SCAFFOLDING
WHY:      #5 — a modal that tells the user "key moments are limited to 5
          minutes". `config.MAX_RECORDING_DURATION_SECONDS = 300` exists but
          is referenced NOWHERE in the codebase (verified), and the setup
          wizard offers 30/45/60 min and "No limit". So today the claim is
          not true of anything the server does. Copy is founder-sign-off
          territory regardless.
REDIRECT: answer Q1 first. If the cap is real, BE-2 makes it a served
          number (never an FE hardcode) and the modal is honest; if it is
          not real, the story dies rather than shipping a false statement.
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

## BE-2 — the key-moment window as a served number (story #5) — **HOLD FOR Q1**

Do not start until Q1 is answered. If the answer is "yes, 5 minutes is real":

- `config.py`: rename nothing; **add**
  `KEY_MOMENTS_WINDOW_SECONDS = int(os.getenv("KEY_MOMENTS_WINDOW_SECONDS", "300"))`
  next to `MAX_RECORDING_DURATION_SECONDS` (line ~100). Leave the dead
  `MAX_RECORDING_DURATION_SECONDS` alone in this PR — deleting it is a
  separate cleanup and it is referenced in no code path today.
- `routes/v2_routes.py::v2_config_recording` (`GET /v2/config/recording`,
  line 9426) — the existing "stop the FE hardcoding 60s" endpoint, exactly the
  right home. Add one key:

```
200 { min_duration_sec, min_voiced_sec, key_moments_window_sec }
```

- `routes/v2_routes.py::v2_explore_arc_setup` (`GET /v2/explore/arc/<id>/setup`)
  — add the same `key_moments_window_sec` so the continue-a-project path does
  not need a second call.
- **No enforcement in this PR.** Nothing is truncated, rejected or capped. The
  number is served so the FE can state it truthfully in one place; if the
  founder later wants a real gate that is its own task with its own verdict.

Tests: extend `test_video_size_cap_config.py` style — assert both endpoints
carry the key, that it reads the env override, and that the default is 300.

**Fence note for whoever writes the modal copy:** the modal says what the
product *covers*, never a verdict on the user's speech. "We surface key moments
from the first 5 minutes" is fine; anything that grades length is AC-9 bait.
Copy ships only with founder sign-off.

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

## BE-4 — the strategy downloads as a real file (story #11) — ship last

Today `GET /v2/life/strategy/download` (`routes/life_routes.py:365`) returns
**JSON** — `{body, versions}` — so "download" is the FE writing a `.txt` by
hand. The story asks for PDF or DOC.

- Add `?format=` to that endpoint: `json` (**default — unchanged**, existing
  callers keep working), `md`, `pdf`.
- `pdf` → `services/life_panel.py` gets `render_strategy_pdf(assembled: str,
  *, title: str) -> bytes` modelled **exactly** on
  `services/dev_tasks.py::_render_pdf` (lines 227+): lazy `reportlab` import,
  A4, `getSampleStyleSheet`, `KeepTogether` per horizon heading + body. The
  dep is already pinned (`reportlab==5.0.0`) and already lazy-imported
  elsewhere.
- A missing/failed `reportlab` import **degrades to `md`** with a 200 and the
  markdown content type — the same degradation contract
  `services/dev_tasks.py:206-226` uses. Never a 500 on a download.
- Response headers: `Content-Disposition: attachment; filename="strategy.pdf"`,
  correct `Content-Type`. The body is `_assemble(latest)` — reuse it, do not
  re-derive.
- **`.docx` is not in scope** unless the founder says otherwise (Q4): it needs
  a new dependency (`python-docx`) for a non-F1 surface, and PDF already
  travels everywhere.

Tests: `test_life_panel.py` — default still JSON; `?format=md` is text;
`?format=pdf` returns `%PDF` magic bytes and the attachment header; reportlab
import patched to raise → 200 markdown, no exception.

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

## Open questions (answer before the tasks they gate)

**Q1 — gates BE-2.** Is the "key moments are limited to 5 minutes" rule real?
`MAX_RECORDING_DURATION_SECONDS = 300` is defined in `config.py` and used
nowhere; the setup wizard offers 30/45/60 min and "No limit". Either (a) it is
a real product rule → BE-2 serves it and the modal is honest, or (b) it is not
→ the story should not ship as written. Please pick.

**Q2 — gates the BE-3 fallback threshold.** Is the target document a *deckless*
project (one block) or is the master-document skeleton simply not built for it?
If decked projects also show one cue, the bug is upstream in the skeleton and
BE-3 is treating a symptom.

**Q3 — gates BE-3 verification.** Which of `LIVING_TRANSCRIPT_ENABLED`,
`MASTER_DOCUMENT_ENABLED`, `KEY_POINTS_ENABLED`, `POLISH_AS_SUGGESTIONS_ENABLED`
are **1 in prod right now**? `key_points` ships only when the first and third
are both on; BE-1's fold path depends on the others.

**Q4 — gates BE-4.** PDF only (zero new deps), or PDF + `.docx` (adds
`python-docx` for a life-panel surface)?
