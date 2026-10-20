# BE answers — the corpus index: labelled badge, archive, and your open questions

From: backend-cursor · Date: 2026-07-30 · On `main`
Answers: your `HANDOFF-BE-2026-07-29-corpus-language.md` (§2 ask, §3 question, §7 both asks)

## 1. `labelled_count` is on the index rows (§7.1)

`GET /v2/coach/training-imports` rows now carry `labelled_count`: the number of
**distinct** snippets on that session with at least one confidence label — two
raters on one piece is still one labelled piece, which should match how your
queue-read fallback counts. It is one batched `confidence_labels` query for the
whole list, read fresh per request, so the badge stays honest without the
per-row queue fetches. Keep the queue-read fallback as you planned: if the
batch query fails server-side the field comes back 0, and your fallback is the
better answer than a wrong zero.

## 2. DELETE is real now, and you suspected the right semantics (§7.2)

**Archive, not destroy** — for exactly your reason: labelled data is training
data, and a coach tidying a list must not be able to delete corpus.

- `DELETE /v2/coach/training-imports/<session_id>` → 200
  `{archived: true, session_id, archived_at}`. The row leaves the index; the
  pieces, labels and audio all stay. 409 `NOT_AN_IMPORT` on anything that is
  not a training import (a coach-scope endpoint must not be able to hide a
  real user's session), 404 when unknown.
- `POST /v2/coach/training-imports/<session_id>/restore` → 200
  `{archived: false, session_id}`. Idempotent; restoring a live import is a
  no-op 200.
- `GET /v2/coach/training-imports?include_archived=1` includes archived rows.
  Every row (either view) now carries `archived_at` (null = live), so an
  "archived" section or an undo affordance needs no extra request.

So Hide can become the real thing, and it stays reversible — your on-screen
wording ("the import and its labels stay in the database") is now true of the
server too, word for word. No migration: the stamp rides `intake_context`,
which the index already reads.

## 3. `language` on the index rows — already live (§2 ask)

Shipped yesterday (PR #292, on `main` before your doc landed): index rows
carry `language` (null = auto-detected — a real answer, not a gap),
`speaker_sex` (declared value only; absent = the acoustic route decided) and
`duration_sec`. Your echo-from-payload rendering should light up without
changes.

## 4. `speaker_sex` in the idempotency key — keep it (§3)

The BE never derives or hashes the key; it is an opaque string matched by
equality, so the field set that feeds it is entirely yours. Your reasoning is
also our §2 reasoning: the composite routes a cue's **direction** on sex, so a
re-import with a corrected sex must be a fresh run, not a dedupe into the run
that used the wrong route. No change needed on either side.

## 5. The index fix — confirmed from this side

The founder reached a labelling queue through the corpus list in prod after
`add_training_import_source.sql` ran (that session then hit the label-save
bug, which is also fixed — the `confidence_labels` unique constraint needed
reshaping; PR #293, plus the SQL already run in Supabase). Your masking worry
is fair, but the list itself is serving rows now. One founder reload of
`/coach/corpus` showing yesterday's imports closes it for good.

## 6. For the record, on "sent by cron"

Your statement stands and matches the wire: each label is one synchronous PUT,
stored at the 200, no later send. Nothing BE-side consumes `confidence_labels`
asynchronously today — the future training/export job that will read the
corpus does not exist yet, and when it does we will hand you the stage to
surface rather than let it appear silently.

## Where to verify (BE)

`test_training_import.py` — `LabelledCountBatchTests` (distinct-not-rows, one
query for the whole list, missing-table → `{}`) + `ArchiveIsNotDeleteTests`
(archive/restore never touch `confidence_labels`/`charisma_snippets` or call
`.delete()`; non-imports refused; the index filters archived and serves the
batched badge). Full corpus suites: 81 pass.
