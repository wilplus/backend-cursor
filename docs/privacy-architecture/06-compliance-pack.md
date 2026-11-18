# Compliance pack — drafts

> **Drafts for counsel and for the client. Not legal advice. Not in force. Not a signed record.**
> Do not file these over `docs/legal/ROPA-ART30.md` or the signed privacy text. Those describe the public coaching product, where Artur Willoński is the controller. This pack describes the separate deployment in [03-target-architecture.md](03-target-architecture.md), where the client organisation is the controller.
> Square brackets are facts the client has to supply. Nothing in brackets was invented.

The technical design can pass an engineering audit and still be unlawful to switch on. This pack is the minimum paper that has to exist, filled in, before any real recording is uploaded.

## 1. Roles

| Party | Role | When |
|---|---|---|
| [Client legal name, registration, address, EU establishment] | Controller | Always, for its employees' and guests' conversations |
| The people in the recordings | Data subjects | Always |
| Artur Willoński, operating as WillpowerLab, Poland | Processor | Only in mode B (he operates the host), or in mode A if a support contract lets him see content |
| Hetzner Online GmbH | Sub-processor | Only in mode B |
| Everyone else in the public product's vendor register (OpenAI, Supabase Cloud, Railway, Vercel, Cloudflare, Resend, Sentry, Stripe, Meta, ElevenLabs) | Not a processor of this content | They are not in the deployment. If a later change adds one, this pack is wrong and processing stops. |

Mode A with no vendor access has an empty processor list. Write that down. An empty list that is a lie (because someone has SSH) is worse than a short list.

The supervisory authority for a controller established in Poland is the President of the Personal Data Protection Office (UODO). If the client's main establishment is in another EEA state, that state's authority leads. Do not assume Poland because the software author lives there.

## 2. Record of processing — one activity

Article 30. One activity, so it stays fillable. Split it if the client later uses the same box for a second purpose.

| Field | Draft |
|---|---|
| Name | Pattern spotting on conversations the organisation uploads |
| Controller | [name, contact, representative if Art. 27 applies — it should not, if they are established in the EU] |
| DPO | [name, or "no DPO, assessment dated …"] Article 37 is a judgement. Workplace monitoring of many employees often tips into "regular and systematic monitoring". Counsel decides. If they decide no DPO, the assessment is a page of its own. |
| Purposes | To find recurring themes in the organisation's own meetings and conversations, and to show a person their own transcript. Not to score a person. Not to identify a person by their voice. Not to train a model. |
| Categories of data subjects | [Employees / contractors / customers on the call]. No children. If a recording might include a child, the upload is refused until counsel has written a basis. The software does not try to detect children. |
| Categories of data | Voice recording; transcript; redacted transcript; meeting metadata the uploader typed (title, date, team); account identity from the client's IdP (name, email, role); technical logs (IP, for 14 days). No voiceprint. No special-category data on purpose. A recording may contain some anyway, because people say things; the redaction step is the mitigation, not a guarantee, and the DPIA says so. |
| Recipients | The data subject (their own transcript). [Named roles inside the client, e.g. a designated reviewer]. The processor and sub-processor in mode B. No one else. Aggregates with a cell of at least five may be shown more widely inside the organisation, and the DPIA records why those are not personal data. |
| Transfers to a third country | None intended. The host, the replicas, the backups and the keys are in the EEA. No model API. If a transfer appears, it is an incident, not a chapter V mechanism. |
| Retention | Content: until the data subject or the controller deletes it, and in any case no longer than [N months] from upload. Deletion destroys the key the same day and deletes the live ciphertext the same day. Backup media of ciphertext expires on the schedule in the deletion policy below. Aggregates that do not single a person out: [N months], recomputed, cells under five never stored. Edge IP logs: 14 days. Accounting documents, if any, live in a different system and do not contain transcripts. |
| Security | The technical and organisational measures in section 7. |

A processor in mode B keeps its own Article 30(2) record: the controller's name, the categories, the transfers (none), and a general description of the measures.

## 3. DPIA outline

Article 35. This processing needs one. It is systematic, it uses new technology on conversations, and in the employment context it is hard to argue it is not high risk. The controller writes it. The processor helps with the technical sections. A DPIA that the vendor writes and the client rubber-stamps is the finding.

Suggested headings, and the honest content this design can support:

1. **Description.** Upload of meetings the participants know about. Not ambient microphones. If the client wanted ambient microphones, stop and rewrite. Polish Labour Code art. 22² covers images, art. 22³ covers work email. Neither is a basis for audio. The basis has to be written here, or the DPIA's conclusion is "do not proceed".
2. **Necessity.** Why the pattern cannot be spotted from notes people already type. If it can, the audio fails data minimisation and the DPIA should say so.
3. **Risks to the people.** A name surviving redaction. A small team being singled out by a bad aggregate. A deleted recording readable from a backup. A support engineer reading a meeting. A voice being used later as a biometric. Loss of the only copy of a key, which is a loss of availability, not of confidentiality.
4. **Measures, each tied to a risk.** Per-person keys outside the backup. Ledger replay. Presidio fail-closed, Polish and English, checksums for PESEL, NIP, REGON, phone, IBAN. Cell size of five. No embeddings. No third-party model. Egress denied. No standing vendor access in mode A. MFA. The seven-day undo of the public product is not used.
5. **Residual risk the client accepts.** Nickname missed by the recogniser, inside a sentence that looked clean. Ciphertext on backup disks until the disk expires, unreadable without a key that was not backed up. SSD remnant of a key on a LUKS volume. Site loss destroying living keys as well as the server. These are the accepted mediums from audit round 3.
6. **Consultation.** Article 35(9), the data subjects or their representatives, where appropriate. In a workplace that often means the trade union or the employee representatives, and it matches the spirit of the Labour Code's consultation rules even where those articles do not apply directly. Counsel says whether Article 36 prior consultation with UODO is required. The software team does not decide that.
7. **Decision.** Proceed / proceed with the residuals / do not proceed. Named owner, date, review date.

## 4. DPA and sub-processors

Article 28. Mode A with no access needs no DPA with WillpowerLab; a software licence is enough, and the licence should say the vendor does not process content. Mode B needs a DPA before any upload. Minimum clauses the draft has to contain, in the Commission's language rather than a paraphrase invented here:

- Subject matter: hosting the deployment and operating it for the term. Duration: the contract. Nature and purpose: storage, transcription, redaction, pattern spotting, deletion, on the client's instructions. Types of data and categories of people: as the ROPA.
- Process only on documented instructions, including for transfers. The standing instruction is the runbook. A verbal "can you check this meeting" is not an instruction; it is a breach of the design.
- Confidentiality of the people who operate the host.
- The measures in section 7.
- Sub-processors: Hetzner only, named with the site (Germany or Finland). A new sub-processor is a change the client can refuse. There is no general authorisation for "whatever the stack needs".
- Assistance with data-subject requests. Deletion is the product: the controller's admin action, or the person's own action, runs the key destruction the same day. The processor does not insert a queue.
- Assistance with Articles 32 to 36. The incident timings in section 6.
- Deletion or return at the end of the contract: destroy the OpenBao unseal shares' copies the processor held (in mode B the processor should hold none), delete the volumes, and confirm in writing. Ciphertext without keys is then the residual already accepted in the DPIA, until the host's disk is wiped. Ask Hetzner for the wipe confirmation rather than assuming it.
- Audits: the client, or an auditor they mandate, may review the host on an agreed notice, and the yearly pen-test report is shared.
- The processor tells the controller immediately if an instruction looks unlawful. "Turn on OpenAI for a week" is the example to put in the training of operators, because it will be suggested.

No standard contractual clauses are needed while everyone and every disk stays in the EEA. Do not sign SCCs "just in case" with a vendor who is not in the path; it implies a transfer that should not exist.

## 5. Retention and deletion policy

For the client's notice to its people, and for the operator's runbook.

**What a person can do.** They can delete their recordings, transcripts, and derived analysis at any time, from the product, without a waiting period and without a ticket. The same day: the live files and rows are deleted, and the key that encrypted them is destroyed. A backup of the database or the file store cannot be read after that, because the key was never in the backup and the key store is not snapshotted.

**What the organisation can do.** An administrator the controller named can delete a person or a meeting on the same path.

**What is left, on purpose.**

| Thing left | Why | How long |
|---|---|---|
| Ciphertext on backup disks | Ransomware recovery of people who have not asked to be deleted. Useless for a person whose key is gone. | [7 days, unless the client writes a different number] |
| The erasure ledger line | To stop a restore bringing the key back, and to show the deletion happened | Life of the system |
| An aggregate that does not single anyone out | Not personal data if the cell-size rule held | [N months] |
| IP address in the edge log | Security of the service | 14 days, and deleted from the live log on request |
| A legal hold | Only when the controller's counsel has written one, with an owner and an end date | Until that date, then the key is destroyed |

**What is not left.** A copy at OpenAI, a copy at a transcription API, a copy in an error tracker, a copy in an email, a copy in the browser's database, a public link, a model fine-tuned on the meeting.

**How someone is told.** The notice says the deletion is immediate for live systems, that encrypted backup media expires on the schedule above, and that the key is not on that media. It does not say "within one month". That sentence belongs to the public product and is the wrong promise here.

**Restore.** A restore is not served until the erasure ledger has been replayed and every listed key is absent. This is rehearsed before go-live and once a year, on fake data.

## 6. Incident response outline

One page the on-call can follow. Names to be filled by the client.

1. **Detect.** Falco alert, a boot refusal, a ledger replay that found a key still present, a person reporting a transcript they should not see, a vendor saying the host was imaged.
2. **Contain.** Disconnect egress (it should already be denied; confirm it). Revoke the suspected Keycloak session. Do not snapshot the key volume as part of forensics if the snapshot would leave the site; if a forensic copy is required, it stays on an encrypted disk in the same room and is destroyed at the end, and the DPIA's key-backup ban is the reason to think twice.
3. **Decide if personal data left the EEA or was read by someone who should not have read it.** A Falco alert for an outbound socket is treated as a yes until shown otherwise.
4. **Tell the controller** (mode B) without undue delay. The DPA target is 24 hours from the processor knowing. The content of the notice: what happened, what categories, how many people as far as known, what was done. No transcript in the notice.
5. **Controller decides on Article 33.** 72 hours to the supervisory authority from becoming aware, where the risk to people is not unlikely. Article 34 to the people when the risk is high. Counsel makes the call. The engineering team provides the facts and does not send the notice alone.
6. **Fix and record.** The record is kept, without the content of the meetings. A deletion that was in doubt is re-run (ledger replay is safe to repeat).
7. **Review.** What the alert missed. Whether the egress rule was still on. Whether anyone added a SaaS logger during the incident, which is a second incident if they did.

## 7. Technical and organisational measures

Article 32, written so they can be pasted into the DPA's annex. Each line is something an auditor can sample.

| Measure | What "done" looks like |
|---|---|
| Encryption in transit | TLS to the browser. Private services are not on a public interface. |
| Encryption at rest | LUKS on volumes. AES-256-GCM per person for audio and transcripts. Keys in OpenBao, not in the database. |
| Key destruction | Hard-delete on erasure. No export policy. No snapshot of OpenBao. Ledger replay before serving. Yearly rehearsal. |
| Minimisation before analysis | Presidio, Polish and English, checksum recognisers, fail-closed. The model process receives only the redacted type. |
| Anonymity is not claimed for transcripts | ROPA and the notice say pseudonymised. Aggregates exist only for cells of five or more. |
| Access control | Keycloak, MFA, roles named by the controller. No shared admin password. Service credential in OpenBao. PostgREST not reachable from outside. |
| No multi-tenant database | One database, one MinIO, one OpenBao mount, for this client. The public product is a different host. |
| Network | Inbound 443 only. Outbound denied. Weights baked into images. |
| Logging | Security events without content. 14 days for IPs. A test fails the build if a transcript appears in a log line. No Sentry, no third-party log drain. |
| Runtime | Falco and auditd, alerts reviewed. Coraza on the edge. Unprivileged containers. Core dumps off. |
| Deletion of live data | Same day as the request, using the purge graph plus key destruction. No seven-day window on this deployment. |
| Backups | Ciphertext only. Retention written down. Restore rehearsed. |
| Suppliers | Mode A: none for content. Mode B: Hetzner, named site, DPA, no snapshot feature enabled. |
| Change control | A new outbound host, a new processor, or a new model API requires a written change and a stop if it contradicts the boot list. |
| People | Operators are authorised, and in mode B they are bound by the DPA's confidentiality term. No production content in a chat tool, a ticket, or a laptop. |
| Vulnerability handling | Dependency review on each image build. OS patches on a schedule. A yearly independent pen test is the paid escalation the executive summary prices; until it has happened, do not tell the client the control is "pen-tested". |
| Resilience | Three OpenBao nodes. Site loss is an accepted residual, written in the DPIA, because a site-level key backup would undo erasure. |
| Privacy by default | The enterprise profile is the only way this deployment boots, and it boots denied. Training, guest access, public buckets, browser model sockets, and email of transcripts are off. |

## 8. Sub-processor list, ready to attach

**Mode A, no vendor access**

| Sub-processor | Processing | Location | Data |
|---|---|---|---|
| None | | | |

**Mode B**

| Sub-processor | Processing | Location | Data |
|---|---|---|---|
| Hetzner Online GmbH | Dedicated server, disk, network | [Falkenstein / Helsinki / other EEA site, as ordered] | Ciphertext on disk, and the encrypted key volume. Hetzner does not receive a key and does not receive a snapshot, by contract and by configuration. |

If the list grows, the design has been abandoned and round 3's pass does not apply.
