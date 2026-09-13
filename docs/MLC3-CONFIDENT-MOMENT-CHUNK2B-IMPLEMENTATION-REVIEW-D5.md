# MLC-3 Confident Moment Coaching Bundle — Chunk 2B implementation review D5

## Review boundary

- Repository: `wilplus/backend-cursor`
- Branch: `codex/confident-moment-chunk2b-transfer`
- Parent checkpoint: `fb024fc0e6b82f1e662fc545cb70ce9afa3a52eb`
- Migration remains pending, unnumbered, and absent from the numbered manifest.
- This packet authorizes no push, merge, deployment, activation, collection,
  dataset creation, training, evaluation, promotion, or serving.

## Frozen contract inputs

| File | SHA-256 |
| --- | --- |
| `docs/MLC3-CONFIDENT-MOMENT-COACHING-CONTRACT-DELTA-D3.md` | `59c4bad81e1b0a4917d76ce27f48b9a049ca29ea5ba94ad0829ba9ed5650dc67` |
| `docs/MLC3-CONFIDENT-MOMENT-COACHING-INTERFACE-MANIFEST-D6.md` | `73514e30005c4b780011f5b6e1631b4c9bb3c3d1f087afea8408bf24df0f15b2` |
| `docs/MLC3-CONFIDENT-MOMENT-COACHING-INTERFACE-MANIFEST-D11.md` | `ec2d92bed3a0da354b4ecfd0051d68677e83f9f0d40382c9e3d9678c287c49ea` |
| `docs/MLC3-CONFIDENT-MOMENT-COACHING-CURRENTNESS-AMENDMENT-D12.md` | `0f6a9e9f7068c4881f0bb728033d62ee6ac80c9766dd5eecd14cd6630e7a86ea` |

## Frozen implementation pins

| File | SHA-256 |
| --- | --- |
| `docs/MLC3-CONFIDENT-MOMENT-CHUNK2B-IMPLEMENTATION-REVIEW-D4.md` | `92d2729add0e2faf33718b4880391f8ae375aa147e6e9fa29acaa7aebee41eae` |
| `migrations/pending/add_confident_moment_coaching_bundle_v1.sql` | `cd97302e35fd76372f44bae129fd7811bea5fc89556c997bc2d6be349e12b9e4` |
| `tests/integration/confident_moment_rehearsal.sh` | `f3f2be4e552142029449b13ea44ddd1e936655dd66ab4ef9cee3c6aca36171d4` |
| `tests/test_confident_moment_coaching_bundle_postgres.py` | `d64a4e9082b32e9dd8ca48f631ba2f89bd96dbb2e3f7f837cf70e50af9975f08` |
| `tests/test_confident_moment_bundle_security.py` | `97addcc09a0b03a8581f5b264d31f4bc50638377eb33c7605ad020029fbd2f37` |
| `tests/confident_moment_production_fixtures.py` | `6cb50926d3f75b20d52677278a0c9209b8b07cc915cda01fcb30773407d14569` |
| `tests/test_confident_moment_production_fixtures.py` | `180da7c0b7e810fbaeafac0961464c301d665bab21f1ed204965d3a640f86d98` |

## Corrections under review

1. The v2 response contains one authoritative `feedback_language_items[]`
   entry per exact attachment. It omits the lossy singular Comment, Rephrase,
   and coach-update fields and reports only an aggregate unread summary.
2. Two coach-resolved attachments retain separate revision, delivery,
   presentation, exposure, and unread identities. Rendering either item cannot
   clear or inherit the other item's state.
3. A selected `rewrite_clarity` observation without replacement text is an
   `actionable_observation` Comment; a praise Comment may coexist in the same
   Bundle without losing either Manager-selected item.
4. `ack_feedback_language_revision_render_v2` binds the exact attachment,
   revision, delivery, presentation, render instance, recipient and current
   source/coach authority. Exact replay occurs only after exact presentation
   validation. V1 is not a runtime path.
5. ACK unconditionally acquires the two Take-level speaker serializers, freezes
   the audio/deletion/purge identity set, acquires derived audio locks in global
   order, rederives, and returns only the typed projection-retry condition on
   drift. Projection hashing includes the audio validity leaves.
6. Current delivery/revision/presentation/exposure cardinality fails closed;
   multiple exposure heads are never resolved by timestamp or UUID order.
7. The writer signature/proname/overload and application caller registries are
   updated for v2 and fail on obsolete or extra writers.
8. The released rehearsal uses the actual recording-attempt/Take boundary and
   exact final-form v2-session → recording-attempt → Take identity. GNU/BSD
   temporary-file creation is portable.
9. Exclusion vocabulary is closed; negative probes assert exact constraints and
   errors; concurrency tests use lock observation rather than sleeps.
10. Render acknowledgement and persisted coach currentness require exactly one
    canonical non-shadow presentation; a null or duplicate presentation fails
    before exposure.
11. Every delivery is bound to the exact attachment anchor, falling back only
    to the exact no-anchor Bundle subject. Invalidated deliveries still
    revalidate current reviewer/source authority before exclusion.
12. The delivery writer derives that same attachment binding for both subject
    kinds, so a no-anchor correction can be scheduled, projected and rendered
    without inventing a confidence anchor.

## Executed evidence

- Fresh narrow database: pending migration applied and exactly reapplied.
- PostgreSQL regression suite: **48/48 passed**.
- Fresh released-schema database: pending migration applied and exactly
  reapplied.
- Released production fixture suite: **9/9 passed**.
- Security, rooting and deletion suites: **39/39 passed**.
- Ruff, Python compilation and `git diff --check`: passed.

## Required reviewer output

Return `ACCEPTED` or `REVISIONS_REQUIRED` with exact evidence. Review
snapshot integrity, contract/version shape, concurrency, replay, current
authority/deletion/media lineage, RLS/RPC-only permissions, AC-9, L1/L2/L3,
Manager budget, and structural non-learning boundaries.

```text
VERDICT:  ADVANCE-F2
CATEGORY: F2
WHY:      Per-attachment currentness and production-shaped verification now
          preserve exact blind-coach provenance without enabling serving or
          learning.
REDIRECT: Obtain independent ML/data and Engineering acceptance, then freeze
          the exact Chunk 2B base consumed by Chunk 3.
```
