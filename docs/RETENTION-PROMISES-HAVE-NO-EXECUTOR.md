# The retention promises have no executor

**2026-09-23. Finding, not a change.** `docs/HANDOFF-2026-09-23.md` §1.4 asks
whether the retention rules actually run, and says the answer is one query.
The query is necessary but it is not sufficient, and the code answers a larger
question without needing production at all.

`FILTER: JUSTIFIED-SCAFFOLDING — cat {F1-SUPPORT} — fences {clear: reports,
changes no copy} — locks {clear} — redirect: the named in-flight task is
publishing the Phase-1 policy (#622), which this finding gates.`

> **This document changes nothing.** The handoff is explicit: *"Report, do not
> quietly change the copy — it is hashed and needs a new policy version."* No
> copy, migration, manifest entry or schedule is touched here.

---

## The finding

**There is no scheduled retention executor. Not disabled — absent.**

| | |
|---|---|
| reads `data_retention_rules` | `services/data_purge.py`, `services/data_purge_registry.py` |
| writes `data_purge_events` | `services/data_purge_registry.py` |
| scheduled entrypoint | **none** |
| `scripts/` purge or retention | `run_phase1_data_purge.py`, and only that |

`run_phase1_data_purge.py` takes one `--purge-request-id`, defaults to
`preview`, requires `--confirm-request-id` to match, and refuses entirely
unless `PHASE1_PURGE_EXECUTION_ENABLED=true`. It is the **erasure-request**
path: a human running a script for one named subject. Nothing runs on a timer.

So `SELECT count(*) FROM data_purge_events` is worth running, but a zero would
not mean "the job has not fired yet". There is no job.

## Two corrections to the handoff, offered in the spirit it was written

**1. There is no purge cron.** §1.4 says *"the cron is what runs the purge"*
and §1.3 builds on it. The five cron scripts are `annotation-export`,
`devbugs`, `drift`, `life-reminders` and `mlc2-confidence-readiness`. §1.3's
observability gap is real and worth closing for the crons that exist — none of
them echoes the gate flag, and `tests/test_railway_boot_scripts.py` pins
`BOOT_SCRIPTS` to web and worker — but it is not why retention does not run.

**2. `data_retention_rules` is not the timed-deletion table.** Its four rules
are evidence categories — `authorization_evidence`, `deletion_evidence`,
`processor_evidence`, `transparency_evidence` — every one of them
`retention_until_rule = 'accountability_need_ends'`. They decide what
**survives** an erasure request under Art 17(3) / Art 5(2). They are not a
schedule for deleting content. `RETENTION_RULE_UNRESOLVED` means "this
evidence category has no retention decision", not "the sweeper found nothing".

## Why the seed is held back, and why that is right

`migrations/pending/seed_phase1_retention_schedule.sql` is not in
`manifest.txt`, so it has never run and the table is empty. Its own header
says why: it needs the `object_key` and `sha256` of the **signed** retention
schedule, and that document is not signed —
`legal/phase1-2026.1/06-retention-schedule-v1.0-DRAFT.md` §4 holds it open on
OpenAI's own retention window. Inventing those two values would write a record
asserting that a document exists and was approved, into an append-only table
that cannot be corrected afterwards.

That is the CONFIG-FIRST escape hatch used correctly, and the file also
explains why a migration that RAISED on placeholders would be worse: under
`MIGRATE_ON_BOOT=1` a raising migration fails container start, so an accidental
merge would take production down rather than refuse politely.

`financial_evidence` is deliberately unseeded and the file says the purge stays
blocked until it is decided: `token_ledger` and `llm_usage` are per-user usage
ledgers that **survive an erasure request today**, doc 06 §3 puts three options
to counsel, and engineering must not pick one.

## What this means for #622, which is the live decision

The copy on `p11-unbundle-the-policy` §7 makes **four timed promises**:

| promise | executor |
|---|---|
| Recordings (audio): 12 months after last use | none |
| Practice attempts: the rest deleted after 30 days | none |
| Uploaded files that never became a recording: 24 hours | none |
| Security and technical logs: 90 days | none |

The **currently live** 2026-09-20 copy makes one of these (the 30-day practice
attempts). Publishing §7 as written takes a single unkept promise to four.

§7 also cites `willpowerlab.com/legal/retention` for the full schedule. There
is no `src/app/legal/` directory in `frontend-cursor`. A published privacy
policy would point at a 404.

And §9 names two survivors of deletion — accountability records, and records
kept by law "for example accounting records". Per doc 06 §3 the service takes
no payment, so there are no accounting records to point at, while
`token_ledger` and `llm_usage` do survive. The named survivors and the actual
survivors are not the same set.

## The decision, which is the founder's

Three options, and the honest one is not obviously the third.

1. **Build the timed executor before publishing.** Largest, and it does not
   fit before the first tester.
2. **Say what the system does.** §7 describes deletion on request and on
   account deletion, which is true today and is performed, and drops or
   qualifies the four periods until there is something that performs them.
   The schedule link goes when the page does not exist. Cheapest, honest, and
   it needs founder sign-off like any copy.
3. **Publish as written and build after.** A written retention period is a
   promise from the day it is accepted, not from the day it is implemented.

Option 2 costs nothing now because **#622 has not been run.** After it runs,
changing §7 needs a new policy version and re-acceptance by everyone who
accepted the old one. This is the cheapest moment this decision will ever be.

## What was NOT done here

No copy edited. No migration moved into the manifest. No schedule invented. No
retention executor built — that is a build, not a finding, and it needs its own
decision about what deletes what and what proves it happened.

## How to verify each claim

```
# no scheduled executor
git grep -ln "data_retention_rules" -- services/ scripts/ routes/ bin/
git ls-tree -r --name-only HEAD scripts/ | grep -iE "purge|retention"
ls bin/railway-*-cron.sh

# the seed never runs
grep -c seed_phase1_retention_schedule migrations/manifest.txt   # 0

# the cited page does not exist
ls ../frontend-cursor/src/app/legal 2>&1

# and in production, the founder's query
SELECT count(*) FROM data_purge_events;
```
