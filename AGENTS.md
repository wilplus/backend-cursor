# AGENTS.md — read this first

This file exists so that ANY coding agent — whatever filename its harness
conventions look for — finds the house rules before touching this repo.

**The operating doctrine lives in [`CLAUDE.md`](CLAUDE.md). Read it before
any work.** It is canonical there on purpose (single home, anti-drift): do
not fork or paraphrase its content into this file. It carries:

- the north star (F1 / F2) and the LOCKED choices (L1 / L2 / L3),
- the FENCES — AC-9, CONSTRUCT, BLIND COACH, LIVE LOOP, NORTH-STAR LOCK,
- the **WILLAB DECISION FILTER**, to be run on EVERY task before work
  starts (feature, refactor, bugfix, library, copy, infra, prompt edit —
  everything), with the full procedure in
  [`docs/willab_decision_filter.md`](docs/willab_decision_filter.md),
- the standing engineering constraints: the local CI gate
  (`scripts/local_ci.sh`), the `MIGRATE_ON_BOOT` warning (merging a
  migration IS running it in prod), the CONFIG-FIRST rule, and
  founder sign-off on all user-facing copy.
- the Phase-1 processing boundary: no direct user-data provider calls, no
  route-local authorization logic, and no Phase-2 learning activation without
  its own reviewed authorization.

The frontend repo (`frontend-cursor`) carries the same filter, kept
**identical** on purpose — a divergence between the two copies is itself
drift. Same rule here: this pointer must never grow a competing version
of the doctrine.

Project state, system map, shipping mechanics, billing, and the
maintainer checklist: [`docs/HANDOFF.md`](docs/HANDOFF.md).
