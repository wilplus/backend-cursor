# MLC-3 Confident Moment Coaching Bundle — Interface Manifest D11

**Status:** proposed executable re-freeze for ML/data review. It authorizes no
implementation, migration numbering, commit, push, merge, deployment,
activation, collection, dataset creation, training, evaluation, or promotion.

## 1. Bound authorities and scope

D11 retains accepted Contract Delta D3 and Interface Manifest D6, and replaces
only the secure-read/currentness portions of D7.

- Contract Delta D3: `59c4bad81e1b0a4917d76ce27f48b9a049ca29ea5ba94ad0829ba9ed5650dc67`
- Manifest D6: `73514e30005c4b780011f5b6e1631b4c9bb3c3d1f087afea8408bf24df0f15b2`
- Secure Read A3: `f19b661ea1efebcfec4467c673c1c0162ee6249bc26e3830c0671ee716227488`
- Manifest D7: `f5df35bcba89d3c4486fb892655e26cbb2f543fe47a9ac8c04abfbcf3d331dd3`
- Chunk 2 HEAD: `b63f0f98cf55e420072324a681a48fbcfd55b9e8`
- recovered Chunk 3 patch: `83d2ab7f0d811605871c3d6b0f4d2c3099c17b1bfb7044deb1d93e0245e61088`

Exercise delivery is excluded from this projection. `exercise` is always JSON
null and is included in the response hash. It means only “not supplied by this
projection.” Exercise offer, media, playback and practice continue exclusively
through the reviewed `/v2/user/mlc3/*` routes. The UI must not interpret null as
a no-match, absence of eligibility, or learning signal.

## 2. Closed global serializer order

Idempotency-only locks may be taken before this graph only by operations the
reader never acquires. Every shared inventory/validity writer and projection
uses this numeric order:

| Order | Exact serializer |
| ---: | --- |
| 10 | `mlc3-rollout-policy-v2` |
| 20 | `mlc3-service-principal:<principal_uuid>` |
| 30 | `confident-moment-project-inventory:<project_uuid>` |
| 40 | `confident-moment-take-inventory:<take_uuid>` |
| 50 | `feedback-v3-membership-inventory:<project_uuid>:<take_uuid>` |
| 51 | `feedback-v3-membership-current:<membership_uuid>` |
| 52 | `ideal-text-document-head:<project_uuid>` |
| 53 | `ideal-text-document-snapshot:<snapshot_uuid>` |
| 60 | `mlc3-speaker-attempt:<attempt_uuid>` |
| 70 | `mlc3-processing-audio-object:<object_uuid>` |
| 90 | `confident-moment-bundle-subject:<membership_uuid>:<candidate_uuid>` |
| 100 | `root-block:<project_uuid>:<slide_index>:<block_key>` |
| 110 | `feedback-language-candidate:<candidate_uuid>:<reviewer_uuid>` |
| 120 | `feedback-language-delivery-subject:<recipient_uuid>:<target_take_uuid>:<membership_uuid>:<candidate_uuid>` |
| 130 | `feedback-language-revision-head:<membership_uuid>:<candidate_uuid>:<reviewer_uuid>` |
| 140 | exact current validity/head rows using the canonical writer's row-lock mode |

UUID sets are sorted by UUID bytes; Projects, Takes, Slides, blocks, revisions
and delivery revisions use ascending canonical numeric/UUID tie order.

Every writer derives omitted Project/Take/principal identities server-side from
immutable FK lineage before mutation. It locks every affected Project/Take set
in sorted order, rederives the set, and raises
`CONFIDENT_MOMENT_PROJECTION_RETRY_REQUIRED` before mutation if the identity hash
changed. Browser values never establish authority. Shared-object writers derive
and lock the complete affected set.

## 3. Exhaustive affected-writer registry

The following is the complete allowed registry for v1. Unknown functions,
overloads, triggers or worker callers touching a projection or validity family
block apply/reapply and implementation acceptance.

| Exact identity | Family / authoritative derivation | Required action |
| --- | --- | --- |
| `freeze_synthetic_feedback_v3_membership_v1(uuid,uuid,uuid,uuid,uuid,text,jsonb,text,text)` | membership/items; principal, Project, Take, candidate set and snapshot are arguments | rewrite through 10→20→30→40→50; retain exact inventory replay hash; runtime inaccessible |
| `freeze_feedback_v3_service_membership_v1(uuid,uuid,uuid,uuid,uuid,text,jsonb,text)` | membership/items; same authoritative arguments | rewrite through 10→20→30→40→50; retain exact service replay hash |
| `publish_ideal_text_document_snapshot_v1(text,text,uuid,uuid,uuid,integer,bigint,text,jsonb,jsonb)` | snapshot/head; principal, Project and source Take are arguments | rewrite 10→20→30→40→52→53; retain generation/fingerprint replay |
| `prepare_confident_moment_bundle_v1(uuid,uuid,uuid,uuid,uuid,text)` | bundle attachment; subject derived from exact membership item | rewrite 10→20→30→40→50→51→52→53→90; exact attachment replay |
| `freeze_root_phrase_coverage_frame_v1(uuid,uuid,uuid,uuid,uuid,text,text)` | coverage frame/items; identities are arguments | rewrite 10→20→30→40→50→51→52→53→100; recompute ordered inventory and achieved count on replay |
| `record_root_phrase_product_action_v2(uuid,uuid,uuid,uuid,integer,text,uuid,uuid,uuid,uuid,uuid,uuid,bigint,uuid,uuid,uuid,text,text)` | action/head; Slide from content, practice lineage from supplied exact source | rewrite 10→20→30→40→50–70 when applicable→100; rerun source/speaker guard and exact head replay |
| `activate_synthetic_root_phrase_v1(uuid,uuid,boolean,boolean,text)` | legacy action/head; derive principal/Project/Take/membership from qualification→content | internal derivation then same order; runtime contract unchanged |
| `remove_synthetic_root_phrase_v1(uuid,integer,integer,uuid,uuid,text)` | legacy action/head; derive through expected head→action→content→membership | internal derivation then same order; runtime contract unchanged |
| `transition_ideal_text_root_state_v1(uuid,uuid,uuid,uuid,bigint,text,text)` | internal Ideal Text root transition | callable only inside already-held global order; runtime inaccessible |
| `record_feedback_language_coach_revision_v1(uuid,uuid,uuid,uuid,uuid,uuid,uuid,uuid,text,text,text,text,uuid,text)` | revision chain; principal/Project/Take/member derived from reveal/assignment | replace by v2 below; v1 runtime inaccessible |
| `schedule_feedback_language_revision_v1(uuid,uuid,uuid,uuid,text)` | delivery chain | replace by v2 below; v1 runtime inaccessible |
| `ack_feedback_language_revision_render_v1(uuid,uuid,uuid,uuid,text)` | exposure only | use current delivery/revision head locks and final live checks; does not mutate wording authority |
| `ack_confident_moment_bundle_item_render_v1(uuid,uuid,uuid,uuid,text)` | prepared presentation/render receipt | derive Project/Take from attachment/member; 10→20→30→40→50–53→90 then canonical exposure lock |
| `ack_feedback_v3_service_render_v1(uuid,uuid,uuid,uuid,uuid,uuid,text,timestamptz,text,text)` | canonical presentation/render receipt | same derived inventory locks; existing replay retained |
| `register_mlc3_general_rollout_v2(uuid,uuid,jsonb,jsonb,uuid,timestamptz,text)` | rollout authority | retain order 10 and immutable revision replay |
| `halt_mlc3_service_rollout_v1(text,text)` | rollout authority | retain order 10 and immutable revision replay |
| `ensure_mlc3_service_enrollment_v2(uuid,uuid,text)` | enrollment authority | retain 10→20 and exact enrollment replay |
| `activate_phase1_policy_v1(text,text,text)` | policy authority for affected receipts | derive affected principals; 10 then all principals at 20; exact policy replay |
| `accept_phase1_processing_authorization_v1(uuid,text,text,text,text,text,text,boolean,text,text,text,timestamptz,text)` | receipt/purpose authority | derive exact principal; 10→20; exact receipt/policy replay |
| `mark_phase1_storage_object_purged_v1(uuid,text,uuid,text,text,text,text)` | purge/audio validity; identity from object/request lineage | shared trigger/helper derives 10→20→30→40→60→70 before mutation |
| `finalize_phase1_purge_v3(uuid,text)` | purge traversal; complete affected identity set from request | sorted 10→20→30→40→60→70 sets; exact completion replay |

The exhaustive non-test runtime caller registry on the frozen Chunk 2 base is:

```text
services/first_client_repository.py::FirstClientRepository.ensure_service_enrollment
  → ensure_mlc3_service_enrollment_v2
services/first_client_repository.py::FirstClientRepository.freeze_feedback_v3_service_membership
  → freeze_feedback_v3_service_membership_v1
services/first_client_repository.py::FirstClientRepository.ack_feedback_v3_service_render
  → ack_feedback_v3_service_render_v1
services/db.py::DatabaseService.publish_ideal_text_document_snapshot
  → publish_ideal_text_document_snapshot_v1
services/processing_authorization.py::ProcessingAuthorizationService.accept
  → accept_phase1_processing_authorization_v1
services/data_purge.py::DataPurgeOrchestrator._resolve_object
  → mark_phase1_storage_object_purged_v1
services/data_purge.py::DataPurgeOrchestrator.finalize
  → finalize_phase1_purge_v3
```

The closed operations/administration caller registry is separate:

```text
scripts/monitor_mlc3_general_service.py::_halt
  → halt_mlc3_service_rollout_v1
```

`scripts/check_mlc3_founder_canary_readiness.py` and
`scripts/check_mlc3_general_service_readiness.py` contain exact signature
registry constants only; they do not invoke the mutation RPCs and are classified
as inspection consumers. `register_mlc3_general_rollout_v2` and
`activate_phase1_policy_v1` have no non-test repository caller on the frozen
base; they are administration-only database entry points and remain classified
in the SQL permission/operations registry. Every other registered synthetic,
legacy or internal writer has no non-test Python caller and remains runtime
inaccessible unless its frozen public wrapper invokes it inside PostgreSQL.

The exhaustive new Chunk 3 database-caller registry uses one focused class and
the following exact method-to-RPC tuples:

```text
services/confident_moment_bundle_repository.py::ConfidentMomentBundleRepository.project_take_bundles
  → project_confident_moment_bundles_v1
services/confident_moment_bundle_repository.py::ConfidentMomentBundleRepository.prepare_bundle
  → prepare_confident_moment_bundle_v1
services/confident_moment_bundle_repository.py::ConfidentMomentBundleRepository.ack_item_render
  → ack_confident_moment_bundle_item_render_v1
services/confident_moment_bundle_repository.py::ConfidentMomentBundleRepository.ack_revision_render
  → ack_feedback_language_revision_render_v1
services/confident_moment_bundle_repository.py::ConfidentMomentBundleRepository.freeze_coverage_frame
  → freeze_root_phrase_coverage_frame_v1
services/confident_moment_bundle_repository.py::ConfidentMomentBundleRepository.record_coach_revision
  → record_feedback_language_coach_revision_v2
services/confident_moment_bundle_repository.py::ConfidentMomentBundleRepository.transition_revision_delivery
  → transition_feedback_language_delivery_v2
services/confident_moment_bundle_repository.py::ConfidentMomentBundleRepository.record_root_action_v2
  → record_root_phrase_product_action_v2
```

`transition_revision_delivery` is the sole additive Chunk 3 method introduced
by D10. No route or service may call `transition_feedback_language_delivery_v2`
directly. The existing method names above remain fixed; moving an RPC to another
method is an interface change and fails the registry test.

No Chunk 3 route, service or repository may call `.table(...)` for a canonical
Bundle/projection table. Routes call only the focused repository. Synthetic
writers remain runtime inaccessible.

### Trigger registry

The exact allowed mutation/serialization triggers are:

```text
coach_ideal_text_advances_document_generation
user_ideal_edit_advances_document_generation
ideal_text_part_advances_document_generation
ready_take_advances_ideal_text_document_generation
  → advance_ideal_text_document_generation_v1()
data_purge_requests_mlc3_service_serialization
  → serialize_mlc3_service_purge_v1()
processing_audio_deletion_mlc3_serialization
processing_audio_object_mlc3_serialization
  → serialize_mlc3_processing_audio_leaf_v1()
feedback_v3_membership_complete
  → validate_feedback_v3_membership_v1()
```

The four document-generation triggers derive principal/Project/Take and acquire
10→20→30→40→50 before changing currentness. Purge/audio serialization helpers
derive the full immutable lineage and acquire their complete ordered sets.
`feedback_v3_membership_complete` is validation-only and runs after writer
serialization. Append-only/immutability/runtime-event guards are denial-only
and are separately checksum-pinned; they do not establish currentness.

Owner response writers are outside the projection identity because responses
are never projected. They remain required by the separately guarded root-action
path. Exercise/practice/coach-media writers are outside this projection because
`exercise` is always null and no media is joined.

## 4. Immutable Feedback Language currentness

### 4.1 Revision chain

Retain `feedback_revisions` and add a composite unique identity covering:

```text
id, taxonomy_version, feedback_membership_id, feedback_candidate_id,
rater_id, acquisition_principal_id, candidate_output_version,
candidate_output_sha256
```

The composite predecessor FK includes `supersedes_id` plus the same identity.
There is one original per membership/candidate/reviewer and one successor per
predecessor. A current revision head is defined only by absence of a successor
with `taxonomy_version='feedback-language-coach-revision-v1'`; timestamps and
UUID ordering never choose a head.

### 4.2 Delivery chain

Extend `feedback_language_revision_deliveries` with exact membership, candidate,
reviewer, candidate-output hash, `delivery_subject_sha256`,
`supersedes_delivery_id`, and `delivery_policy_version`. Add composite FKs to
the exact revision identity and predecessor delivery subject. There is one
original per recipient/target Take/membership/candidate and one successor per
predecessor. Each successor increments `delivery_revision` exactly once under
serializer 120.

Invalidation is an immutable successor delivery with state `invalidated`; no
existing delivery row is updated. The current delivery head is defined only by
absence of a successor. A usable head must be scheduled, point to the current
revision head, preserve candidate/output/recipient/target-Take lineage, and pass
current reviewer and recipient authority/deletion checks. An invalidated head
suppresses the item and never resurrects machine fallback.

### 4.3 Exact coach authority

Every coach revision must join the exact revision to review batch/frame/item,
`ml_review_assignment`, canonical `blind_coach` judgment, reveal grant and
judgment inventory, reveal access, source role, membership item, evidence and
snippet. Reviewer role is coach; batch/reviewer/assignment/judgment/grant/access,
recipient principal, evidence, candidate and candidate-output hash must match;
the reveal purpose must authorize guidance authoring. A foreign or stale chain
fails the entire projection.

### 4.4 Resolution rules

- Zero valid coach deliveries uses only the frozen Manager machine artifact and
  sets `coach_update=null`.
- Exactly one valid current delivered head uses that revision. Render state
  controls buzz/read state only, never wording authority.
- Multiple heads, a broken/forked chain, foreign authority, corrupt delivery,
  or stale candidate hash is fatal typed projection invalidity.
- Explicit invalidation yields the per-item exclusion
  `delivery_explicitly_invalidated`, not fallback.
- Machine fallback copies only the exact frozen candidate output and recognized
  `why_key`, quote and proposed-text fields. It never generates new prose.
- Missing/malformed/unrecognized machine output is a typed item exclusion.

Canonical item order is attachment canonical position then candidate UUID bytes.

## 5. Canonical persistence and RPCs

Add forced-RLS, append-only, RPC-only tables:

```text
confident_moment_bundle_projections
confident_moment_bundle_projection_items
```

A frozen projection stores principal, Project, Take, membership, document
snapshot/hash, policy/code version, stabilized ordered inventory hash, response
hash and idempotency identity. It has exactly one item per attachment, including
typed excluded items; omission and duplication fail closed. Every item stores
its subject/anchor identities, resolution state (`coach_revision`,
`machine_fallback`, `excluded`), exact revision/delivery/output hashes when
applicable, canonical position, `exercise_present=false`, and
`dataset_eligible=false`.

Exact RPCs:

```text
record_feedback_language_coach_revision_v2(
  uuid,uuid,uuid,uuid,uuid,uuid,uuid,uuid,
  text,text,text,text,uuid,text
) -> jsonb

transition_feedback_language_delivery_v2(
  uuid,uuid,uuid,uuid,uuid,text,text
) -> jsonb

project_confident_moment_bundles_v1(
  p_acquisition_principal_id uuid,
  p_project_id uuid,
  p_take_id uuid
) -> jsonb
```

The v2 revision RPC's final UUID is the expected current revision head. The
delivery RPC receives expected current delivery head and action `schedule` or
`invalidate`. Natural-identity serializers precede idempotency locks; both
revalidate after contention. The projection RPC implements A3, freezes or exact-
replays the projection rows, and returns the D6 Bundle response plus first-paint
summary from the same stabilized snapshot.

`CONFIDENT_MOMENT_PROJECTION_RETRY_REQUIRED` maps to HTTP 409. Fatal chain,
authority, deletion and inventory errors return no payload. A valid empty
attachment inventory returns explicit empty objects with a response hash.

## 6. Verification registry

Tests must inspect `pg_proc`, `pg_trigger`, `pg_depend`, function bodies, table
ACLs and repository callers against the exact closed registries above. A Python
AST/static extractor scans every production `.py` file outside tests and build/
dependency directories, resolves literal `.rpc(name, ...)` calls and direct SQL
references to every affected RPC, and compares the exact `(file, enclosing
symbol, rpc)` set with the runtime and operations registries. It separately
checks signature-only readiness constants. Missing, extra, renamed, overloaded
or dynamically constructed affected callers fail; dynamic affected RPC names
are prohibited. Missing or runtime-callable writers, unknown enabled triggers,
direct runtime table reads/writes, changed serializer text/order, or an
unclassified mutation also causes failure.

Required executable tests include:

- clean apply/reapply and atomic negative rollback;
- production caller extraction matches the exact runtime and operations sets;
  adding, removing, renaming, overloading or dynamically constructing one
  affected call fails the registry check; a fabricated class qualification for
  a module-level function also fails;
- every writer exact replay and changed-identity conflict;
- identity-set changes between coarse discovery and fine locks;
- both race orders for authority, membership, document, source deletion/purge,
  root replacement, revision supersession and delivery transition;
- deadlock-free concurrent operations following the numeric graph;
- revision/delivery fork races produce exactly one winner;
- stale expected heads and delivery of a superseded revision reject;
- explicit invalidation never falls back;
- complete blind authority foreign/stale cases and `blind_peer` reject;
- valid frozen Manager fallback only; malformed fallback excludes;
- exactly one item per attachment and stable exact replay;
- `exercise=null` even when a separate exercise offer exists, with no exercise
  event created by projection;
- response denylist, RLS/forced-RLS, append-only, RPC-only, deletion traversal,
  `serves_user=false`, and `dataset_eligible=false`; and
- enabled Chunk 3 bundle/summary reads call only the projection RPC and never a
  table client or broad exception fallback.

## 7. Decision filter

```text
VERDICT:  ADVANCE-F2
CATEGORY: F2
WHY:      D11 freezes revocation-safe currentness for the existing asynchronous
          coaching projection without changing Manager, confidence or learning
          semantics.
REDIRECT: Obtain ML/data acceptance, then implement locally behind disabled
          gates and review the combined Chunk 2/3 snapshot.
```

`FILTER: ADVANCE-F2 — cat F2 — fences clear — locks clear — redirect: implement
the closed registry and immutable head chains before frontend work.`
