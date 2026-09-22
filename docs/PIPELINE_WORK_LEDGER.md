# Pipeline work ledger

**What this is.** One file that every workstream pull request appends to, so
five parallel agent sessions can see what the others did without any of them
talking to each other. Git is the channel; this file is the message.

**Why a file and not a chat thread.** Sessions do not share context. A branch
does. A session that opens this file before it starts learns which contract
lines have moved, which findings are already closed, and which questions are
sitting with the founder — none of which it could learn any other way.

---

## The mechanism, in three parts

**1. The contract.** `tests/test_f1_loop_contract.py` holds the behaviours a
speaker would feel: bookmarks that arrive and stay answered, a document that
is never rebuilt, no number on a user's screen. It runs on every pull request
in this repository, in the unit tier, with no database. The frontend half is
`src/lib/willab/f1LoopContract.test.ts` in `frontend-cursor`.

**2. The scoreboard.** Lines that are false today because the audit found a
real defect ship as `xfail(strict=True)`, tagged with the finding id. Strict
means the suite fails when such a test starts **passing**. So the workstream
that closes a finding is mechanically forced to come here and flip its line,
and cannot quietly close a finding the contract still believes is open.

**3. This ledger.** One entry per merged pull request, appended, never edited.

---

## How to add an entry

Append at the bottom, newest last. Keep it to what another session needs:

```md
### <date> · WS<n> · <branch> · #<pr>

**Closed:** <finding ids>
**Contract lines flipped:** <test name> xfail → passing, or "none"
**Contract lines added:** <test name>, or "none"
**Broke and fixed:** anything in the contract that went red on the way, or "none"
**Open for the founder:** one line, or "none"
```

Three rules, and they are the reason the ledger is worth reading:

- **Never edit an earlier entry.** A wrong entry gets a correcting entry below
  it. The history of what people believed is the useful part.
- **A finding is not closed because a pull request says so.** It is closed when
  its contract line is a plain passing test, or when its own named regression
  test passes and the reviewer agreed. Say which.
- **If you broke a contract line and fixed it, say so.** That is the single
  most valuable line in this file for whoever comes next: it names a coupling
  nobody had written down.

---

## Current state of the contract

Run it rather than trust this table — it is a convenience, and it goes stale:

```sh
.venv-ci/bin/python -m pytest tests/test_f1_loop_contract.py -q
```

| Contract line | State | Owner |
|---|---|---|
| a Take frozen under the old policy still shows its bookmarks | **xfail** | R-4 |
| a Take frozen under its own policy is still filtered to it | green | — |
| every answer decides an item one way or the other | green | — |
| the lock gate asks the page's own question | green | — |
| a Project with no document gets one from its next Take | green | — |
| a Project **with** a document never has it rebuilt | green | — |
| the freshness rule names every route an answer takes | green | — |
| the computation window reaches the writer | green | — |
| the page offers exactly the five owner states | green | — |
| each of the five states routes as itself | **xfail** | F-4 |
| a promoted model cannot reach the document without a gate | green | — |
| a later Take proposes and never applies | green | — |
| the words a speaker waits on name work, not judgement | green | — |

Two open, eleven held. The two are the audit findings that touch what a
speaker sees; every other finding has its own regression test in its own file
and does not appear here.

---

## Order of work

Settled with the founder on 2026-09-22. A workstream may run out of order only
if it names why in its pull request.

1. **The live bugs**, because they break what the product just established:
   R-4, G-1, F-4.
2. **The gates that move without a decision**: LEGACY-1 and R-13, then R-1.
   Before any widening to real users.
3. **The write side of the lineage**, every gate still closed: A-1's write
   first and only then the tightening of its serve, then A-2, then B-2 and
   B-3.
4. **The exercise's own foundations**: R-2, G-3 consent, the N1 context. All
   three, or the switch means nothing.
5. **The exercise on**, founder account first.

Independent of all of it, any time: the dataset and release findings (D-1,
D-3, D-6, G-2). Nothing serves from them and no user sees them.

---

## One warning for every session

The audit is pinned to `backend-cursor` at `87a9309` and `frontend-cursor` at
`6768fbc`. Both have moved. Migration 0351, the Ideal Text recovery rule, the
spinning slot and the two-phase wait bar all landed afterwards. **Rebase onto
current `main` and re-locate every cited line before editing.** A finding
whose line has moved is still a finding; a finding whose line no longer says
what the audit quoted is a finding to re-verify, not to "fix".

`services/ideal_text_changes.py` has changed most. R-4 lives in it, the stored
bookmark set reads through it, and the answered-item marking runs inside it.

---

## Entries

### 2026-09-22 · WS0 · claude/dazzling-johnson-excc8e · #609, #611, FE #432

The work this contract exists to protect, recorded so a later session can see
what it is holding.

**Closed:** none (pre-audit product work)
**Contract lines flipped:** none
**Contract lines added:** the whole of `tests/test_f1_loop_contract.py`
**Broke and fixed:** none
**Open for the founder:** none

What shipped, in order: the stored bookmark set learned about both answer
routes and about its own clock (#609, migration 0351); a Project whose Take 1
never confirmed an Ideal Text may now get one from a later Take, and the
refusal that left a Take on "processing" for eleven days became a terminal
state (#611); the reserved slot spins, the wait label stopped rewinding, and
the progress bar now spans both phases with its top point reserved for the
document actually arriving (frontend #432).

Two settings the code depends on: `IDEAL_TEXT_FEEDBACK_BAKE_ENABLED` must be
`1` on the backend **and** the worker service, confirmed from each boot log
rather than the panel.

### 2026-09-22 · WS1 · ws1-ungated-promotion · #(pending)

**Closed:** LEGACY-1, J1-2, E-6, H-1, J1-3, R-13; E-5 in part
**Contract lines flipped:** `test_a_promoted_model_cannot_reach_the_document_without_a_gate` xfail → passing
**Contract lines added:** none
**Broke and fixed:** none in the contract. Three tests OUTSIDE it asserted the
defect and were rewritten to assert the decision instead — see the coupling
note below, it is the useful part of this entry.
**Open for the founder:** does any row exist today in production
`runtime_config` under `openai_surface_model_%`, `openai_chat_model` or
`openai_copilot_model`? One SELECT. If one does, this pull request STOPS
SERVING IT on the next boot, which is the fix working — but it is a live
change of which model answers, and the founder should know before the merge,
not after.

Contract baseline before 13 passed / 3 xfailed, after 14 passed / 2 xfailed.
R-4 and F-4 are untouched and still belong to their owners.

**What was open.** `runtime_config` has no RLS, no trigger and `GRANT ALL` to
`service_role` — which the backend client itself holds. Five of its keys were
read straight into the `model` argument of a chat completion, and two of those
five compose the Take-1 Ideal Text (`surface="best_presentation"`) and every
Say It Stronger card. One INSERT changed the words in a speaker's document
within the sixty-second cache, with `MLC2_PROMOTION_ENABLED` still false.
None of the three MLC2_* constants was read by anything but the readiness
evaluators.

**The gate is in four places** because the hole is reachable from four:
`services/runtime_model_gate.py` (the allowlist and the one gate),
`ml_surface_contracts.resolve_surface_model` (the read is fenced, not
removed), `services/llm.py` (the assertion that the gate ran, immediately
before the provider call), and migration **0352** (the table refuses, because
a Python gate cannot bind a psql session). Promotion additionally binds the
model to the `prompts.lock.json` digest it was evaluated under (H-1), and the
export and fine-tune scripts refuse while their own constants are false.

**A coupling nobody had written down.** `evaluation_model_override` — the
ContextVar the golden evaluations use — resolves to a model that is not the
caller's default, so the obvious gate ("the served model differs from the
default, was promotion enabled?") silently breaks the evaluation path, which
is the very thing the founder opens the gate ON. The gate exempts an active
override explicitly. Anyone adding a second model source here has to do the
same, or promotion becomes unreachable.

**Three tests asserted the defect.** `test_ml_dpo_loop`'s eval-override case
asserted that a stored row IS served; it now asserts both postures. Its two
`moment_suggestion` cases treated a canonically rejected alias as trainable.
`test_coach_comment_drafter::test_surface_promoted_model_is_used` asserted a
promoted model reaching a user-facing generator with the gate shut; it now
opens the gate first. All four patch
`services.runtime_model_gate.promotion_is_enabled` rather than a `Config`
attribute: something in the suite reloads `config`, so
`scripts.promote_openai_model.Config` and a test module's `Config` are not
always the same class object, and a `patch.object` on the wrong one passes
for the wrong reason. Use that seam.

**New rehearsal lane.** `model-gate` (`RUNTIME_MODEL_GATE_REHEARSAL_DSN`,
`willab_model_gate_rehearsal`), its own two-file chain 0051 → 0352, each
applied twice. `tests/test_runtime_config_model_guard_postgres.py`, 20 cases,
executes the trigger rather than string-asserting the migration.

**No Railway variable is required.** Every constant this reads is a Python
constant in `config.py`, not an environment variable, and all three ship
false. The boot line that would prove a gate flag's effective value is
Workstream 2's (J1-4/B-1) and is deliberately not duplicated here.

**Noticed, not fixed** (they belong to other workstreams): `db.py`'s
`upsert_runtime_config` is now unreachable for model keys and its callers are
zero — a deletion candidate for whoever does Q-A1; `services/moment_suggestions.py`
still passes `surface="moment_suggestion"` into `chat_complete`, which is
harmless (unknown surface → caller's default) but reads as if a contract still
exists; and `ml_finetuning_export`/`ml_dpo_export` still carry no producing-model
identity, which is E-5's other half and Workstream 6's.
