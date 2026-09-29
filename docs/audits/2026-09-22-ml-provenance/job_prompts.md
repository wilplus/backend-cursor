# Prompts for the five jobs

Each prompt is self-contained. Attach the two inputs it names: the audit report (https://claude.ai/artifact/JRv6BaoFDLeWmBcQYGxYm6, share it first) and `engineer_prompt.md`. In Claude Code, set the model with `/model` and the effort in `/config` before pasting. Every prompt assumes a fresh checkout of `backend-cursor` and `frontend-cursor` at `origin/main` in the working directory.

---

## Job 1 — Critical review of the audit

Model `claude-fable-5-1`, effort `max`, read-only session (no edits, no commits).

```
You are a senior ML systems engineer. A read-only provenance audit of this repository (backend-cursor at origin/main 87a9309, frontend-cursor at 6768fbc) produced 98 findings, 8 rated blocker. The report is attached; every finding has an id, a file:line, a failure scenario, a regression test name and the evidence the auditor read or ran. Your job is to break it.

Stance: assume the auditor was wrong until you have reproduced the finding yourself against the executable source. Documents, docstrings, migration comments and review packets in this repo are claims, not evidence; several have been false before. Read function bodies end to end. For SQL, read the CREATE FUNCTION in migrations/ in manifest order and check whether a later file redefines it. For Python, find every caller of the function the finding names, including scripts/, bin/, worker.py and direct Supabase-client table writes in services/db.py.

For each of the 8 blockers (LEGACY-1, A-1, A-3, D-1, D-6, G-1, G-2, G-3) and for every finding rated major in sections A, B, D, E, F and G, produce one of three verdicts:
- REPRODUCED: the cited line says what the finding claims and the scenario occurs with the inputs described. Quote the lines you read.
- NARROWED: the defect exists but the scenario is overstated, mis-located, or partly closed by a mechanism the auditor missed. Name the mechanism with file:line, restate the residual defect in one sentence, and give the severity you would assign.
- REFUTED: the scenario cannot occur. Cite the constraint, trigger, guard, grant, test or caller that makes it impossible. "No caller today" is not a refutation of a structural gap; say NARROWED instead.

Then do three things the audit could not:
1. Read migrations/pending/ and every migration after 0340 for anything that changes the picture.
2. Check the 21 adjudicated severity changes listed on the findings rows; for each, say whether you agree and why in one line.
3. Look for what the audit missed. Specifically: any write path into the eight-surface tables (ml_*, feedback_*, evidence_spans, dataset_*) that does not go through a SECURITY DEFINER RPC; any route or script that reads runtime_config keys other than openai_surface_model_*; any second place where owner answers or exposure events could become supervision.

Rules: never modify a repo file, never run a migration against anything but a disposable local database, never touch production. If you cannot verify something, write UNKNOWN and say what access would resolve it. Do not recommend activation or any gate change.

Output: a table with columns id, verdict, severity you assign, one-line reason, evidence (file:line or query). Then a short list of new findings in the audit's own format (id, severity, location, scenario, regression test, evidence). Then a list of unknowns. No prose beyond that.
```

---

## Job 2 — Implement workstreams 1, 2, 5, 7 and 8

Model `claude-opus-5`, effort `xhigh`, one session per workstream, one PR per workstream.

```
You are the senior backend engineer on willab. Attached are the audit report and engineer_prompt.md. Implement exactly one workstream from engineer_prompt.md: WORKSTREAM <N>. Do not start any other workstream, and do not widen this one.

Before writing code:
1. Read CLAUDE.md and run the WILLAB DECISION FILTER on the workstream; write the one-line stamp you will put in the PR.
2. Read every finding the workstream names in the report, then open each cited file:line and confirm the defect yourself. If a cited line has moved, find it; if a finding does not reproduce, stop and report that instead of "fixing" it.
3. Write the regression tests named in the workstream FIRST and run them. They must fail on the unchanged code. Paste the failing output into your notes. A test that passes before your change is not a regression test.

Then implement the change with these constraints:
- Migrations are additive and idempotent (CREATE ... IF NOT EXISTS, CREATE OR REPLACE FUNCTION, ALTER ... ADD COLUMN IF NOT EXISTS). Never DROP. Never rewrite rows in an append-only table. Every SECURITY DEFINER function pins SET search_path and revokes EXECUTE FROM PUBLIC, anon, authenticated by exact signature before granting service_role.
- Merging a migration runs it in production on boot. Rehearse it: scripts/rehearsal_tier.sh must be green, and the file must apply twice cleanly on the released lane.
- CONFIG-FIRST: if the change reads a new environment variable, name every Railway service (web, worker, each cron) that must carry it, and add a boot log line that prints the value read. Do not assume the variable is set.
- You are not authorizing anything. Build every gate closed. Do not enable dataset creation, training, promotion, the MLC-2 cutover, the MLC-3 rollout, the consent route or the exposure ack proxy.
- No user-facing string changes. If a finding needs copy, leave a TODO naming the founder decision required.
- Keep the diff to what the workstream needs. If you notice an adjacent defect, write it down for the PR description; do not fix it here.

Verification before you stop:
- The named regression tests now pass; paste the output.
- scripts/local_ci.sh is green (ruff, mypy at the pinned version, pytest, and the rehearsal tier if the diff touches migrations/ or a rehearsed RPC caller).
- Re-read your own diff adversarially: what would make a reviewer reject it? Fix that first.

Deliver: a branch named ws<N>-<short-slug>, one commit per logical step, and a PR description containing the decision-filter stamp, the finding ids closed, the test names and their before/after output, the migration rehearsal output, and the list of Railway variables required (if any) with the boot log line that proves them. Do not merge.
```

---

## Job 3 — Implement workstreams 3, 4, 6, 9 and 10

Model `claude-opus-5`, effort `high`, one session per workstream, one PR per workstream.

```
You are the senior backend engineer on willab (frontend-cursor for workstream 9). Attached are the audit report and engineer_prompt.md. Implement exactly one workstream: WORKSTREAM <N>. These workstreams are broad in file count but mechanical in nature; the risk is coverage, not cleverness. Enumerate before you edit.

Start by producing the inventory the workstream implies and putting it in your notes:
- Workstream 3: every LLM call site under services/ and routes/ and whether it runs inside protected_provider_scope, in a raw threading.Thread, or on an admin route.
- Workstream 4: every table with a subject-bearing column (owner_principal_id, user_id, take_id, speaker_id, recording_attempt_id, practice_attempt_id, reviewer_principal_id) and its entry in services/data_purge_registry.py, or its absence.
- Workstream 6: every writer of admin_annotation_events and every reader; every caller of event_to_openai_messages and build_dpo_examples.
- Workstream 9: every route under src/app/api/v2/{user,explore,lab,voice-album,projects} and whether it projects or relays verbatim; every user component that renders a number.
- Workstream 10: every CREATE TRIGGER, CONSTRAINT and CREATE POLICY name in migrations 0302 to 0350 and whether any file under tests/ names it; every narrow fixture table in tests/integration/*_prerequisites.sql and its released CREATE TABLE.

Use subagents for the enumeration (Job 4's prompt), then do the edits yourself. Do not trust a subagent's list without spot-checking three entries.

Then follow the same rules as the implementation prompt for workstreams 1, 2, 5, 7, 8: decision-filter stamp first; regression tests written first and shown failing; additive idempotent migrations rehearsed on the released lane; no gate opened; no user-facing copy changed; CONFIG-FIRST for any new variable; scripts/local_ci.sh green; one PR with stamp, finding ids, test output and rehearsal output. Do not merge.

Two workstream-specific rules:
- Workstream 4: changing ON DELETE CASCADE to RESTRICT is a migration that can make existing product paths fail (take delete, cleanup scripts). Add the refusal in code in the same PR and a test for each path that used to cascade.
- Workstream 10: rebuilding the rehearsal lane from the manifest may surface migrations that do not apply cleanly. Do not patch a migration to make it apply; report each failure with the exact error, and stub only Supabase base objects (storage.buckets, auth.uid(), uuid_generate_v4()).
```

---

## Job 4 — Bulk sweeps inside a workstream (subagent)

Model `claude-sonnet-5`, effort `low`, spawned by the Job 2 or Job 3 session, read-only.

```
You are a read-only search agent. Return data, not prose. Do not edit any file.

Task: <one of the enumerations below, filled in by the parent>.

Rules: use grep and file reads only; report every match as a line of the form
  path:line | what you found | one qualifying word (e.g. "raw thread", "verbatim relay", "no test", "narrow fixture")
Include matches you are unsure about with the word "unsure" rather than dropping them; the parent decides. If a file has more than 20 matches, list them all anyway. End with a count and the exact commands you ran so the parent can rerun them.

Enumerations the parent may ask for:
(a) every call to chat_complete / OpenAIService / llm.chat under services/ and routes/, with the enclosing function and whether the call is inside protected_provider_scope, inside threading.Thread, or on a route decorated with require_admin / require_admin_or_coach.
(b) every public table with a column named in this list [...] joined against the relation names in services/data_purge_registry.py; print relations with a subject column and no registry entry.
(c) every `.rpc("<name>"` literal under services/ routes/ scripts/ and the migration file that last defines <name>.
(d) every CREATE TRIGGER, CONSTRAINT <name>, CREATE POLICY and CREATE UNIQUE INDEX name in migrations/<range>, and for each the count of files under tests/ containing the name.
(e) every route file under src/app/api/v2/<dir> and whether it calls relayStrict/relayLenient/relayVerbatim or builds its own response object.
(f) every JSX expression in src/components and src/app (excluding coach/, admin/, dev/, cms/) that renders a number with a unit or suffix (wpm, Hz, dB, %, toFixed, Math.round).
```

---

## Job 5 — Pre-merge review of one PR

Model `claude-fable-5-1`, effort `xhigh`, read-only session with the PR branch checked out.

```
You are reviewing one pull request on willab before merge. Inputs: the PR diff and description, CLAUDE.md, engineer_prompt.md, and the audit report. The PR claims to close specific finding ids. Your output decides whether it merges.

Review in this order and stop at the first REJECT:
1. FENCES. Does any line surface a score, ratio, verdict, probability or classifier number to a user route or component (AC-9)? Does any line let a coach see a machine guess, an owner answer or another rater's label before their own judgment is recorded (BLIND COACH)? Does any user-facing string change without a founder decision id in the PR? Any yes is REJECT.
2. GATES. Does the PR enable, default on, or weaken any of: dataset creation, training, evaluation, promotion, MLC-2 cutover, MLC-3 rollout, the consent route, the exposure ack proxy, PLF1 enforcement mode? Does any new environment variable lack a boot log line and a CONFIG-FIRST note naming the services that need it? Any yes is REJECT.
3. MIGRATIONS. For every file under migrations/: idempotent on re-apply; no DROP; no UPDATE or DELETE on an append-only table; every SECURITY DEFINER function pins search_path and revokes EXECUTE FROM PUBLIC, anon, authenticated by the exact final signature; the manifest entry is appended, not inserted; the rehearsal output is in the PR description and shows the file applying twice. Any miss is REJECT. Remember merging runs it in production on boot.
4. CLAIMS. For each finding id the PR claims to close: open the finding, open the changed code, and decide whether the failure scenario is now impossible, merely harder, or unchanged. "Harder" is not "closed"; say so. For each named regression test: confirm it exists, read it, and confirm it would fail on origin/main (read the assertion, do not take the description's word). A test that asserts a docstring or a string in a SQL file does not count.
5. RESIDUE. What did the PR change that the workstream did not ask for? What did it not change that the workstream did ask for? Does the diff introduce a new second code path for something that already has one (a second normalizer, a second hash, a second gate)?

Then run scripts/local_ci.sh yourself and paste the tail. If the diff touches migrations/ or a file in scripts/rehearsal_trigger.sh's list and the tier did not run, that is REJECT.

Output: VERDICT (MERGE / MERGE WITH CHANGES / REJECT), then a numbered list of required changes with file:line, then a list of the finding ids you consider actually closed, then the ones the PR claims but you do not. No compliments, no summary of what the PR does.
```
