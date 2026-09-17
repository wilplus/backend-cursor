# Product legal approval — WillpowerLab Phase-1 recording and coaching service

    artifact_kind:       product_legal_approval
    version:             1.0
    approving_authority: [[FOUNDER: named person or firm — e.g. "Kancelaria X / J. Nowak"]]
    approved_at:         [[FOUNDER: ISO-8601 UTC timestamp of signature]]
    object_key:          [[FOUNDER: storage path of the signed PDF, e.g. legal/phase1-2026.1/product-legal-approval-v1.0.pdf]]
    sha256:              [[computed from the signed PDF at registration time]]
    metadata:            {"policy_version": "phase1-2026.1", "jurisdictions": ["PL", "EU", "EEA"]}

**STATUS: DRAFT — NOT APPROVED, NOT SIGNED.** Written by engineering from the
source code. It is a description of what the system does and a proposed
lawful-basis mapping for counsel to accept, amend or reject. It is not legal
advice and it does not become an approval by being committed to the repository.

---

## 1. What this document approves

That WillpowerLab may, for an identified adult user who has explicitly accepted
the policy `phase1-2026.1`:

- capture and durably store an audio recording of that user's voice;
- transmit those audio bytes to a third-party AI provider for transcription;
- transmit bounded transcript text to a third-party AI provider for generation
  of the Ideal Text document and of Feedback;
- compute acoustic measurements locally over the recording;
- retain the recording, the transcript, and everything derived from them;

and it names the lawful basis for each of those, separately.

It approves nothing else. It does not approve pooled datasets, model training,
evaluation, promotion, or any use of one user's material for another user's
benefit. Those are Phase-2 purposes, they are refused at the database boundary
(`PHASE2_PURPOSE_FORBIDDEN`), and this document must not be read as touching
them.

## 2. Controller and processors

**Controller:** Artur Willoński, a natural person resident in Poland, operating
under the name "WillpowerLab". Contact: `contact@willpowerlab.com`. No DPO
appointed; Article 37 does not require one at this scale, and this should be
revisited if processing volume grows materially.

**⚠️ There is no company.** The live Privacy Policy (v1.2) states that
WillpowerLab operates as *działalność nieewidencjonowana* — unregistered
business activity below the Polish revenue threshold. Two consequences that
counsel must address rather than note:

1. **Charging money almost certainly ends it.** The unregistered-activity
   threshold is a monthly revenue cap tied to the minimum wage, and exceeding it
   obliges registration within days. The founder has decided on a freemium
   model, so the first paid subscriptions make this live. Registration is a
   prerequisite to taking payment, not a follow-up to it.
2. **The controller is personally liable.** A natural person carries the
   regulatory and civil exposure himself, with no corporate veil — including the
   US exposure, where the founder has decided to serve Illinois and BIPA
   provides a private right of action with statutory damages per person.
   **Founder decision, 2026-09-17: a *spółka z o.o.* will be formed before the
   US launch.** Counsel should confirm that sequencing and flag anything that
   should move with it.

**Sequencing that follows, and it saves real work.** Registering a business
changes the controller identity, which changes the Privacy Policy, which changes
its SHA-256, which makes every existing receipt stale and forces every user to
accept again. So the order is:

1. Form the *sp. z o.o.* now, in parallel. Online formation (S24) plus KRS entry
   runs roughly one to two weeks — about the same as the outstanding engineering,
   so it is not the critical path unless it is left until last.
2. Complete the engineering and the legal review.
3. Register policy `phase1-2026.1` naming **the company**, and launch Poland.
4. Add the US once US counsel has signed off.

Doing step 3 before step 1 means doing it twice. The user-facing copy in this
pack currently names the natural person, because that is who the controller is
today; if the company exists before registration, that copy is updated once,
before the first hash is ever taken, and no user is ever asked twice.

**Merchant of record, decided 2026-09-17: Paddle.** Confirm the exact
contracting entity from the signed Paddle agreement — it can differ by region —
and record it here. Paddle contracts from the UK, which holds a UK adequacy
decision, so the transfer analysis is straightforward; the characterisation
question in §2 is unaffected and still needs counsel.

Every user-facing document in this pack names the natural person, because that
is who the controller is today. Each carries a marker requiring update on
registration. Registration changes the controller identity, which changes the
Privacy Policy, which changes its hash, which forces every user to re-accept —
so it is cheaper to register before the first policy is registered than after.

**Processors and sub-processors, as implemented:**

| Party | Receives | Where in code |
|---|---|---|
| OpenAI | Raw audio bytes (transcription); bounded transcript and prompt context (Ideal Text, Feedback) | `services/authorized_provider.py` — the only provider name in the adapter |
| Cloudflare R2 | The stored audio object | `services/audio_storage.py`, `storage_provider = 'r2'` |
| Supabase | The database; audio storage in the dev fallback path | `storage_provider = 'supabase'` |
| Railway | Application hosting (web, worker, cron) | `bin/railway-web.sh` |
| [[FOUNDER: email provider]] | Transactional email | `services/email_service.py` |
| [[FOUNDER: merchant of record]] | Billing data for paid plans | not a processor — see below |

`services/authorized_provider.py` is a typed adapter and the protected recording
modules are test-enforced not to import a provider SDK directly
(`tests/test_phase1_compliance_contract.py::test_protected_user_data_modules_do_not_import_provider_client`).
Every provider call takes a short-lived database permit naming the operation and
a minimum data manifest (`processing_provider_permits`), and records a terminal
outcome event without storing raw user content in the metadata.

**The merchant of record is not a processor.** Paddle, Lemon Squeezy and their
equivalents contract with the user as seller of record, so for the purchase they
are an independent controller, not our supplier. That means an Article 28 DPA is
the wrong instrument: what is needed is a controller-to-controller arrangement,
and the Privacy Policy must point users at the seller's own policy for their
payment data. Counsel should confirm the characterisation and say what document
it needs, if any. Do not tick this off the DPA list by signing the wrong paper.

**Counsel must confirm separately:** a signed DPA with each *processor* above, the
transfer mechanism for OpenAI (US — SCCs and/or Data Privacy Framework
certification), and a transfer impact assessment. This document does not assert
that any of those are in place.

## 3. The operations, and the basis for each

The mapping below deliberately departs from the `mlc2-bundled-consent-v1.json`
precedent, which put every purpose on Article 6(1)(a) consent **and** made that
consent a condition of using the service. Article 7(4) GDPR makes consent that
is a condition of service presumptively not freely given, and the EDPB has
consistently treated bundled service-conditional consent as invalid. The result
is the worst case: an invalid consent and no fallback basis. Contract is both
more honest and more robust for the operations that genuinely *are* the service.

| # | Operation | Registry purpose | Proposed Art. 6 basis | Required for core service |
|---|---|---|---|---|
| 1 | Capture + durable storage of the recording | `recording_voice_processing` | 6(1)(b) contract | yes |
| 2 | Transmit audio to OpenAI for transcription | `transcription_feedback` | 6(1)(b) contract | yes |
| 3 | Transmit bounded transcript to OpenAI for Ideal Text generation | `transcription_feedback` | 6(1)(b) contract | yes |
| 4 | Transmit bounded transcript to OpenAI for Feedback generation | `transcription_feedback` | 6(1)(b) contract | yes |
| 5 | Local acoustic measurement + voice-confidence composite | `recording_voice_processing` | 6(1)(b) contract | yes |
| 6 | Retention of recording, transcript and derived documents | both of the above | 6(1)(b) contract; 6(1)(c) where a legal retention duty applies | yes |
| 7 | Security, abuse prevention, service integrity logging | — | 6(1)(f) legitimate interest | n/a |
| 8 | Asynchronous human coach review | `coach_review` | 6(1)(a) consent | **no — held out of v1** |
| 9 | Practice attempt capture and comparison | `personalized_exercise_recommendation` | 6(1)(b) contract | **no — held out of v1** |
| 10 | Individual learning profile | `individual_learning_profile` | 6(1)(b) contract | **no — held out of v1** |
| 11 | Pooled model improvement | `pooled_model_improvement` | **none — not authorised** | forbidden |

### Why 6(1)(b) and not consent, for 1-6

The user's request to WillpowerLab is: record me presenting, and give me back a
transcript, a presentation document and feedback. Processing the recording is
not an adjacent activity that the service could be delivered without — it *is*
the delivery. Operations 1-6 are therefore necessary for performance of the
contract the user asks for, within the narrow reading of 6(1)(b) the EDPB
applies in Guidelines 2/2019. Nothing in 1-6 is profiling for a separate
commercial purpose, and nothing in 1-6 is used for anyone but that user.

The corollary, which must hold or the basis fails: **if the user cannot use the
product without agreeing to something outside 1-6, the extra thing is bundled
and the whole structure is back to the Article 7(4) problem.** That is the
reason 8, 9 and 10 are held out of the v1 policy rather than marked optional
(see §6).

### Article 9 — special category data

The acoustic composite does not process biometric data "for the purpose of
uniquely identifying a natural person", so Article 9(1) is not engaged on that
limb (see document 02 §5). But a voice recording of a person speaking freely can
incidentally carry special-category content: a health condition audible in the
speech itself, or something the user simply says while presenting. Article 9 has
no contract exemption, so this cannot ride on 6(1)(b).

**Proposed treatment:** explicit consent under Article 9(2)(a) for incidental
special-category content, captured as a distinct element of the acceptance
screen rather than folded into the same sentence as the contract acknowledgement.
This carries forward the `9(2)(a)_when_special_category` treatment already
recorded in `mlc2-bundled-consent-v1.json`.

Counsel should confirm whether (a) this framing is right, or (b) the better
position is that the controller does not *intend* to process special categories,
does not infer them, and so Article 9 is not engaged at all — in which case the
acceptance screen should say so rather than ask for a consent it does not need.
The draft agreement copy takes position (a) because it is the safer of the two
and costs one sentence.

## 4. Data subject rights, as implemented

| Right | Mechanism | State |
|---|---|---|
| Access, export, rectification, restriction, objection | `data_rights_requests` (`request_kind IN ('access','export','correction','restriction','objection')`) | Table and workflow exist; each is a reviewed procedure, not a self-service button |
| Erasure | `data_purge_requests` → `data_purge_targets` → `data_purge_events` | Orchestrator inventories canonical SQL and exact storage targets and **stops at `review_required`** on mixed-purpose tables, unknown retention, coach copies, provider artifacts, caches, or model lineage |
| Withdrawal of consent | Ends the consent-based purposes only; does not end 6(1)(b) processing, which ends with the contract | Requires the optional-consent surface that does not yet exist |

**The erasure limitation is material and must be described honestly to users.**
`docs/PHASE1-PROCESSING-RUNBOOK.md` states it plainly: the fail-closed
`review_required` state "is not completed erasure". The draft Privacy Policy
therefore does not promise one-click deletion of everything. Counsel must decide
whether the current state is compatible with Article 17 response deadlines given
that a request halting at `review_required` still requires a human to finish it
within one month.

Append-only evidence rows (`processing_authorization_receipts`,
`processing_authorization_snapshots`, `phase1_processing_job_events`,
`data_purge_events`) are protected by
`reject_phase1_immutable_mutation()` and survive erasure by design, because they
are the proof that processing was authorised. Counsel should confirm the
Article 17(3)(e) / Article 5(1)(f) accountability argument for retaining them,
and that they are minimised — they hold identifiers and hashes, not content.

## 5. Age

The schema pins `minimum_age = 18` with a CHECK constraint that permits no other
value, and `age_18_attested` is a non-nullable, CHECK-true column. A user who
does not attest cannot produce a receipt and therefore cannot record. This is
self-declaration, not verification; counsel should confirm that is proportionate
for this service under Article 8 and the applicable national rules.

## 6. What is deliberately excluded from v1

`coach_review`, `individual_learning_profile` and
`personalized_exercise_recommendation` are all defensible purposes with sensible
bases. They are held out of the first policy for one mechanical reason:

`accept_phase1_processing_authorization_v1` writes receipt purpose rows only
`WHERE pp.required_for_core_service`. An optional purpose therefore appears in
the policy the user reads and leaves **no consent evidence in the receipt**. For
`coach_review`, whose proposed basis *is* consent, that is not a gap in the
paperwork — it is the absence of the lawful basis itself.

The alternative — marking them required — would make agreeing to coach review
and practice a condition of using the product, which is exactly the Article 7(4)
bundling this mapping exists to avoid.

So: v1 carries operations 1-7. A v1.1 adds 8, 9 and 10 at the same time as a
consent surface that can actually record them. Cost of this choice, stated
plainly: **under `enforce`, coach review and practice cannot run until v1.1.**
That is a real product cost and it is the founder's call, not counsel's.

## 7. Conditions on this approval

This approval, if given, is valid only while all of the following hold. Any one
of them breaking requires the determination to be revisited before processing
continues.

1. The product is offered to individual adults on their own account. It is not
   deployed into a workplace where an employer directs, monitors or receives its
   output, and not into an education institution. (Document 02 §7 — this
   condition is doing a great deal of work.)
2. `PLF1_PROCESSING_AUTHORIZATION_MODE=enforce` on every service, so no
   recording, retry or provider call bypasses the authorization path.
3. No Phase-2 purpose is registered, and `pooled_model_improvement` remains
   `phase = 'phase2'`.
4. The provider inventory in §2 is complete. A new provider receiving audio or
   transcript requires this document to be re-versioned before it is added.
5. `pooled_learning_eligible` remains false everywhere, as the CHECK constraints
   enforce.

## 8. Signature

By signing, the approving authority records that they have reviewed the
operations in §3 against the code paths cited, and that the lawful-basis mapping
is correct for [[FOUNDER: jurisdictions]].

    Name:      ______________________________
    Firm:      ______________________________
    Date:      ______________________________
    Reference: ______________________________
