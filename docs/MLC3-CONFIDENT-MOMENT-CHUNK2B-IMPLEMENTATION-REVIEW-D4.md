# MLC-3 Confident Moment Coaching Bundle — Chunk 2B implementation review D4

## Review boundary

- Repository: `wilplus/backend-cursor`
- Branch: `codex/confident-moment-chunk2b-transfer`
- Exact base commit: `5a2601e18728e516443924cfd9f32691b55ce5fd`
- Migration remains pending, unnumbered, and absent from the numbered manifest.
- No commit, push, merge, deployment, activation, collection, dataset, training,
  evaluation, or promotion is part of this packet.

## Frozen contract inputs

| File | SHA-256 |
| --- | --- |
| `docs/MLC3-CONFIDENT-MOMENT-COACHING-CONTRACT-DELTA-D3.md` | `59c4bad81e1b0a4917d76ce27f48b9a049ca29ea5ba94ad0829ba9ed5650dc67` |
| `docs/MLC3-CONFIDENT-MOMENT-COACHING-INTERFACE-MANIFEST-D11.md` | `ec2d92bed3a0da354b4ecfd0051d68677e83f9f0d40382c9e3d9678c287c49ea` |

## Frozen implementation pins

| File | State | SHA-256 |
| --- | --- | --- |
| `migrations/pending/add_confident_moment_coaching_bundle_v1.sql` | modified | `d9bae09632e926cef30c84a92b046c61cde43540e04619019cdef6cd9f253e15` |
| `tests/integration/confident_moment_rehearsal.sh` | modified, test-only | `95b5c1a138e3ddbfacdf3f6ca7d64f3c0d52b0980e6201d9a99003bf8d4857d6` |
| `tests/test_confident_moment_coaching_bundle_postgres.py` | modified, test-only | `f0adca27d8240292437e7adbd3dd99c478ca216ef0bf8f55108617e95fdce5fd` |
| `tests/test_confident_moment_bundle_security.py` | modified, test-only | `4aca211c650cddbe905c9a51cac8d64f3c5a44e0e375bc373f5b6bc2d7f247a6` |
| `tests/confident_moment_production_fixtures.py` | new, test-only | `51244e7840028f10187a10c6ddac188bda86bc2b36da8725dd06ab31cf8bb810` |
| `tests/test_confident_moment_production_fixtures.py` | new, test-only | `0064a6c9de621b16fe1501f933d83df7b88de540b04c733ebc7f42fbc0d2bf02` |

## Corrections under review

1. Render acknowledgement rejects stale/superseded deliveries and invokes the
   same exact D11 coach/source/current-membership guard before and after the
   potentially blocking rendered-exposure insert.
2. The shared guard binds the exact review batch/frame/item, assignment,
   canonical blind-coach judgment, reveal grant and judgment inventory, reveal
   access with `guidance_authoring`, source role, membership item, evidence,
   snippet, recipient, candidate, candidate-output hash, coach role, and live
   authorization/deletion state.
3. Projection-item shape checks are validated and a closed, non-callable
   `BEFORE INSERT` validator binds projection, attachment, principal, Project,
   Take, snapshot, membership, candidate, coach revision, current v2 delivery,
   presentation, rendered exposure, and output hashes. The populated-reapply
   audit is NULL-safe and fails closed; it never backfills immutable history.
4. Current coach delivery render state creates an immutable unread-to-read
   projection successor. With zero valid coach deliveries, the response retains
   the `coach_update` key with JSON `null`, per D11 section 4.4.
5. Attachment-scoped state is reset on every loop iteration. A true three-family
   bundle (confidence, rewrite, praise) is exercised in both canonical extremes
   and rendered/unrendered states, including the coach-comment/praise collision.
6. The new validator function and trigger are included in the closed registry;
   runtime direct execution remains revoked. All tables remain forced-RLS,
   RPC-only, non-serving, and structurally dataset-ineligible.

## Executed evidence

- Fresh narrow disposable database: 27 prerequisite migrations; pending
  migration applied and reapplied successfully.
- `tests/test_confident_moment_coaching_bundle_postgres.py`: **35 passed**.
- Bundle security, rooting coverage, and phase-1 deletion suites: **39 passed**.
- Fresh released-schema database: 28 prerequisite migrations; pending migration
  applied and reapplied successfully.
- Production-shaped fixture suite on the released-schema database: **7 passed**.
- Focused final exact-lineage / three-family matrix: **6 passed**.
- Ruff on changed Python, `compileall`, and `git diff --check`: passed.

The disposable narrow fixture temporarily suspends only legacy-helper-incompatible
append-only triggers during fixture construction and restores them in `finally`.
Every production RPC and race runs with the production/D11 triggers enabled.
The released-schema fixture uses canonical writers and final-form named inserts.

## Required reviewer output

Return `ACCEPTED` or `REVISIONS_REQUIRED` with exact file/line evidence. Review
contract, concurrency, authority/deletion currentness, relational lineage,
permissions/RLS, replay, and ML/data boundaries. Acceptance authorizes no later
gate by itself.

```text
VERDICT:  ADVANCE-F2
CATEGORY: F2
WHY:      The packet closes exact asynchronous coach-currentness and projection
          provenance without mixing signals or enabling serving/learning.
REDIRECT: Obtain independent ML/data and Engineering implementation acceptance,
          then freeze an exact Chunk 2B commit for the Chunk 3 adapter base.
```
