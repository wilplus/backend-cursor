# Enterprise privacy architecture — executive summary

> **Proposal. Not in force.** Not a founder decision, and not a change to the product rules in `CLAUDE.md`, the decisions log, or the signed legal pack. This folder is a design study for one organisation that wants its own conversations processed under a strict GDPR and security audit. Nothing here is built. Shipping any of it, including any new words a person would see, needs the founder's OK.

Reviewed against backend `main` at `706bbf96` and frontend `main` at `e9a43ba` (16 November 2026).

## Verdict

**The system as it runs today would fail the audit.** Audio and transcripts go to OpenAI, deletion waits seven days and then leaves copies in provider logs and backups, nothing is anonymised before analysis, and several processors sit outside the EU or outside the client's control.

**The target design in [03-target-architecture.md](03-target-architecture.md) passes the technical audit.** After three rounds ([04-audit-rounds.md](04-audit-rounds.md)) no critical or high technical gap remains. Medium gaps have a stated mitigation. The design is not a claim that the engagement is finished: a strict auditor still withholds a pass on the *processing* until the organisational acts in the cost table below are done. Those are money and legal work, not code. Client content must not be loaded until they are done.

The pass is for a **separate single-tenant deployment**. It does not redesign the public WillpowerLab loop, and it does not weaken that loop's deletion, consent, or coach rules.

## The architecture in plain words

Give the client their own machine in the EU, or a single dedicated EU server that nobody else shares. The browser talks only to that machine. Audio is encrypted the moment it lands, transcribed on that machine with faster-whisper, and never sent to OpenAI, Mistral, ElevenLabs, or any other model host.

Before any pattern-spotting model sees text, a local redaction service (Microsoft Presidio, with Polish and English models, plus recognisers for PESEL, NIP, REGON, phone numbers and IBANs) strips or replaces identifiers. If a sentence looks like it might still name someone, that sentence is dropped from analysis rather than sent through. The model is an open-weight model (Qwen2.5-14B-Instruct, Apache 2.0) served on the same machine. It is not trained on the client's text.

Each person has their own encryption key, kept in OpenBao and nowhere else. There is no backup of those keys. Deleting someone's data deletes the live rows and objects and destroys the key, in that order, at the time of the request. Database backups hold only ciphertext. A restore cannot bring a destroyed key back, because keys are not in the backup, and an erasure ledger outside the backup is replayed before the service starts. Three OpenBao nodes provide availability; snapshots of the key store are not taken.

What the pattern report is allowed to keep is an aggregate that cannot single a person out (a cell smaller than five is suppressed). Everything that can still be tied to a person stays encrypted with that person's key and dies with it. Pseudonymised text is still personal data and is treated as such. This design does not call it anonymous.

The public product's processors (Supabase Cloud, Railway, Vercel, Cloudflare R2, Sentry, Resend, Stripe, Meta WhatsApp, Google, LinkedIn, Apple) are not in this deployment. Identity is the client's own Keycloak, or Keycloak on the same host. The network default-denies outbound traffic once the images are built.

## Cost

### Zero-cost path

Software licences: **€0**. Postgres, MinIO, OpenBao (MPL-2.0), Keycloak, Caddy, Coraza, Falco, faster-whisper, vLLM, Presidio, and Qwen2.5-14B-Instruct are free to run. Presidio's Polish spaCy model is GPL-3.0 and runs in its own container so it is not linked into the application.

Hosting: **€0** if the client already has a machine in the EU that can hold the data. A modern CPU with 64 GB of RAM can transcribe and run a quantised 14B model overnight, which is enough for pattern spotting that is not interactive. If no machine exists, a Hetzner dedicated server in Germany or Finland in the AX42 class is about **€57 per month** excluding VAT (Hetzner price list effective 1 April 2026). Electricity on the client's own hardware is theirs.

This path is what the audit pass assumes. It does not include a GPU, a commercial RASP product, Supabase Team, or OpenAI Zero Data Retention. Those were considered and rejected in [02-research.md](02-research.md).

### Paid escalations

Only items a strict auditor can still demand, or that buy latency rather than a control the free stack lacks.

| Item | Why the free path is not enough | Rough cost |
|---|---|---|
| Polish counsel reviews the DPA, the DPIA, and the basis for recording workplace conversations | Software cannot supply a lawful basis. Workplace audio is not covered by Labour Code art. 22² (image only) or 22³ (email). The client, as employer and controller, needs its own notice and basis before anyone is recorded. | €2,000–8,000 for the first pack |
| Independent penetration test, yearly | In-house scanners (ZAP, nuclei, pip-audit) are necessary and are in the plan. A strict auditor asks for a report from someone who is not the builder. | €5,000–15,000 a year |
| ISO/IEC 27001 certificate, only if the client requires a certificate rather than the controls | The controls in [06-compliance-pack.md](06-compliance-pack.md) can be operated without a certificate. The certificate is the auditor's paperwork, plus a certification body. SOC 2 is the US equivalent; buy ISO first for an EU client, not both, unless they ask. | €8,000–25,000 in the first year, then annual surveillance |
| GPU server, only if overnight batch is too slow | Not required for the audit. Hetzner's GEX44 was listed at €212.30 per month excluding VAT from 1 April 2026 and was not available to order when checked. A successor in the same class (about 20 GB of Nvidia memory, Finland or Germany) has been reviewed around €180–260 per month excluding VAT. Confirm the live price. | about €180–260 per month |
| Hardware security module, only if the auditor insists the unseal key live in hardware | OpenBao with no key snapshots, Shamir unseal split between two client officers, and a replayed erasure ledger meets the design. A YubiHSM 2 is the cheap way to go further. | about €500–700 once |
| Named commercial RASP product | Not recommended. Falco plus Coraza is the control. Buy a named product only if the client's checklist literally requires one. | often €15,000 or more a year |

Supabase Team ($599 per month) is not on this list. It adds a company in the United States as a processor, keeps daily backups for 14 days, and sells point-in-time recovery that keeps deleted rows for 7, 14, or 28 days. That is the problem the client already named. Paying for it does not fix erasure.

## Top risks

1. **The lawful basis is the client's, and it is not obvious.** Recording employees' meetings for pattern spotting can be monitoring. The Labour Code's camera and email articles do not authorise audio. If the client cannot show a basis, a notice, and a DPIA, the architecture must not be switched on. This is the highest non-technical risk.
2. **Crypto-shredding is not, by itself, a legal eraser.** The EDPB has not blessed "we deleted the key" as Article 17 erasure, and ciphertext can remain personal data. The design therefore deletes the live plaintext as well, keeps keys out of every backup, and bounds key resurrection with an erasure ledger. Counsel should still say this in the DPIA in their own words.
3. **Redaction will miss some names.** Polish diminutives, nicknames, and unusual spellings get through NER. The design fails closed (the unsure sentence never reaches the model). The residual is a worse pattern report, not a silent leak, and it belongs in the DPIA.
4. **A restored disk image can still hold a deleted key in SSD free space.** Cryptographic erase is the method NIST SP 800-88 gives for that media. The design adds full-disk encryption and refuses key-store snapshots. The forensic remnant is an accepted low risk, not a second backup policy.
5. **The public product and this deployment must not share a database, a bucket, or a model host.** One service-role key across tenants, or one OpenAI key "just for transcription", puts the client back into the current failure. The enterprise profile refuses to boot if those are configured.
