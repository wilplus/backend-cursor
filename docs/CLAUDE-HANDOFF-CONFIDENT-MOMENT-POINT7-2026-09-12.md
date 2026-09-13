# Claude Handoff — Confident Moment Coaching Bundle point 7

Updated: 2026-09-13. Point 7 implementation and local disabled-gate verification
are complete; this is the end-to-end continuity handoff for review/release work.

## Objective

Finish all five Confident Moment Coaching Bundle chunks, integrate backend and
frontend, obtain independent ML/data and Engineering acceptance, and verify the
complete dark end-to-end flow. Do not stop at unit tests. Point 7 is complete
only after all serving/collection/dataset/training/evaluation/promotion gates are
proven disabled.

## Exact worktrees

- Backend: `/private/tmp/willab-confident-moment-chunk3-backend`
  - branch `codex/confident-moment-chunk3-integration`
  - HEAD/base `c7ff532fcc892e0e8c2ad6098c5146dcb2eabdd3`
  - uncommitted integrated work; pending migration remains unnumbered and
    unmanifested.
- Frontend: `/private/tmp/willab-confident-moment-frontend`
  - branch `codex/confident-moment-chunks4-5`
  - HEAD/base `0f88bd4a3f96d0f39c6679a232a1a32837f0dde6`
  - uncommitted integrated work.
- Never use or overwrite the user's ordinary dirty checkouts.

No commit, push, merge, migration numbering/manifest edit, deployment,
activation, real collection, dataset release, training, evaluation or promotion
is authorized.

## Accepted architecture chain

- Delta D3 SHA `59c4bad81e1b0a4917d76ce27f48b9a049ca29ea5ba94ad0829ba9ed5650dc67`
- Manifest D11 SHA `ec2d92bed3a0da354b4ecfd0051d68677e83f9f0d40382c9e3d9678c287c49ea`
- D43 SHA `80ad06e01f2bfee7e91e2ac090afec1a3ed758e96ec2b53410dae51b4edf1fdf`
- D44 SHA `28c25d2213cac89636218df3013eaa8f35cd8033b52e6f094a6c519b3131dae0`
- D45 SHA `80897ce76b1fba0ed3d9cd11cb7100f56bc0a5efa868351bd9d1bfb13866c680`
- D46 SHA `2cc526321f10387ec775356995700e57c889c57b48d0441f1a2ffdd781d65db4` — accepted
- D47 SHA `49957a14ab21701d5a7cbc56c38bbda0ed69ca9eb218850aafb957204a5267be`
- D48 SHA `e637c3b25b77f24444b38ef7ad628890abf248869337a6ddc50c2d81090d0509` — accepted
- D49 SHA `a833c211cf077f294a7973714c065aaa65a1c1aede33c49e4d7ae3debcdc7031` — accepted

Read all referenced documents in `docs/` before changing a boundary. D49 is the
latest override.

## Current implementation state

Chunks 1–5 are implemented behind literal default-off gates and independently
accepted for the local, unnumbered snapshot.

- Pending migration SHA: `7ba7660f8cb5c808b3c246693c67769f048016d08c6192cc15a04fecd11aee91`.
- SQL/data audit: accepted after executable D46–D49 currentness, contention,
  exact owner-decision and target-speaker tests; PostgreSQL/security `110 passed`; narrow and production-shaped
  apply/reapply green.
- Backend application audit: accepted; focused `144 passed`; exact D49 v2 shapes,
  owner-decision validation and truthful no-byte deadline verified.
- Backend full local CI: `5237 passed, 445 skipped, 113 subtests`; manifest,
  migration runner, Ruff and mypy green.
- Frontend audit: accepted after terminal playback, durable exercise-playback,
  canonical comparison, exact owner-decision and neutral automatic-root copy corrections.
- Frontend: `1579 passed`; ESLint and BFF green; TypeScript only has the
  pre-existing missing `docx` module.

The exact frozen implementation evidence is:

- `docs/MLC3-CONFIDENT-MOMENT-POINT7-IMPLEMENTATION-EVIDENCE.md`
- `docs/MLC3-CONFIDENT-MOMENT-POINT7-BACKEND-SHA256.txt`
- `docs/MLC3-CONFIDENT-MOMENT-POINT7-FRONTEND-SHA256.txt`

Durable complete working-tree archives are generated only after this document
and both checksum manifests are frozen. Their outer SHA-256 values accompany
the final review packet; they are not self-referential contents of this handoff.

No implementation work remains in flight. The next action is checksum-pinned
ML/data implementation review of this final packet, followed by a separately
authorized release-preparation stage if accepted.

## Reproduction commands

Backend disposable PostgreSQL socket (if still running):
`/private/tmp/cm-pg-final.Xfxoe7`, port `55555`, user `postgres`.

Run fresh uniquely named databases:

```text
env CONFIDENT_MOMENT_PGHOST=/private/tmp/cm-pg-final.Xfxoe7 CONFIDENT_MOMENT_PGPORT=55555 CONFIDENT_MOMENT_PGUSER=postgres tests/integration/confident_moment_rehearsal.sh narrow willab_confident_moment_<unique>_narrow
env CONFIDENT_MOMENT_REHEARSAL_DSN=postgresql://postgres@/willab_confident_moment_<unique>_narrow?host=/private/tmp/cm-pg-final.Xfxoe7&port=55555 .venv-ci/bin/python -m pytest -q tests/test_confident_moment_coaching_bundle_postgres.py tests/test_confident_moment_bundle_security.py
env CONFIDENT_MOMENT_PGHOST=/private/tmp/cm-pg-final.Xfxoe7 CONFIDENT_MOMENT_PGPORT=55555 CONFIDENT_MOMENT_PGUSER=postgres tests/integration/confident_moment_rehearsal.sh released willab_confident_moment_<unique>_released
```

Then run backend `scripts/local_ci.sh`, focused worker/route tests, Ruff, mypy,
and `git diff --check`.

Frontend must use Node 24: `PATH=/opt/homebrew/bin:/usr/bin:/bin npm test`, then
`npm run lint`, `npm run check:bff`, `npx tsc --noEmit`, and `git diff --check`.
Treat only the already-known missing `docx` environment dependency as pre-existing.

## Required end-to-end assertions

- Visible item creates one exact render exposure even without playback/answer.
- Private same-origin source playback must succeed before confidence answer is
  enabled; no transcript/key/presigned URL; all failure paths emit no bytes.
- Exact response reveals concise Comment, optional Rephrase Update/Cancel.
- Available exercise correlation is read-only and confidence-anchor-only;
  `not_supplied` is invisible/nonsemantic and creates no offer.
- Existing offer playback/practice/self-speaker chain is reused; chosen re-record
  supplies exact practice attempt and source/practice binding IDs to Save.
- Reload reconstructs exact owner decision and accepted text binding.
- Coach sees all items only after complete blind reveal and one editor per exact
  assignment; async revision updates buzz/read state without changing wording
  authority.
- 30/80/100 roots, Save/restore/lock and exact replay preserve provenance.
- No fabricated judgment, confidence, improvement, adequacy, outcome, dataset or
  ninth learning-surface row.
- Every product and learning gate remains literal disabled.

If any test or audit changes executable files, re-freeze all hashes and repeat
both independent reviews. Do not infer activation permission from completion.
