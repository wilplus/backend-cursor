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

### 2026-09-23 · WS0 · claude/dazzling-johnson-excc8e · #(pending)

**Closed:** none (product work, contract 24j)
**Contract lines flipped:** none
**Contract lines added:** `tests/test_reasonable_confidence.py` in full; two
assertions on `test_the_client_row_gets_a_tier_and_never_the_band_or_the_score`
**Broke and fixed:** none red, but see the AC-9 note below — I wrote the leak
and caught it before the gate, not after.
**Open for the founder:** `REASONABLE_CONFIDENCE_ENABLED` is unset everywhere
and this ships OFF, so merging changes nothing a speaker sees. Turning it on
is a separate decision on a separate day, and it must be set on **web, worker
and cron** together (CONFIG-FIRST): a worker that ranks one way while the web
service ranks another would freeze one order and serve the other.

**What this is.** Contract 24j, signed in session: a Confident Voice item is a
moment where *the words carried the point they were meant to carry, and the
delivery sounded more assured than that speaker's own norm*. Until now only
the second half decided. `services/reasonable_confidence.py` reads the first
half back and puts it in front of the second, **sequenced, never blended**.

**The design note worth carrying.** A weighted blend of "sounded assured" and
"made the point" would have broken the CONSTRUCT fence — 0.4 could be fine
delivery of nothing or a mumbled bullseye, so the measured state would ask two
things at once, the exact defect that retired charisma on 2026-08-13. Ordering
does not have that problem: the tier decides WHICH candidates compete,
`voice_confidence` still decides which of them wins, and it still answers its
one question about delivery. **Selection criteria are not measurements**, which
is also why `conf-q-v2` in `services/state_ratings.py` is untouched and must
stay untouched — the rater is asked about the clip they are shown, and that
stays true when a tier chose the clip.

**No new parameter, and that surprised me.** `on_slide_score` returns
`max(_STRENGTH)` over the slide's claims and `_STRENGTH` is
`{covered: 1.0, partial: 0.5, not: 0.0}`, so the stored composite already IS
the verdict. There was no continuum to cut, no λ and no threshold — the module
reads three names back out. If you are about to add a weight here, read
`slide_alignment.py` first and check you are not calibrating something that is
already categorical.

**I told the founder change 1 needed a new measurement path. It did not.**
`compute_piece_slide_scores` already scores EVERY piece against its slide; only
the `piece_llm_budget()` subset (16) gets true entailment, and the rest get
`_lexical_verdict`, which is word overlap. So the tier exists for every
candidate today. What remains is a QUALITY question, not an availability one,
and it is why the tier carries `reason_degraded`: a coarse read still orders —
it beats no read — but nothing downstream may mistake it for the measured kind.
Word overlap is precisely the keyword matching this product does not want to
be, so the flag travels with the verdict rather than being dropped at the door.

**The AC-9 leak I wrote and then caught.** `_presentable` in
`take_feedback_policy_v3_service.py` is a DENYLIST — `dict(row)` minus
`candidate_score` — so every new key on the served row rides the browser
payload by default. `reason_tier` would have. It is not a number, but `"not"`
is a verdict about what the speaker's words did, and it is the ordering input,
so a client holding it could reconstruct the ranking the tier decided. It now
leaves by the same door as the score. **If you add a field to that row that
says something ABOUT the speaker, add it to that pop on the same day.**

**Nothing was deleted, on purpose and twice over.** The bottom tier is never
empty, so 24b still puts exactly one item on every valid block, and a candidate
with no slide read at all sorts LAST rather than being excluded — excluding
could empty a block. Deleting the weak end was rejected because 24f's exercise
fires on the weakest item below the neutral band, and because the owner is only
ever asked about what surfaces: surface one end of the range and you collect
judgements from one end of it, which is not a corpus you can later learn
confidence from.

**Two things went red on the way and both are couplings worth knowing.**
(1) `services/reasonable_confidence.py` read `os.getenv` directly and the Q-A5
config fence failed the whole tier for it — the flag now lives in `Config` and
`enabled()` reads it there. (2) The tests then passed alone and FAILED in the
full run: four modules in this suite reload `config`, which builds a new class
object, so a module-level `from config import Config` in a test holds the
pre-reload class while `enabled()` — importing inside the function — reads the
post-reload one. The helper looks the class up at call time. If you write a
test that patches a `Config` attribute, run the whole tier, never just your file.

### 2026-09-23 · WS0 · claude/dazzling-johnson-excc8e · #(pending)

**Closed:** none (observability for 24j, which shipped in #624 the same day)
**Contract lines flipped:** none
**Contract lines added:** `TestTheOnlyPlaceTheLayerIsObservable` in
`tests/test_reasonable_confidence.py`
**Broke and fixed:** none
**Open for the founder:** none. This is additive and carries no flag — the line
is emitted whether the reason layer is on or off, and says which.

**Why an observability change earned priority over the quality lever.** 24j is
live for every user with no canary, which was the right call (there are no
users to protect with a small blast radius, and rollback is one variable). But
it means the ONLY defence left is noticing, and the failure 24j can actually
have is not loud. It cannot crash — it is a sorting rule — and it cannot empty
a block, because the bottom tier is never empty. What it can do is be quietly
mediocre: if the words read badly, nothing errors, the bookmarks are simply on
worse moments, for everyone, looking entirely normal. Nothing anywhere recorded
that the layer had ranked anything at all.

**One aggregate line per Take, not one per block.** `selection_summary` in
`services/reasonable_confidence.py`:

    reason layer take=<id> enabled=1 selected=12 covered=2 partial=1 not=9
                           unmeasured=0 degraded=11

Two numbers in that line answer the question the whole rollout rests on.
`not=9` says the gate is barely gating — nine of twelve winners carried nothing
of their slide. `degraded=11` says eleven of those verdicts came from word
overlap rather than entailment, which is the `piece_llm_budget()` ceiling
showing up as data instead of as an argument. The founder has parked that
ceiling deliberately; this is how it will be re-read when he unparks it.

**`enabled=` is on the line for a reason.** Without it the log is ambiguous:
an all-`covered` Take could mean the layer worked, or that it was off and the
delivery read happened to agree. It also gives a second, cheaper answer to
"did the flag actually reach this service" than reading three boot logs — the
service that processed the Take says so on every Take.

**It cannot raise, and that is asserted.** It runs on the live path purely to
produce a log line, and a log line is never worth a failed Take. The test hands
it nine shapes of junk — `None`, a string, a list of `None`, a block whose
candidates are not a list — and asserts a `str` comes back every time.

**Counts only.** No quote, no transcript, no score. AC-9 proper is about what
reaches a speaker and a deploy log is not that surface (`_row_rejection` in
`take_feedback_policy_v3_service.py` says the same of its own values), but a
log is also not a place to put someone's words, so a test asserts a `quote` on
the row does not appear in the line.
