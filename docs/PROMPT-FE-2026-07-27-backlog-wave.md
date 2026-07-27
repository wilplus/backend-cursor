# FE prompt — the 2026-07-27 backlog wave

Source: `willpowerlab backlog` (13 user stories). Companion:
`docs/PROMPT-BE-2026-07-27-backlog-wave.md`.

> **STATUS 2026-07-27 — every backend dependency in this file is IMPLEMENTED
> and merged-ready on `claude/be-fe-prompts-0f4z8j`.** Nothing here is waiting
> on the BE. All founder answers are folded in: FE-5 is unblocked and reshaped
> (a **10-minute soft caution**, not a 5-minute limit), FE-6's ambiguity is
> resolved (an ✕ **cancel** control on the **onboarding step** indicator),
> FE-2 and FE-8 have their decisions.
>
> **Prod flags:** `LIVING_TRANSCRIPT_ENABLED`, `MASTER_DOCUMENT_ENABLED` and
> `KEY_POINTS_ENABLED` are **all on**. So `changes[]`, `pieces[]` and
> `key_points[]` are all live on the wire today — code for their presence, not
> their absence.

**Read §0 before writing anything.** Ten of these thirteen stories need no
backend change at all — every field is already served. Do not ask for a new
endpoint before checking the table.

---

## 0. What is already served (do not build a BFF shim for any of this)

| Story | You need | It is already at |
|---|---|---|
| 1 | the text + its markers | `GET /v2/explore/arc/<arc_id>/ideal-text` → `text` |
| 4 | the user's projects | `GET /v2/user/trainings` → `trainings[]` (`arc_id`, `topic`) |
| 4 | continuing a project | `POST /v2/lab/recordings` with flat `continue_arc_id` |
| 4 | a project's saved setup | `GET /v2/explore/arc/<arc_id>/setup` |
| 5 | the caution threshold | `GET /v2/config/recording` → `long_take_caution_sec` (**live**, 600) |
| 6 | the target length | `GET /v2/explore/arc/<arc_id>/setup` → `target_length_seconds` |
| 7 | the key sentences | same ideal-text GET → `key_points[]` `{text, start, end}` |
| 8 | verification state | same ideal-text GET → `status: "verified" \| "unverified"` |
| 11 | the strategy document | `GET /v2/life/strategy/download` (+`?format=pdf` after BE-4) |
| 2, 3, 9, 10, 13 | — | pure client work, no endpoint |

Story **12** (a scraped "wall of phrases" in the life panel) is **rejected as
drift, founder-confirmed 2026-07-27**. There is no corpus and no endpoint
coming — do not build a surface for it.

Priority order for this wave: **FE-1 → FE-7 → FE-4**, then the rest in any
order. Those three touch the ideal-text read path (the product's actual
deliverable); the remainder is chrome and can ship in one batched PR.

---

## FE-1 — render the markers, stop printing them (story #1) · **P0**

### The defect

The *Your ideal text* screen currently prints this to the user, verbatim:

```
… realizing how it is important. ☆
{{orange:
How little important it is, what he has just achieved
from the perspective of human integrity. ☆
}} And being, in general, human, …
```

`{{orange:` and `}}` are raw wire markers leaking into the reading surface.
Two causes, one on each side: the BE was emitting an accent span that straddles
a paragraph break (fixed in **BE-1**), and this client's marker parser is flat
and single-line, so it cannot close a span that crosses `\n`. **Fix the parser
regardless of BE-1** — old rows already baked into stored documents will keep
arriving for a while, and a leaked token must never reach the reader again.

### The marker grammar (authoritative — `services/ideal_text_block.py:5-20`)

| Marker | Meaning | Render as |
|---|---|---|
| `**…**` | bold | `<strong>` |
| `__…__` | underline | `<u>` |
| `//…//` | italic | `<em>` |
| `{{orange:…}}` | **the one** accent colour (brand orange) | orange text span |
| `[[moment:<snippet_id>\|<take_session_id>]]…[[/moment]]` | a key moment | distinct from a plain underline; tapping deep-links to that moment on the take's feedback page |

There is exactly one accent colour by design. Do not invent a second.

### Parser rules — all of them non-negotiable

1. **Flat, not nested.** The backend emits a flat marker stream (see the note
   in `routes/v2_routes.py:12236`). Parse left to right; the first opener wins
   until its matching closer. A marker token found *inside* an open span is
   literal text of that span, not a nested style.
2. **Multi-line tolerant.** Every span may contain `\n`. Use dot-matches-all /
   an explicit scanner — never a line-by-line regex. This is the exact bug in
   the screenshot.
3. **An unmatched opener is never shown.** No `}}` before end of text (or
   before the next `{{orange:`) ⇒ drop the *token*, keep every *word*, render
   the rest unstyled. Same for a stray `**`, `__`, `//`, `}}` or an unclosed
   `[[moment:…]]`. **The reader must never see a brace, a bracket or an
   asterisk from this grammar.** Add a dev-only console warning so leaks stay
   visible to us.
4. **Key moments need both ids.** A `[[moment:…]]` whose `snippet_id` or
   `take_session_id` is missing renders as plain text, not a dead tap target.
5. **Idempotent on empty.** `text: ""` renders an empty document, not a crash.

### Layout — "medium-like"

- Split the rendered text on blank lines into real `<p>` elements. Paragraph
  spacing comes from CSS margin, **never** from rendering `\n\n` as `<br><br>`.
- Reading measure ~60-70 characters, generous line-height (≈1.6), the same
  body type the screenshot uses. No monospace, no `white-space: pre-wrap` on
  the container (that is what makes stray markers look like content).
- The suggestion stars (☆) already inline in the text keep their current
  position and behaviour — this task does not touch the star layer.

### Edit mode is the same renderer

The story's second acceptance criterion — *"text formatting remains consistent
in both view and edit modes"* — is the hard part. Requirements:

- Edit mode shows **styled** text, not the marker source. A user must never
  see `{{orange:` while editing either.
- On save, serialize **back to markers**, byte-exact for any span the user did
  not touch. The save route strips raw HTML and preserves markers; if you post
  HTML the styling is silently destroyed.
- `PUT /v2/explore/arc/<arc_id>/ideal-text/user-edit` is the save target.
- Deleting a styled span deletes its markers with it. Typing at a span
  boundary extends the *unstyled* side (do not silently swallow new words into
  an accent).
- A `[[moment:…]]` span the user edits keeps its ids attached to the surviving
  text. If the user deletes the span entirely, the moment goes with it — that
  is the intended behaviour (the BE re-derives `key_moments` from the text).

### Acceptance
No character of the five grammars above ever renders as literal text, in view
or edit mode, including on a document whose accent span crosses two paragraphs.
Round-trip a document through edit-with-no-changes → `text` posted back is
identical to `text` received.

---

## FE-7 — the key-words view, and the tint in the full text (story #7) · **P0**

### The defect

The *Key words* tab renders exactly one card — `Identity and human nature is` —
for a full-length talk. The backend cause is fixed in **BE-3** (a deckless
project produced one milestone per block, and there is only ever one block).
After BE-3 the same field returns 2-12 entries.

### Do this

- `key_points[]` on the ideal-text GET: `{block_key, block_label, text, start,
  end}`, in document order. `block_key`/`block_label` may be `null` (a
  paragraph-derived cue) — do not key rendering on them.
- **Key words tab** — render each `text` as its own card, in the array's order.
  Never re-sort. Never number them by importance.
- **Full text tab** — tint the same spans. `start`/`end` are character offsets
  into the *served* `text`, exactly like a tracked change. **Verify before
  tinting:** `text.slice(start, end) === key_point.text`. If it does not match,
  drop that key point silently — same rule as tracked changes, never guess a
  position.
- Offsets index the **served text including markers**. Map them through your
  FE-1 parser's source→rendered index map; do not compute them on the
  marker-stripped string.
- The tint is the existing brand orange accent — the *same* one `{{orange:}}`
  uses. One accent colour in the product.
- `key_points` **absent** from the payload ⇒ hide the *Key words* toggle
  entirely (the field is flag-gated server-side). `key_points: []` ⇒ show the
  toggle with an empty state. Absent ≠ empty.

### Fence
Never render a rank, a percentage, a "top 3", a confidence or any ordering
signal on a key point. It is a qualitative cue, full stop (AC-9). If a design
comp shows a number here, it is wrong — flag it, do not build it.

---

## FE-4 — "Start your first project", and never a prefilled project (story #4) · **P0**

Two halves, and the second one is the load-bearing one:

1. **Empty state.** `GET /v2/user/trainings` returns `{trainings: []}` ⇒ the
   first screen is a single centred **"Start your first project"** button.
   Nothing else competing with it.
2. **Never prefill or assume.** Every tap on that button — and on the global
   "record official recording" entry — opens a project **choice**: the plain
   list of project titles (`trainings[].topic` + `arc_id`) plus a distinct
   **"Start a new topic"** button. No last-used default, no auto-select when
   the list has exactly one entry, no "continue where you left off" shortcut.

   This is not cosmetic. A take submitted with the wrong `continue_arc_id`
   lands in the wrong project, which splits the arc and corrupts the
   cross-take comparison the ideal text is built from. Silence here is a data
   defect, not a UX preference.

- Continuing a project → `GET /v2/explore/arc/<arc_id>/setup` to prefill topic
  / audience / target length / slides, then `POST /v2/lab/recordings` with flat
  `continue_arc_id: <arc_id>`. **Never** send `take_index` (the server numbers
  takes). **Never** mint a fresh arc for a continuation — that resets the take
  count and splits the project.
- "Start a new topic" → today's full setup wizard, no `continue_arc_id`.

---

## FE-2 — the navbar (story #2)

Reference: the founder's WhatsApp screenshot (the circled control cluster).

Founder 2026-07-27: **WhatsApp placement — the control INSIDE the text
composer**, on the right. Not the full-width "Record the next take" CTA, which
is a different control and stays as it is.

- Right side of the composer, and **slightly wider than an icon button**: a
  recording **dot** plus the small label **"Record"** next to it.
- Remove the **`+`** control from the text-input area. The composer is the
  input field and the record button — nothing else.
- Net effect must be *more* horizontal room for the chat input; if the redesign
  does not measurably widen it, it has not landed. The "Record" label costs
  width, so check this at the narrowest supported breakpoint — if the label
  cannot fit there without squeezing the input, keep the label and shrink the
  padding, not the input.

---

## FE-3 — one hamburger for blog and lab (story #3)

The lab's menu (screenshot) is: user email · Principles · Support · Community ·
Credits `455` · Log out.

- Ship the **same component** on the blog.
- **Lab** goes at the **top** of the list, separated from the rest by a light
  1px stroke.
- Identical styling, spacing, open/close behaviour and animation to the chat's
  menu. One component, two mounts — not a copy.
- Signed-out on the blog: no email row, no credits row, Lab still first.

---

## FE-5 — the long-take caution (story #5) · **unblocked, reshaped**

The 5-minute limit is **dropped** — it described nothing the product did. What
ships is a **soft caution at 10 minutes**.

- **Trigger:** on the length step (`How long should it run?`), when the chosen
  value is **at or above** `long_take_caution_sec` from
  `GET /v2/config/recording` (600 today). Note **`>=`**, not `>` — 10 min
  itself triggers it. **Read the number from the endpoint; never hardcode
  600.** "No limit" also triggers it.
- **Copy — founder-authored, signed off, render verbatim:**

  > *"Preparing for a long workshop? It's often better to practice just the
  > beginning and the ending. Consider recording a few 2-3 minute takes to
  > practice those vulnerable moments instead of focusing on a long speech.
  > Note: Analysis of long speeches might take considerably longer."*

- **Soft, always:** the primary action **proceeds with the long take**. Never a
  block, never a forced downgrade, never a disabled Next. A secondary action
  returns to the length step. Dismissible with Esc / backdrop / ✕.
- Shown **once per setup flow**, not on every re-tap of a length chip.
- Nothing server-side enforces this — a long take records, uploads and
  processes exactly as before. The modal is advice.

---

## FE-6 — the ✕ cancel control on the onboarding steps (story #6) · resolved

Founder 2026-07-27, and it is **not** what the story text implies. There is no
moving playhead and no recording timeline here:

- **"Progress bar"** = the **onboarding/setup step indicator** — the dot row
  above *How long should it run?* that shows how many steps remain. Exactly the
  control in the attached screenshot.
- **"Cross"** = an **✕ button that cancels** and leaves the flow. Not a
  position marker, not a crosshair.

So:
- Put an ✕ on the step indicator row, consistently placed on every step of the
  flow (the wizard's existing top-right ✕ is the reference position — if it is
  already there on some steps and not others, the story is that inconsistency).
- Tapping it exits the setup flow. **Confirm before discarding** anything the
  user has already entered — a mis-tap must not silently destroy a half-filled
  setup.
- The step dots keep showing position and remaining steps as they do now. No
  behaviour change to them beyond making the current step legible at a glance.
- It must not overlap or obscure any other control at any breakpoint, and it
  needs a real touch target (≥44 px) and an accessible label.

---

## FE-8 — the verification badge (story #8)

The badge already exists and is already correct — it is driven by `status` on
the ideal-text GET (`"verified" | "unverified"`), served since 2026-07-17. No
backend work.

What is actually wrong is **copy drift**: the ideal-text screen says *"Pending
verification by the coach"*, the chat card says *"Not verified by the coach"*,
for the identical state.

Founder 2026-07-27: standardise on **"Pending verification"** — the short form,
everywhere. Chat bubbles, the ideal-text screen, and **any other surface
carrying this state**. Grep for the old strings rather than fixing the two in
the screenshots; a third copy somewhere is exactly how this drifted.

---

## FE-9 — centre the toggle (story #9)

The *Full text / Key words* segmented control is left-aligned under the badge.
Centre it horizontally. Stays centred at every breakpoint, keyboard-focusable,
no layout shift when switching tabs. Ten-minute task — batch it with FE-10.

---

## FE-10 — onboarding cleanup (story #10)

From the *Your three bets* screenshot, remove:
- the **"Your data"** link at the bottom,
- the grey supporting paragraph ("Eight horizons. You can stop anywhere…"),
- the **"Principles"** pill above the step header.

Then make every onboarding screen match: one goal per screen, one heading, the
same spacing scale and the same Back/Next placement as the screens that are
already right. `STEP n OF 9` stays. Audit all nine — consistency is the story,
not three deletions on screen 1.

---

## FE-11 — download the strategy (story #11)

BE-4 is **done**. `GET /v2/life/strategy/download?format=` accepts `json`
(default, the original payload), `md`, `pdf` and `docx`.

- Add a visible download control in the life panel's strategy view, offering
  **PDF** and **Word (.docx)** — the founder asked for an editable Word file
  alongside the PDF.
- Both return real bytes with `Content-Disposition: attachment`. Let the
  browser handle the save; do not re-wrap the body.
- **Honour the response `Content-Type`, never the requested one.** The endpoint
  degrades to markdown with a 200 if a renderer is unavailable — assuming
  `.pdf` there would save a `.pdf` containing markdown.
- Omitting `format` still returns today's JSON, so any existing caller is
  unaffected.

---

## FE-13 — clickable links in chat (story #13)

From the screenshot: Will replies with
`https://cal.com/artur-willonski-zywzu7/lesson?duration=60&overlayCalendar=true.`
as dead text.

- Linkify `http://` and `https://` URLs in chat bubbles (both sides).
- **Trailing punctuation is not part of the URL.** A `.`, `,`, `)`, `!`, `?`,
  `:` or `;` at the end of the match stays outside the anchor — the screenshot
  ends in a sentence period and linking it breaks the URL. Balance `)` only
  when the URL contains a matching `(`.
- Query strings survive intact: `?duration=60&overlayCalendar=true` must not be
  entity-mangled or truncated at the `&`.
- `target="_blank" rel="noopener noreferrer"`.
- **Escape first, linkify second.** Never build an anchor by injecting unescaped
  message text into HTML — chat content is user- and model-authored.
- Long URLs wrap (`overflow-wrap: anywhere`) instead of widening the bubble.
- Bare `www.` and raw emails: out of scope unless the founder says otherwise.

---

## Closed questions (founder, 2026-07-27)

All four are answered and folded into the tasks above — kept here so the
reasoning survives:

- **Q1 (FE-5)** — the 5-minute rule is **dropped**. A 10-minute **soft
  caution** replaces it, always proceedable, copy supplied.
- **Q5 (FE-2)** — **WhatsApp placement**, inside the composer, slightly wider,
  with a "Record" label beside the dot. The full-width CTA is untouched.
- **Q6 (FE-6)** — the **onboarding step indicator**, and "cross" means an **✕
  cancel button**. No playhead.
- **Q7 (FE-8)** — **"Pending verification"**, everywhere.

## What the backend changed under you

Shipping on `claude/be-fe-prompts-0f4z8j`, no migration, no flag to flip:

1. **A marker can no longer straddle a newline** — the BE emits an accent per
   line and sanitizes the served text (unmatched tokens lose their braces,
   never their words; legacy multi-paragraph accents are re-wrapped, not
   dropped). Your FE-1 parser still needs its multi-line tolerance — nothing
   guarantees an old client or an unseen path won't produce one — but the
   common case is fixed at source.
2. **`key_points[]` now returns 2-12 cues** on a deckless document instead of
   1, with `block_key`/`block_label` **null** on paragraph-derived entries.
   Do not key rendering on those two fields.
3. **`long_take_caution_sec: 600`** added to `GET /v2/config/recording`.
4. **`?format=pdf|docx|md`** added to `GET /v2/life/strategy/download`.

`GET /v2/explore/arc/<id>/setup` is **unchanged** — the caution threshold is
deliberately not echoed there (it is a product constant, not a project field,
and a pinned test keeps that payload minimal). Read it from
`/v2/config/recording` once at boot.
