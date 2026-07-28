# FE prompt — Training corpus: audio import + confidence labelling

**Repo:** `frontend-cursor` · **BE branch:** `feat/training-corpus` (`cde9abb`)
**Date:** 2026-07-28 · **Status:** BE complete, CI green, contracts pinned and safe to build against
**Migrations owed before it works in prod:** `add_confidence_labels.sql`, and
`add_admin_import_fields_to_recordings.sql` if never run (the import degrades without it)
**Surface: COACH ONLY.** Nothing here appears for a normal user, ever.

---

## Why this exists

The app's core function is recognising the **confident snippet** — vocal *and* verbal cues.
To train that, the coach needs a corpus: upload real human speech from outside the app
(other people's talks, an archive, YouTube), have it chopped into pieces, and label each
piece *confident yes/no, and how strongly*. That corpus is the whole point; every screen
below serves it.

The imported audio is **never a project the speaker owns** — it doesn't appear in anyone's
history, and it's deliberately excluded from per-speaker acoustic baselines (a corpus of
fifty voices under one account would corrupt that account's own norm).

---

## 0. Non-negotiables

| # | Rule | Why |
|---|---|---|
| N1 | **Never show a machine confidence read on the labelling screen.** No score, no band, no "the system thinks…", no colour-coding, no sorting by it. The queue payload deliberately omits all of it. | BLIND COACH. The composite chooses *who gets asked*; the coach decides *the answer*. A visible hint makes the label a confirmation of the machine, and the corpus becomes circular. |
| N2 | **Don't re-sort the queue.** Render in payload order. The order is deliberately band-shuffled so position isn't a tell. | Same reason as N1 — an ordering tell anchors labels as effectively as a visible score. |
| N3 | **`confident` is required; `intensity` is optional.** Never send `intensity` alone, and never default `confident` to a value the coach didn't pick. | An unpicked default silently fabricates training data. |
| N4 | **Coach-only surface.** No entry point, route, or menu item reachable by a normal user. | Users get full analysis with no choices (§4). |
| N5 | Import stages are **coach-only ticks**. Never surface them on the normal record/upload flow. | A half-analysed take is a broken deliverable for a real user. |

---

## FE-1 — Import audio (the upload screen)

```
POST /v2/coach/training-imports        multipart, coach/admin JWT
```

**One file per request** — deliberate. A batch endpoint would either block for minutes or
need a job queue; per-file requests give you real progress and per-file failures. For a
folder of 30, fire them **sequentially** (the analysis is CPU-heavy; parallel mostly
produces timeouts).

```jsonc
// form fields
audio_file       (required)  webm | mp3 | m4a | wav | ogg | flac | mp4 …
topic            (required)  what the talk is about — labels it on the review screen
speaker_label    (optional)  whose voice this is  ← see the note below
user_id          (optional)  defaults to the uploading coach
note             (optional)  free-text provenance ("2019 conference, YouTube")
stages           (optional)  comma-separated ticks, default "confidence"
queue_per_band   (optional)  how many pieces per band to queue (default 5)

// 200
{ "ok": true, "session_id": "…", "arc_id": "…", "recording_id": "…",
  "snippet_count": 42,        // pieces cut
  "queue_count": 15,          // pieces queued for labelling
  "stages": ["confidence"],
  "duration_sec": 612.4, "speaker_label": "Jane Doe", "filename": "talk.mp3" }

// 422 — the same content gate live takes pass (silence / corrupt / too short)
{ "code": "AUDIO_REJECTED", "reason": "too_short", "error": "…" }
// 400 missing audio_file or topic · 500 { code, reason, error }
```

**Worth nudging in the UI:** `speaker_label` is optional to the API but it is the only
grouping key a per-speaker model will ever have. A corpus without it can't tell whose
voice a piece is. Prefill it per batch.

### The stage ticks (N5)

| Tick | Default | What it costs | What it's for |
|---|---|---|---|
| `confidence` | **always on, not un-tickable** | Whisper only | transcript, pieces, acoustics, the confidence read, the label queue — **this is the corpus** |
| `analytics` | off | ~16 LLM calls per file | the advice layers (stars, say-it-stronger) — only if training the *advice* model |
| `ideal_text` | off | LLM compose | the assembled ideal text — a user deliverable, irrelevant to training |

Render `confidence` as a checked, disabled checkbox with a one-line reason, not as a
hidden implicit — the coach should see that it's always on. On a 50-file batch the other
two are the difference between minutes and hours.

## FE-2 — The corpus index

```
GET /v2/coach/training-imports              → { imports: [...], count }
GET /v2/coach/training-imports?user_id=…    → filtered
```

```jsonc
{ "imports": [
    { "session_id": "…", "arc_id": "…", "topic": "…",
      "speaker_label": "Jane Doe" | null, "created_at": "…" } ],
  "count": 12 }
```

Each row opens two things: the **labelling queue** (FE-3, `session_id`) and — if the
coach ticked `analytics` — the normal **star review** at
`GET /v2/coach/arc/<arc_id>/stars`, which already works on imports with no changes.

## FE-3 — The labelling screen (the important one)

```
GET /v2/coach/sessions/<session_id>/confidence-queue
```

```jsonc
{ "session_id": "…", "count": 15, "labelled": 4,
  "queue": [
    { "snippet_id": "uuid",
      "transcript": "…",              // the words
      "audio_ref": "…",               // play this
      "start_offset_ms": 12345,       // clamp playback to the piece
      "duration_ms": 4200,
      "session_id": "…",
      "label": { "confident": true, "intensity": 4 } | null   // this coach's prior call
    } ]
}
404 · 500
```

The queue is sampled **across the confidence spectrum** — some pieces the system reads as
confident, some middling, some doubtful — so the corpus contains the negative examples a
binary recogniser needs. **Which band a piece came from is not in the payload and must not
be inferred or displayed** (N1/N2).

```
PUT /v2/coach/snippets/<snippet_id>/confidence-label
{ "confident": true, "intensity": 4, "note": "optional, never shown to anyone" }

200 { "saved": true, "snippet_id": "…", "confident": true, "intensity": 4 }
400 { "code": "INVALID_INPUT", "error": "…" }   ← surface verbatim
404 · 500 (500 names the migration when unrun)
```

- `confident` must be a **real JSON boolean** — `"true"` is a 400, not a coercion.
- `intensity` is **1–5** or omitted. It's the same scale used in the research this is
  anchored to, so the numbers are comparable to published data — worth a tooltip
  (1 = barely, 5 = unmistakably), but **no band labels on the buttons**.
- Re-labelling replaces this coach's call; other raters' labels are untouched.

**Suggested interaction** (not locked; copy needs founder sign-off): play the piece,
show the words, then `Confident? [Yes] [No]` and — once answered — a 1–5 row. Auto-advance
to the next unlabelled piece. Show progress as `4 / 15 labelled`, **not** as a score.

## FE-4 — What must NOT change

The normal user's upload path (`POST /v2/lab/recordings`) is **untouched**: full analysis,
no stage choice, no tick UI. Do not surface stages, the import lane, or the labelling
screen anywhere a non-coach can reach (N4).

---

## Before it works in prod

- `migrations/add_confidence_labels.sql` — until it runs, the label PUT 500s with a message
  naming it; the queue still loads and plays.
- `migrations/add_admin_import_fields_to_recordings.sql` — if never run, imports still work
  but lose provenance (`speaker_label` etc.); it logs and degrades.

## Open (do not guess)

1. Where the coach reaches this — its own section, or inside the existing coach panel.
2. All copy on both screens — founder sign-off.
3. Whether a coach may label **their own students'** real takes through the same screen
   (the endpoints allow any session id; only the UI decides). Founder's call — it changes
   what the corpus is made of.
