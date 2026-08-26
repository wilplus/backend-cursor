# Canonical Feedback Data Contract — Migration Map

Status: additive dual-write foundation. Legacy reads remain authoritative.
Legacy retirement is explicitly out of scope until parity and rollback are
approved.

## Phase 1–6 delivery state

- Active dual-writes: complete Manager candidate/exposure ledger, typed owner
  responses, blind coach confidence labels, paragraph lock/evolve/reopen
  decisions, exact root-phrase select/skip history, and per-attempt processing
  stages.
- Deployment-window recovery: exposure, owner decisions, and already-committed
  coach labels are idempotently backfilled when their existing product surface
  is reopened. No user is asked to repeat a final answer.
- Available internal boundaries: peer assignment/label RPCs, database-enforced
  blind coach/peer reads, post-commit comparison, observation-only parity
  report, and immutable single-surface dataset release creation.
- Deliberately not promoted: canonical product reads, training exports, and
  derived Voice Album/flagship read models. They stay behind parity/approval;
  legacy behavior remains authoritative.

## Canonical identity map

| Canonical concept | Current production coordinate | Canonical boundary |
|---|---|---|
| Owner | `owner_principals.id` | Immutable owner/guest identity. A display name is never an identity. |
| Project | `projects.id` (mirrored historically as `arc_id`) | `projects.owner_principal_id`; duplicate `display_name` values are valid. |
| Take | `v2_sessions.id` | `v2_sessions.project_id` + `owner_principal_id` + project-scoped `take_index`. |
| Recording | `recording_1` / historical `recordings` | Referenced by immutable evidence; no table rename during dual-write. |
| Transcript version | assembled transcript JSON and snippet rows | `transcript_versions` immutable snapshot with text/input hash and version provenance. |
| Slide | slide index inside session/document JSON | `slides` immutable rows scoped to one transcript version. |
| Paragraph | `ideal_text_part` plus document paragraph offsets | `paragraphs` immutable rows scoped to one transcript version and slide. |
| Evidence | snippet IDs and JSON locators | `evidence_spans` with exact audio and/or transcript interval plus target locator. |

## Current write paths and migration destination

| Surface | Current write | Canonical dual-write |
|---|---|---|
| Manager selection | `ideal_text_feedback_sets`, `take_feedback_exposure` | `candidate_sets`, `feedback_candidates`, `feedback_exposures`, exact `evidence_spans` |
| Machine output | detector fields and `shadow_predictions` | append-only `machine_predictions`, `generation_runs` |
| Owner Confident Voice response | `take_feedback_self_report` | `confidence_self_reports` |
| Praise response | `take_feedback_self_report` | `praise_helpfulness` |
| Correction response | `take_feedback_self_report` | `correction_decisions`; `edit_myself` remains unresolved rather than being fabricated as acceptance/rejection |
| Paragraph lock/evolve | `ideal_text_part`, `ideal_text_part_revision` | `paragraph_decisions` and immutable `feedback_revisions` |
| Coach confidence judgment | mutable `confidence_labels` plus `label_revision` shadow | append-only `confidence_coach_labels`; revisions use `supersedes_id` |
| Peer confidence judgment | `confidence_labels`/`snippet_peer_labels` | append-only `confidence_peer_labels`, never read by a user surface |
| Voice Album | `voice_album` mirror | append-only `voice_album_admissions` referencing machine + owner + coach evidence |
| Root phrase | columns on `ideal_text_part` | append-only `root_phrases` referencing the paragraph decision |
| Processing | `processing_jobs` | per-attempt `processing_stage_runs` with hashes, idempotency and timestamps |

`feedback_data_parity_v1(take_id)` compares candidate counts, the exact-three
selection, and every semantically mappable owner decision. It is service-role
only and observation-only; it cannot switch reads or mutate either model.

## Route inventory

Owner/project boundaries:

- `POST /v2/projects`
- `POST /v2/projects/claim`
- `POST /v2/projects/{project_id}/takes/{take_id}/send-to-coach`
- recording creation paths using `resolve_take_project` and
  `bind_project_take`

Feedback and Ideal Text:

- `GET /v2/explore/arc/{project_id}/ideal-text`
- `POST /v2/user/takes/{take_id}/feedback-response`
- `PUT /v2/explore/arc/{project_id}/parts/{part_id}/lock`
- `PUT /v2/explore/arc/{project_id}/parts/{part_id}/root`
- `PUT /v2/explore/arc/{project_id}/ideal-text/user-edit`

Coach/blind review:

- `GET /v2/coach/queue`
- `GET /v2/coach/sessions/{take_id}`
- `GET /v2/coach/sessions/{take_id}/confidence-queue`
- `PUT /v2/coach/snippets/{snippet_id}/confidence-label`
- `GET /v2/coach/sessions/{take_id}/confidence-comparison`
- coach publish/revision routes under `/v2/coach/*`

Compatibility/legacy feedback reads that must be observed during parity:

- `GET /v2/explore/arc/{project_id}/feedback`
- user snippet confidence/suggestion routes
- Voice Album reads under `/v2/explore/arc/{project_id}/voice-album`
- professional `coach_snippet_drafts` publication

## Locked data semantics

- `shown`, `answered`, `skipped`, `rejected`, `locked`, and `useful` are
  distinct facts. No canonical writer derives one from another.
- Machine, owner, coach and peer answers land in different tables.
- A Confident Voice clip is the exact audio interval, not a paragraph-wide
  proxy.
- Coach reads before judgment use an allowlisted database function. Comparison
  data becomes available only after that coach has an immutable row.
- Dataset export reads immutable `dataset_releases`; it never queries the live
  product tables as an evolving corpus.
- Split assignment is unique per `owner_principal_id`, so all Projects and
  Takes from one speaker remain in exactly one split across releases.

## Cutover and rollback

1. Characterization tests pin the current user payload and coach blind packet.
2. Canonical tables and RPCs land with RLS, service-role-only access and
   append-only triggers.
3. Existing routes dual-write best-effort. A canonical write failure is logged
   and counted but does not break the live recording loop during observation.
4. Parity reports compare legacy and canonical membership, evidence, decisions
   and provenance by immutable IDs.
5. Canonical reads may be enabled only after parity is complete for the full
   observation window.
6. Rollback disables canonical reads/writes; legacy reads/writes remain intact.
7. No table, column or historical row is dropped automatically. Legacy
   retirement requires a separate founder-approved migration.
