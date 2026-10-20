# MLC-3 Confident Moment Coaching Bundle — Interface Manifest D6

**Status:** frozen for local disabled-gate implementation against the accepted
Contract Delta D3; not migration-assignment, release, deployment, activation,
collection, dataset, training, evaluation, or promotion authority.

This manifest binds
`MLC3-CONFIDENT-MOMENT-COACHING-CONTRACT-DELTA-D3.md` at accepted SHA-256
`59c4bad81e1b0a4917d76ce27f48b9a049ca29ea5ba94ad0829ba9ed5650dc67`.
Chunks 2–5 must stop if that file, either base commit, or this manifest differs.
This revision adds the exact canonical Ideal Text transition seam discovered by
Chunk 2, clarifies prepared-presentation versus rendered-exposure identity,
names the exact typed bundle subject without implying a confidence anchor, and
corrects the Ideal Text revision identity to its released `bigint` type, and
freezes the per-action root-source matrix plus exact re-record speaker lineage.

## 1. Exact bases and workspace state

### Implementation bases

| Repository | Base commit |
| --- | --- |
| backend-cursor | `4acaa2c997c1c0a4ff93c4fa0fbb4adc7868db92` |
| frontend-cursor | `0f88bd4a3f96d0f39c6679a232a1a32837f0dde6` |

### Inspected worktrees

| Path | Branch / HEAD | Dirty state |
| --- | --- | --- |
| `/Users/arturwillonski/Documents/hunter-frontend` | not a Git repository | invocation directory only; not an implementation checkout |
| `/private/tmp/willab-coach-exercise-backend` | `codex/d4-production-resolver-chain-correction` / `338493681b47ddd25cabf7507ef26c02b2ddb767` | two untracked accepted PAM design files; do not delete or overwrite |
| `/private/tmp/willab-coach-exercise-frontend` | `codex/mlc3-general-availability` / `a369226cd9ee3f57abf726f8bc3d897e462b0589` | clean |
| `/Users/arturwillonski/Documents/hunter-backend` | `codex/deferred-confidence-canary-runbook` / `e23ae79503a1a63fa3abd66cc83ef35269796787` | untracked contract/prompt documents created for this task |
| `/Users/arturwillonski/Documents/frontend-cursor` | `docs/fix-subscriptions-handoff` / `402265b7d03d033f253f0a2e080a49ba95d55415` | pre-existing unrelated modified/untracked files; never use for implementation |

Create new isolated worktrees from the exact implementation bases. Do not use
or clean the dirty worktrees above. A later `origin/main` requires Manifest D7.

## 2. Version identifiers

Proposed closed identifiers:

| Contract | Version |
| --- | --- |
| Bundle projection | `confident-moment-coaching-bundle-v1` |
| Bundle attachment | `confident-moment-attachment-v1` |
| Feedback Language output | `feedback-language-output-v1` |
| Coach Feedback Language revision | `feedback-language-coach-revision-v1` |
| Root coverage | `rooting-coverage-30-80-100-v1` |
| Exact clause extraction | `root-exact-clause-v1` |
| Root lexicographic routing | `root-lexicographic-routing-v1` |
| No-anchor presentation trigger | `confident-moment-no-anchor-trigger-v1` |
| Bundle user state | `confident-moment-user-state-v1` |
| Bundle first-paint summary | `confident-moment-core-summary-v1` |

Every persisted version also binds the relevant source checksum, deployment
commit, upstream policy versions, and canonical input hash. Version strings
without matching checksums are unrecognized.

## 3. Canonical entities: reuse, extend, and project

### 3.1 Reuse without duplication

Use the existing canonical identities:

- `owner_principals.id` as `acquisition_principal_id`;
- D4 rollout and enrollment revision IDs;
- `projects.id`, `v2_sessions.id`, Recording Attempt/recording/audio identities;
- `ideal_text_document_snapshots.id`, Paragraph/part ID and exact revision;
- `candidate_sets.id`, `feedback_candidates.id`, `evidence_spans.id`;
- `feedback_v3_memberships.id` and exact membership item candidate identity;
- exact rendered `feedback_exposures.id` or service exposure identity;
- exact `feedback_v3_owner_responses.id` / canonical correction decision;
- `ml_review_assignments.id`, blind packet, presentation, rendered exposure,
  `ml_judgments.id`, batch, reveal grant and reveal access IDs;
- coach-guidance attachment/version/media/lifecycle IDs;
- exercise offer, complete catalogue/candidate inventory, exercise version,
  assignment, rendered exposure, playback, practice session/attempt/selection,
  acoustic measurement and comparison IDs;
- D4 source/practice target-speaker binding and same-speaker eligibility IDs;
- RPQ content, semantic input/result, owner routing, qualification, product
  action, and block-head identities; and
- canonical learning-surface presentation/exposure and dataset-release IDs.

No second candidate, review assignment, exposure, judgment, Paragraph lock,
exercise, practice, root-head, or dataset system may be created.

### 3.2 Bundle is a read model

`ConfidentMomentCoachingBundle` is a server-built projection, not a new feedback
family. Its stable `bundle_id` is the exact selected subject
`feedback_candidate_id`; it is always accompanied by `feedback_membership_id`,
subject evidence and exact Take/document identity. The candidate ID cannot be
reused across regenerated sets.

`bundle_subject_kind` is closed to:

```text
confidence_anchor
no_anchor_paragraph_trigger
```

`confidence_anchor` uses the already-selected V3 Confident Voice candidate.
`no_anchor_paragraph_trigger` uses the already-selected correction candidate
when no usable same-Slide confidence anchor exists. The latter is exact,
non-orange and presentation-only; its identity binds membership, candidate,
family, evidence, Paragraph, document snapshot, policy and canonical
presentation. It creates no confidence anchor/root/qualification or Manager
slot. Preparation creates no exposure or response.

Each attached selected item freezes:

```text
feedback_membership_id
bundle_subject_kind
bundle_subject_candidate_id
bundle_subject_evidence_span_id
attached_candidate_id
attached_evidence_span_id
anchor_candidate_id nullable
anchor_evidence_span_id nullable
paragraph_id
document_snapshot_id
canonical_feedback_presentation_id
attachment_policy_version
attachment_input_sha256
```

`canonical_feedback_presentation_id` is the already-frozen selected
`feedback_exposures.id` whose `shown_at` is null. In the released V3 service
contract that row is prepared presentation inventory, not proof of exposure.
Bundle preparation may reference it but must create no `feedback_exposures`,
render-receipt or response row and must not set `shown_at`. Authenticated visible
render calls the canonical V3 render transition, which creates/reuses exactly
one `feedback_v3_service_render_receipts` row and changes only `shown_at` under
the existing guarded transition. In this manifest, “zero exposures before
render” means zero rendered receipts and zero rows with non-null `shown_at`;
the immutable prepared presentation row remains present.

The projection never copies a coach judgment, model score, rank, or qualification
value into a user-visible field.

### 3.3 Minimal additive persistence

Chunk 2 may add only:

1. `confident_moment_bundle_attachments`
   - exact membership, subject kind/candidate/evidence, attached selected
     candidate/evidence, nullable same-Slide confidence anchor, Paragraph and
     document snapshot;
   - canonical order, attachment/trigger policy, the exact pre-existing
     selected presentation identity and
     immutable input hash;
   - preparation state only: it contains no render-receipt or response ID and
     does not create or mark an exposure;
   - disabled `serves_user=false`, `dataset_eligible=false`.
2. `root_phrase_coverage_frames`
   - exact principal, Project, Take, document snapshot and V3 membership;
   - Take ordinal, immutable Slide denominator, target count, achieved count;
   - policy/code versions, complete inventory hash, idempotency key;
   - disabled `serves_user=false`, `dataset_eligible=false`.
3. `root_phrase_coverage_items`
   - exact frame, Slide, block, anchor candidate/evidence, content version and
     current root-action identity when present;
   - closed routing state, typed exclusion/shortfall reason, canonical order,
     item hash;
   - internal ranking evidence only; never user-visible scores;
   - disabled `serves_user=false`, `dataset_eligible=false`.
4. Exact-lineage columns/constraints on canonical `feedback_revisions`
   - V3 membership, candidate, evidence, candidate output version/hash;
   - output kind `comment|rephrase` and closed Comment purpose;
   - batch, reveal, assignment, blind judgment and supersession identity;
   - old rows remain immutable and nullable legacy rows cannot authorize v1.
5. `feedback_language_revision_deliveries`
   - exact coach revision, recipient principal, scheduled Take, bundle anchor,
     delivery state/revision and idempotency identity;
   - delivery is not render/exposure;
   - render uses the canonical learning-surface presentation/exposure receipt.
6. The accepted evolution of `root_phrase_product_actions` and its constraints,
   not a parallel root-action table, to represent the independent origin,
   persistence, and qualification axes in Contract Delta §6 plus exact optional
   practice attempt, source/practice target-speaker binding and practice-guard
   hash provenance required by §5.9.

No additional bundle, exposure, response, review, practice, outcome, dataset or
learning tables are permitted.

## 4. Closed values

### 4.1 Feedback Language

```text
output_kind:
  comment | rephrase

comment_purpose:
  confidence_explanation
  actionable_observation
  positive_praise

revision_origin:
  machine | coach
```

`positive_praise` retains canonical family `great_formulation`.
`actionable_observation` and `rephrase` retain canonical family
`rewrite_clarity`. `confidence_explanation` retains `confident_voice`.

### 4.2 Coverage routing

```text
coverage_item_state:
  covered_existing_owner_lock
  covered_automatic_root
  covered_owner_selected
  eligible_automatic_proposal
  eligible_owner_proposal
  pending_rerecord
  uncovered_no_aligned_clause
  uncovered_owner_declined
  excluded_unusable_source
  invalidated
```

Coverage state is product routing, never a confidence or adequacy label.

### 4.3 Root axes

```text
activation_origin:
  automatic_product_selection | owner_selection

persistence_state:
  automatic_replaceable | owner_locked

qualification_state:
  not_qualified_reference | qualified_confident_reference
```

The user payload exposes only the current display/lock affordances, never
`qualification_state` or internal automatic-eligibility reasons.

## 5. Backend RPC interfaces

All signatures below are proposed v1 boundaries and remain unavailable to
runtime roles while their gates are disabled. PostgreSQL derives identity and
authoritative text/context; callers cannot supply hashes as authority.

### 5.1 Bundle preparation

```text
prepare_confident_moment_bundle_v1(
  p_acquisition_principal_id uuid,
  p_project_id uuid,
  p_take_id uuid,
  p_feedback_membership_id uuid,
  p_bundle_subject_candidate_id uuid,
  p_idempotency_key text
) -> jsonb
```

Requires an exact selected subject within the membership and projects only the
already-selected Manager items. The database derives `bundle_subject_kind`; the
caller cannot submit it. A selected `confident_voice` subject becomes
`confidence_anchor`. A selected correction becomes
`no_anchor_paragraph_trigger` only when the frozen policy proves that a usable
same-Slide confidence anchor is absent; its nullable anchor fields remain null.
A correction is rejected as a subject when a usable same-Slide confidence
anchor exists, because it must attach to that anchor instead. Foreign family,
membership, Take, Slide, content or policy identity fails closed. Preparation
creates no exposure receipt or response and no confidence/root/qualification
state.

### 5.2 Bundle-item visible render

```text
ack_confident_moment_bundle_item_render_v1(
  p_acquisition_principal_id uuid,
  p_bundle_attachment_id uuid,
  p_presentation_id uuid,
  p_render_instance_id uuid,
  p_idempotency_key text
) -> jsonb
```

The function writes only through the existing canonical feedback exposure
ledger. Preparation/delivery never call it. One authenticated visible render
creates one receipt; exact retry returns it. The later canonical feedback
response must bind that receipt. Missing, foreign or stale presentation,
attachment or exposure identity fails closed.

### 5.3 Root coverage frame

```text
freeze_root_phrase_coverage_frame_v1(
  p_acquisition_principal_id uuid,
  p_project_id uuid,
  p_take_id uuid,
  p_feedback_membership_id uuid,
  p_document_snapshot_id uuid,
  p_policy_version text,
  p_idempotency_key text
) -> jsonb
```

The database derives Slide denominator, target, candidate/root inventory,
achieved count and hashes. Browser-supplied coverage counts are rejected.

### 5.4 Coach Feedback Language revision

```text
record_feedback_language_coach_revision_v1(
  p_reviewer_principal_id uuid,
  p_review_batch_id uuid,
  p_reveal_grant_id uuid,
  p_reveal_access_id uuid,
  p_review_assignment_id uuid,
  p_blind_judgment_id uuid,
  p_feedback_membership_id uuid,
  p_feedback_candidate_id uuid,
  p_candidate_output_sha256 text,
  p_output_kind text,
  p_comment_purpose text,
  p_revision_text text,
  p_supersedes_revision_id uuid,
  p_idempotency_key text
) -> jsonb
```

The database reloads the canonical output/version, complete-batch reveal and
current coach authority. `p_comment_purpose` is null for `rephrase` and required
for `comment`. Exact replay returns the same revision; changed text or lineage
with the same key fails.

### 5.5 Coach revision delivery

```text
schedule_feedback_language_revision_v1(
  p_revision_id uuid,
  p_recipient_principal_id uuid,
  p_target_take_id uuid,
  p_anchor_candidate_id uuid,
  p_idempotency_key text
) -> jsonb
```

Scheduling occurs for the current unresolved bundle or next relevant Take. It
never changes Ideal Text/root state and never creates an exposure.

### 5.6 Coach-update render

```text
ack_feedback_language_revision_render_v1(
  p_recipient_principal_id uuid,
  p_revision_delivery_id uuid,
  p_presentation_id uuid,
  p_render_instance_id uuid,
  p_idempotency_key text
) -> jsonb
```

This must delegate to or write through the canonical surface-specific exposure
boundary; it must not create a parallel exposure ledger.

### 5.7 Canonical Ideal Text root transition — internal only

```text
transition_ideal_text_root_state_v1(
  p_acquisition_principal_id uuid,
  p_project_id uuid,
  p_take_id uuid,
  p_content_version_id uuid,
  p_expected_part_revision_id bigint,
  p_transition_action text,
  p_idempotency_key text
) -> jsonb
```

This is the sole low-level writer for `ideal_text_part.locked_at`, `root_phrase`,
`root_start`, `root_end`, `root_selected_at`, `iteration` and the corresponding
append-only `ideal_text_part_revision` rows after this migration. It is an
internal `SECURITY DEFINER` helper with EXECUTE revoked from `PUBLIC`, `anon`,
`authenticated` and `service_role`; only reviewed higher-level root RPCs may
invoke it.

Closed transitions are:

```text
set_automatic_root
set_owner_selected_root
lock_current_root
restore_owner_selected_root
unlock_current_root
remove_current_root
legacy_qualified_lock_and_activate
legacy_qualified_activate
legacy_qualified_remove
```

The helper derives exact text and offsets from `root_phrase_content_versions`,
resolves the owner from the acquisition principal, locks the current document
head/Paragraph/revision, verifies exact snapshot text and expected latest
`ideal_text_part_revision.id`, then performs the transition and appends the
canonical revision(s). `set_automatic_root` never changes `locked_at`;
`lock_current_root` and the legacy lock-and-activate transition increment
`iteration` once and append `lock`; root set/remove appends `root_set` or
`root_skipped`; unlock appends `unlock`. Exact replay returns the same revision
identities after live revalidation; changed state or payload fails closed.

The migration must replace the released bodies of
`activate_synthetic_root_phrase_v1` and `remove_synthetic_root_phrase_v1` so
their Ideal Text mutations delegate to this helper while preserving their exact
public signatures, RPQ qualification requirements, results, error semantics,
product-action/block-head behavior and grants. Static and PostgreSQL tests must
prove those functions contain no remaining direct Ideal Text mutation and that
legacy qualified activation/removal behavior is byte-for-byte equivalent at the
state/revision boundary. No other route or function receives helper access.

### 5.8 Root action v2

```text
record_root_phrase_product_action_v2(
  p_acquisition_principal_id uuid,
  p_project_id uuid,
  p_take_id uuid,
  p_paragraph_id uuid,
  p_block_key integer,
  p_action text,
  p_expected_block_head_action_id uuid,
  p_source_candidate_id uuid,
  p_source_evidence_span_id uuid,
  p_source_feedback_exposure_id uuid,
  p_source_owner_response_id uuid,
  p_source_practice_attempt_id uuid,
  p_source_ideal_text_revision_id bigint,
  p_source_target_speaker_binding_id uuid,
  p_practice_target_speaker_binding_id uuid,
  p_restore_product_action_id uuid,
  p_policy_version text,
  p_idempotency_key text
) -> jsonb
```

Nullable source IDs are action-specific and constrained by §5.9; the database
derives text, content version, Slide and root axes from authoritative records.
Callers cannot supply root text, eligibility, qualification, score or axis
values. It atomically reuses the authoritative Ideal Text lock/revision and
current root block head. Closed actions are:

```text
activate_automatic_root
save_owner_selected_root
lock_current_root
restore_previous_root
unlock_current_root
remove_current_root
```

`activate_automatic_root` is server-policy-only. Runtime user roles may never
declare automatic eligibility or qualification. It requires exact
`confident_yes`, aligned semantics and the frozen lexicographic coverage
decision. `save_owner_selected_root` is explicit owner selection and does not
qualify the phrase. `lock_current_root` atomically performs the canonical Ideal
Text lock transition. `restore_previous_root` requires the exact prior action.
All actions lock the block head and authoritative Paragraph/content identity in
stable UUID order, write Ideal Text only through §5.7, and revalidate after
contention and on replay.

### 5.9 Closed root-action source matrix and practice guard

The following is the complete allowed matrix. “Required when revision-backed”
means required exactly when the selected content version has
`source_part_version_kind=existing_part_revision_v1`; it must equal that
content version's `source_part_revision_id`.

| Action | Candidate/evidence | Exposure/owner response | Practice attempt | Source/practice speaker bindings | Ideal Text revision | Restore action |
| --- | --- | --- | --- | --- | --- | --- |
| `activate_automatic_root` | required; exact content candidate/evidence | required; exact rendered `confident_yes` | null | null | required when revision-backed | null |
| `save_owner_selected_root`, transcript source | required; exact content candidate/evidence | required for a V3 self-report proposal; otherwise null only for an explicit canonical user edit | null | null | required when revision-backed | null |
| `save_owner_selected_root`, re-record source | required; exact content candidate/evidence | optional historical source lineage only when exact | required | both required | required when revision-backed | null |
| `lock_current_root` | null | null | null | null | null | null |
| `restore_previous_root` | null | null | null | null | null | required exact prior active/root action |
| `unlock_current_root` | null | null | null | null | null | null |
| `remove_current_root` | null | null | null | null | null | null |

Every other combination fails `ROOTING_PHRASE_SOURCE_COMBINATION_INVALID` before
any write. A non-null practice attempt is legal only for the re-record-source
row above and invokes internal guard:

```text
require_root_phrase_practice_source_live_v1(
  p_acquisition_principal_id uuid,
  p_content_version_id uuid,
  p_practice_attempt_id uuid,
  p_source_target_speaker_binding_id uuid,
  p_practice_target_speaker_binding_id uuid
) -> jsonb
```

The guard is inaccessible to runtime roles. It locks source and practice
recording-attempt identities in UUID order, then reloads after contention:

1. the exact practice attempt/session, `require_practice_source_live_v1`, live
   recording/audio object, exact audio hash, retention/deletion/media state;
2. the session's exact source offer and its membership/candidate/Slide/block;
3. either the content candidate itself or the exact frozen Bundle attachment
   connecting that correction candidate to the offer's confidence anchor;
4. exact normalized practice passage and transcript equality to the immutable
   content phrase;
5. the supplied source and practice target-speaker bindings as the latest
   active bindings for their exact recording attempts/acquisition revisions;
6. equality of their resolved canonical `speaker_id` values; and
7. current D4 rollout access and both same-receipt service purposes.

Missing, stale, superseded, foreign, unresolved or different-speaker identity,
invalid practice, mismatched text/offer/bundle lineage, authority withdrawal,
deletion or media invalidation fails closed. Exact replay reruns the guard before
returning. This routing proof creates no comparison, preference, judgment,
improvement, adequacy or learning row. The two binding IDs and guard-result hash
are stored on the root product action as immutable provenance.

## 6. HTTP/API interfaces

All routes require authenticated canonical principal resolution and current D4
service access. Frontend flags are presentation-only.

### 6.1 User bundle read

```http
GET /v2/explore/arcs/{project_id}/confident-moment-bundles?take_id={take_id}
```

Response:

```json
{
  "contract_version": "confident-moment-coaching-bundle-v1",
  "project_id": "uuid",
  "take_id": "uuid",
  "document_snapshot_id": "uuid",
  "feedback_membership_id": "uuid",
  "bundles": [
    {
      "bundle_id": "anchor-candidate-uuid",
      "bundle_subject_kind": "confidence_anchor",
      "slide_index": 0,
      "block_key": 0,
      "paragraph_id": "uuid",
      "subject": {
        "candidate_id": "uuid",
        "evidence_span_id": "uuid",
        "canonical_feedback_presentation_id": "uuid"
      },
      "confidence_anchor": {
        "candidate_id": "uuid",
        "evidence_span_id": "uuid",
        "playback_reference_id": "opaque-string"
      },
      "comment": null,
      "rephrase": null,
      "exercise": null,
      "root": {
        "is_orange": false,
        "is_locked": false,
        "can_restore_previous": false
      },
      "coach_update": {
        "current_revision_id": null,
        "unread": false
      },
      "state_revision": 1
    }
  ],
  "coverage": {
    "target_slide_count": 1,
    "achieved_slide_count": 0,
    "target_met": false
  },
  "response_sha256": "64-lowercase-hex"
}
```

For `no_anchor_paragraph_trigger`, `confidence_anchor` is null and no playback
or orange/root affordance is implied. The subject presentation becomes exposed
only after the render acknowledgement returns its canonical receipt.

No score, rank, model verdict, coach judgment, qualification state, or hidden
human answer may be returned.

### 6.2 User action reuse

- Confidence/Rephrase/Praise responses continue through the exact canonical
  `/v2/user/takes/{take_id}/feedback-response` boundary with candidate,
  membership and rendered-exposure identity.
- Visible bundle-item render uses
  `POST /v2/user/confident-moment-bundles/{bundle_id}/render`, carrying exact
  attachment, presentation, render-instance and idempotency identities. It
  delegates to RPC §5.2 and returns the canonical exposure receipt. No response
  is created by this endpoint.
- Ideal Text wording changes continue through the canonical
  `/v2/explore/arc/{project_id}/ideal-text/user-edit` and save/decision paths.
- Exercise offer, render/playback, practice, attempt, preference and media reads
  continue through the accepted `/v2/user/mlc3/*` routes.
- Root actions continue under
  `/v2/explore/arcs/{project_id}/rooting-phrase-qualification/actions`, but a
  reviewed v2 request/SQL contract is required for automatic roots.

Do not introduce generic event endpoints that allow the browser to choose an
authoritative event kind.

### 6.3 Coach Feedback Language revision

```http
POST /v2/coach/guidance/feedback-language-revisions
```

Request contains the exact IDs and values of RPC §5.4. Response contains only
the stored revision ID/version/hash and replay outcome. The route derives
reviewer principal from authentication and rejects a mismatched body identity.

Existing coach queue, inline render/judgment, complete-batch reveal, guidance,
media, exercise-draft and publication routes remain canonical.

### 6.4 Coach-update render

```http
POST /v2/user/confident-moment-bundles/{bundle_id}/coach-updates/{revision_id}/render
```

Request:

```json
{
  "revision_delivery_id": "uuid",
  "presentation_id": "uuid",
  "render_instance_id": "uuid",
  "idempotency_key": "non-empty-string"
}
```

Opening the overlay triggers this independently of accepting/cancelling the
revision. Exact retry returns the same exposure receipt.

## 7. Stable first-paint core summary

Extend the existing Ideal Text core response, not optional enrichment, with:

```json
{
  "confident_moment_summary": {
    "contract_version": "confident-moment-core-summary-v1",
    "document_snapshot_id": "uuid",
    "items": [
      {
        "bundle_id": "uuid",
        "paragraph_id": "uuid",
        "slide_index": 0,
        "block_key": 0,
        "marker_present": true,
        "is_orange": false,
        "is_locked": false,
        "has_unread_coach_update": false,
        "state_revision": 1
      }
    ],
    "summary_sha256": "64-lowercase-hex"
  }
}
```

Every Paragraph continues to reserve its bookmark/marker control from first
paint. Optional enrichment may fill content but cannot remove/reinsert the
control or transiently reset an already-known root/buzz state.

## 8. Frontend state-machine contract

One user hook owns bundle state; do not duplicate it inside the Ideal Text
component.

```text
loading_core
  -> ready_closed
  -> opening
  -> open_unanswered
  -> confidence_answered
  -> correction_pending | exercise_available | root_review
  -> recording
  -> attempt_review
  -> root_review
  -> completed

Any state -> recoverable_error -> prior stable state
```

Closed events:

```text
CORE_SUMMARY_LOADED
BUNDLE_OPENED
EXPOSURE_ACKED
CONFIDENCE_SUBMITTED
CORRECTION_UPDATED
CORRECTION_CANCELLED_FOR_TAKE
EXERCISE_OPENED
EXERCISE_SKIPPED
PRACTICE_STARTED
PRACTICE_ATTEMPT_SAVED
ROOT_SAVED
ROOT_RESTORED
ROOT_CHANGE_CANCELLED
COACH_UPDATE_RENDERED
```

The reducer keys state by exact `bundle_id + state_revision`; snippet ID or
text is never sufficient. A stale revision produces a reload, never an
optimistic cross-binding.

## 9. Gates and disabled defaults

### Backend

```text
CONFIDENT_MOMENT_BUNDLE_V1_ENABLED=false
ROOTING_COVERAGE_V1_ENABLED=false
PAM_PROFILE_V1_ENABLED=false
PAM_BASELINE_V1_ENABLED=false
PAM_MATCHING_V1_ENABLED=false
PAM_COACH_AUTHORING_V1_ENABLED=false
PAM_USER_SERVING_V1_ENABLED=false
```

The new bundle also requires the existing authoritative D4 database rollout,
`MLC3_SERVICE_ENABLED`, and, for coach authoring,
`MLC3_COACH_INLINE_AUTHORING_ENABLED`. One gate never implies another.

### Frontend

```text
NEXT_PUBLIC_CONFIDENT_MOMENT_BUNDLE_V1_ENABLED=false
NEXT_PUBLIC_ROOTING_COVERAGE_V1_ENABLED=false
```

Existing `NEXT_PUBLIC_MLC3_SERVICE_UI_ENABLED` and
`NEXT_PUBLIC_MLC3_COACH_INLINE_AUTHORING_ENABLED` remain separately required.

### Learning

No configuration flag may convert product evidence into dataset evidence.
`dataset_eligible=false` is structural. Dataset release, training, evaluation,
promotion, and serving require their separately permissioned contracts and are
absent/disabled in this implementation.

## 10. Error codes

Freeze these route/RPC error families:

```text
CONFIDENT_MOMENT_BUNDLE_DISABLED
CONFIDENT_MOMENT_EXACT_IDENTITY_REQUIRED
CONFIDENT_MOMENT_MEMBERSHIP_INVALID
CONFIDENT_MOMENT_SUBJECT_INVALID
CONFIDENT_MOMENT_ANCHOR_INVALID
CONFIDENT_MOMENT_ATTACHMENT_INVALID
CONFIDENT_MOMENT_STALE_REVISION
CONFIDENT_MOMENT_REPLAY_CONFLICT
CONFIDENT_MOMENT_AUTHORITY_REQUIRED
CONFIDENT_MOMENT_SOURCE_NOT_LIVE
CONFIDENT_MOMENT_NO_SAME_SLIDE_ANCHOR
FEEDBACK_LANGUAGE_REVISION_INVALID
FEEDBACK_LANGUAGE_REVEAL_REQUIRED
FEEDBACK_LANGUAGE_REPLAY_CONFLICT
ROOTING_COVERAGE_DISABLED
ROOTING_COVERAGE_INVENTORY_INVALID
ROOTING_COVERAGE_TARGET_UNMET
ROOTING_PHRASE_AUTOMATIC_POLICY_INVALID
ROOTING_PHRASE_OWNER_APPROVAL_REQUIRED
ROOTING_PHRASE_SOURCE_COMBINATION_INVALID
ROOTING_PHRASE_PRACTICE_SOURCE_INVALID
ROOTING_PHRASE_SPEAKER_IDENTITY_INVALID
IDEAL_TEXT_ROOT_TRANSITION_STALE
IDEAL_TEXT_ROOT_TRANSITION_REPLAY_CONFLICT
IDEAL_TEXT_ROOT_TRANSITION_NOT_AUTHORIZED
PAM_APPROVED_POPULATION_REFERENCE_UNAVAILABLE
```

`ROOTING_COVERAGE_TARGET_UNMET` is an honest product state, not necessarily an
HTTP failure. Authorization, foreign identity, stale leaf, and replay conflicts
fail closed without partial writes.

## 11. Idempotency identities

| Operation | Exact identity inputs |
| --- | --- |
| Bundle projection | principal + Project + Take + membership + exact subject candidate + database-derived subject kind + document snapshot + projection version |
| Attachment | membership + attached candidate/evidence + anchor candidate/evidence + attachment policy |
| Coach revision | reviewer + batch/reveal/access + assignment/judgment + membership/candidate/output hash + output kind + superseded revision + text hash |
| Revision delivery | revision + recipient principal + target Take + anchor + current authorization/rollout revision |
| Revision render | delivery + presentation + recipient + render instance |
| Coverage frame | principal + Project + Take + membership + document snapshot + coverage policy + full Slide/block inventory hash |
| Ideal Text root transition | principal + Project + Take + content version + expected latest part revision + closed transition + authoritative before/after state hash |
| Root action | principal/actor kind + content version + exact attempt and source/practice speaker bindings when applicable + source-matrix/guard hash + prior block head + action + origin/persistence/qualification axes + state revision |

Changed payload with a reused idempotency key is a conflict. Exact replay must
revalidate current authority, deletion/media/speaker/content leaves before
returning the stored result.

## 12. Authorization and deletion edges

Every new user-scoped row must bind `acquisition_principal_id` and register
deletion traversal to:

- Project, Take, recording attempt, recording/audio object and evidence span;
- document snapshot, Paragraph/part and revision;
- V3 membership/candidate/exposure/owner response;
- bundle attachment and coverage frame/item;
- coach revision, delivery, presentation/render receipt;
- review batch, assignment, blind packet, judgment, reveal grant/access;
- guidance attachment/version/media and lifecycle;
- exercise offer/catalogue/candidate/version/assignment;
- practice session/attempt/measurement/selection and source/practice pair;
- target-speaker binding, same-speaker eligibility and capture comparability;
- root content/semantic/qualification/product action/block head; and
- authorization receipt/snapshot, rollout and enrollment revisions.

Creation, delivery, render, replay, practice, root replacement, and media read
must call the current D4 rollout-aware access resolver after contention and
recheck both service purposes on the same current receipt/policy. Withdrawal,
purge, retention expiry, quarantine, stale media, speaker correction, or source
deletion fails closed. Logical invalidation remains distinct from physical
shared-media retention.

## 13. File ownership matrix

No file may be edited by two delegated chunks. If implementation discovers an
unlisted shared-file need, stop and return an interface-change request.

### Chunk 2 — backend data/SQL (delegate cautiously)

Owned proposed files:

```text
migrations/pending/add_confident_moment_coaching_bundle_v1.sql
tests/test_confident_moment_coaching_bundle_postgres.py
tests/test_rooting_coverage_policy_postgres.py
tests/test_confident_moment_bundle_security.py
services/data_purge_registry.py
tests/test_phase1_deletion_completion.py
```

Chunk 2 owns no Python route/service or frontend file. Migration stays
unnumbered and absent from `migrations/manifest.txt`.

### Chunk 3 — backend application/API (delegate)

Owned proposed files:

```text
config.py
services/confident_moment_bundle.py
services/confident_moment_bundle_repository.py
services/feedback_language.py
services/rooting_coverage.py
routes/v2/confident_moment_bundles.py
routes/v2/rooting_phrase_qualification.py
routes/v2/coach_guidance_delivery.py
routes/v2/explore_ideal_text.py
routes/v2/user_sessions.py
tests/test_confident_moment_bundle.py
tests/test_confident_moment_bundle_routes.py
tests/test_feedback_language.py
tests/test_rooting_coverage.py
tests/test_ideal_text_core_confident_summary.py
```

Chunk 3 must not add wrappers to `services/db.py`. The dedicated repository is
the only new database adapter. Avoid editing Manager ranking source; consume the
frozen V3 membership.

### Chunk 4 — user frontend (delegate)

Owned proposed files:

```text
src/components/willab/ConfidentMomentCoachingBundle.tsx
src/components/willab/useConfidentMomentBundle.ts
src/components/willab/DeckChunkModal.tsx
src/components/willab/IdealTextOverlay.tsx
src/components/willab/IdealTextReadout.tsx
src/components/willab/RootingPhraseQualificationActions.tsx
src/lib/willab/rootPhraseLayer.ts
src/services/api/confidentMomentBundles.ts
src/services/api/idealText.ts
src/app/api/v2/explore/arcs/[arcId]/confident-moment-bundles/route.ts
src/app/api/v2/user/confident-moment-bundles/[bundleId]/render/route.ts
src/app/api/v2/user/confident-moment-bundles/[bundleId]/coach-updates/[revisionId]/render/route.ts
src/components/willab/ConfidentMomentCoachingBundle.test.tsx
src/components/willab/ConfidentMomentFirstPaint.test.tsx
src/services/api/confidentMomentBundles.test.ts
```

Chunk 4 owns no coach component/API module.

### Chunk 5 — coach frontend (delegate)

Owned proposed files:

```text
src/components/willab/CoachFeedbackLanguageEditor.tsx
src/components/willab/CoachConfidentMomentComposer.tsx
src/components/willab/CoachSnippetReviewCard.tsx
src/components/willab/CoachGuidanceComposer.tsx
src/components/willab/CoachInlineBlindExposureBoundary.tsx
src/services/api/coachGuidanceDelivery.ts
src/services/api/stateRatings.ts
src/app/api/v2/coach/guidance/feedback-language-revisions/route.ts
src/components/willab/CoachFeedbackLanguageEditor.test.tsx
src/components/willab/CoachConfidentMomentComposer.test.tsx
src/services/api/coachGuidanceDelivery.test.ts
```

Chunk 5 owns no user Ideal Text/bundle component.

### Integration-only files — Chunk 6 here

Only the final integrator may edit:

```text
app.py or central backend route-registration file, if required
migrations/manifest.txt
release/checksum packets
shared frontend exports/index files not allocated above
cross-repository contract/E2E tests
```

The manifest must remain unchanged during Chunks 2–5. Migration numbering and
manifest edits require later release-preparation authorization, not ordinary
integration.

## 14. Exact test allocation

### Chunk 2

- PostgreSQL clean apply/populated apply/reapply/negative rollback.
- Exact FK/constraint, append-only, forced-RLS, grants/RPC-only checks.
- Cross-principal/stale/replay/contention/deletion/media/speaker adversarial
  paths for new persistence.
- No-anchor preparation creates zero exposures/responses; visible render creates
  one canonical exposure; exact retry reuses it; response requires it; absent,
  foreign and stale exposure identities fail closed.
- Both subject kinds are derived correctly; a foreign family rejects; a
  correction subject rejects when a usable same-Slide confidence anchor exists;
  exact retry preserves subject kind; a correction subject creates no
  confidence/root/qualification state.
- The prepared selected presentation row remains unshown; preparation creates
  no new presentation/exposure row, render receipt or response and never changes
  `shown_at`.
- The internal Ideal Text transition is inaccessible to every runtime role;
  legacy RPQ activation/removal and v2 actions all delegate to it; legacy state,
  revision, replay and rollback behavior remains equivalent.
- Every root action accepts only its §5.9 source combination; arbitrary practice
  attempts reject. Exact re-record source, offer/bundle/text/media/authority and
  latest-active same-speaker binding lineage pass; stale/different/unresolved
  speaker, deleted/quarantined media, withdrawn authority and replay after a
  leaf change fail closed with no product or learning partial row.
- No partial frame/revision/root state after failure.

### Chunk 3

- Clause extraction golden cases and 75-word Slide/block boundaries.
- Ranking determinism with vocal dominance and alignment safeguards.
- 30/80/100 target derivation, rounding, mandatory Slide 1, and honest shortfall.
- Attachment projection without Manager-budget mutation.
- One-at-a-time correction, cancel-for-Take and next-Take coach update.
- API exact identity, disabled gate and response denylist tests.

### Chunk 4

- Bundle reducer/state transitions and exact keying.
- Stable first paint with no icon disappearance.
- Update/Cancel, Save/Cancel, skip, re-record, prior-root restoration.
- Buzz-until-render and post-render persistence without buzz.
- Mobile, keyboard/focus, screen-reader, loading/retry/error behavior.
- No score/verdict/qualification/internal-state surface.

### Chunk 5

- Visible unanswered card creates one exposure and zero judgments.
- Later judgment reuses exposure; exact retry; foreign/stale rejection.
- Complete-batch reveal; duplicate snippet with distinct assignment identities.
- Comment versus Rephrase editing and latest-current version.
- General guidance versus exercise eligibility; private media recovery.
- Unauthorized coach and pre-reveal leakage rejection.
- Mobile/accessibility behavior.

### Chunk 6 here

- Combined backend/frontend full CI-equivalent suites.
- Production-shaped PostgreSQL apply/reapply and all adversarial races.
- End-to-end record → feedback → bundle → text decision → exercise → practice →
  root flow with coach asynchronous.
- V3 budget/family/exposure preservation.
- Eight-surface registry and `dataset_eligible=false` proof.
- Gate/static/security/diff checks and checksum-pinned review packet.

## 15. Retained external blockers

Contract Delta D3 is ML/data design-accepted, so separately authorized local
disabled-gate Chunks 2–5 may execute against this exact manifest. The following
remain intentionally outside their authority:

1. dataset/evaluation thresholds require independent ML/data acceptance and do
   not make any product row dataset-eligible; and
2. PAM cannot serve without its separately reviewed population artifact plus
   implementation, release and activation acceptance.
