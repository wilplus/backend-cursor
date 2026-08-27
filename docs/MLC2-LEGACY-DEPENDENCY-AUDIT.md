# MLC-2 Legacy Dependency Audit

Status: `FOUNDATION INVENTORY — NO CUTOVER AUTHORIZED`

Unknown dependencies fail closed. Foundation schema work may proceed, but no
legacy learning writer, reader, table or export path may change until its
surface-specific audit is complete and ML/data-approved.

## Classification contract

- **product-state** — still required by the product; preserve until deliberately
  migrated and verified.
- **learning-only** — may stop writing only at the corresponding atomic surface
  cutover; never import its history into MLC-2.
- **mixed-purpose** — split product state from canonical provenance before any
  removal. Requires a named migration owner.
- **unknown** — blocks cutover and deletion.

## Initial checked-in mapping

This inventory is deliberately conservative. File names identify known
producer/reader areas; the per-surface audit must expand each row to functions,
routes, jobs and UI callers before approval.

| Legacy dependency | Known producers | Known readers/routes/jobs/UI | Classification | Migration owner | Cutover status |
|---|---|---|---|---|---|
| `moment_suggestions` | `services/moment_suggestions.py`, `services/manager_engine.py`, `services/db.py` | `routes/v2/arcs.py`, `routes/v2/user_sessions.py`, Ideal Text/feedback services | mixed-purpose | Señor Engineer | blocked pending full correction+praise audit |
| `star_verdicts` | `services/star_verdicts.py`, `services/db.py` | feedback routes, `services/voice_album.py`, admin/coach reads | mixed-purpose | Señor Engineer | blocked pending confidence audit |
| `user_suggestion_feedback` | feedback routes and `services/db.py` | Manager/feedback history and export paths | mixed-purpose | Señor Engineer | blocked pending correction+praise audit |
| `feedback_exposures` | canonical-feedback RPCs and compatibility services | readiness/report and feedback decision paths | mixed-purpose | Señor Engineer | blocked; server selection timestamp is not rendered exposure |
| `confidence_labels` | confidence/coach review services | confidence evaluation and admin review | mixed-purpose | Señor Engineer | blocked pending practice/blindness audit |
| `confidence_self_reports` | canonical-feedback RPCs | readiness, Voice Album and comparison paths | mixed-purpose | Señor Engineer | blocked pending confidence audit |
| `confidence_coach_labels` | coach-review RPCs | readiness, quorum and comparison paths | mixed-purpose | Señor Engineer | blocked pending blind-coach audit |
| `confidence_peer_labels` | peer-review RPCs | readiness, quorum and comparison paths | mixed-purpose | Señor Engineer | blocked pending blind-peer audit |
| `praise_helpfulness` | feedback-decision RPC | readiness and export paths | mixed-purpose | Señor Engineer | blocked pending praise audit |
| `correction_decisions` | feedback-decision RPC | accepted rewrite/product state and export paths | mixed-purpose | Señor Engineer | blocked pending correction audit |
| `annotation_events` and export corpora | annotation services/admin routes | `scripts/export_*`, DPO/fine-tuning exporters | learning-only/unknown by subtype | Señor Engineer | blocked; no MLC-2 consumer may read them |
| `training_labels` | coach/admin labeling | legacy confidence/evaluation scripts | unknown | Señor Engineer | hard blocker pending corpus dependency audit |
| `intervention_arms` and related experiment state | intervention services | Manager/experiment code | mixed-purpose | Señor Engineer | blocked; retired experiments require separate removal audit |

## Required artifact for each surface

The reviewer must check in a complete matrix containing:

- table/object;
- exact writer function and route/job caller;
- exact reader function and route/job/UI caller;
- current product behavior supported;
- current learning/export behavior supported;
- target product-state destination;
- target canonical event/payload;
- migration owner;
- tests proving no remaining reader/writer;
- ML/data review reference;
- cutover flag and rollback evidence.

No historical record is imported, relabeled or interpreted. Product state is
preserved only when its meaning and dependency are proven.

## Structural training-source prohibition

All new canonical learning modules use the `mlc2_` naming boundary. The
isolation test scans those modules and fails if they reference a listed legacy
table or exporter. Later dataset/release/training modules must use the same
prefix and remain behind the separate authorization gates.

