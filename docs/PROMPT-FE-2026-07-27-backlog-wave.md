# FE prompt — the 2026-07-27 backlog wave

Source: `willpowerlab backlog` (13 user stories). Companion:
`docs/PROMPT-BE-2026-07-27-backlog-wave.md`.

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
| 5 | the window number | `GET /v2/config/recording` → `key_moments_window_sec` **(BE-2, gated on Q1 — until then do not hardcode 300)** |
| 6 | the target length | `GET /v2/explore/arc/<arc_id>/setup` → `target_length_seconds` |
| 7 | the key sentences | same ideal-text GET → `key_points[]` `{text, start, end}` |
| 8 | verification state | same ideal-text GET → `status: "verified" \| "unverified"` |
| 11 | the strategy document | `GET /v2/life/strategy/download` (+`?format=pdf` after BE-4) |
| 2, 3, 9, 10, 13 | — | pure client work, no endpoint |

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

- Move the small record button to the **right** side of the composer, as an
  icon button: record glyph + the red dot on its **left**.
- Remove the **`+`** control from the text-input area. The composer is the
  input field and the record button — nothing else.
- Net effect must be *more* horizontal room for the chat input; if the
  redesign does not measurably widen it, it has not landed.
- The full-width **"Record the next take"** CTA above the composer (visible in
  the chat screenshots) is a different control and is **not** in scope here.
  Confirm before touching it — see Q5.

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

## FE-5 — the 5-minute key-moments modal (story #5) · **BLOCKED**

**Do not build this yet.** `MAX_RECORDING_DURATION_SECONDS = 300` exists in the
backend config but is referenced by no code path, and the length step offers
30 min, 45 min, 60 min and "No limit". Until the founder confirms the rule is
real (Q1), this modal would state something the product does not do.

When unblocked:
- Trigger on the length step (`How long should it run?`) when the chosen value
  exceeds `key_moments_window_sec` from `GET /v2/config/recording`. **Read the
  number from the endpoint — never hardcode 300.**
- Copy names what the product covers ("we surface key moments from the first N
  minutes — focus your practice there"), never a judgement about the user's
  speech. Founder sign-off required on the final wording.
- Two ways out: proceed, or go back and change the length. Dismissible.
  Shown once per setup flow, not per keystroke.

---

## FE-6 — a position marker on the progress bar (story #6) · **needs Q6**

The story asks for "a cross that moves along the progress bar to show the
user's current position in the recording process". The attached screenshot is
the setup wizard's **step** indicator (the dot row above *How long should it
run?*), not a recording timeline — so the target surface is genuinely
ambiguous. See **Q6**.

Whichever it is, these hold:
- The marker is driven by real elapsed progress, updated in real time (rAF or a
  ≤250 ms tick), never an animation guess.
- Duration for the recording reading comes from
  `GET /v2/explore/arc/<arc_id>/setup` → `target_length_seconds`; when it is
  null ("No limit") render the bar without a target and without a marker rather
  than inventing a denominator.
- It must not overlap or obscure any other control at any breakpoint.
- Never render elapsed/remaining as a **score or verdict** on pace. A clock is
  fine; "you're behind" is not (AC-9).

---

## FE-8 — the verification badge (story #8)

The badge already exists and is already correct — it is driven by `status` on
the ideal-text GET (`"verified" | "unverified"`), served since 2026-07-17. No
backend work.

What is actually wrong is **copy drift**: the ideal-text screen says *"Pending
verification by the coach"*, the chat card says *"Not verified by the coach"*,
for the identical state. Pick one string and use it in both places. Because it
is user-facing copy it needs founder sign-off — see Q7.

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

- Add a visible download control in the life panel's strategy view.
- After **BE-4**: `GET /v2/life/strategy/download?format=pdf` returns a real
  file with `Content-Disposition: attachment`. Let the browser handle it.
- The endpoint may degrade to markdown when PDF rendering is unavailable —
  honour the response `Content-Type`, do not assume `.pdf` from the request.
- Until BE-4 lands the endpoint still returns JSON `{body, versions}`; if you
  ship early, save `body` as `.md`, not as a fake `.pdf`.

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

## Questions

**Q5 (FE-2)** — "move the small record button to the right": is that the small
mic icon inside the composer, or the full-width **"Record the next take"** CTA
sitting above it? The screenshot is a WhatsApp reference, so the target control
is inferred.

**Q6 (FE-6)** — which progress bar? (a) the setup wizard's step indicator, (b)
a live elapsed-time bar during recording, or (c) a read-position marker over
the ideal text while recording? And is "cross" an **✕ glyph** or a **crosshair
/ vertical playhead line**? The attached screenshot shows (a) but the story
text describes (b).

**Q7 (FE-8)** — which string wins: *"Pending verification by the coach"* or
*"Not verified by the coach"*? User-facing copy, so your call.

**Q1 (FE-5, shared with BE)** — is the 5-minute key-moments window a real
product rule? Blocks FE-5 entirely.
