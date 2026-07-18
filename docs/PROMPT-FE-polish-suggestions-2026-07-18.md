# FE handoff — polish as suggestions + re-read mic (paste into `frontend-cursor`)

Founder 2026-07-18. The ideal text was silently replacing the speaker's words with the compose LLM's "light polish." Now the BE **serves the verbatim words** and offers each polish as an **approvable grey star** — the same star machinery you already built, plus one new label and one bottom mic. Behind BE flag `POLISH_AS_SUGGESTIONS_ENABLED` (on top of `MOMENT_SUGGESTIONS_ENABLED`); build safe-ahead.

## What changed on the wire (all additive)
`GET /v2/explore/arc/<id>/ideal-text` — the SD `key_moments[].suggestion` object now carries **`trigger`** alongside `kind`/`replacement`/`why`:

```jsonc
"suggestion": {
  "kind": "replace",
  "replacement": "It is not about winning, it is about growth.",  // the polished version
  "why": null,                 // polish has no generated why
  "trigger": "polish"          // NEW — "polish" | "threat" | "profanity" | "stickiness"
}
```

Everything else is unchanged: the star is grey (`star: "suggestion"`), `anchor` is the speaker's **verbatim** words (a substring of the served `text`), Approve/Revert go through the existing `POST /user/snippets/<id>/suggestion-feedback` with target `moment_replace`, and on Approve the BE folds verbatim→polished into the served text (same as any replace).

## FE-1 — label a polish star distinctly
In `mapKeyMoment`, read `suggestion.trigger`. When `kind === "replace"` and `trigger === "polish"`, the sheet is a **flow suggestion**, not a "your words are weak" replace. Copy (propose for founder sign-off; keep it warm/neutral):
- Sheet label: **"Smoother version"** (vs the existing "Try instead" for threat/profanity/stickiness replaces)
- Body: the snippet plays on top (existing clamped player), then the polished `replacement` shown as the alternative, then **Approve** / **Undo**.
Unknown/absent `trigger` on a replace → fall back to today's "Try instead" copy (safe-ahead).

## FE-2 — the re-read microphone (founder's explicit ask)
On the ideal-text screen (the post-recording `IdealTextReadout` AND the notebook), add a **microphone at the bottom** wired to the existing re-read pipeline (`recording_kind: "read"` + `paired_session_id` = the current take). This lets the user **read the whole corrected text aloud** and send it for analysis — the reading becomes the next refinement input and produces the next ideal-text version. This is the same `onReadAloud` mechanism already on the notebook; surface it as a persistent mic control, not a one-off button. Copy: **"Read it aloud"** / after tapping, **"Send for analysis"** (founder-approved earlier).

## FE-3 — no silent bold under this flag
Under polish mode the BE serves plain verbatim (no `**bold**` key-phrase markers). So the text should render clean, with emphasis appearing **only** when the user approves an emphasize (charisma) star. Nothing to build — just don't reintroduce client-side auto-bolding.

## Verify
tsc + vitest + build + adversarial review. List any new copy string verbatim in the commit for founder sign-off. The two new strings above ("Smoother version" and the re-read labels) need his OK.

## Note on granularity (for the founder, not a blocker)
The polish is offered **per pick/paragraph** (Approve swaps the whole paragraph verbatim→polished), because the compose rewrite is holistic, not word-level. If he wants per-phrase diffs ("deserving more → worthy of more"), that's a separate future feature (a verbatim↔edited diff), not this ticket.
