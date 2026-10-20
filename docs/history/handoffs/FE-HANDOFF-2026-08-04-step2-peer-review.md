# FE handoff — coaching chat STEP 2 becomes the peer-review flag

**Date:** 2026-08-04 · **From:** BE (backend-cursor) · **Founder-signed copy.**

STEP 2 of the state-machine coaching chat used to ask *"would you actually
label your voice here as Charismatic?"* and wire its Yes/No to
`POST /v2/user/snippets/<id>/label`. That route was deleted with the stress
lane (2026-08-03, PR #331) and your BFF proxy for it went in the same pass —
so **the button has been inert since then**. Nothing regressed; nothing was
captured either.

The founder has now signed the replacement copy. STEP 2 validates **the AI's
pick**, and its answer lands in the peer-review corpus.

---

## 1. What changed in the turn payload

`POST /v2/coaching/state-machine/turn` — STEP 2 turns only.

| | Before | Now |
|---|---|---|
| `triggers[]` | `show_charisma_label_buttons` | **`show_confidence_review_buttons`** |
| Question (in `narration`) | "Would you actually label your voice here as Charismatic?" (branched on `coach_label`) | **"Did the AI pick the right moment here?"** (one question, every snippet) |
| `label_buttons.yes_label` | model-authored | **"Yes, accurate"** |
| `label_buttons.no_label` | model-authored | **"Not quite"** |
| `label_buttons.snippet_id` | unchanged | unchanged |
| POST target | `/v2/user/snippets/<id>/label` (deleted) | **`/v2/user/snippets/<id>/confidence-review`** |
| Body | `{ user_label: "charisma" \| "stress" }` | **`{ ai_correct: true \| false }`** |

**The trigger is renamed, not reused.** You have to change either way — the
POST target moved — and a rename means an un-updated FE renders *nothing*
rather than rendering the old dead button. Please treat
`show_charisma_label_buttons` as gone; it is out of the response schema enum,
so the model can no longer emit it.

## 2. Wiring

```ts
// on a STEP 2 turn
if (turn.triggers.includes("show_confidence_review_buttons")) {
  const { snippet_id, yes_label, no_label } = turn.label_buttons;
  // yes_label → { ai_correct: true }
  // no_label  → { ai_correct: false }
}
```

You already ship the client for the POST —
`services/api/confidenceReview.ts` and the BFF at
`/api/v2/user/snippets/[snippetId]/confidence-review`. Nothing new to build
there; STEP 2 just becomes a second caller of it.

**Render `yes_label` / `no_label` from the payload — do not hardcode them.**
They are founder-signed copy, and the BE stamps them server-side (see §4), so
the payload is the single source of truth. If you hardcode and the copy is
re-signed later, your buttons silently drift out of sync with the question.

## 3. Strict boolean, still

`ai_correct` must be a real boolean. `"true"` the string is a **400, not a
coercion** — this is training data, and a coerced value is a fabricated label
nothing downstream can tell from a real one. Send `true` / `false`.

Re-flagging is safe and idempotent: one row per
`(snippet_id, reviewer_user_id)`, so a user who taps the other button just
updates their row.

## 4. Why the labels are stamped server-side

The prompt asks the model for those exact strings, but "asked nicely" is not a
guarantee. A model that helpfully softens *"Not quite"* into something
friendlier would be shipping **unsigned copy into a live chat**, and nothing
downstream would catch it. So the route overwrites `label_buttons.yes_label`
and `.no_label` with the signed constants on every turn carrying the trigger
(`services/coaching_state_machine.py:STEP2_YES_LABEL` / `STEP2_NO_LABEL`).
`snippet_id` is left as the model supplied it — it varies per turn.

The question itself sits inside `narration`, so it can't be stamped the same
way; the prompt marks it VERBATIM and forbids rewording. If you ever see the
question paraphrased in a live turn, that's a prompt bug worth reporting —
tests pin the instruction but not the model's obedience.

## 5. What this is asking, precisely

The question validates **the AI's selection of the moment** — not whether the
user liked their own delivery. That distinction is the corpus's meaning: a
`peer_review` row records *"the pick was right / wrong"*. The prompt tells the
model as much and forbids editorialising either answer, so please don't add
surrounding UI copy that reframes it as self-assessment.

Also unchanged from the #331 handoff: these flags are **non-blind** (the
reviewer saw the AI's choice), they carry `selection_source = "peer_review"`,
and they do **not** count toward the shadow lane's retrain trigger. Keep this
surface off the blind game rounds.

## 6. AC-9

Nothing about this beat surfaces a score, verdict, ratio or number. The
response to the POST is `{ saved, snippet_id, ai_correct }` — an echo of the
human's own answer, never a machine read.
