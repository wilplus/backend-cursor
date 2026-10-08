# Build plan of 7 Oct 2026

The founder asked (7 Oct): where does every agreed design stand, how tightly
is it defined, and what are the DEV tasks to build it inch-perfect, with the
ML and backend under it. Eight read-only audits (one per area) compared the
locks with `main` at 018d502d. A critic pass then looked for missing areas,
conflicts between locks, duplicates and weak claims. A planner wrote the
result.

- `BUILD-PLAN-2026-10-07.json`: the full result. `plan` holds the readiness
  summary, the eight areas, 101 DEV tasks with acceptance, executor and
  filter stamp, 15 founder questions and 5 build waves. `critic` and
  `audits` hold the evidence behind them.
- The founder's page: https://claude.ai/artifact/1wTXKW2FRabbKcbweZPCfz
- The questions and each wave's green light are in the Navigation Panel
  (https://claude.ai/artifact/HtegguK1CS8R2VBNmmufhT), on the board
  `build-2026-10-07`. Answers are recorded in `docs/SPEC-DECISIONS-LOG.md`
  as they come.

Executors: `this-session` for migrations and every locked screen (GPT
check and side-by-side picture check happen there); `fable-session` for
large self-contained builds in a new session; `grok-prompt` for repetitive
code the founder pastes to Grok and pastes back.

## The panel archive

The Navigation Panel started a fresh board on 7 Oct.
`../NAVIGATION-PANEL-ARCHIVE-2026-10-07.json` is a full copy of everything
it held before: 265 questions (all closed or withdrawn), 238 answers, 26
hand-offs, 8 Done cards and 84 news cards. The panel still stores them; it
shows only the new board. Every decision in them is already in
`docs/SPEC-DECISIONS-LOG.md`.
