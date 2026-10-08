# How audit work runs (founder-approved 6 October 2026)

Every rule below is a founder answer from the Navigation Panel (https://claude.ai/artifact/HtegguK1CS8R2VBNmmufhT). The answers are kept word for word in `PANEL-ANSWERS-2026-10-06.md`.

## Sources of truth, in order
1. The repo's `CLAUDE.md` (fences, locks, the decision filter).
2. The design lock: https://claude.ai/artifact/AeRVS91VUAiJLCePB82s3d
3. The V4 decision page and its Developer brief: https://claude.ai/artifact/UXiVaBvGLRTg83kjmHKY6E
4. `LEDGER.md`. The audit is a list of claims, not facts.

## The ledger is the only to-do list (W1 A)
- If it isn't a row, nobody works on it. A new idea becomes a row first.
- Rows are never deleted. DONE needs a merged PR and a passing test.

## Order (W2 A)
Most serious first: S1 live loop broken, S2 data loss, S3 fence breach, S4 wrong behaviour, S5 looks. Within a level, the lowest row ID first. Rows that wait on the founder (FOUNDER) or are PARKED are skipped.

## Roles
- **Coordinator:** the long-running session. It picks the next row, writes the hand-offs, puts every question to the founder in the panel (W4 A: questions only come there), and writes one Done screen per finished row (W5 A). For speaker or coach flows, a Done screen shows real app screens.
- **Test author: Grok** (M3 A, M3a A). It sees only the ledger row and the facts in its hand-off. It writes the done-test first, which must fail before the fix and pass after it.
- **Fixer:** a fresh session per row (W3 A). It reads only `LEDGER.md`, `REPO-MAP.md` and its row's files.
  - Serious effort (F1-CORE, migrations, multi-file logic): Fable.
  - Routine (docs, small scripts, mechanical edits): Sonnet.
  - Otherwise: the session's current model.
  - An external coding agent may take small rows (M5 A): a few files, no database change, no design-locked screen. Frontend chunks and repetitive code are the best fit (W3 note). Its work is pasted back into the panel and integrated by a fixer session.
- **The fixer never edits the done-test** (M3b A). If it thinks the test is wrong, it stops and writes why, and the test author or the founder decides. A check fails any PR in which the fixer changed the test file (X3/X1).
- **Checker: GPT (through use.ai today; M1a), the second model** (M3a A). It reviews every screen PR, every migration PR and every 10th other PR against the row and the design lock (H8 A). Its verdict goes into the PR word for word.

## Hand-offs (M4 A)
For now hand-offs are manual: the coordinator writes a task in the panel's Hand-offs screen, and the founder copies it to the other model and pastes the answer back. If this works well but takes too much manual work, the founder sets up API access later (keys as environment variables, never in chat).

## Safety checks to build (H1–H12 A; rows X1–X10)
Ledger checker, PR report form, Ledger-Row trailer, three fence checks (no number to a speaker, signed words only, human-only training labels), design-lock guard, independent checker, screen pictures compared with the design, next-row hook at session start, `REPO-MAP.md`, and a weekly adherence check.
