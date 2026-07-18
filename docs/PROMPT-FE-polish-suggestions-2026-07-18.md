# FE handoff — polish as suggestions, Approve all, re-read mic (paste into `frontend-cursor`)

Founder 2026-07-18 (rev 2: + the Approve-all button). The ideal text was silently replacing the speaker's words with the compose LLM's "light polish." The BE now **serves the verbatim words** and offers each polish as an **approvable grey star** — the star machinery you already built, plus one label, one bulk button, one bottom mic. Behind BE flag `POLISH_AS_SUGGESTIONS_ENABLED` (on top of `MOMENT_SUGGESTIONS_ENABLED`); build safe-ahead.

## What changed on the wire (all additive)
`GET /v2/explore/arc/<id>/ideal-text` — the SD `key_moments[].suggestion` object now carries **`trigger`**, clamped server-side to exactly `"polish" | null` (the internal trigger vocabulary never rides a user payload):

```jsonc
"suggestion": {
  "kind": "replace",
  "replacement": "It is not about winning, it is about growth.",  // the polished version
  "why": null,                 // a polish has no generated why
  "trigger": "polish"          // "polish" | null (null = the existing replace kinds)
}
```

Everything else is unchanged: grey star, `anchor` = the speaker's **verbatim** words (substring of the served `text`), Approve/Revert via the existing `POST /user/snippets/<snippet_id>/suggestion-feedback` (`target: "moment_replace"`, `action: "applied" | "reverted"`), BE folds verbatim→polished into the served text on the next fetch.

## FE-1 — label a polish star distinctly
In `mapKeyMoment`, read `suggestion.trigger`. `kind === "replace" && trigger === "polish"` → the sheet is a **flow suggestion**, not a "your words are weak" replace:
- Sheet label: **"Smoother version"** (vs the existing "Try instead")
- Body: snippet playback on top (existing clamped player), the polished `replacement` as the alternative, **Approve** / **Undo**.
`trigger` null/absent → today's "Try instead" copy (safe-ahead).

## FE-2 — the Approve-all button (founder 2026-07-18)
When the text has **2+ un-applied polish stars** (`trigger === "polish"` only — acoustic and structural stars stay strictly per-star; the founder's earlier no-apply-all rule still holds for them), show one **"Approve all"** control near the text (e.g. beside the status chip).

- Tap → optimistically fold **every** polish star at once (each span swaps verbatim→polished, stars vanish), and fire the existing per-star POST for each: `{target: "moment_replace", action: "applied"}`. **No new BE endpoint — this is N per-star calls**, which keeps every approval individually recorded and individually revertible.
- Partial failure: keep the optimistic fold (the next refetch reconciles — un-persisted ones return as stars); no error modal for a background write.
- **Undo all** replaces the button until the screen closes → fires `action: "reverted"` per star and unfolds. Per-star Undo in each sheet still works independently.
- Scope note for the founder (flag if wrong): Approve-all covers **polish stars only**, on the reasoning that flow-smoothing is mechanical while acoustic/structural stars are judgment calls.

## FE-3 — the re-read microphone (founder's explicit ask)
On the ideal-text screen (post-recording `IdealTextReadout` AND the notebook), a **persistent microphone at the bottom**, wired to the existing re-read pipeline (`recording_kind: "read"` + `paired_session_id` = the current take): the user reads the whole corrected text aloud and sends it for analysis — the reading becomes the next refinement input and produces the next ideal-text version. Same `onReadAloud` mechanism already on the notebook; surface it as a fixed bottom control, not a one-off button. Copy: **"Read it aloud"** → while recording/after, **"Send for analysis"** (founder-approved earlier).

## FE-4 — no client-side bolding under this flag
Under polish mode the BE serves plain verbatim (no `**bold**` key-phrase markers). Render clean; emphasis appears **only** when the user approves an emphasize (charisma) star. Nothing to build — just don't reintroduce auto-bolding.

## Verify
tsc + vitest + build + adversarial review. List every new copy string verbatim in the commit for founder sign-off — expected: **"Smoother version"**, **"Approve all"**, **"Undo all"** (plus the previously-approved "Read it aloud" / "Send for analysis").

## Granularity note (for the founder, not a blocker)
A polish star swaps a **whole pick/paragraph** verbatim→polished (the compose rewrite is holistic). Per-phrase word diffs would be a separate future feature.
