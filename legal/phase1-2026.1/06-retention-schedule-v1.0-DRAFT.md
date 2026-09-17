# Retention and destruction schedule — WillpowerLab Phase-1

    artifact_kind:       retention_schedule
    version:             1.0
    approving_authority: [[FOUNDER: named person or firm]]
    approved_at:         [[FOUNDER: ISO-8601 UTC timestamp of signature]]
    object_key:          [[FOUNDER: storage path of the signed PDF]]
    sha256:              [[computed from the signed PDF at registration time]]
    control_version:     phase1-retention-schedule-v1

**STATUS: DRAFT.** Periods approved by the founder 2026-09-17. Not yet signed,
not yet seeded.

This document exists because `data_retention_rules.legal_artifact_id` is
`NOT NULL` and references `processing_legal_artifacts`. There is no retention
rule without a signed schedule to point at. It is also the document Illinois
BIPA §15(a) requires to be **published**, so it must be written to be read by
users, not only by auditors.

---

## 1. The schedule

| Category | Period | Trigger |
|---|---|---|
| Audio recordings | 12 months | last use of the recording |
| Transcripts, Ideal Text, feedback | until account deletion | user request or account closure |
| Voice measurements | 12 months | last use of the source recording — deleted with the audio, never after it |
| Practice attempts | 30 days | after the practice closes, keeping only the chosen attempt |
| Uploaded files that never became a recording | 24 hours | upload |
| Security and technical logs | 90 days | creation |
| Account and billing records | [[FOUNDER: TBD — depends on the paid/free decision; normally set by accounting law]] | account closure |
| Authorization evidence | while needed to show processing was lawful | — |

**Voice measurements are never outlived by their source.** They are deleted with
the audio they came from, and never persist after it. Keeping an analysis of a
recording you have deleted is the position hardest to defend — under GDPR
storage limitation and, more sharply, under BIPA §15(a)'s "when the purpose has
been satisfied".

## 2. Rules to seed

One row per rule in `data_retention_rules`, all `active = true`, all pointing at
this document's artifact id.

| `rule_code` | `evidence_category` | `retention_until_rule` |
|---|---|---|
| `audio-object-12m-v1` | `r2_object`, `supabase_object` | `last_use + 12 months` |
| `voice-measurement-12m-v1` | `database_row` (the `voice_confidence` stamp) | `source_audio_retention` |
| `transcript-until-erasure-v1` | `transcript` | `account_deletion` |
| `derived-content-until-erasure-v1` | `derived_feedback` | `account_deletion` |
| `practice-attempt-30d-v1` | `database_row`, `r2_object` (practice) | `practice_closed + 30 days` |
| `orphan-object-24h-v1` | `r2_object`, `supabase_object` (unreferenced) | `upload + 24 hours` |
| `technical-log-90d-v1` | `cache` | `created + 90 days` |
| `provider-operation-with-parent-v1` | `provider_operation` | `parent_recording_retention` |
| `coach-packet-with-parent-v1` | `coach_packet` | `parent_recording_retention`, or immediately on withdrawal of coach consent |
| `processing-queue-with-parent-v1` | `processing_queue` | `parent_recording_retention` |
| `authorization-evidence-v1` | `database_row` (append-only evidence) | `accountability_need_ends` |

**`dataset_lineage` and `model_lineage` get no rule.** No Phase-2 processing is
authorised, so neither should ever appear as a purge target. If one does, that
is a bug and the fail-closed path is the correct outcome.

**`unknown` gets no rule, deliberately.** An unmatched target must reach
`review_required` and wait for a person. A catch-all rule here would silently
convert "we do not know what this is" into "we have handled it", which is the
exact failure the boundary was built to prevent.

## 3. Two implementation notes for the seeding migration

**Voice measurements are a field-level redaction, not a row delete.** The
`voice_confidence` stamp lives in the `metrics` JSONB on snippet rows that also
carry transcript text — and transcripts live until account deletion. So at
12 months the key must be stripped from the blob while the row survives.
`data_purge_targets.target_kind` has no natural value for this;
`database_row` with the JSONB path in `target_ref` is the closest fit. Flag the
approach before building it.

**Destruction must be evidenced, not assumed.** Each destruction writes a
`data_purge_events` row with an `evidence_sha256`. BIPA §15(a) asks for
guidelines you follow, and an audit trail is what shows you followed them.

## 4. Provider-held copies

Audio sent to OpenAI for transcription is covered by the same schedule, and
deletion at the provider is recorded as a `processing_provider_operations`
event.

**Open:** OpenAI's own retention window for transcription calls, and whether
those calls qualify for zero data retention. Until answered, §1 describes what
*we* hold and cannot describe what the provider holds. **This document must not
be signed until that answer is in it** — a published destruction schedule that
is silent about a copy held elsewhere is worse than no schedule.

## 5. Signature

    Name:      ______________________________
    Firm:      ______________________________
    Date:      ______________________________
