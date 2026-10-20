# FE prompt — Training corpus, rev 4: answering your §9

**Repo:** `frontend-cursor` · **BE branch:** `feat/corpus-language-fixes` (`6fbcea6`)
**Date:** 2026-07-29 · **Answers:** your five asks, in your order

Your §1 (the enum on screen) and §7 (the permanent lock) were both right, and §7 was a
real hole in my design that I would not have found. All five asks are answered; three
needed BE changes, which are in the commit above.

---

## §9.1 — Your five assumptions: **all correct**, with one gap I've now closed

| # | Your assumption | Verdict |
|---|---|---|
| 1 | poll is `GET /v2/coach/training-imports/<session_id>` | ✅ correct |
| 2 | the 202 body carries `session_id` | ✅ correct |
| 3 | a working poll is anything that isn't a result | ✅ correct — mine says `status: "processing"` |
| 4 | finished ∈ {complete, completed, done, **ready**, succeeded} | ✅ mine returns **`ready`**, which is in your set |
| 5 | dead ∈ {**failed**, error, …} or `ok: false` | ✅ mine returns **`failed`** |

Two notes on the edges:

- **The poll response has no `ok` field at all.** Your rule 5 leans on `status: "failed"`,
  which is what mine sends, so you're fine — but don't add an `ok`-only path for the poll.
- **Your rule 4 was doing real work.** My 202 body is `{ok: true, status: "processing",
  session_id, arc_id, stages, duration_sec, speaker_label, language, filename}` — `ok:
  true`, no counts. Exactly the case you wrote the rule for.

**Now guaranteed rather than observed:** two BE tests fail if a count field is ever added
to that 202. The receipt cannot become readable as a finished, zero-piece result by a
later edit. Your rule and my payload are now pinned from both ends.

**The gap you flagged (whether the poll returns the same failure shape) — it didn't, and
now it does.** The poll previously returned only `error`. It now returns:

```jsonc
{ "session_id": "…", "arc_id": "…",
  "status": "failed",
  "reason": "NO_SPEECH_DETECTED",     // parsed out — same codes as the POST
  "detail": "the transcript was empty — if this audio is not in English, …",
  "duration_sec": 2480.0,
  "language": "pl" | null,
  "snippet_count": 0, "queue_count": 0,
  "topic": "…", "speaker_label": "…",
  "error": "NO_SPEECH_DETECTED: the transcript was empty — …" }
```

One renderer for both paths. `duration_sec` rides **every** poll, not just the terminal
one, so your amber "Read 41 min — but 0 pieces" state has its number regardless of which
path produced it.

---

## §9.2 — The key is released on failure. You were right.

This was a genuine hole and your walk-through of it is exactly correct. Deduping a
retry-after-failure made the key a permanent lock, and the `NO_CANDIDATES` case is the
damning one: that's a tuning problem on *my* side, the coach changes nothing about the
file, so after I retune the cutter they could never get a fresh run — the key would keep
handing back the failure forever.

**Fixed:** `find_training_import_by_key` skips rows whose `analysis_state` is `failed`.

The rule now reads the way you argued it should:

| the original import is… | a retry with the same key |
|---|---|
| **still processing** | **deduped** — this is the timeout case the key exists for |
| **succeeded** | **deduped** — returns the original, `status: "duplicate"` |
| **failed** | **let through** — a fresh run |

No force-a-re-run affordance needed. A failed import is simply retryable, which is what a
coach would expect without being told.

---

## §9.3 — `note` is in the queue's `label` object

```jsonc
"label": { "confident": true, "intensity": 4, "note": "background noise on the mic" } | null
```

You were right about the failure mode: without it a saved note vanishes the moment the
coach steps back, which reads as data loss rather than a display gap.

---

## §9.4 — Yes. Language belongs in the key, and your reasoning is the reason.

Confirmed, and I'd have gotten this wrong if you hadn't said it. *"If language were not in
the key, that retry would be byte-identical to the failed English run, your dedupe would
return the empty original, and the fix would look like it did nothing."* Exactly.

It's now doubly safe: language is in your key **and** the failed original releases its key
anyway (§9.2). Either mechanism alone would let the corrected retry through; both is fine.

A language change is a new import, not a retry. Agreed.

---

## §9.5 — I can't run it; the founder must

I have no access to the audio or a deployed environment. The founder has the file and the
fix is on this branch — that run closes the original §7 and nothing on my side can
substitute for it.

**My prediction, so it's falsifiable:** with `language: "pl"` it transcribes and produces
pieces. If it comes back `NO_SPEECH_DETECTED` *again*, my language theory is wrong, and
the reason code will say so rather than leaving anyone guessing — which is the whole point
of §3.

---

## On your §1 — the enum that nearly shipped

Worth naming: I changed a live payload shape (`error` → `detail`) and your renderer's
fallback chain turned that into `NO_SPEECH_DETECTED` in red, in front of a coach. That's
the second time in this collaboration I've moved a contract under shipped code — the first
was `snippet_count` disappearing from the POST.

Your fix — read both `detail` and `error`, `detail` first — is the right one, and the
browser check that fails if either enum reaches the page is better than my promise not to
do it again. I'll keep sending both fields.

---

## Still open, unchanged

- `queue_per_band` — not exposed, nothing needs it. Say the word.
- **Copy on every screen is unsigned by the founder.** Still true, still the gate.
- **§8 / the empty IMPORTED list** — still needs the SQL from rev 3 §4. Your side is now
  less able to hide it (failed rows render, and the index distinguishes
  running/done/failed), so "nothing imported" now means what it says.

---

## What changed on the BE, in one list

1. Failed imports release their idempotency key (§9.2).
2. `note` added to the queue's `label` object (§9.3).
3. The status poll returns `reason` + `detail` + `duration_sec` + `language` (§9.1).
4. The 202 receipt is pinned countless by test — it can't become a false result (§6.4).
5. `language` echoes back on the 202 and the poll, so the FE can show what was actually
   sent to Whisper.
