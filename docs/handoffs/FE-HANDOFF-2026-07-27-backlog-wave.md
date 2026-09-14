# FE handoff — the backlog wave (2026-07-27)

Every BE-facing contract from the 13-story backlog, consolidated. All of it is
on `claude/be-fe-prompts-0f4z8j` and merge-ready. **No migration. No flag to
flip.** `requirements.txt` gains `python-docx==1.1.2` — a deploy concern, not
yours.

**Prod flags are all ON:** `LIVING_TRANSCRIPT_ENABLED`,
`MASTER_DOCUMENT_ENABLED`, `KEY_POINTS_ENABLED`. So `changes[]`, `pieces[]` and
`key_points[]` are live on the wire today — code for their presence, not their
absence.

Four things changed. Ten of the thirteen stories need **no** backend change at
all; their per-story specs live in
`docs/PROMPT-FE-2026-07-27-backlog-wave.md` — this file is the wire contract,
that one is the task list.

---

## 1. `text` on the ideal-text GET — markers can no longer straddle a newline

`GET /v2/explore/arc/<arc_id>/ideal-text` → `text`.

**What was broken.** The screen printed this to the student:

```
… realizing how it is important. ☆
{{orange:
How little important it is, what he has just achieved
from the perspective of human integrity. ☆
}} And being, in general, human, …
```

An approved emphasis whose phrase contained a newline was wrapped by
concatenation, producing an accent span that opened on one line and closed two
paragraphs later. A flat parser cannot close that, and it does not degrade
readably as plain text either.

**What the BE now guarantees on `text`:**

- an accent is emitted **one line at a time** — `a\nb` arrives as
  `{{orange:a}}\n{{orange:b}}`, never `{{orange:a\nb}}`;
- **no marker token opens on one line and closes on another**;
- `{{orange:`/`}}` counts are balanced, and `**` occurs an even number of times;
- an unmatched token loses its **braces**, never its **words**;
- a legacy multi-paragraph accent (baked before this change) is **re-wrapped per
  line, not discarded** — the emphasis the coach or student chose survives.

Applies to the live payload **and** to `?version=N` historical snapshots.

**The marker grammar you render** (unchanged — `services/ideal_text_block.py`):

| Marker | Render as |
|---|---|
| `**…**` | bold |
| `__…__` | underline |
| `//…//` | italic |
| `{{orange:…}}` | the **one** accent colour (brand orange) |
| `[[moment:<snippet_id>\|<take_session_id>]]…[[/moment]]` | key moment — deep-links to that moment on the take's feedback page |

`[[moment:…]]` wrappers are **stripped from `text`** before it is served (the
anchors travel on `key_moments[].anchor` instead). The other four arrive
intact — they are yours to render.

**What you must still do**, even with the BE fixed:

1. **Keep the parser multi-line tolerant.** Dot-matches-all or an explicit
   scanner — never a per-line regex. The BE no longer *emits* a crossing span,
   but a parser that cannot survive one is one stored row away from printing
   braces at a student again.
2. **Never print a token.** An unmatched or unknown marker drops the token and
   keeps the words. No brace, bracket or asterisk from this grammar ever
   reaches the reader.
3. **Parse flat, not nested.** First opener wins to its matching closer; a
   marker inside an open span is literal text of that span.
4. **Edit mode is the same renderer** — styled text while editing, serialized
   **back to markers** on save. `PUT /v2/explore/arc/<arc_id>/ideal-text/user-edit`
   strips raw HTML and preserves markers; post HTML and the styling is
   destroyed. A no-op edit must round-trip byte-identical.

---

## 2. `key_points[]` — 2-12 cues, and two fields can be null

Same GET. Shape is unchanged:

```
key_points: [ { block_key, block_label, text, start, end } ]
```

**What was broken.** The *Key words* tab rendered one card —
`Identity and human nature is` — for a whole talk. Cues were emitted one per
master-document **block**, blocks are keyed on slide index, so a deckless
project is one block and therefore one cue.

**What changed.** When the block path yields fewer than two milestones, cues
are derived **per paragraph** instead. Typical documents now return **2-12**.

- **`block_key` and `block_label` are `null` on paragraph-derived entries.**
  Do not key rendering, sorting or grouping on either.
- **`text` is a verbatim slice** of the served text — never a summary, never a
  rewrite.
- **`start`/`end` index the served `text` exactly**, including any
  `{{orange:`/`**` characters and excluding the stripped `[[moment:…]]`
  wrappers. Map them through your parser's source→rendered index map; do not
  compute them against the marker-stripped string.
- **Verify before you use one:** `text.slice(start, end) === key_point.text`.
  On mismatch, **drop that cue silently** — same rule as tracked changes, never
  guess a position. The BE already applies this check; the client-side one
  costs nothing and catches a stale render.
- Order is **document order, always.** Nothing ranks or scores a cue, and
  nothing ever will — do not sort, number by importance, or render a
  rank/percentage/confidence on one. If a comp shows a number here, it is
  wrong.
- **Absent ≠ empty.** Key missing → hide the *Key words* toggle entirely.
  `[]` → show the toggle with an empty state.

Both tabs read this one array: *Key words* renders each `text` as a card;
*Full text* tints the same `start`/`end` spans in the brand accent.

---

## 3. `GET /v2/config/recording` — the long-take caution

```
200 { min_duration_sec, min_voiced_sec, long_take_caution_sec }
```

`long_take_caution_sec` is **600**. The old five-minute idea is **dropped** — it
described nothing the server did.

- **Trigger:** on the setup wizard's length step, when the chosen value is
  **at or above** `long_take_caution_sec`. Note `>=` — 10 min itself triggers.
  "No limit" triggers it too.
- **Read the number from this endpoint. Never hardcode 600.**
- **Copy — founder-authored, signed off, render verbatim:**

  > *"Preparing for a long workshop? It's often better to practice just the
  > beginning and the ending. Consider recording a few 2-3 minute takes to
  > practice those vulnerable moments instead of focusing on a long speech.
  > Note: Analysis of long speeches might take considerably longer."*

- **Soft, always.** The primary action **proceeds with the long take**. Never a
  block, never a forced downgrade, never a disabled Next. Secondary action
  returns to the length step. Dismissible. Shown once per setup flow, not per
  chip tap.
- **Nothing server-side enforces this.** A long take records, uploads and
  processes exactly as before.

---

## 4. `GET /v2/life/strategy/download?format=` — real files

```
?format=json   → 200 { body, versions }        ← DEFAULT, unchanged
?format=md     → text/markdown
?format=pdf    → application/pdf
?format=docx   → application/vnd.openxmlformats-officedocument.wordprocessingml.document
```

- File formats carry `Content-Disposition: attachment; filename="strategy.<ext>"`.
  Let the browser save it; do not re-wrap the body.
- **Honour the response `Content-Type`, never the requested one.** If a renderer
  is unavailable the endpoint degrades to **markdown with a 200** rather than
  500ing — assuming `.pdf` there would save a `.pdf` full of markdown.
- Offer **PDF** and **Word (.docx)**; the editable Word file was an explicit
  ask.
- Omitting `format` returns today's JSON, so existing callers are untouched.

---

## 5. Deliberately unchanged — do not build around these

- **`GET /v2/explore/arc/<arc_id>/setup`** — payload is byte-identical
  (`arc_id, topic, audience, strategic_context, target_length_seconds, slides,
  presentation_ref`). `long_take_caution_sec` is **not** echoed here on
  purpose: it is a product constant, not a project field, and a pinned test
  keeps this payload minimal. Read it from `/v2/config/recording` once at boot.
- **The verification badge** — `status: "verified" | "unverified"` has been on
  the ideal-text GET since 2026-07-17 and already drives the badge. No BE work
  existed for that story. The fix is copy: standardise on **"Pending
  verification"** on every surface (chat bubbles, ideal-text screen, anywhere
  else). Grep for the old strings rather than fixing only the two in the
  screenshots — a third copy is how it drifted.
- **`GET /v2/user/trainings`** — unchanged; `trainings[]` with `arc_id` +
  `topic` is the project chooser's source. Empty array is the
  "Start your first project" empty state.
- **`POST /v2/lab/recordings`** — unchanged. Continue with flat
  `continue_arc_id`; never send `take_index`; never mint a fresh arc for a
  continuation.

---

## 6. The stories with no BE dependency

Specs in `docs/PROMPT-FE-2026-07-27-backlog-wave.md`; contracts, where any, are
in §5 above.

| Story | One line |
|---|---|
| #2 navbar | Record control **inside** the composer, right side, slightly wider: dot + the label "Record". Remove the `+`. The full-width "Record the next take" CTA is untouched. |
| #3 hamburger | Same component on blog and lab; **Lab first**, separated by a light stroke. |
| #4 first project | Empty `trainings[]` → one centred CTA. **Never prefill or auto-select a project** — a take on the wrong `arc_id` splits the project and corrupts the cross-take comparison. |
| #6 the ✕ | The **onboarding step indicator**, and "cross" = an **✕ cancel** button. No playhead, no timeline. Confirm before discarding a half-filled setup. |
| #8 badge | Copy only — "Pending verification" everywhere (§5). |
| #9 toggle | Centre the Full text / Key words control. |
| #10 onboarding | Remove the "Your data" link, the grey paragraph and the "Principles" pill; then make all nine screens consistent. |
| #13 links | Linkify chat URLs. **Trailing `.`/`,`/`)` stays outside the anchor** — the reference URL ends in a sentence period. Escape first, linkify second. `rel="noopener noreferrer"`. |

**Story #12** (a scraped "wall of phrases") is **rejected — founder-confirmed**.
No corpus, no endpoint. Do not build a surface for it.

---

## 7. Suggested order

1. **§1 marker rendering** — the one defect a student sees on the product's
   actual deliverable, every session.
2. **§2 key points** — the BE change lands the moment this deploys (all flags
   are on), so the Key words tab starts returning 2-12 cues with `null`
   `block_key`s whether or not the FE is ready. Handle the nulls first.
3. **#4 project chooser** — the silent data defect.
4. Everything else, batchable.

Ping BE on: a marker you cannot render, a `key_points` entry whose slice does
not match, or any payload field this document does not describe.
