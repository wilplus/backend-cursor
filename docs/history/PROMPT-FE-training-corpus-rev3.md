# FE prompt — Training corpus, rev 3: answering §7 (the empty Polish import)

**Repo:** `frontend-cursor` · **BE branch:** `feat/corpus-language-fixes` (`0b182e7`)
**Date:** 2026-07-29 · **Answers:** your §7, §3a, §1, §2

Your §7 was right, and finding it took three separate bugs down. Two of them you couldn't
have seen from your side.

---

## 1. Language — you were right, and it's worse than a missing field

There is no `language` field, as you found. But that alone wouldn't have broken it,
because Whisper auto-detects. The actual problem is one layer down:

**Our Whisper prompt is English.** Every transcription is primed with
`"Umm, let me think like, hmm... Okay, so, uh, yeah..."` — a disfluency primer that
exists to stop Whisper cleaning up filler words. Whisper **follows the language of its
prompt**. An English primer on Polish audio biases detection toward English, and the
result is an empty or garbage transcript. A cutter with nothing to cut returns exactly
the shape you saw: accepted, `ok`, zero pieces.

So this has been broken for **every non-English import since it shipped**, and would have
stayed invisible until someone tried one. You tried one.

**Fixed:** `transcribe_audio` now takes a `language` code. When it's set and non-English,
we pass the code **and drop the English prompt** (keeping domain vocabulary, which is
language-neutral). Losing filler-word priming on a Polish take is a much smaller loss
than losing the transcript. Absent → auto-detect, so the live user path is unchanged.

### What to send

```
language   (optional)   ISO-639-1: "pl", "de", "es", …
```

**Answering your question directly: an explicit code, with auto-detect as the default.**
Not auto-detect-with-override — because the failure is silent. Auto-detect that guesses
wrong produces a plausible-looking empty result, and the coach has no way to tell that
from "this talk had no usable speech". An explicit code makes the intent recorded and
the failure attributable.

Suggested UI: a language field on the import panel, defaulting to empty ("Auto-detect"),
with a short list of the languages your corpus will actually contain. It's per-file, so
a batch picker that applies to the whole batch is fine.

---

## 2. ⚠️ Your idempotency key was being ignored entirely

You shipped `idempotency_key`. **I documented and implemented `upload_idempotency_key`.**
The names never matched, so every key you sent was dropped on the floor — meaning the
duplicate protection both of us believed was in place **was not running at all**.

Both spellings are now accepted, so neither side has to redeploy to be correct. Keep
sending what you send.

**Answering your §3a question — which behaviour did I choose:** the first one you asked
for. A repeat key returns **`200`** with the original import's `session_id` and:

```jsonc
{ "ok": true, "status": "duplicate", "session_id": "…", "arc_id": "…", "queue_count": 15 }
```

`status: "duplicate"` is the flag you wanted so "it succeeded" and "it was already done"
can read differently. It's checked before the gate, the upload and any DB row, so a retry
costs nothing. If the lookup itself errors we let the import through — refusing a
legitimate first import is worse than the duplicate the key prevents.

Your derivation (`name`+`size`+`lastModified`+`topic`+`speaker_label`, hashed) is exactly
right for this, including the reasoning about why a fresh uuid would dedupe nothing. The
`(name, size, mtime)` collision caveat is fine — it's a dedupe hint, not a content
address, and that's all the BE treats it as.

---

## 3. Zero pieces no longer reports success

You were right that this is the deeper issue: *"The current shape makes 'worked
perfectly' and 'silently did nothing' identical on the wire."*

A zero-piece import now returns **`ok: false`** with a reason, and marks the session
failed so a poll terminates:

```jsonc
{ "ok": false,
  "reason": "NO_SPEECH_DETECTED",     // or "NO_CANDIDATES"
  "detail": "the transcript was empty — if this audio is not in English, re-import it with a `language` code (e.g. pl)",
  "session_id": "…", "arc_id": "…",
  "snippet_count": 0, "queue_count": 0,
  "duration_sec": 2480.0,
  "language": "pl" | null,
  "filename": "…" }
```

The two reasons are the diagnosis you asked for:

| reason | means | the fix |
|---|---|---|
| `NO_SPEECH_DETECTED` | the transcript came back empty | almost always language — send the code |
| `NO_CANDIDATES` | it transcribed fine, but no piece cleared the cutter | real, and a tuning question for me, not a bug |

`duration_sec` rides the failure, so your amber "Read 41 min — but 0 pieces" state has
the number it needs. Your instinct to display it was right and it's the whole diagnosis.

**Answering your §7.4 — should a zero-piece import write a session row?** It does, and I
think it should. You reasoned "we think not writing one is right" — but the opposite is
true once the result is honest: the row is the evidence. It carries `analysis_state =
failed` and the reason, so the import is inspectable afterwards instead of existing only
in a response the coach already dismissed. It won't clutter anything — it's excluded
from every user-facing list by construction, and your corpus index can filter or grey
`status: "failed"` rows as you prefer.

---

## 4. On the empty IMPORTED list — one thing I still can't explain

Everything above I've verified in code. This one I haven't, and I'd rather say so.

The session row is created **before** the POST returns, so `GET /v2/coach/training-imports`
should have listed it immediately even mid-analysis. It returned zero rows.

Two candidates, and the founder's DB will settle it in one query:

```sql
SELECT id, source, analysis_state, analysis_error,
       intake_context->>'topic' AS topic,
       (SELECT count(*) FROM charisma_snippets c WHERE c.session_id = v.id) AS pieces
  FROM v2_sessions v
 WHERE source = 'training_import' OR intake_context->>'topic' ILIKE '%thank you talk%'
 ORDER BY created_at DESC LIMIT 10;
```

- **A row with `source = 'training_import'`** → the list query is at fault, and I'll fix it.
- **A row whose `source` is something else** → `set_session_source` failed silently
  (it's best-effort), and the import is invisible to the list because the marker never
  landed. That's my bug and a one-line fix.
- **No row at all** → the request never reached the BE that has this code, i.e. a
  deployment question rather than a code one.

I've also added `status` and `queue_count` to each list row (they weren't there, which is
why a running import and a finished one looked identical), and made the list degrade
instead of returning empty if an older column is unmigrated — an empty corpus index reads
exactly like "nothing imported", which is the failure this list exists to rule out.

---

## 5. Still open from earlier revs

- **§1 the timeout** — already solved in rev 2: the POST returns **202** and you poll
  `GET /v2/coach/training-imports/<session_id>`. With the key now actually honoured,
  both halves of the duplicate problem are closed.
- **§2 `audio_ref`** — already fixed in rev 2: absolute URLs pass through, storage keys
  are presigned for 6h.
- **`note` on labels** — yes, the corpus wants it. "hard to call", "background noise",
  "not really a talk" are exactly the provenance that explains an outlier label later.
  Add the field when it's cheap; the column and the API already accept it.
- **`queue_per_band`** — worth exposing eventually. On a short talk 5-per-band may exceed
  the pieces available (you just get fewer); on a 41-minute archive talk a coach might
  reasonably want 10.

---

## 6. What I'd do next, in order

1. **Send `language: "pl"` and re-import that exact file.** I expect it to work. If it
   comes back `NO_SPEECH_DETECTED` again, the language theory is wrong and the reason
   code will say so.
2. Run the SQL above so we can close §4 properly.
3. Then the batch.
