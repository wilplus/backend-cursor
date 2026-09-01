# Ideal Text cold-open implementation

Status: locally implemented and verified; not yet migrated or deployed.

## Contract

The user-visible Ideal Text opens from one immutable, actor-scoped document
snapshot. The core response contains only the document needed for first paint:
project/Take identity, title, Slide references and titles, Paragraph text and
stable IDs, locks, orange roots, version/status, and next-Take availability.

Optional feedback, explanations, playback, notes, history, journey state,
entitlement and learning-exposure preparation load independently afterward.
They are bound to the exact `document_snapshot_id`. A stale enrichment request
returns `SNAPSHOT_STALE`; sections from different document revisions are never
merged.

## Freshness and retry boundary

`ideal_text_document_generations` is the durable publication boundary.
Triggers advance one monotonic generation in the same database transaction as
changes to the coach document, user Ideal Text edit, Paragraph state, or a
spoken Take becoming `ready`. The old snapshot becomes unreadable immediately
at that commit.

A publisher:

1. Captures the current generation.
2. Builds the complete read model outside the GET path.
3. Publishes through one RPC that locks and revalidates the generation.
4. Atomically appends the immutable snapshot and swaps its head.

If a source changes during materialisation, the RPC rejects the stale build and
the publisher retries. A generation with no matching snapshot is durable retry
work. Immediate delivery uses the existing Redis/RQ queue; the existing
pipeline sweeper re-enqueues missed work from PostgreSQL. Redis is not the
source of truth.

The core GET performs one read-only, owner-checked RPC. It never composes,
repairs, persists, signs media, invokes a provider, prepares feedback, or
records an exposure.

## Endpoints

- `GET /v2/explore/arc/:arc_id/ideal-text/core`
- `GET /v2/explore/arc/:arc_id/ideal-text/enrichment?document_snapshot_id=…`

Enrichment sections are independently typed as `ready`, `pending`,
`unavailable`, or `failed`. Only unfinished retryable sections are retried.
An enrichment failure never hides a valid core document.

The endpoint revalidates the generation-fenced core after all optional readers
settle. A source mutation during enrichment returns `SNAPSHOT_STALE`; no stale
presentation acknowledgement token is delivered to the browser.

## Performance contract

- Warm backend core read: p95 at or below 300 ms.
- User-visible core paint: p95 at or below 1 second.
- Core and enrichment latency are measured separately through `Server-Timing`
  and browser Performance entries.
- A performance regression in enrichment cannot block first paint.

These are production SLOs, not claims derived from the synthetic database.
Production monitoring must establish the real p50/p95/p99 after deployment.

## Security and lifecycle

- Snapshot and generation tables use RLS.
- Writes are RPC-only for `service_role`; snapshots are append-only.
- Owner, project, acquisition principal and successful Take lineage are
  database-validated.
- Snapshot, head and generation rows are included in the existing
  principal-scoped deletion registry.
- Optional learning exposure is created only in enrichment and confirmed only
  after the corresponding UI renders. Core delivery is not an exposure.

This read-path split changes no feedback labels, candidate selection, dataset
eligibility, training data, or model behavior. It requires Engineering review,
not a new ML/data design decision.

## Deployment sequence

1. Review and assign the pending migration its next immutable manifest version.
2. Apply the backend migration and deploy the backend endpoints/publisher.
3. Run the backfill script in preview mode and review its counts.
4. Run the same script with `--apply`; investigate every failed or
   missing-lineage row.
5. Verify zero unexpected pending generations and sample owner isolation.
6. Deploy the frontend core-first reader.
7. Verify backend and paint SLOs, stale-request behavior, retry recovery and
   deletion inventory in production.

No environment variable or feature flag is required. Backend-first deployment
keeps the existing full endpoint available during the migration window.

## Rollback

Rollback the frontend to the existing full-document endpoint. The backend
migration is additive and should remain in place; do not delete immutable
snapshots as a rollback mechanism. Writers may continue publishing snapshots
while the older client is active. Repair forward before reenabling core-first
reads.

## Verification evidence

- Disposable PostgreSQL migration apply/reapply and rejection rehearsal.
- Stale source generation rejected; old head unreadable after mutation.
- Durable pending publication discovered and cleared by a current snapshot.
- Direct service-role snapshot writes rejected; cross-owner reads rejected.
- Backend CI mirror: 4,861 passed, 162 skipped; migration, Ruff and Mypy gates
  green.
- Frontend: 1,490 passed; production build, TypeScript, lint and BFF
  architecture checks green.

