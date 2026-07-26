# FE handoff — the full versioning + recording wave (2026-07-23)

Every FE-facing BE contract shipped this wave, consolidated. All of it is
merged to `main`. Flags: `LIVING_TRANSCRIPT_ENABLED` and
`MASTER_DOCUMENT_ENABLED` gate the document behavior; the endpoints below
are live regardless.

The project **IS** the arc. Pass `arc_id` / `continue_arc_id`. There is
no `ideal_text_id`.

---

## 1. The ideal-text document (`GET /v2/explore/arc/<arc_id>/ideal-text`)

Single-deliverable payload (the fields the FE renders):

```
{ arc_id, version, status:"verified"|"unverified", title, updated_at,
  latest_take_session_id, take_count, reread_done, reread_processing,
  text, user_edited, key_moments, moments_unlocked,
  explanations_available, price_credits, notes_text,
  changes?, pieces? }
```

* **`text`** — the reading text. Render this; never reconstruct it from
  pieces.
* **`take_count`** — the project's official-take count. **Render the
  document badge as `` `${take_count}.0` ``** (per-project, climbs on
  every take). Do NOT badge from `version` (that only moves on a change).
* **`explanations_available`** — show the 5-credit unlock CTA ONLY when
  true. Otherwise no paywall surface at all.
* **`?version=N`** → the historical read-only step: `{historical:true,
  status:"superseded", text, key_moments}` (render read-only, no
  accept/dismiss/mic), or `{historical_unavailable:true}` → open the live
  view as today.

## 2. Tracked changes (`changes[]`, LIVING_TRANSCRIPT on)

Google-Docs inline editing. Each item:

```
{ id, snippet_id, take_session_id, kind:"replace"|"bold"|"advice",
  source, span:{start,end}, quote, proposed_text?, why?, why_key?,
  device?, take_index? }
```

* **`quote` is a character-exact substring of `text`** at `span`. Locate
  via the span / indexOf; **drop any change whose quote no longer
  matches** — never guess.
* **`replace`** → strike `quote`, show `proposed_text` inline; Accept
  swaps, Keep dismisses.
* **`bold`** → accent the `quote` span. As of T3 this is the **sub-phrase**
  (~20–50 chars), not the whole fragment — the renderer bolds exactly the
  span.
* **`advice`** (delivery/structural) → no text change; render copy from
  `device` (unknown device → no card).
* **`source:"prior_take"` / `"new_take"`** → cross-take/block upgrade:
  "your previous/other take said this better". The reason is on
  **`why_key`** (`energy|steadiness|coverage|overall`), NOT `why` (null
  on these). `take_index` is the origin badge.
* **`kind:"insert"`** (master mode) → a candidate block addition; span is
  zero-width at the document end.
* Accept/Keep post to the existing suggestion-feedback endpoint
  (`applied`/`dismissed`) using `snippet_id` + `take_session_id` (the
  latter fills the required `session_id`). **A replace/bold without
  `take_session_id` is not actionable — drop it.** After any Accept,
  **refetch** — the document reassembles server-side and the crossed text
  disappears on the next read.

## 3. Master-document badges & block decisions (`MASTER_DOCUMENT` on)

* **`pieces[]`** — `{piece_key, text, take_index, block_key, block_label,
  snippet_id, take_session_id, start, end}`. Render a subtle
  `` `${take_index}.0` `` badge per fragment (provenance; non-interactive
  except where a change is attached).
* **Block upgrade offers** arrive as `source:"new_take"` changes (§2).
  Accept → `POST /v2/explore/arc/<arc_id>/blocks/<block_key>/decide`
  `{action:"accept"|"keep", take_session_id:<echo>}` → 200 / 409
  `STALE_OFFER` / 409 `NOT_PENDING`. On 409, silently refetch.
* **Save** → `POST /v2/explore/arc/<arc_id>/ideal-text/save` →
  `{saved, saved_version}`. Resolves open offers as kept-mine and freezes
  the version.
* **`is_saved`** (on the GET) — true only when saved AND no offers pend.
  Gate the re-read button reveal on it (the save hides the take badges).

## 4. The two-state mic + the orphaned-recording fix

Three states, from the GET — **never a local optimistic flip**:

| `reread_done` | `reread_processing` | render |
|---|---|---|
| false | false | the **re-read mic** |
| false | **true** | **loading in the button's place** ("Finishing up your recording…") |
| true | — | the **"record another official take"** button |

* **Re-read** (state 1): record in place → `POST /v2/lab/recordings`
  multipart `recording_kind:"read"`, `paired_session_id:<latest_take>`
  (REQUIRED — unpaired read is 422), `read_target:"ideal_text"`,
  `ideal_version:<version>` (all **flat** fields). Goes to the coach; never
  render it back.
* **Guard (critical, from the orphaned-mic bug):** once a recording
  starts, a background poll/refetch of the ideal-text screen must NEVER
  unmount or navigate away from it. Cancel that screen's polling on
  leaving to record — the recording owns the foreground until stopped.

## 5. Context-aware official recording

The "record another official take" button (state 3 above) carries the
**red recording dot** and goes **straight to the recording screen with
the project's setup inherited** — no bounce back to the chat.

* On tap: `GET /v2/explore/arc/<arc_id>/setup` →
  `{arc_id, topic, audience, target_length_seconds, slides,
  presentation_ref}` → prefill + load slides.
* On submit: `POST /v2/lab/recordings` with **`continue_arc_id:<arc_id>`**
  (flat field). Do NOT send `take_index` (server numbers it); do NOT mint
  a fresh arc — that resets the count and splits the project.
* **Global "record official recording"** entry → a plain list of project
  titles (`GET /v2/user/trainings` → `topic` + `arc_id`; ignore
  thumbnails/counts) + a distinct **"Start a new topic"** button (today's
  blank setup, no `continue_arc_id` → a fresh project at 1.0).

## 6. Star iconography

* `star:"verified"` → **filled yellow star** (coach-verified only).
* `star:"suggestion"` → **empty outline star** (every unverified
  suggestion, including historical payloads).
* No `star` → no star. Never infer the icon from any other field.
* **No orange on click/focus.** Selection is shown by the popover / a
  neutral tint — never by turning suggestion text orange. The only orange
  text is the `{{orange:…}}` marker (approved/coach emphasis), always on.

## 7. Coach — audio-only annotation mode (T4)

New coach action: `POST /v2/coach/annotation-uploads` (coach/admin),
multipart `audio_file` + optional `label` → `201 {session_id, n_snippets,
annotation_mode}`. Audio only (video → 415). The uploaded audio is chopped
into labelable snippets and appears in the **existing coach review queue +
snippet UI** — the `/coach/queue` row now carries **`annotation_mode:
bool`**; badge those rows so they read as annotation vs a student take.
Exclude `annotation_mode` rows from the per-student roster grouping (they
have no student).

---

## Endpoint index (all live on `main`)

| Endpoint | Purpose |
|---|---|
| `GET /explore/arc/<id>/ideal-text[?version=N]` | the document + changes + pieces + badges |
| `POST /explore/arc/<id>/blocks/<key>/decide` | accept/keep a block upgrade |
| `POST /explore/arc/<id>/ideal-text/save` | accept-and-freeze |
| `POST /explore/arc/<id>/prior-take/decide` | accept/keep a prior-take change |
| `GET /explore/arc/<id>/setup` | inherited recording setup |
| `POST /lab/recordings` | takes; `continue_arc_id` / `recording_kind:read` |
| `GET /user/trainings` | project list (`topic` + `arc_id`) |
| `POST /coach/annotation-uploads` | coach audio → labelable snippets |
| `GET /coach/queue` | review queue (+ `annotation_mode`) |

No migrations owed by the FE. The document behavior is gated by
`LIVING_TRANSCRIPT_ENABLED` + `MASTER_DOCUMENT_ENABLED`; everything else is
unconditionally live.
