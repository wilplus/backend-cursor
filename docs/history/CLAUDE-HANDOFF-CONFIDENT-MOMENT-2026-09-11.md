# Claude Handoff — Confident Moment Coaching Bundle

**Date:** 2026-09-11  
**Goal:** continue the checksum-gated Chunk 2B → Chunk 3 → Chunk 4 → Chunk 5
implementation without architecture drift. Nothing in this handoff authorizes
migration numbering, merge, deployment, activation, collection, datasets,
training, evaluation, or promotion.

## Start here

Read completely, in order:

1. `/Users/arturwillonski/Documents/hunter-backend/AGENTS.md`
2. `/Users/arturwillonski/Documents/hunter-backend/CLAUDE.md`
3. `/Users/arturwillonski/Documents/hunter-backend/docs/willab_decision_filter.md`
4. Contract Delta D3:
   `/Users/arturwillonski/Documents/hunter-backend/docs/MLC3-CONFIDENT-MOMENT-COACHING-CONTRACT-DELTA-D3.md`
   SHA-256 `59c4bad81e1b0a4917d76ce27f48b9a049ca29ea5ba94ad0829ba9ed5650dc67`
5. Accepted executable Interface Manifest D11:
   `/Users/arturwillonski/Documents/hunter-backend/docs/MLC3-CONFIDENT-MOMENT-COACHING-INTERFACE-MANIFEST-D11.md`
   SHA-256 `ec2d92bed3a0da354b4ecfd0051d68677e83f9f0d40382c9e3d9678c287c49ea`
6. Dataset/Learning contract:
   `/Users/arturwillonski/Documents/hunter-backend/docs/MLC3-DATASET-AND-LEARNING-READINESS-D1.md`
7. Master execution prompt:
   `/Users/arturwillonski/Documents/hunter-backend/docs/cursor-prompts/MLC3-CONFIDENT-MOMENT-COACHING-EXECUTION-PROMPT.md`

Superseded/rejected A1/A2 and D7–D10 drafts must not be implemented. D11
incorporates accepted Secure Read A3.

## Non-negotiable product architecture

- F1 live loop: recording → transcript → persistent user-controlled Ideal Text
  → exactly three Manager families. Coach work is asynchronous.
- L1: later Takes/model/coach never silently overwrite Ideal Text.
- L2: no raw candidates or extra Manager slots.
- L3: machine, owner, blind coach, product action, acoustic movement,
  preference and authoring provenance remain separate.
- AC-9: never surface scores, ranks, ratios, probabilities or model verdicts.
- Bundle is a read/presentation model, not a feedback family or learning surface.
- Feedback Language is `Comment | Rephrase`; praise is a positive Comment at
  interaction level but retains canonical praise provenance.
- Automatic root, owner-selected/locked root, and quorum-qualified confident
  reference are independent axes.
- Coverage targets are 30% after Take 1, 80% after Take 2, 100% after Take 3;
  shortfall stays honest and never manufactures confidence.
- `exercise` is exactly `null` in the secure Bundle projection. Exercise
  availability/media remain on the existing guarded `/v2/user/mlc3/*` path;
  null is not a no-match or learning signal.
- All new/product evidence remains `dataset_eligible=false`. No ninth learning
  surface. All serving/collection/dataset/training/evaluation/promotion gates
  remain literally disabled.

## Repositories and frozen bases

### Chunk 2B backend worktree — ACTIVE WORK

Path: `/private/tmp/willab-confident-moment-chunk2-backend`  
Branch/HEAD base: `b63f0f98cf55e420072324a681a48fbcfd55b9e8`  
State: five modified files, intentionally uncommitted and unpushed:

```text
migrations/pending/add_confident_moment_coaching_bundle_v1.sql
services/data_purge_registry.py
tests/test_confident_moment_bundle_security.py
tests/test_confident_moment_coaching_bundle_postgres.py
tests/test_phase1_deletion_completion.py
```

Current hashes at handoff:

```text
13333fec619e2fbf7b6845c253056268c07a3550331f068f8671eb0ece2f35b8  migration
bc53b53a81a168fdf2889280a17b955cfb1efc3daba8934151f2d29090d6e410  purge registry
0afe94df285a4e96fa5c04cb373568afcec567daf546e42c082f250a1b221803  security tests
cdd58ade4e80ab66c78b5df60f756936985b1803b1564b3c5916a6625040f457  PostgreSQL tests
b5050fe1ef4ee6c437008e2096c03b8e2a315035e2e95b7598327584a772e6d4  deletion tests
```

These hashes predate the final two requested ML corrections below; the working
tree was stopped safely before those corrections were applied.

### Held Grok Chunk 3 patch — DO NOT APPLY YET

Exact recovered patch:
`/private/tmp/grok-chunk3-cumulative.patch`  
SHA-256 `83d2ab7f0d811605871c3d6b0f4d2c3099c17b1bfb7044deb1d93e0245e61088`

Disposable applied checkout:
`/private/tmp/willab-chunk3-corrected.5CsGz4`  
Base: `b63f0f98cf55e420072324a681a48fbcfd55b9e8`  
Evidence before secure-read revision: 38 focused tests passed.

Grok conversation:
`https://grok.com/c/c97cbea8-5230-433c-b2f1-74ad53c92b38`

Grok has been explicitly told to hold the patch, not push, and not start
Chunks 4/5 until it receives the accepted Chunk 2B commit/checksum.

## Chunk 2B implementation already completed

The uncommitted draft implements D11's secure database-owned projection,
immutable revision/delivery heads, staged writer-shared serializer graph,
identity-set hashing, forced-RLS projection tables, exact blind-coach lineage,
frozen Manager fallback, full runtime privilege revocation including TRUNCATE,
subject/reviewer deletion traversal, and `exercise=null`.

Engineering accepted these corrected boundaries after executable tests:

- exact coach revision/delivery replay, conflict, successor and stale replay;
- zero partial records on rejection;
- legacy-root-versus-projection two-connection lock order;
- stale/current delivery render, exact replay, unread→read successor;
- projection/render serialization in both commit orders;
- permissions, deletion and apply/reapply.

Latest evidence before the final ML review: submitter 55 focused passed;
independent Engineering 52 focused passed; Ruff/compileall/diff-check green.
The DB is a D11 closure fixture, not a fresh full production-chain clone.

## CURRENT BLOCKER — implement next

The latest ML/data verdict is **REVISIONS_REQUIRED** with exactly two P1 fixes:

1. `ack_feedback_language_revision_render_v1` must revalidate, both before and
   after the blocking exposure write, the same exact authority/source chain as
   the projection: current reviewer access, exact live blind assignment,
   judgment/reveal/source role, membership/source deletion-purge validity, and
   recipient D4 dual-purpose authority. Add two-connection tests for reviewer
   withdrawal and source deletion/purge in both commit orders. Invalidation-
   winning order creates zero exposure; unchanged exact replay is idempotent.
2. Reset every attachment-scoped PL/pgSQL variable at the beginning of every
   projection item loop. This includes revision/delivery, unread,
   presentation/rendered-exposure, resolution, exclusion and output hashes.
   Add structural constraints tying them to the same projection item. Test
   mixed confidence/rewrite/praise attachments in both orders and both
   rendered/unrendered states. No item or summary may inherit another
   candidate's state.

Do not send Chunk 3 to Grok until these fixes pass, receive independent
Engineering re-review, and receive ML/data implementation acceptance.

## Exact continuation sequence

1. Inspect the five-file dirty diff; preserve unrelated user work.
2. Implement only the two current ML blockers with `apply_patch`.
3. Run the full focused static/security/deletion/PostgreSQL suite, migration
   apply/reapply, Ruff, compileall and `git diff --check`.
4. Freeze a new exact five-file packet/checksums. The earlier packet
   `e491b7a...` is superseded and must not be reused.
5. Obtain independent Engineering and ML/data implementation acceptance.
6. Ask the founder for explicit permission before creating the Chunk 2B commit;
   prior acceptance does not authorize commit/push.
7. After commit, tell Grok to rebase/reconstruct Chunk 3 on that exact SHA and:
   - replace all direct Bundle/summary table reads with exactly
     `ConfidentMomentBundleRepository.project_take_bundles →
     project_confident_moment_bundles_v1`;
   - make zero enabled `.table(...)` calls for Bundle/projection data;
   - remove broad exception suppression and never convert authority/identity/
     source failures into an empty valid summary;
   - map `CONFIDENT_MOMENT_PROJECTION_RETRY_REQUIRED` to HTTP 409;
   - use the exact eight D11 repository method→RPC tuples;
   - preserve all disabled gates and return `exercise=null` unchanged.
8. Recover Grok's new patch, verify checksum, apply to a disposable checkout,
   run tests, and obtain combined Chunk 2/3 ML/data + Engineering acceptance.
9. Only then begin delegated Chunk 4 (frontend) and Chunk 5 (coach integration).
10. No numbering, release, deployment or activation until separate gates.

## Git and safety

- Do not clean/reset the dirty worktree.
- Do not modify existing numbered migrations or the manifest.
- The pending migration remains unnumbered.
- Do not paste PATs or secrets into Claude/Grok/chat.
- Do not claim a commit, push, deployment or production test that did not occur.

## Decision filter

```text
VERDICT:  ADVANCE-F2
CATEGORY: F2
WHY:      This finishes the exact provenance-safe Confident Moment coaching
          path without changing F1, Manager budget, AC-9 or learning surfaces.
REDIRECT: Close the two current ML blockers, re-review Chunk 2B, then hand the
          exact accepted commit to Grok for the narrow Chunk 3 adapter change.
```

`FILTER: ADVANCE-F2 — cat F2 — fences clear — locks clear — redirect: finish
Chunk 2B currentness before any frontend or activation work.`
