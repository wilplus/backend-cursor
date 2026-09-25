# Retention and destruction schedule — WillpowerLab Phase-1

    artifact_kind:       retention_schedule
    version:             1.0
    approving_authority: Artur Willoński (founder and controller)
    approved_at:         2026-09-18T00:00:00Z
    object_key:          phase1-2026.1/legal/retention-schedule-v1.0.pdf
    sha256:              [[computed from the signed PDF at registration time]]
    control_version:     phase1-retention-schedule-v1

**STATUS: APPROVED BY THE CONTROLLER 2026-09-18, SIGNED AS A PDF 19 September
2026. Not yet uploaded, not yet seeded.** The periods in §1 were settled on
2026-09-17 and are unchanged. §3 was corrected on 2026-09-19 and is the only
substantive change since approval.

**Why the founder is the right authority for THIS document and not for 02.**
A retention schedule is an operational decision about how long the controller
keeps its own data. The controller is Artur Willoński, so he is the person whose
decision it records — there is no one else it could be. The periods themselves
were settled on 2026-09-17 and are unchanged.

Contrast `02-power-score-classification` §9. That document records a
determination about how the AI Act applies to the code — a qualified legal
judgement, and not the same kind of decision as this one. **On 2026-09-19 the
founder signed it anyway**, as an interim determination under an explicit
written condition: counsel must confirm it before any person other than the
founder records.

That is a recorded departure, not the `mlc2-bundled-consent-v1.json` pattern
the pack README exists to stop. There, the founder was recorded as *"recording
the approved counsel determination"* when no counsel determination existed —
the defect was that the artifact misstated **who had decided**. Here 02 names
the founder as the decider in its `approving_authority` field, in its STATUS
line and in §9, and names what is missing. The distinction between the two
documents is still not seniority, it is subject matter; 02 simply says on its
face that the wrong person signed it, and what has to happen next.

**What still has to happen before registration.** The signed PDF exists as of
2026-09-19. It must be uploaded to the `object_key` above and its `sha256`
computed from the stored bytes, under the canonicalisation rule recorded in
`04-policy-registration`. Until that is done the database has nothing to point
at: a name in a markdown file is a recorded decision, not the artifact.

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
against `PurgeDependency.retention_category` (`services/data_purge.py:232`),
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
justified by Polish accounting law. A later draft deleted it on the premise
that the service is free and takes no payment. **Both were wrong, in opposite
directions.** Corrected 2026-09-19: the model is freemium — Terms §2 sells
three paid plans in USD — so accounting obligations do exist, but they do not
reach the rows this category actually holds.

The two have to be split:

- **Invoices and billing records.** Payment is taken by Stripe, which acts as a
  controller in its own right rather than as our processor, so the card data
  and the primary payment records sit with Stripe under its own terms. Whatever
  invoice records WillpowerLab itself holds are accounting records and carry a
  statutory period this schedule does not set — in Poland, five years from the
  end of the accounting year (`ustawa o rachunkowości`, art. 74). **Counsel
  should confirm the period, and whether a seller operating as
  *działalność nieewidencjonowana* falls inside that regime at all.** No rule
  in §2 covers these today because no such table exists in our database.
- **`token_ledger` and `llm_usage`**, the two dependencies actually in this
  category, are **not** invoices. They are internal records of model usage and
  cost, per user, written for free and paid users alike. No accounting
  obligation reaches them. They are marked `retain`, so today they survive an
  erasure request.

**Retaining per-user usage ledgers after someone has asked to be erased is the
weakest position in this schedule.** For these two tables there is no
accounting obligation to point at, and "we want our own cost history" is a thin
answer to Article 17. Three options, for counsel rather than engineering:

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

By signing, the approving authority records the retention periods in §1 as the
controller's own operational decision, and acknowledges that §3's
`financial-evidence-v1` disposition is **not** settled by this signature: it
carries option 2's bounded period as a conservative placeholder until counsel
answers, and §3b's two proposed categories still require confirmation.

    Name:      Artur Willoński
    Firm:      None — natural person, no company (działalność nieewidencjonowana)
    Date:      19 September 2026
    Reference: WILLAB-PHASE1-2026.1-RET-2026-09-19
