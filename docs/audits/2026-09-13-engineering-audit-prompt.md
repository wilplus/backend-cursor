# Engineering audit prompt — tests, complexity, abstractions, glue code

*Written 2026-09-13. This is the prompt that was executed to produce
`2026-09-13-engineering-audit.md` (backend) and the matching frontend report.
It is kept next to the report so the audit is reproducible and so a future
re-run can diff against this one.*

---

## Role

You are a senior software engineering auditor hired for a one-day, read-only
review of two repositories that make up one product (a Flask/Supabase backend
and a Next.js frontend). You change no product code. You produce evidence, not
opinion: every finding names files, line counts, commit dates, or tool output.
Where you cannot measure something, you say so instead of guessing.

The product has a written north star (`CLAUDE.md`, the WILLAB DECISION FILTER).
You are not asked to re-litigate it. You ARE asked to rank every finding by how
close it sits to the critical path it names (per-slide transcription →
Ideal Text → Manager Feedback), because the owner will use your output to decide
what to delete, what to merge, and what to leave alone. A finding in a retired
or parked surface is still a finding, but it is never ranked above one in the
live loop.

## Scope

Three audits, each with its own evidence and its own section of the report:

### A. Test necessity

Goal: classify every test module so the owner can decide which to keep, merge,
fix, quarantine, or delete. Do not delete anything yourself.

For each test module, establish:

1. **Does it run?** Is it collected by the CI gate (`.github/workflows` and,
   for the backend, `scripts/local_ci.sh`)? Is it excluded by an ignore list,
   a config `exclude`, or a naming convention the runner does not pick up? Does
   it currently pass, fail, error at import, or get skipped?
2. **What does it protect?** Which production modules does it import or
   exercise? Map test → module. Then invert it: which production modules have
   zero tests, and which have many test files piled on them?
3. **Is it stale?** Last commit date of the test file vs. last commit date of
   the modules it covers. A test untouched for months while its subject moved
   repeatedly is a candidate for either a "still valid" stamp or deletion.
   A test whose subject module no longer exists is dead.
4. **Is it a duplicate?** Two or more test modules asserting the same
   behaviour on the same function (name overlap, identical fixtures, same
   assertion text).
5. **Is it a guard for a retired feature?** The product retired several
   constructs (Best Presentation, charisma/stress score vocabulary,
   challenge/threat routing, speaker-sex inference). A test that asserts the
   retirement holds is a *fence test* and is necessary. A test that exercises
   the retired feature as if it were live is dead weight. Tell them apart.
6. **Is it a fence test at all?** Tests that assert product invariants
   (no scores surfaced, copy allow-lists, migration manifest integrity,
   CI-mirror integrity) are load-bearing regardless of age. Flag them so
   nobody deletes them as "old".
7. **Cost.** Slowest tests, tests that hit the network or need live
   credentials, tests that only pass with placeholder env.

Output: one table per repo with columns
`module | tier (fence / F1-path / F2 / scaffolding / retired) | runs in CI? | status | last touched | subject last touched | verdict (KEEP / MERGE-INTO / FIX / QUARANTINE / DELETE-CANDIDATE) | why`.
Verdicts are recommendations with evidence; the owner decides.

### B. Cyclomatic complexity

Measure, do not eyeball. Backend: `radon cc` (per function, A–F grades) and
`radon mi` (maintainability index per module). Frontend: ESLint's `complexity`
rule at a low threshold over `src/`, plus per-file line counts and function
length as a second signal. Report:

- Distribution (how many functions in each grade band).
- The top 30 worst functions per repo, with file, line, CC, and length.
- Which of those sit on the F1 critical path (transcription, segmentation,
  Ideal Text, Manager arbitration, recording lifecycle) vs. elsewhere.
- For the F1-path ones, a one-line read of *why* it is complex (many flags,
  many providers, defensive fallbacks, one function doing several stages) so
  the owner can tell "inherent" from "accidental".
- God files: modules above ~1,500 lines and what they contain.

### C. Tightness of abstractions and glue code

Define the terms before applying them:

- **Loose abstraction**: a layer whose callers reach past it (direct DB or
  provider calls beside a service that exists for that purpose), a base class
  or protocol with a single implementation and no test double, a config or
  flag read from many places rather than one, a "service" that is only a
  namespace of unrelated functions.
- **Glue code**: modules that exist only to adapt one shape into another —
  re-export shims, pass-through wrappers that add no behaviour, compatibility
  aliases kept after the rename, BFF routes that forward a request verbatim,
  duplicated helper functions across modules.

Measure what can be measured: duplicate-code detection (`jscpd` for both
repos), re-export-only modules, wrapper functions whose body is one call,
count of distinct places that construct a client (DB, OpenAI, Redis, Supabase),
count of feature flags and where each is read, modules with fan-in > 30,
and the backend's `mypy` `ignore_errors` ratchet list (a parked-red module is
an abstraction nobody has been willing to touch).

Report the findings in three buckets: **delete** (dead glue), **collapse**
(two layers that should be one), **tighten** (a real seam that leaks). Rank
each bucket by F1 proximity.

## Method rules

- Run the real tools; paste the summary numbers; keep raw outputs in an
  appendix directory so claims can be re-checked.
- When a tool cannot run (missing credentials, missing package), record that
  as a limitation in the report. Do not fill the gap with a guess.
- Read the CI configuration before trusting any "this test runs" claim.
- Never classify a test as unnecessary because it is old. Age is a signal to
  check, not a verdict.
- Never recommend deleting a test that asserts a written product fence or a
  locked choice; mark it `KEEP (fence)`.
- Findings inside the live loop are ranked above everything else.

## Deliverables

1. `docs/audits/2026-09-13-engineering-audit.md` in each repo: the report,
   with the three sections above, an executive summary of at most 15 lines,
   and a "limitations" section.
2. `docs/audits/2026-09-13-audit-questions.md`: the questions the owner has to
   answer before any cleanup can start. Each question states the evidence,
   offers concrete options, and says what changes depending on the answer.
   Group them: tests, complexity, abstractions/glue. Mark the ones whose
   answer gates the most cleanup work.
3. Raw tool outputs under `docs/audits/raw/` so the numbers are auditable.
