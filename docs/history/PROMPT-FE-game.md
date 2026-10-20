# FE prompt — The Key-Moments Game (Engine 5)

**Repo:** `frontend-cursor` · **Date:** 2026-07-28
**Status:** BE complete and LIVE on `main` since 2026-07-11 (`services/game_engine.py`,
routes in `routes/v2_routes.py`, covered by `test_game_engine.py`). No FE exists — this
document is the whole handoff. No migration pending except `add_game_saves.sql` if not yet
run in prod (save/list degrade gracefully without it).

**What it is for (founder's frame):** the user collects the moments where their voice
sounded confident. The game shows them their OWN moments — coach-confirmed key moments
mixed with neutral decoys — and they guess blind which is which. Reviewing your own
confident-voice moments is the hypothesis under test (does it down-regulate stress); every
answer is also a peer label the learning loop captures. The game is a training surface
AND an annotation surface at once — that duality is why the non-negotiables below exist.

---

## 0. Non-negotiables

| # | Rule | Why |
|---|---|---|
| N1 | **Truth is never in the rounds payload.** Render the rounds without any is-key styling difference; the user learns the truth only from the answer response. Never cache "which were keys" client-side across a replay. | The blind guess IS the product and the annotation. A tell in the UI poisons both. |
| N2 | **No scores, no streaks, no accuracy percentages.** After each answer show correct/incorrect + the "why" — never a running tally, never "7/10". | AC-9. The read is qualitative. |
| N3 | **Answers are labels.** Send exactly one POST per user decision; never auto-answer, never re-send on re-render (duplicates append as junk peer labels server-side). | Every answer persists into the learning corpus (`snippet_peer_labels`, second-order). |
| N4 | The `**keyword**` wrapping inside `why` paragraphs is a TINT contract, not markdown. Parse `**…**` (and `==…==`) spans and tint them orange; do not render bold. | The BE comment names the FE helper: `services/api/arcGame.ts splitTintedSegments`. |
| N5 | **A decoy is not a failure.** The reveal copy for `truth_is_key: false` must read as neutral ("this one was solid, not a key moment"), never as criticism. Copy needs founder sign-off. | The decoys are the user's own words; threat-labeled moments are decoys too and must never be called out as such. |

---

## FE-1 — Load the game

```
GET /v2/arc/<arc_id>/game            (auth: user JWT; the arc OWNER only — a coach gets 404)
GET /v2/arc/<arc_id>/game?snippet=<snippet_id>    // deep link: pin that moment as round 0
```

```jsonc
200 {
  "arc_id": "…",
  "rounds": [
    {
      "round": 0,                    // 0-based, already ordered (deterministic, replayable)
      "round_id": "uuid",            // IS the snippet id — echo it back on answer
      "snippet_id": "uuid",          // same value, explicit alias
      "transcript": "…",
      "audio_ref": "…",              // playback source (audio_segment_path preferred server-side)
      "start_offset_ms": 12345,      // may be null — clamp playback when present
      "duration_ms": 4200
    }
  ]
}
// Empty state — the coach hasn't challenge-labeled any moment yet:
200 { "arc_id": "…", "rounds": [], "reason": "NO_KEY_MOMENTS_YET" }
404 { "code": "NOT_FOUND" }          // arc not owned by the caller
500 { "code": "V2_ERROR" }
```

- Up to 10 rounds: ≤5 coach-confirmed key moments + an equal-or-smaller number of the
  user's own unmarked/threat moments as decoys. **A 1-round game is legal** (1 key, 0
  decoys) — design for tiny round counts, not a fixed 10.
- Same arc → same rounds in the same order, every time (sha1 ordering, no randomness).
  The `?snippet=` pin only reorders when that snippet is already among the chosen rounds;
  otherwise it is silently ignored — don't error on a stale deep link.
- Empty state is a valid state, not an error: "Your coach hasn't marked key moments here
  yet." (copy → founder sign-off).

## FE-2 — Answer a round

```
POST /v2/arc/<arc_id>/game/answers
{ "round_id": "uuid", "answer": true }        // true = "this is a key moment"
// aliases accepted: snippet_id, answer_is_key — prefer the canonical names
```

```jsonc
200 {
  "correct": true,
  "truth_is_key": true,
  "why": [                            // ≤3 paragraphs, render in order; **kw** spans = orange tint (N4)
    "The load-bearing words in this moment: **tripled** …",
    "A longer-than-usual pause tends to come right before your strongest moments.",
    "Comfortable pace, natural rise and fall."
  ],
  "keywords": ["tripled", "revenue"],  // the raw list, if you need it separately
  "video_ref": "…" | null              // coach's breakthrough video for this moment — top-level, not inside why
}
400 { "code": "INVALID_INPUT" }        // round_id not a UUID · answer not a strict boolean
404 { "code": "NOT_FOUND" }            // arc not owned
404 { "code": "SNIPPET_NOT_FOUND", "error": "That moment is not part of this training" }
500 { "code": "V2_ERROR" }
```

- `answer` must be a JSON boolean — `"true"` (string) is a 400.
- When `video_ref` is present, offer the coach's video on the reveal — it is the moment's
  breakthrough video, the strongest reveal content available.
- One POST per decision (N3). Disable the buttons while in flight.

## FE-3 — Save + history

```
POST /v2/arc/<arc_id>/game/save      // no body → 200 { "saved": true, "arc_id": "…" }
GET  /v2/user/game-sessions          // → 200 { "sessions": [{ id, arc_id, saved_date, created_at, saved_at }] }
```

- Save is a bookmark, idempotent per (user, arc, day). Rounds are NOT frozen in a save —
  reopening re-derives them from current coach truth, so a saved game can have more (or
  different) rounds than when saved. Don't promise "resume exactly where you left off";
  frame it as "practice this talk again".
- Read `saved_at` for display (it aliases `saved_date`; `created_at` is the row timestamp).

## FE-4 — Suggested flow (not locked; all copy → founder sign-off)

1. Entry from the arc surface once the coach has labeled ("Practice your key moments").
2. Per round: play the audio (clamped to `start_offset_ms`/`duration_ms` when present),
   show the transcript, two buttons: **Key moment** / **Solid, not key**.
3. Reveal: correct/incorrect (qualitative, N2), the tinted `why` paragraphs, the video
   when present.
4. End of rounds: offer Save. No summary score screen (N2) — end on the library framing:
   these moments are yours to come back to.

## Gotchas

- The route docstrings still mention a 402 — stale; the $25 gate is retired, no 402 path
  exists in code. The game is free.
- A coach or admin cannot open a student's game (404 by ownership) — don't build a coach
  preview against these endpoints.
- Empty-transcript snippets never appear as rounds; you can rely on `transcript` being
  non-empty.
- Answer side-effects are best-effort server-side: a peer-label write failure still
  returns 200 — never block the reveal on anything but the HTTP response itself.

## Open (do not guess)

1. Where the game entry lives (arc page? readout? its own tab) — founder's call.
2. All reveal/empty-state copy — founder sign-off before ship (N5).
