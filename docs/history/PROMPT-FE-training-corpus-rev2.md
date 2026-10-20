# FE prompt — Training corpus, rev 2 (answers to your handoff)

**Repo:** `frontend-cursor` · **BE branch:** `feat/training-corpus-async` (`931d1fe`)
**Date:** 2026-07-28 · **Replaces:** the §1/§2 open items in `PROMPT-FE-training-corpus.md`
**Status:** BE complete, full suite green. Two contract changes below — both make your side simpler.

---

## §1 — You were right. The import is now async, and idempotent.

I didn't try to find the ceiling, because your framing made it clear the ceiling is the
wrong thing to chase: on a 45-minute conference talk this is minutes of Whisper, so any
cap short of "several minutes" loses, and the failure you described — **a timeout on a
request whose BE work then succeeds** — is the one that quietly corrupts the corpus.

Both halves are fixed:

### The POST now returns 202 in a second or two

```jsonc
POST /v2/coach/training-imports        // same multipart fields as before
202 {
  "ok": true, "status": "processing",
  "session_id": "…", "arc_id": "…",
  "stages": ["confidence"], "duration_sec": 612.4,
  "speaker_label": "Jane Doe", "filename": "talk.mp3"
}
422 { "code": "AUDIO_REJECTED", "reason": "too_short", "error": "…" }   // still synchronous — the gate runs before the 202
400 · 500
```

The 202 means *stored and queued*, **not** *analysed*. Everything expensive now runs in a
background thread. Set your FE budget back to something ordinary — this returns as fast as
the upload itself.

### Poll for the outcome

```jsonc
GET /v2/coach/training-imports/<session_id>
200 {
  "session_id": "…", "arc_id": "…",
  "status": "processing" | "ready" | "failed",
  "topic": "…", "speaker_label": "…",
  "snippet_count": 42,     // 0 until ready
  "queue_count": 15,       // 0 until ready
  "error": null            // a short reason when status is "failed"
}
404 · 500
```

A crashed analysis stamps `failed` — the poll always terminates, never hangs on
`processing` forever. Suggested cadence: every 3–5s, and it's fine to run the next file's
upload while the previous one analyses (the BE handles concurrent imports; just keep the
*uploads* sequential as you already do).

### Send `upload_idempotency_key` — yes, please

```
upload_idempotency_key   (optional but wanted)   any stable client token per file
```

Same field name as the coach-video lane, so it'll look familiar. A retry carrying a key
that was already used returns the **original** import and creates nothing:

```jsonc
200 { "ok": true, "status": "duplicate", "session_id": "…", "arc_id": "…", "queue_count": 15 }
```

Note it's **200 + `status: "duplicate"`**, not 202 — you can treat it exactly like a
success, and if you want to tell the coach "already imported", that's the flag.

Generate it per file and **keep it stable across retries of that same file** (a content
hash, or a uuid you mint once per file and reuse). It's checked before the gate, the
upload and any DB row, so a retry costs nothing. If the lookup itself fails, the import
proceeds — refusing a legitimate first import is worse than the duplicate the key exists
to prevent.

**With 202 + the key, the duplicate scenario is structurally gone.** Your option 3, plus
the belt you offered.

---

## §2 — `audio_ref` is now a resolved, playable URL

Confirmed and fixed. The queue resolves it before serving: absolute `http(s)` URLs pass
through untouched, storage keys are **presigned for 6 hours** — long enough for a coach to
work through a queue without links expiring mid-batch.

You were right about why it matters: a bare key renders a dead player and the surface
silently degrades to labelling *text*, which is a different task and produces a corpus of
a different thing. If a key ever fails to sign, it's passed through as-is rather than
nulled — so a broken player is a visible bug, not a missing field.

---

## §3 — Your write pattern found a real bug. Fixed.

You wrote: *"Yes/No saves on its own (one PUT); picking a grade re-sends the same answer
with the intensity."* That's fine — but it exposed something on my side.

The upsert was **partial**: it only wrote `intensity` when present. So a coach who
answered *Yes → 4*, then changed their mind and tapped *No*, sent `{confident: false}`
alone — and the stored row kept `intensity: 4`. A 5-point grade attached to a "no" that
nobody graded, sitting in the training corpus.

The upsert is now **full-state**: an omitted `intensity` writes NULL. Your two-write
pattern is safe exactly as built, and a flipped answer now clears the stale grade.

Nothing to change on your side — I'm flagging it because it means **any label you
recorded against the pre-fix BE could carry a stale grade**. If you tested the flip path
during development, clear those rows.

---

## §4 — Your other points, confirmed

| Your item | Answer |
|---|---|
| `stages` always starts with `confidence` | Correct, and the BE forces it anyway — you can't produce an invalid combination. |
| `user_id` never sent | Right; defaults to the uploading coach. |
| `queue_per_band` never sent | Default 5 stands. **Worth exposing eventually**: for a short talk 5-per-band may exceed the pieces available (you'll just get fewer), and for a long archive talk a coach might want 10. Not urgent. |
| `note` on labels not sent | Fine. The column exists whenever you want it — per-label provenance ("hard to call", "background noise") would be useful corpus metadata, so add the field when it's cheap. |
| Two writes per graded piece | Safe (see §3). Write volume is trivial at corpus scale. |
| Founder's answers 1–3 | All noted. **Imports-only labelling is the right call** — it keeps the confidence corpus and the blind direction-labelling lane disjoint, so the same coach never gives both kinds of label on the same audio. That separation is worth protecting; if it ever changes, tell me, because it changes what the corpus *is*. |

---

## §5 — On your fence test

`corpusFence.test.ts` refusing the read-carrying lanes *at the import level* is stronger
than anything I can enforce from here, and the dev harness serving a decoy `band` /
`confidence_score` so a leak fails a browser test is a genuinely good idea — that's the
kind of fence that survives a refactor by someone who wasn't in this conversation.

Your ask — *keep the payload free of the read anyway* — is already the contract and is
pinned by a BE test (`queue_payload` is an allowlist, and a test feeds it a snippet
polluted with `voice_confidence` / `acoustic_read` / a tone word and asserts none of it
survives). Two fences, both sides. Good.

---

## Unchanged

Migrations (`add_confidence_labels.sql`, `add_admin_import_fields_to_recordings.sql`), the
stage ticks, the queue's blind payload, coach-only gating. Everything in
`PROMPT-FE-training-corpus.md` still holds except §1's shape and §2's `audio_ref` note.
