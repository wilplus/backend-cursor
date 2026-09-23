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

### 2026-09-23 · WS3a · b4-deletion-reaches-practice · #(pending)

**Closed:** B-4
**Contract lines flipped:** none — B-4 has no line in `test_f1_loop_contract.py`
**Contract lines added:** none. B-4's regression tests live in their own file,
`tests/test_phase1_deletion_completion_postgres.py`, per the rule that only
findings against what a speaker *sees* go in the F1 contract.
**Broke and fixed:** none. Baseline before and after: 17 passed, 1 xfailed
(F-4), 45 subtests.
**Open for the founder:** none. No gate moved, no route opened, no copy
changed.

**Why out of order.** The settled order does not list B-4 anywhere; §3 runs
A-1's write, then A-2, then B-2 and B-3. B-4 jumps that queue for one reason:
it is the first finding in the audit that names something a real person can
ask for and the app cannot do. A subject whose only stored audio is a practice
recording **could not be erased at all** — and a dozen testers are days away.
It is also the cheapest thing in the audit to hold: two `CREATE OR REPLACE
FUNCTION`s, no table, no column, no grant, no gate.

**The shape of the defect.** `services/data_purge.py` has emitted storage
targets carrying `source_relation = 'processing_practice_objects'` since
migration 0334 gave practice audio its own registry. Neither function that
consumes those targets knew the relation existed:
`freeze_phase1_purge_inventory_v4` raised `PURGE_STORAGE_TARGET_SOURCE_INVALID`
and `mark_phase1_storage_object_purged_v1` raised `PURGE_OBJECT_SOURCE_INVALID`.
So the request was written, the freeze refused, and the row sat at `requested`
for ever with nothing erased. Not a partial deletion — **no** deletion, and a
record saying one had been asked for.

**The table was always ready.** 0334 gave `processing_practice_objects` a
`deleted_at` column commented "stamped by the purge once the object is gone
from storage… mirrors the sibling tables". The registry was built for exactly
this and only the two functions were never told. Migration 0353 adds one
`ELSIF` branch to each, mirroring the orphan branch line for line, ownership
check included; every other path, check and error code is byte-identical to
what runs today.

**Why nobody caught it, and what now would.** No rehearsal lane carried a
`processing_practice_objects` row to purge, so the two functions were never
asked. Two things changed, and the second is the one that generalises:

1. The released lane now builds the registry
   (`tests/integration/confident_moment_rehearsal.sh`), and five cases in
   `tests/test_phase1_deletion_completion_postgres.py` EXECUTE both functions
   against it. Evidence: against the pre-0353 definitions restored onto a
   clone of the same lane, 4 of the 5 fail with the two error codes above.
   The fifth — "an unknown relation is still refused by both" — passes on
   both sides, which is the point of it.
2. `test_every_emitted_source_relation_is_known_to_the_purge_functions`
   (unit tier) walks `migrations/manifest.txt` in order, finds the LAST
   definition of each function, and asserts every `source_relation` literal
   in `services/data_purge.py` appears there. The next table to get its own
   registry cannot drift the same way silently. Verified genuine: remove 0353
   from the manifest and it fails.

**A trap in the lane, worth writing down.** My first cut added
`hard migrations/add_confident_voice_practice.sql` (0279) to build the two
practice tables. 0279 creates `diagnostic_exercise` first, whose
`journal_post_id` references `public.journal_post` — the entire Journal chain,
a surface this lane does not carry and has no reason to. The right answer was
much smaller: `mlc3_exercise_foundation_prerequisites.sql` **already** defines
narrow `confident_voice_practice` / `confident_voice_practice_attempt`, and
0334 needed exactly one thing they lacked — `closed_at`, for its retention
index. One nullable trailing column on the narrow copy, which is the pattern
that file already documents. **When a lane needs a released migration, check
first whether the fixture already has the two keys it wants.**

**Where 0353 sits in the lane.** After BOTH current definitions: the mark
comes from `add_phase1_deletion_completion.sql` and the freeze from
`add_mlc3_exercise_dark_foundation.sql`, and the narrow lane applies the
deletion file in a later block. Applied twice on the released lane, cleanly.

**Restated grants, and why.** `CREATE OR REPLACE FUNCTION` preserves a
function's ACL, so the REVOKE/GRANT pairs in 0353 change nothing. They are
there because `test_every_created_function_revokes_anon_and_authenticated`
has no "revoked by an earlier migration" carve-out — its sibling PUBLIC test
does — and because a reader auditing an erasure writer should not have to open
another file to learn it is service_role-only.

---

### 2026-09-23 · WS3 · b2-b3-acquisition-principal · #(pending)

**Closed:** B-2, B-3, B-11
**Contract lines flipped:** none — none of the three has a line in
`test_f1_loop_contract.py`
**Contract lines added:** none. Their regression tests live in their own
files, per the rule that only findings against what a speaker *sees* go in the
F1 contract.
**Broke and fixed:** none. Baseline before and after: 17 passed, 1 xfailed
(F-4), 45 subtests.
**Open for the founder:** none. No gate moved, no route opened, no copy
changed. Merge order: this stacks on #618 (B-4), which owns migration 0353.

**Three names, one defect.** Phase-1 lineage rests on a single claim — the
principal named on a permit is the principal that acquired the recording — and
three places let that claim be false:

  * **B-2** `issue_phase1_provider_permit_v1` read the authorization of
    `p_acquisition_principal_id` and then inserted `p_source_take_id` /
    `p_source_recording_id` verbatim. Nothing anywhere said those coordinates
    were that principal's to name. The auditor minted a permit for one guest's
    recording under another principal's receipt; the snapshot table then held
    two rows for that recording naming different principals, with nothing
    downstream able to say which was the truth.
  * **B-3** `resolve_phase1_acquisition_principal_v1` returned a claim's
    SOURCE only when that source already held a receipt, and otherwise fell
    through to the TARGET. A guest who recorded while the gate was off holds
    no receipt *by construction*, so after they signed up every one of those
    recordings resolved to the new account principal.
  * **B-11** `resolve_acquisition_principal` returned the product owner
    unchanged whenever the gate was off, before either read — so one human's
    acquisition identity depended on which mode was deployed when they tapped
    Agree, and one person could end up with two receipts on two principals.

**The shape of each fix, and why none of them refuses more than it must.**

1. B-2 adds an ownership check that runs BEFORE the authorization read, so a
   caller cannot probe another principal's authorization state with their
   recording id. The attempt row is authoritative wherever it exists. Where it
   does not — every recording acquired while the gate was off — the session's
   owner is the only statement left, and because `claim_guest_owner` rewrites
   `v2_sessions.owner_principal_id`, the acquirer is either that owner or a
   principal claimed into it. **Both pass**, or signing up would cut a speaker
   off from their own recordings. A source with neither an attempt row nor a
   session row is left alone: absence of evidence is not evidence of theft,
   and refusing on it would take the live loop down for a data gap this
   function did not create.
2. B-3 turns a WHERE filter into an ORDER BY preference. The answer is
   **identical** for every claim whose source holds a receipt — `ORDER BY
   has_receipt DESC, claimed_at DESC` still picks the newest such source. It
   changes only the case where none does, which previously returned the wrong
   principal outright.
3. B-11 removes the off-mode short-circuit. Reading is now mode-independent;
   what the mode still decides is the disposition of a FAILURE — `enforce`
   refuses, `off` degrades to the product owner it would have returned anyway.
   A gate that is off may not start failing requests for the state it was off
   for.

**Why the loop survives B-3, which was the thing worth checking.** Resolving a
claimed guest to their old principal means `get_phase1_processing_authorization`
says not-authorized, and the client asks the human to accept — which sounds
like a regression until you follow `routes/v2/processing_authorization.py`:
`_principal_id()` runs the SAME resolver, so the acceptance lands on the GUEST
principal, not the account. The person taps Agree once and the receipt is
written where the audio actually came from. No founder decision needed; I went
looking for one.

**A dead test this replaced.** `tests/test_phase1_processing_rehearsal_contract.py`
and `tests/test_phase1_compliance_contract.py` assert SUBSTRINGS of
`tests/integration/phase1_processing_rehearsal.sql` — a 700-line script that
exercises the whole Phase-1 chain including `issue_phase1_provider_permit_v1`,
and that **nothing runs**. `rg` for its name finds only those two readers. That
is exactly the pattern the audit called out on B-4 ("the only tests for this
path assert source-text substrings and never call the DB function"), and it is
why B-2 and B-3 sat in a covered-looking area. The new
`tests/test_phase1_processing_postgres.py` executes the real functions on the
released lane. **Someone should decide what to do with that .sql file** — run
it in the tier or delete it; a script nobody runs is worse than no script,
because it reads as coverage. Not mine to settle, and left alone.

**Evidence that the tests are real.** Against the pre-0354 definitions restored
onto a clone of the same lane, 3 of the 8 postgres cases fail — both B-2
refusal cases and the B-3 resolver case. The other 5 pass on both sides, which
is their job: they are the guards that the fix is not a blanket refusal.
Likewise 2 of the 5 B-11 cases fail with the service change stashed.

**A lane trap, for whoever writes the next postgres suite.** A fixture that
registers its own Phase-1 policy works alone and fails in the tier:
`processing_purpose_registry` freezes a purpose's control versions once it is
operational, so a second registration inventing its own raises
`PURPOSE_CONTROL_VERSION_CONFLICT`; and `activate_phase1_policy_v1` retires
whatever was active, which would pull the policy out from under any suite
sharing the lane. **Reuse the active policy** — read its version, copy hashes
and first allowed country — and only register one when there is none.
