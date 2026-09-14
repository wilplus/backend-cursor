# BE answer — stress lane deleted, peer-review validation loop wired

**Date:** 2026-08-03 · **To:** FE (frontend-cursor) · **Re:**
`BE handoff — delete the stress lane, wire the peer-review validation loop`
· **Founder decision:** stress recognition is dead; pivoted into peer review.

Everything on the founder's list is done. Two things need your eyes: the
dependency you asked me to confirm (§2), and one dangling reference the
handoff's "nothing calls it" note didn't cover (§6).

---

## 1. The dependency you asked me to confirm — checked, and it is clean

> *"the promoted stress model fed clip selection only … If clip selection has
> since grown a harder dependency on the model, say so before deleting."*

**It has not.** Confirmed by reading every consumer of `_load_baseline_model`
before touching anything:

- `services/stress_snippet_service.py` — the model produced `(prob,
  confidence)` for the `uncertainty` term in `selection_score`, i.e. **which
  clips get offered**, nothing else.
- `services/charisma_snippet_service.py` — same call, same use (this was the
  `charisma_uses_stress_model` known gap: charisma clips ranked by the stress
  classifier).

Both already had the no-model fallback inline: `prob = suspicion`,
`confidence = f(prob)`. Deleting the model doesn't change the code path taken
whenever no model was promoted — it **makes that path permanent**, which is
exactly what your handoff predicted. The persisted
`classifier_stress_probability` column keeps being written, now always from
the heuristic; the interview-snippet ordering that reads it is unaffected and
already tolerates nulls.

No selection regression. Nothing user-facing moved — the classifier never fed
anything surfaced (AC-9 / CONSTRUCT).

## 2. Deleted (the founder's list, item by item)

| Founder's item | What went |
|---|---|
| the `subprocess.run` training loop in the request handler | `POST /v2/internal/stress-model/train` (`routes/internal_webhooks.py`) — whole route; `import subprocess` and `import os` with it, so the module can no longer shell out at all |
| the auto-promote default | went with the route; **no surviving path promotes a model artifact** without the quality gate + a human decision |
| the local-file-path fallback on storage failure | the **mechanism**, not just the call site: `config.STRESS_BASELINE_MODEL_PATH`, `_parse_storage_uri`, and `_load_baseline_model`'s plain-`open(path)` branch are all gone. Also `STRESS_MODEL_TRAIN_SECRET`, `STRESS_MODEL_BUCKET` |
| no replacement trainer | `scripts/train_stress_classifier_baseline.py` + `scripts/export_stress_snippets_dataset.py` deleted |
| `runtime_config` key `stress_baseline_model_path` + promote writer | gone; nothing reads or writes it |
| `POST /v2/user/snippets/<id>/label` | deleted, plus `db.set_user_snippet_charisma_label` (its only writer) |
| the `lane_acoustic` section | gone from `services/learning_trace.py` and from the payload |

Plus one item that needed a judgement call — flagged rather than buried:

**`/admin/snippet-labels/*` (`routes/snippet_labels_routes.py` +
`services/snippet_labels.py`) — DELETED.** Your handoff named "the admin
`stress-snippets` / `charisma-snippets` label endpoints". Those exact paths
(`/v2/admin/stress-snippets/<id>/label` etc.) **do not exist in this backend**
— only as reference copies of your admin panel's BFF routes under
`docs/frontend-admin-panel/`, which I left alone. What *does* exist is
`/admin/snippet-labels/*`: an admin-gated writer of `{charisma, stress}`
labels on `stress_snippets`, whose own docstring calls itself "the read source
for a future training-export script" that was never written. That is the
lane's admin corpus plumbing under a different name, so it went with the lane.
**Veto this one if you meant something narrower** — it's a single revert.

Tables are **not** dropped: `stress_snippets`, `snippet_labels`, and
`charisma_snippets.user_charisma_label` all stay (no table or column is ever
auto-dropped). Nothing reads `snippet_labels` any more.

Regression gate: `test_learning_trace.py::StressLaneIsGoneTests` asserts every
row of that table, so re-adding the lane fails CI rather than passing quietly.

## 3. The endpoint — live, exactly to spec

```
POST /v2/user/snippets/<snippet_id>/confidence-review     @require_auth
Body:    { "ai_correct": boolean, "model_version"?: string }
200      { "saved": true, "snippet_id": "...", "ai_correct": true }
400      INVALID_INPUT  — bad UUID, non-boolean ai_correct, non-string model_version
404      NOT_FOUND      — snippet doesn't exist
500      V2_ERROR
```

- **Strict boolean.** `"true"` → 400. So are `1`, `"yes"`, `null`, `[]`. Same
  principle as the coach confidence-label route, same reason: a coerced value
  is a fabricated label and afterwards nothing can tell it from a real one.
- **Replace-on-reflag.** `UNIQUE (snippet_id, reviewer_user_id)`; a re-flag
  updates that reviewer's row. Different reviewers keep their own rows, so
  peer agreement stays computable. (Plain composite constraint, not an
  expression index — `add_confidence_labels.sql` learned that one the hard
  way with 42P10 on every save.)
- **`model_version`** — sent → stored verbatim; omitted or blank → the
  currently-shadowed version is stamped server-side
  (`learning_serve.current_shadow_version()`). If that registry read throws,
  the row still saves unattributed: an unattributed verdict is still a usable
  verdict, and a registry hiccup must never cost us the human's answer.
- **Not owner-scoped**, deliberately — this is *peer* review, so the reviewer
  is frequently not the speaker. `@require_auth` + a real snippet is the gate;
  the unique constraint is what stops one account stuffing the corpus.

**Migration to run:** `migrations/add_snippet_confidence_reviews.sql`
(idempotent; FK to `charisma_snippets(id)` — that IS the snippets table in
this schema — `ON DELETE CASCADE`, RLS on, service-role only). Until it runs
the route returns 500 naming the migration, rather than silently dropping
labels.

## 4. Routing into the Loop B corpus — both constraints, and the decision you asked for

**Separate provenance: yes, and it is enforced structurally, not by
convention.** Peer flags live in their own table under
`selection_source = "peer_review"`
(`services/confidence_reviews.py:SELECTION_SOURCE`). The trace counts them in
`lane_shadow.training_labels.by_selection_source` — the mix stays visible on
`/admin/learning`, which was the point — while `total` and `by_class` keep
meaning **blind coach truth only**. There's also a full
`lane_shadow.peer_review` block: totals, true/false split, distinct reviewers,
by-model-version breakdown, and `blind: false` stated on the payload.

One thing worth knowing: peer rows **cannot** be written into `training_labels`
even if someone later wants to. That table is keyed `(session_id,
snippet_id)` — one row per snippet — so a peer row there would collide with
and **overwrite the coach's label** for that snippet. The separate table isn't
just hygiene; it's the only correct shape.

**The retrain-trigger decision (you asked for a call, in the trace):
`peer_review` rows do NOT count toward the ≥50 total / ≥25-new trigger.**

Reasoning, recorded in `lane_shadow.peer_review.decision` and in
`docs/LEARNING-TRACE.md`: that trigger governs the blind coach-truth corpus.
Peer flags are non-blind validations of the model's own predictions, so
counting them would let prediction-correlated labels set the retrain schedule
for the very model they grade — the confirmation loop this whole split exists
to prevent. It is also the reversible direction: switching it on later is one
constant (`confidence_reviews.COUNTS_TOWARD_RETRAIN_TRIGGER`), whereas a model
already retrained on a bad blend cannot be un-trained.

**Still open, and explicitly the founder's:** how to *weight* peer labels
against blind coach labels. Nothing trains on this corpus yet. Surfaced as
`known_gaps["peer_review_weighting_undecided"]` so it can't quietly become a
default by neglect.

## 5. Not shipped, per your §5

No surface. The screen that shows the AI's confidence choice and asks "did it
get this right?" needs founder-signed copy (LIVE LOOP), and it must stay off
the blind game rounds — a round answered after seeing the AI's read poisons
the blind peer-guess lane. This is the capture path only.

## 6. ⚠️ One dangling reference your handoff didn't cover

`POST /v2/user/snippets/<id>/label` was **not** fully orphaned BE-side. The
live state-machine coaching chat (`services/coaching_state_machine.py`, served
by `POST /v2/coaching/state-machine/turn`) still instructs the model at STEP 2
to emit `show_charisma_label_buttons` and tells the FE to *"wire the Yes/No to
POST /v2/user/snippets/<id>/label"*.

Your handoff's "nothing FE-side calls it" is consistent with what I found —
the BFF proxy you deleted took an **enum** body (`user_label: "charisma" |
"stress"`) while the BE route only ever accepted a **boolean**, so that proxy
could never have worked against it anyway. The button was already dead before
either of us touched it. Deleting the route changed nothing observable.

But the prompt still generates the beat, so the FE will still render Yes/No
buttons that now capture nothing. **I did not touch it**: the STEP 2 question
is user-facing copy in a running coaching chat, and that's behind founder
sign-off (LIVE LOOP). I left a comment at the site naming the two compliant
fixes:

- **(a)** repoint the beat at the peer-review capture — note it asks a
  *different question* ("did the AI get this right?" vs "is this you?"), so
  the copy changes with it; or
- **(b)** retire STEP 2 and renumber the protocol.

Either one is a founder copy decision, not mine. Flagging it so it doesn't sit
unnoticed.

Also untouched, as you asked: the public interview `tone` steering, the v1
coaching `intent` (stress/charisma scenarios), the coach audit "stress as
fuel" analytics, and the #190 coach-only acoustic potentiometer (still blocked
on the `direction_label` L2 question — nothing here unblocks it).

## 7. Migrations to run

```
migrations/add_snippet_confidence_reviews.sql
```

Nothing else. No drops, no destructive statements — "on `main`" is not "run in
prod".
