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

**There is no company, and for this configuration none is needed.** The live
Privacy Policy (v1.2) states that WillpowerLab operates as *działalność
nieewidencjonowana* — unregistered business activity below the Polish revenue
threshold. Counsel should confirm the following reasoning rather than assume it.

**No entity is required for the compliance this document approves.** GDPR does
not require a legal person. Article 4(7) makes a natural person a controller on
the same terms, the AI Act's provider obligations attach to whoever places the
system on the market, and every vendor DPA in §2 is executable by an individual.
The pack names Artur Willoński throughout because that is genuinely who the
controller is, not as a placeholder for a company.

**Two things a company would buy, neither of which is compliance:**

1. **The ability to take real money.** The unregistered-activity threshold is a
   monthly revenue cap tied to the minimum wage. Below it, revenue is lawful
   without registration; above it, registration is obligatory within days.
2. **A liability shield.** A natural person carries the regulatory and civil
   exposure personally, with no corporate veil.

**Founder decision, 2026-09-17, AS CORRECTED 2026-09-18: freemium, Poland and
intended EU/EEA, no entity for now.**

> The paragraph that stood here read *"free service, Poland only, no entity"*
> and reasoned from it: *"There is no payment, so the threshold is not
> approached. There is no US exposure."* **Both halves of that premise were
> withdrawn on 2026-09-18** and the reasoning built on them went with it. It is
> replaced rather than deleted because a lawyer reading §8 would otherwise be
> signing over a scoping paragraph this pack's own cover note has retracted.

**Payment.** The model is freemium. `services/token_prices.py:51-57` defines
four sold tiers — free at 12,000 tokens a month, then USD 12, 39 and 89 —
and the checkout surfaces are written and gated on `STRIPE_SECRET_KEY`.
**Zero charges have ever been taken** (verified in Stripe, 2026-09-17). So the
unregistered-activity threshold is not approached *yet*, but it is approached by
design rather than avoided by design, and the first paid subscription starts the
clock. The ⚠️ note below treats condition 1 as a known future event for exactly
this reason.

**Territory.** The service is offered in Poland and is **intended for the
EU/EEA**. `allowed_countries` is not settled: it now waits on the per-country
Art 9(4) conditions counsel is asked for at cover-note ask 5, because Member
States may impose further conditions on processing biometric data — this
product's exact category.

**The US remains parked**, and that part of the original reasoning survives:
with no entity, Illinois BIPA's private right of action would land on a natural
person, so the uncapped personal exposure that made a liability shield urgent is
avoided only for as long as the US stays closed. Document 05 is written and
unsent.

**This approval is therefore scoped to that corrected configuration**, and §7
condition 1 is doing more work than before. Registration must be revisited
*before*, not after, any of:

- **taking the first payment** — the capability exists; the transaction history
  is empty, and those are different facts;
- serving users outside the EU/EEA;
- adding a country to `allowed_countries` before its Art 9(4) position is known;
- processing volume growing to a scale where Article 37 might require a DPO.

> **⚠️ 2026-09-17 — the first condition is now a KNOWN FUTURE EVENT, not a hypothetical.**
>
> The founder has confirmed the model is **freemium**: free is generous, and
> continued use ultimately requires payment. Payment is therefore planned, and
> the code is already written — four Stripe-backed surfaces exist, each gated
> on `STRIPE_SECRET_KEY`. That key was present in production until 2026-09-18,
> so the trigger was arguably met before anyone noticed; zero charges have ever
> been taken (verified in Stripe, 2026-09-17), so nothing was processed under
> it.
>
> **The sequencing consequence, stated because it gets more expensive with
> time and not less.** Registering the policy as a natural person now and
> incorporating later costs **one forced re-acceptance per user held at that
> moment**: incorporation changes the controller identity, which changes the
> Privacy Policy, which changes its SHA-256, which makes every receipt stale.
> Twenty-six users is a cheap re-acceptance. Post-launch it is not.
>
> **No date is recommended here.** Whether to register as a natural person now
> or incorporate first is a founder decision with tax, liability and cost
> consequences that sit outside engineering. What engineering can say is that
> the cost of the choice scales with the user count at the moment it is made.

Each of those changes the controller or the exposure, and the first two change
the controller identity — which changes the Privacy Policy, which changes its
SHA-256, which makes every existing receipt stale and asks every user to accept
again. The cheapest moment to incorporate is before the first policy is
registered. The second cheapest is never-and-stay-free. Anything between those
two costs a re-acceptance of every user.

**Processors and sub-processors, as implemented:**

> **Stripe is NOT in this table, and that is the correction (2026-09-18).**
> It was added here earlier today as a sub-processor. That was wrong, and
> `docs/VENDOR_DPA_REGISTER.md` already had it right: for payments Stripe is an
> **independent controller**, not our processor. It decides for itself how it
> uses payment data — fraud prevention, its own regulatory obligations — under
> its own terms, so there is no Article 28 processor relationship to paper and
> no DPA of ours to hold.
>
> What that changes: Stripe is a **recipient** to be disclosed, not a processor
> to be contracted. The Privacy Policy now names it under Payments and says
> plainly that it is not our processor. **No customer has been charged, so no
> payment data has yet been processed** — the disclosure is in place before the
> first transaction rather than after it.

| Party | Receives | Where in code |
|---|---|---|
| OpenAI | Raw audio bytes (transcription); bounded transcript and prompt context (Ideal Text, Feedback) | `services/authorized_provider.py` — the only provider name in the adapter |
| Cloudflare R2 | The stored audio object | `services/audio_storage.py`, `storage_provider = 'r2'` |
| Supabase | The database; audio storage in the dev fallback path | `storage_provider = 'supabase'` |
| Railway | Application hosting (web, worker, cron) | `bin/railway-web.sh` |
| Resend | Transactional email | `services/email_service.py` |
| Sentry | Error telemetry (EU region) | client + server instrumentation |
| Vercel | Frontend hosting | `frontend-cursor` deployment |

| Stripe | Independent controller; no DPA to sign | — |

**Corrected 2026-09-17: there are eight vendors, not five.** Sentry, Vercel and
Stripe were already named to users in the published Privacy Policy with no
paperwork behind them. Checking `requirements.txt`, `config.py` and `services/`
against the live policy is what surfaced them. Cloudflare is also not a CDN
footnote — it is where the **voice recordings themselves** are stored.

**Where the data actually is:** transcripts, accounts and feedback in Supabase
(Ireland, `eu-west-1`); voice recordings in Cloudflare R2 (Eastern Europe);
error telemetry in Sentry (EU); transcription and generation at OpenAI (United
States, SCCs, 30-day retention).

**DPA status:** Sentry signed (v5.1.0, with DPF certificate); Supabase,
Cloudflare and Vercel in force by reference through accepted terms; Stripe needs
none; OpenAI, Railway and Resend requested. Four of the five originally listed
as "requests" needed no signature at all — the work was establishing which, and
saving dated evidence.

`services/authorized_provider.py` is a typed adapter and the protected recording
modules are test-enforced not to import a provider SDK directly
(`tests/test_phase1_compliance_contract.py::test_protected_user_data_modules_do_not_import_provider_client`).
Every provider call takes a short-lived database permit naming the operation and
a minimum data manifest (`processing_provider_permits`), and records a terminal
outcome event without storing raw user content in the metadata.

**Counsel must confirm separately:** a signed DPA with each processor above, the
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
is correct for **Poland, the European Union and the EEA** — the jurisdictions
this approval is scoped to (§2), and the same set the
`mlc2-bundled-consent-v1` precedent recorded as `["PL", "EU", "EEA"]`.

The United States is expressly **outside** this signature. Document 05 covers it
and is parked until incorporation.

    Name:      ______________________________
    Firm:      ______________________________
    Date:      ______________________________
    Reference: ______________________________
