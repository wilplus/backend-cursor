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
| Account records | until account deletion | user request or closure |
| Authorization evidence | while needed to show processing was lawful | — |

**Voice measurements are never outlived by their source.** They are deleted with
the audio they came from, and never persist after it. Keeping an analysis of a
recording you have deleted is the position hardest to defend — under GDPR
storage limitation and, more sharply, under BIPA §15(a)'s "when the purpose has
been satisfied".

## 2. Rules to seed

**Corrected 2026-09-17. The first draft of this section was wrong** and would
have failed silently. It listed nine `evidence_category` values — `r2_object`,
`transcript`, `cache`, `coach_packet` and so on. Those are
`data_purge_targets.target_kind` values. The column this table feeds is matched
against `PurgeDependency.retention_category` (`services/data_purge.py:231`),
whose vocabulary has five values and shares none of them. Seeding the original
table would have written twelve active rows resolving nothing, left all sixteen
retain-dependencies on `RETENTION_RULE_UNRESOLVED`, and — because
`resolve_targets` is all-or-nothing — deleted nothing for anyone, while the
table looked populated and the control version named a real document. Exactly
the paper-only claim this boundary exists to prevent. Found by engineering
before it shipped.

**The conceptual mistake underneath it:** not every category in §1 needs a
retention rule. §1 is the *published* schedule — what users are told about their
recordings and transcripts. Those are `delete` dispositions: the purge deletes
them and no rule is consulted. A retention rule is only needed where a
dependency is marked `retain`, meaning it deliberately survives an erasure
request. There are sixteen of those, in five categories, and they are all
accountability evidence rather than user content.

§1 and §2 therefore describe different things and that is correct. §1 is the
promise to users; §2 is the set of records that outlive the promise, and why.

| `rule_code` | `evidence_category` | `retention_until_rule` | What it covers |
|---|---|---|---|
| `authorization-evidence-v1` | `authorization_evidence` | `accountability_need_ends` | Acceptance receipts, authorization snapshots, legacy consent rows (4) |
| `deletion-evidence-v1` | `deletion_evidence` | `accountability_need_ends` | Audio object metadata and its deletion events, recording boundary, service blocks, owner identity and claim events (7) |
| `processor-evidence-v1` | `processor_evidence` | `accountability_need_ends` | Provider permits and terminal operation events (2) |
| `transparency-evidence-v1` | `transparency_evidence` | `accountability_need_ends` | AI-notice exposure records (1) |
| `financial-evidence-v1` | `financial_evidence` | **see §3** | `token_ledger`, `llm_usage` (2) |

Four of the five hold records whose entire purpose is to prove something
happened — that processing was authorised, that a deletion was performed, what
was sent to a provider, that the AI notice was shown. Retaining them past an
erasure request is the Article 17(3) / Article 5(2) accountability argument, and
they hold identifiers, timestamps and hashes rather than content.
`accountability_need_ends` is the right rule for all four.

## 3. The financial_evidence rule needs a decision, not a default

An earlier draft of this document carried a `billing-record-5y-v1` rule
justified by Polish accounting law. **That justification is gone** — the service
is free and takes no payment, so there are no accounting records.

But the category has not gone. Its two dependencies are `token_ledger` and
`llm_usage`: internal records of model usage and cost, per user, which exist
whether or not anyone pays. They are marked `retain`, so today they survive an
erasure request.

**For a free service, retaining per-user usage ledgers after someone has asked
to be erased is the weakest position in this schedule.** There is no accounting
obligation to point at, and "we want our own cost history" is a thin answer to
Article 17. Three options, for counsel rather than engineering:

1. **Detach rather than retain.** Strip the user reference and keep the usage
   row as an anonymous cost record. No longer personal data, so Article 17 stops
   applying. Cleanest answer if the rows are only needed in aggregate.
2. **Retain for a bounded period**, e.g. 12 months, aligned with audio, on a
   legitimate-interest basis for cost accounting and abuse investigation.
3. **Change the disposition to `delete`.** A code change in
   `services/data_purge_registry.py`, not a schedule change. Correct if nothing
   actually needs those rows after the user is gone.

Engineering's read is that option 1 is most likely right, but it is a code
change either way and should not be guessed at in a published schedule.
**Until this is decided, `financial-evidence-v1` should carry option 2's bounded
period as the conservative placeholder, marked unapproved.**

## 3b. Two categories this document originally missed

`deletion_evidence` and `transparency_evidence` had no rule at all in the first
draft, because that draft was written against the wrong column. Both cover
append-only evidence tables, so `accountability_need_ends` follows by analogy
with `authorization_evidence`. **The founder must confirm them** — they are
proposed, not approved, and they are marked as such in the seeding migration.

## 4. Provider-held copies

Audio sent to OpenAI for transcription is covered by the same schedule, and
deletion at the provider is recorded as a `processing_provider_operations`
event.

**Answered 2026-09-17: 30 days.** OpenAI retains API inputs and outputs for up
to 30 days for abuse monitoring and then deletes them. Zero data retention was
not in force on our organisation and had not been applied for, contrary to what
the published Privacy Policy asserted. Transfers are under SCCs.

So the provider-held copy is bounded at 30 days, which sits inside every period
in §1 and needs no separate rule. Privacy §7 and §9 now say this rather than
asserting a zero-retention arrangement that did not exist.

**⚠️ Separately, and more seriously:** the same review found that the OpenAI
organisation had *data sharing for model training* enabled, which the Privacy
Policy denied. That is not a retention question and it is not addressed by this
schedule — see the cover note, which leads with it.

## 5. Signature

    Name:      ______________________________
    Firm:      ______________________________
    Date:      ______________________________
