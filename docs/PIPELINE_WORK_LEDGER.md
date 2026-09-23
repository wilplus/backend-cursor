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
| a Take frozen under the old policy still shows its bookmarks | green | — |
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

One open, twelve held — and the table still undercounts, because #613 and
#614 added two green lines without an entry here. F-4 is the last of the
three the audit found against what a speaker sees; every other finding has
its own regression test in its own file and does not appear here.

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

### 2026-09-22 · WS1 follow-up · ws1-ungated-promotion · #615

Closes the open founder question in the entry above. Appended rather than
edited into it, per the rule at the top of this file.

**Closed:** none new
**Contract lines flipped:** none
**Contract lines added:** none
**Broke and fixed:** none
**Open for the founder:** none — the question above is answered.

**The answer.** The founder ran the query on the `willpowerlab` Supabase
project, branch `main` (PRODUCTION), on 2026-09-22:

```sql
SELECT key, value, updated_at
  FROM runtime_config
 WHERE key LIKE 'openai_surface_model_%'
    OR key IN ('openai_chat_model', 'openai_copilot_model');
```

`Success. No rows returned` — **0 rows.**

**What that means for the merge.** No model has ever been promoted into
production `runtime_config`, so every read on that path was already falling
through to the caller's own default. WS1 is therefore **behaviourally inert
for users**: the same model answers before and after. What merges is the
locks, on a door nobody had yet walked through.

Two details worth having on the record, because the next session will want
them and they are not re-derivable later:

- The query SUCCEEDED rather than erroring, so `public.runtime_config`
  exists in production and 0051 has run there. Migration 0352's
  graceful-degradation branch (`to_regclass IS NULL`) will NOT be taken on
  the production lane; the trigger installs for real on the next boot.
- 0 rows is a statement about now, not about history. Nothing in the repo
  writes those keys except `scripts/promote_openai_model.py`, and a
  promotion would have left `updated_at` behind, so "never promoted" is the
  fair reading — but it is an inference, not a proof.

Still not merged. The founder merges.
### 2026-09-22 · WS2 · ws2-lineage-or-nothing · #616

**Closed:** R-4, A-2, A-1's write half, B-1, J1-4
**Contract lines flipped:** `test_a_take_frozen_under_the_old_policy_still_shows_its_bookmarks` xfail → passing
**Contract lines added:** none
**Broke and fixed:** nothing in the contract. I broke five unrelated tests in
`tests/test_ideal_text_changes.py` on the way and fixed them — see below, it
is the most useful line here.
**Open for the founder:** A-1's SERVE half. The audit asks for it, your
2026-09-20 decision forbids it, and the order of work sequences it after
this. It is not in this PR. Also one TODO for copy, named below.

Branched from `ec82a73`, not the audit's pin. Contract baseline before
15 passed / 3 xfailed, after 16 passed / 2 xfailed on this branch alone.
WS1 merged as #615 while this was open, so `origin/main` was merged in here
and the two flips compose: **17 passed / 1 xfailed**, and F-4 is the only
line left open.

The two entries above and below each other conflicted in this file — both
appended, both flipped a row in the convenience table. Resolved by keeping
both verbatim in merge order and editing neither. The `#(pending)` in WS1's
entry is stale and stays stale; that is what "never edit an earlier entry"
costs, and it is cheaper than the alternative.

**A-1 IS HALF DONE AND THAT IS DELIBERATE.** The audit's first prescribed
change is "a lineage RPC failure returns `V3Unavailable` instead of serving
without lineage", and it names the test that pins today's behaviour as
wrong. But that behaviour is a founder decision recorded in
`mlc3_first_client_feedback.py:431-460` and dated 2026-09-20: the lineage
was FATAL until then, and one database state (`MLC3_ROLLOUT_NOT_ACTIVE`)
therefore withheld every bookmark from every user on Takes whose frames were
complete. The test the audit wants changed is labelled `# CHANGED CONTRACT
(founder 2026-09-20)` and `# THE LOAD-BEARING HALF OF THE DECISION`.

The auditor saw that rationale — it predates the audit's own pin — and rated
it a blocker anyway; Job 1 re-verified and agreed. So this is a real
disagreement between the audit and a founder decision, not a missed detail,
and only the founder settles it. The order of work already sequences it
("A-1's write first and only then the tightening of its serve"), so this PR
does the write and leaves the serve alone. A-3's
`processing_boundary_not_enforced` refusal is held for the same reason: it
is the same tightening under another name, and inert anyway now that
`PLF1_PROCESSING_AUTHORIZATION_MODE=enforce` is confirmed on every service.

**R-4's named test already existed and proved nothing.** It ran with
`arm_sid` unset, which makes the `elif` false as well, so it only ever
showed that the FIRST branch is skipped and never reached the one that does
the damage. A student GET always sets `arm_sid`. Strengthened onto the live
path rather than duplicated. If you find another test whose name matches a
finding, check what it actually drives before trusting it.

**The coupling worth writing down.** `v3_replaced_changes` is the wrong
question for the superseded branch. It says which policy produced the rows;
what the branch needs is whether the frozen set ADDRESSES them. And a
predicate for "addresses" must use the same identity rule as
`filter_to_selected` — `(id, kind, source, feedback_family)`, all four
non-empty. My first cut compared ids alone, which would have passed rows the
filter then dropped for a differing `kind`: the original defect wearing a new
predicate. `frozen_set_addresses` therefore lives in `take_feedback_set`
beside the filter, not in the caller.

**What I broke and fixed.** A scripted edit rewrote a helper's DEFINITION as
well as its call sites, so `def _r4_v3_row()` became `def _v3_row(S1)` and
shadowed the module's real `_v3_row` for every test in the file. Five
unrelated tests went red; ruff did not flag the redefinition. They pass on
`origin/main`, which is how I found it — when a test you did not touch goes
red, stash and compare before assuming it was already broken.

**Two fences caught me, and both are better for it.** Reading `os.environ`
in `services/gate_flags.py` broke the Q-A5 rule, so the live read is one
narrow `Config.current_env(names)` that takes a list and returns values and
cannot become a general escape hatch. And `log.note` on the predating-freeze
path would have put a marker in the response's `degraded` list, which the
frontend shows — on a response where nothing degraded for the speaker. It
logs instead.

**One TODO for you, in the code at `ideal_text_changes.py`.** A Take whose
freeze predates its rows now SHOWS its bookmarks, but
`record_take_feedback_response_v1` will refuse every answer to them
("feedback item is not in this Take's frozen set"). That is pre-existing and
this change does not widen it, but a speaker tapping a mark that silently
does nothing deserves to be told something. What it says is copy, and copy
needs your sign-off.

**Noticed, not fixed:** `#613` and `#614` merged without ledger entries, so
the contract table above was two lines stale before I touched it (their two
new lines are green and unrecorded). Not mine to write for them, but worth
knowing that this file undercounts.

---

### 2026-09-23 · WS3b · b6-fanout-inherits-scope · #(pending)

**Closed:** B-6, thread half only. The admin-route half is NOT closed and is
NOT deferred for effort — see below.
**Contract lines flipped:** none
**Contract lines added:** none. B-6's regression tests live in
`tests/test_authorized_provider_scope.py`.
**Broke and fixed:** none. Baseline before and after: 17 passed, 1 xfailed
(F-4), 45 subtests.
**Open for the founder:** one. The audit's prescription for B-6's admin half
is wrong, and the right version is a behaviour change on a live coach surface.

**The thread half.** `threading.Thread` does not copy contextvars: a raw
daemon thread starts with an EMPTY context. Four fire-and-forget dispatches
started one from inside `protected_provider_scope`, so in the child thread
`authorize_protected_generation` found no scope, returned `(None, None)`, and
`llm.chat_complete` went to the provider with the speaker's transcript and no
permit. Nothing raised. The call left no `processing_provider_permits` row and
no `processing_provider_operations` row, so the purge subject graph never
learns the transcript left and the provider-deletion contract has nothing to
act on. Three of the four are live and ungated on every Take
(`say_it_stronger`, the snippet draft fan-out, `conversation_summary`); the
fourth sits behind `COACH_PREFILL_ENABLED=0`.

**Why it happened, which is the part worth keeping.** `run_parallel` already
had this right — it submits `copy_context().run`. The rule lived at that ONE
call site instead of in a named function, so the next four people who needed a
thread wrote `threading.Thread(...)` and silently lost the scope. The fix is
therefore `services/parallel.start_scoped_thread`, not four inline
`copy_context()` calls: a rule that must be remembered at every call site is a
rule that will be forgotten at the fifth. **Reach for it instead of
`threading.Thread` anywhere a request or a Take is what the work belongs to.**

**THE ADMIN HALF: THE AUDIT'S PRESCRIPTION IS WRONG. DO NOT IMPLEMENT IT AS
WRITTEN.** `engineer_prompt.md` says the two admin routes that call LLMs on
user data (`routes/v2/admin.py:1121`, `:1437`) "get `phase1_provider_route`".
That decorator resolves `_principal_id()` — the **caller's** principal
(`routes/v2/processing_authorization.py:68-78`). On an admin route the caller
is the COACH. Applying it there would:

  1. require the coach to have accepted the Phase-1 policy, and
  2. mint a permit under the COACH's acquisition principal for a provider
     call carrying the STUDENT's transcript.

That is precisely the defect B-2 was — authorization evidence attached to
audio it was never given for — wearing an operator's hat. It would also leave
the student's purge subject graph still ignorant of the call, because the
permit would not be under their principal. So the decorator does not fix the
finding; it launders it.

**The version I believe is right, and why it needs you.** Bind to the SUBJECT
(the session's owner, or `user_id`'s principal), not the caller. That is the
honest provenance and it needs no new decision. What does need one: when the
subject has not authorized processing, the correct answer is to REFUSE — a
coach may not send an unauthorized person's transcript to a provider. That is
a behaviour change on a live coach surface, so it is yours, not mine. A
subject with no resolvable principal at all (a legacy account) would refuse
too, which is the case most likely to bite.

I built the thread half, which has none of this ambiguity and is live on every
Take, and stopped at the boundary rather than shipping a permit that says
something untrue.
