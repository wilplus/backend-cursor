# MLC-3 Coach Guidance and Exercise Delivery D3 — Release Preparation Packet

**Scope:** local, synthetic, hard-disabled implementation only  
**Backend base:** `a782ea0c3f8357f213ac3a127fe5d445830470a0`  
**Frontend base:** `530ac9868c5b61d1d6287e245a8cee3b0fddca88`  
**Accepted design SHA-256:**
`b3d65c5a06d67e99bdf20f0024f46fb70c445ceef6b817bafdcc764b990295d1`

Migration `0322` is assigned for release verification only. No push,
production migration, deployment, activation, real collection, dataset
creation, training, evaluation, or promotion is included.

## Implemented contract

- The database derives and freezes each review batch from the complete
  canonical confidence-review assignment inventory at one cutoff.
- Batch membership records terminal assignments as typed exclusions. A
  post-cutoff cancellation or expiry requires a new immutable batch revision;
  replay of the earlier batch fails current liveness checks. A successor whose
  complete inventory is terminal remains valid with zero required assignments
  and retains every typed exclusion; a genuinely empty inventory is rejected.
- A reviewer-specific reveal grant requires an immutable five-state judgment
  with `blind_coach` provenance for every required assignment in that frozen
  coach batch. `blind_peer` never completes or contributes to a coach batch.
- Ordinary batches, reveal and general guidance use the independently accepted
  `coach_review` purpose. Only MLC-3 exercise operations require
  `personalized_exercise_recommendation`; withdrawing that optional purpose
  cannot disable otherwise authorized coach guidance.
- Every post-blind access binds the exact batch, assignment, judgment, reviewer,
  purpose, and current source authority.
- Written notes and general coaching video remain product guidance. `structure`
  and `delivery` are optional product subcategories; neither is registered as a
  feedback family or learning surface.
- MLC-3 exercise attachment requires Confident Voice feedback, the exact fresh
  offer, the frozen complete candidate set, an approved need contract, and the
  deterministic selected exercise or typed no-match state.
- Coach video upload uses an exact permit and durable recovery row created
  before a provider write. `reserved`, `write_started`, `write_acknowledged`,
  `finalized`, and `abandoned` remain distinct and terminal states cannot
  conflict.
- Media registration verifies the private object identity, exact bytes hash,
  size, content type, finalized upload receipt, rights/safety/language/content
  review versions, and current authorization.
- Media validity is an immutable event chain with `active`, `quarantined`,
  `invalid`, and terminal `deleted` states. Upload replay, media binding,
  attachment creation, assignment/delivery/render/playback and publication all
  acquire the same transaction-scoped object lock as the validity writer and
  then fail closed unless the fresh exact-media leaf state is active.
- `independent_clean_media` requires its own immutable review artifact bound to
  the exact object, upload permit, reviewer, byte identity and five explicit
  protected-content absence checks. A caller cannot assert this provenance
  class with version strings alone.
- Attachment lifecycle events are immutable and ordered:
  `authored -> assigned -> delivered -> rendered -> played`. Delivery is not
  exposure; only authenticated render confirmation creates a rendered event.
- Publication creates a separate reviewed exercise version and catalogue
  snapshot reference. Clean media and user-source-dependent publication remain
  distinct; dependent publication supports logical invalidation without
  claiming immediate physical deletion.
- Every subject-linked row is registered in the existing deletion dependency
  inventory. Shared-media source dependencies are recorded separately.
- Tables use RLS, service-role read-only table grants, append-only triggers, and
  validating RPC-only writes.
- SQL and HTTP/UI gates are literal disabled constants with no environment
  override. Product records structurally require `serves_user=false` and
  `dataset_eligible=false`.

## Exact checksum pins

### Backend

| SHA-256 | File |
|---|---|
| `b3d65c5a06d67e99bdf20f0024f46fb70c445ceef6b817bafdcc764b990295d1` | `docs/MLC3-COACH-GUIDANCE-DELIVERY-D3.md` |
| `96e7aa34d9b29822aae0be636a6ed21adc3209baf7241541c7276be87047c275` | `migrations/add_coach_guidance_delivery_d3.sql` |
| `425a3f682229b175c5de9aaf248228958146fee25cda289aeff32a3d965e1115` | `migrations/manifest.txt` |
| `7d6424db278196b28e1c129b1f59f215887fc351cf1139f356d7bab5a5ee47d4` | `routes/v2/coach_guidance_delivery.py` |
| `031aa730bdbbb157f17275a8a2e303dd5a4e4bc2676b866ce6c8c67147b29389` | `routes/v2_routes.py` |
| `8c83e7de548a1dd07395aef5565671c5cfaf167d8f4ec7dac245902f29332fc9` | `services/coach_blind_gate.py` |
| `7b4f67a6a8b21b5bc318ec0c8e19775c1852ebc66fb428ffaa969c31c8db7948` | `services/coach_guidance_delivery.py` |
| `ecab43c281c92af85285efe2d02c77e8fef2b4086b136bb0e2fcf250a3e6f778` | `services/data_purge_registry.py` |
| `a635db1fc1fff58e0ab06c472c40baa4b4322e1dbbe35370913c4e0a2cccb66f` | `tests/test_coach_blind_gate.py` |
| `54cfc28f025911445d61c3aa2bdbdf3d7ae9ad0efffb880134c56cd3df39b18f` | `tests/test_coach_guidance_delivery_d3.py` |
| `3044f4e7b81ee0d6900dcf4a6ce7f5cda42d1eb85781883eadb10281ed0fda38` | `tests/test_coach_guidance_delivery_d3_postgres.py` |

### Frontend

| SHA-256 | File |
|---|---|
| `050a0f6be30c68e056009b9e45443a8581e5e0487a7a0fd3a006131368751f70` | `src/components/willab/CoachStarVerdictOverlay.tsx` |
| `c312c0279064c62c829a254e58c8371281971cae612b8dcdab80ca9ed3bb5423` | `src/components/willab/CoachGuidanceComposer.tsx` |
| `685090bd2e34b3e428eb8e33ed17c7395c14660336c1eae46b9f4fcfbdc076ef` | `src/services/api/coachGuidanceDelivery.ts` |
| `d964b5676be84c6b019aae835c30f3a6831b2613be7e50ee41d2b888da46b768` | `src/services/api/coachGuidanceDelivery.test.ts` |
| `1fbeeaed5fbc04a3c496d445cff47a5898f95f21243522517c69c5ac9ea00158` | `src/app/api/v2/coach/guidance/batches/[arcId]/route.ts` |
| `ec0c403c412529195731008531b96f2ce393c1aab2708aeb3ce15590e6040180` | `src/app/api/v2/coach/guidance/attachments/route.ts` |
| `ea7d93f40a95f49f1aa42857fbbac0037c810bb41093aada401cdc1751e5e676` | `src/app/api/v2/coach/guidance/events/route.ts` |
| `0b72a503400af8e451f7402ae3a76f35f59930cc2f3b9bea092d0827b4118f6a` | `src/app/api/v2/coach/guidance/publications/route.ts` |

## Verification evidence

- Disposable PostgreSQL dependency chain: clean D3 apply and reapply passed.
- Adversarial D3 PostgreSQL suite: 14 passed, covering independent purpose
  withdrawal, cancellation/expiry revisioning, a zero-required terminal-only
  successor, coach-versus-peer provenance, reviewer-access loss during a
  forced two-connection lock wait, immutable clean-media review, and media
  invalidation during forced binding, finalized-replay, independent-review,
  attachment, render, playback and publication lock waits.
- MLC-3 assignment/N1 compatibility suites: 91 passed.
- Database security inspection: all 17 D3 tables have RLS enabled; service role
  has SELECT and no INSERT/UPDATE/DELETE; public has no D3 RPC execution.
- Backend focused static/route tests: 20 passed.
- Exact local CI mirror: 4,910 passed, 234 skipped, 113 subtests passed.
- Ruff and mypy: passed.
- Migration manifest verification: 322 migrations, versions `0001` through
  `0322`, passed with D3 assigned as the terminal migration.
- Release scanners: explicit RLS declarations recognized for all 17 new tables;
  no new destructive migration classification.
- Frontend TypeScript: passed.
- Frontend focused Vitest: 61 passed.
- Frontend targeted ESLint: passed.
- BFF single-idiom guard: passed.
- Backend and frontend `git diff --check`: passed.

## Known limits

- Live R2 calls and provider deletion coordination are not implemented or
  verified in this slice. The exact permit/recovery/database contract is ready
  for a later adapter review.
- The HTTP routes and UI are hard-disabled. They cannot deliver or collect real
  guidance.
- No real exercise catalogue, acoustic threshold, exposure, outcome label, or
  learning operation is activated.
- Publication RPCs record reviewed publication provenance only; no automatic
  catalogue-growth job exists.

## Decision filter

```text
VERDICT:  ADVANCE-F2
CATEGORY: F2
WHY:      Adds a provenance-safe, post-blind product-delivery foundation without activating collection or learning.
REDIRECT: Complete release verification, then request separate push and production-deployment authorization; keep every serving and data gate disabled.
```
