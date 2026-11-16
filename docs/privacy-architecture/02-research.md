# Research notes

> **Proposal. Not in force.** Sources read for this study on 16 November 2026. Where a page is a draft or a consultation text, it is marked as such. None of this is legal advice to the client or to WillpowerLab. Counsel reviews the pack in [06-compliance-pack.md](06-compliance-pack.md) before anyone relies on it.

The question behind the notes: what is the cheapest design that a strict auditor could accept for (1) erasure that still works when backups exist, (2) a real distinction between pseudonymisation and anonymisation, (3) transcription and pattern spotting with no third-party model, and (4) the operational controls an ISO 27001 or SOC 2 review expects, without buying those certificates on day one.

## 1. Pseudonymisation is not anonymisation

GDPR Recital 26: personal data that has been pseudonymised, and which can be attributed to a person by the use of additional information, is still information on an identifiable person. Anonymous information is information that does not relate to an identified or identifiable person, or that has been rendered anonymous so that the person is not or no longer identifiable. The test is "means reasonably likely to be used", including by another person.

Article 4(5) defines pseudonymisation as processing that stops data being attributed to a person without additional information, kept separately, and under technical and organisational measures that stop the attribution.

The EDPB's Guidelines 01/2025 on Pseudonymisation were adopted on 16 January 2025 and then put to consultation.

- Text: <https://www.edpb.europa.eu/system/files/2025-01/edpb_guidelines_202501_pseudonymisation_en.pdf>
- News of the adoption: <https://www.edpb.europa.eu/news/edpb-adopts-pseudonymisation-guidelines-and-paves-the-way-to-improve-cooperation-with_en>

Two points in that text decide the architecture:

1. Pseudonymised data remains personal data if anyone can attribute it using additional information, **even when the additional information is held by someone else**, and even after the controller has deleted the additional information they themselves held, unless the anonymity test is actually met.
2. There is no general duty to pseudonymise. It is one way to meet data minimisation (Art. 5(1)(c)), privacy by design (Art. 25) and security of processing (Art. 32). The "pseudonymisation domain" is the set of recipients who are supposed to be unable to attribute. Its value depends on keeping that domain away from the additional information.

The EDPB's Guidelines 02/2026 on Anonymisation, version 1.0, were adopted **for public consultation** on 7 July 2026. The consultation ran until 30 October 2026. As of this study they are not a final post-consultation text, so they are used as the Board's current analytical frame, not as a closed rule.

- Text: <https://www.edpb.europa.eu/system/files/2026-09/edpb_guidelines_202602_anonymisation_v1_en_0.pdf>
- Consultation page: <https://www.edpb.europa.eu/public-consultations/guidelines-022026-on-anonymisation_en>

The frame has three tests: no record isolation (a person cannot be singled out), no linkage (records cannot be linked to each other or to other data), and no inference (a person cannot be deduced). Failing one test does not automatically mean the data is personal, but it forces a further look. High-dimensional, high-resolution, record-level data is the data that fails. A transcript, even with names replaced by stable tokens, is exactly that kind of data: the words themselves isolate the speaker.

**Decision for the design.** The analysis store is described as pseudonymised personal data and kept inside GDPR. The only output allowed to leave that treatment is an aggregate that has been through the three tests, with a cell size of at least five so a single person cannot be isolated by subtraction. Stable tokens across meetings are personal data. Destroying the mapping table does not, on the EDPB's view, make the tokens anonymous if the record can still be singled out. So erasure deletes or crypto-shreds the records too, not only the map.

Calling the pipeline "anonymisation" in a contract or a privacy notice would be the finding a strict auditor writes first. The client's brief used "anonymised/pseudonymised". The honest control is pseudonymisation plus minimisation, and anonymisation only for the published aggregate.

## 2. Erasure, backups, and crypto-shredding

Article 17 requires erasure without undue delay where the right applies. Article 12(3) gives the controller a month, extendable by two, to *respond*. "Without undue delay" is about the erasure itself. The client's "effectively immediately" is a contractual standard inside the legal one. Meeting the month is not meeting the client.

Article 17(3) keeps data that must be kept for a legal obligation, for legal claims, and for a few other reasons. Polish accounting records are the usual reason a payment row survives. They are not a reason to keep a transcript. The two stores have to be separable, or the transcript hides inside the ledger.

### What supervisors actually say about backups

The EDPB's 2025 Coordinated Enforcement Framework report on the right to erasure (published February 2026) spends section 4.2.6 on backups. Supervisory authorities were worried. Controllers often had no procedure, and relied on the backup's own expiry. The report's practical line is: follow a real destruction standard, be able to show the erasure happened, and, where a backup cannot be edited without damaging it, have a procedure that re-applies the erasure when a backup is restored.

- Report: <https://www.edpb.europa.eu/system/files/documents/2026-02/edpb_cef-report_2025_right-to-erasure_en.pdf>

The UK ICO's erasure guidance says the same thing in plainer words: live systems should be erased now; backup data should be put "beyond use" and not processed for any other purpose until the backup is overwritten on a schedule the person was told about. The ICO text is UK GDPR. It is persuasive for a Polish controller, not binding. It matches the EDPB report, so the design follows it.

- <https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/individual-rights/individual-rights/right-to-erasure>

### Crypto-shredding, and its limit

Cryptographic erase is a sanitisation method in NIST SP 800-88 Rev. 1: destroy the key that encrypts the media, and the ciphertext is no longer recoverable by reasonable means. It is the method NIST prefers for flash and SSDs, because overwriting free space on an SSD is not reliable.

- <https://csrc.nist.gov/pubs/sp/800/88/r1/final>

It is a sanitisation method. It is not an EDPB decision that ciphertext has stopped being personal data. Practitioner and industry write-ups of the EDPB's blockchain guidelines (Guidelines 02/2025, adopted for consultation on 8 April 2025) record the Board's reminder that encrypted personal data is still personal data, and that after the key is gone the ciphertext stays unreadable only for as long as the algorithm holds. A strict auditor will quote that. The design must not answer "we deleted the key, so Article 17 is satisfied and the backups are out of scope."

The design answers with four layers, each of which the research supports on its own:

1. Delete the live plaintext and the live ciphertext at the time of the request (the ICO "live systems" step, and the purge the code already has).
2. Encrypt every content byte with a per-person key that is not in the database backup, so a backup restore does not yield plaintext (crypto-shredding as a security measure, Art. 32, not as a legal fiction).
3. Do not snapshot the key store. Replicate it (three OpenBao nodes) so availability does not depend on a backup that would resurrect a destroyed key. This is the point the EDPB report is reaching for when it says "re-apply the erasure on restore": if there is no key backup, restore has nothing to re-apply except the ledger.
4. Keep an append-only erasure ledger **outside** the database and outside OpenBao, and refuse to serve traffic after a restore until every key named in the ledger is gone. That closes the failure mode every 2026 write-up of crypto-shredding names: a forgotten copy of the key in a snapshot, a replica, or a developer environment. One such write-up, useful as a list of failure modes and not as authority: <https://selina.ai/blog/crypto-shredding-deleting-the-key-instead-of-the-data>.

A 24-hour snapshot of the key store was considered and rejected in audit round 2. Replication gives Art. 32(1)(c) availability for the keys that still exist. A snapshot gives a way to undo an erasure. The client who wants point-in-time recovery of *content* can have it for the ciphertext, for a short window, because the keys are not in that backup. They cannot have point-in-time recovery of a destroyed key.

OpenBao's transit engine will delete a key so that data encrypted with it can no longer be decrypted, but only after `deletion_allowed` is set. It also has a soft-delete that can be restored. Soft-delete must not be the erasure operation. The erasure operation is the hard delete, and the audit log of OpenBao must show it.

- Transit delete: <https://openbao.org/api-docs/secret/transit/>
- Project: <https://openbao.org/> (OpenSSF / Linux Foundation, MPL-2.0, forked from Vault after the Business Source License change)

HashiCorp Vault itself is BSL, not an OSI licence. OpenBao is the zero-cost choice that does not carry a licence question into the audit.

## 3. Supabase, Postgres, and backup retention

Supabase's own documents, read 16 November 2026:

- Pro: daily backups kept 7 days, from $25 per month. Team: 14 days, from $599 per month, and this is the plan that includes SOC 2 and ISO 27001 of *Supabase*. Enterprise: up to 30 days, custom.
- Point-in-time recovery, on Pro, Team and Enterprise: about $100 per month for 7 days, $200 for 14, $400 for 28. While PITR is on, daily backups stop. WAL is archived about every two minutes. A restore can rebuild a deleted row at any second inside the window.
- Free: no managed backups. The vendor register already found "Last backup: No backups" on 17 September 2026.
- Self-hosting is free (Docker or the CLI) and does **not** include managed backups or PITR. Those have to be built, which is what this design wants, because the managed ones are the wrong shape.

Sources:

- <https://supabase.com/docs/guides/platform/backups>
- <https://supabase.com/pricing>
- <https://supabase.com/docs/guides/platform/manage-your-usage/point-in-time-recovery>

**Decision.** Do not buy a higher Supabase plan to satisfy this client. A higher plan lengthens the backup window and adds a US company as processor. Self-host Postgres (the Supabase Docker stack is acceptable if it runs entirely on the EU host and is never connected to Supabase Cloud). Take the application's own backups of ciphertext only, with a retention the client has agreed, and keep keys out of them.

The application talks to Postgres through PostgREST and the service-role key (`services/db.py`). Rewriting that onto raw SQL is a large, risky change to the live loop and is not required for a single-tenant host. On a single-tenant deployment the service role is a god key to one client's database. The controls that make that acceptable are: the key lives in OpenBao, PostgREST is not reachable from the internet, content columns are ciphertext without the per-person key, and the anon key cannot read those tables. A shared Supabase project with one service role for many tenants does not become acceptable by adding RLS later. One database per client is the isolation boundary.

## 4. Transcription and the model, on the same machine

### Transcription

OpenAI Whisper's weights are MIT-licensed. `faster-whisper` (the SYSTRAN implementation on CTranslate2) is also MIT and runs on CPU or GPU, int8 quantised, with word timestamps. Polish is one of Whisper's languages; the current code already has to stop an English prompt from being applied to Polish audio (`services/openai_service.py` lines 98–103). A local model removes that class of bug as well as the transfer.

An OpenAI-compatible HTTP server in front of faster-whisper (the project now called speaches, previously faster-whisper-server) exposes `POST /v1/audio/transcriptions`. That is the same method `services/openai_service.py` already calls. The migration is a base URL and a boot check, not a new transcript format.

CPU is enough if the work is batched. A long meeting on a quantised model on a 2024-class CPU is slower than realtime by a small factor, not by an hour per minute. Interactive coaching on the public product is a different latency budget and is not this deployment. A GPU is a latency purchase, recorded in the cost table, not a control.

### The language model

vLLM serves an OpenAI-compatible `chat.completions` endpoint. Ollama and llama.cpp do the same with less throughput. vLLM is the default because the existing `services/llm.py` client already speaks that API, including through `services/chat_provider.py`, which already knows how to point the OpenAI SDK at a `base_url`.

Model choice, for a zero-licence-risk default: **Qwen2.5-14B-Instruct**, Apache 2.0, which fits a quantised runtime in 16 GB of RAM and a 64 GB host beside Postgres. Llama-family weights are not an OSI licence. Mistral's hosted API is a third party and is out; a Mistral open weight can be swapped in later if its licence is acceptable to the client, behind the same server. The design does not depend on which open weight it is, and it forbids any weight that phones home.

The model is inference only. Fine-tuning on the client's text, and the current training-corpus and learning-lane paths, are off. A fine-tune can memorise a sentence, and a memorised sentence is a copy that erasure of the database does not reach. That is an Article 17 problem with no cheap technical fix, so the design does not create the copy.

### Why not OpenAI with Zero Data Retention

OpenAI's data-controls documentation (read 16 November 2026) says abuse-monitoring logs may contain customer content and are retained for up to 30 days, unless longer retention is required by law. Eligible customers can be approved for Zero Data Retention, which excludes content from those logs and forces `store=false` on some endpoints. Approval is not the default. Not every endpoint is eligible. Private Safety Processing, which OpenAI has been rolling out so that ZDR can continue, still involves encrypted records with a 30-day TTL in storage the customer must not delete early.

- <https://developers.openai.com/api/docs/guides/your-data>
- <https://openai.com/index/offering-zero-data-retention-for-frontier-models/>
- <https://developers.openai.com/api/docs/guides/private-safety-processing>

Even a perfect ZDR agreement fails the client's third requirement: no dependency on OpenAI or any third-party model API that receives raw data. ZDR also fails immediate erasure, because the client cannot destroy a key they do not hold inside OpenAI's logs. It is recorded here so a later review does not "discover" it as a cheaper shortcut.

## 5. PII detection in Polish and English

Microsoft Presidio (MIT) is the recogniser. It does not ship a Polish model. spaCy's `pl_core_news_lg` does NER for Polish and is **GPL-3.0**. `en_core_web_lg` covers English.

Presidio's default label map does not understand spaCy's Polish labels (`persName`, `placeName`, `orgName`). A documented configuration maps them:

- `persName` → `PERSON`
- `placeName` and `geogName` → `LOCATION`
- `orgName` → `ORGANIZATION`
- `date` → `DATE_TIME`

The pattern is the one in Presidio's multilingual tutorial and in the working Polish example discussed against `pl_core_news_lg`:

- <https://github.com/microsoft/presidio/blob/main/docs/tutorial/05_languages.md>
- <https://huggingface.co/spacy/pl_core_news_lg> (GPL-3.0, version 3.7.0)

Structured Polish identifiers are not an NER problem. They are checksums, and they should be regular expressions plus the official check digit, which does not miss:

- PESEL (11 digits and a weighted checksum)
- NIP (10 digits and a checksum)
- REGON (9 or 14 digits)
- Polish phone numbers, with and without `+48`
- IBAN, with the standard mod-97 check
- email addresses, which Presidio already catches with a pattern that does not depend on language

The GPL model runs in its own container. The Flask process sends text and receives spans. It does not import spaCy. That keeps the GPL program from being a linked work of the application. Counsel can confirm the process boundary; the architecture does not depend on linking.

NER misses nicknames, diminutives, and names that look like ordinary words. The safety property is fail-closed, which the EDPB pseudonymisation guidelines support as a measure inside the domain: a sentence the recogniser is not confident about is replaced with a redaction marker and is not given to the model. The cost is recall of the pattern report. That trade is the one the client asked for by putting redaction before analysis.

Reversible replacement (the same person always becomes `PERSON_17`) is pseudonymisation, and the mapping table is "additional information" under Article 4(5). It is encrypted with the person's key and destroyed with it. Irreversible replacement (`[PERSON]`) is what the model sees. The model does not see the stable token. Stable tokens exist only inside the encrypted store, for the client's own later correction, and only if the client turns that on. The default is irreversible markers, so a stolen model log cannot be joined back to a person.

## 6. Key management

Envelope encryption, in the usual shape:

- A per-person data key (DEK), 256-bit, generated in OpenBao, never exported, never written to Postgres, never written to MinIO, never written to an image.
- Content encrypted with the DEK (AES-256-GCM) by the application, or by OpenBao transit if the latency is acceptable. Application-side AES-GCM with the DEK fetched per operation is simpler to reason about and keeps plaintext out of a second hop. The DEK crosses from OpenBao to the worker over a local socket, is used, and is wiped.
- No escrow of DEKs. Escrow is a backup of the key, which is the thing erasure has to destroy. Losing the OpenBao cluster loses the ciphertext's readability. That is the availability trade, and it is stated in the DPIA. Three-node Raft replication is how a single node can die without that loss. A snapshot is not.
- Unseal uses Shamir shares held by two officers of the **client**, not by the developer. OpenBao 2.7 can put a root on an HSM; that is the paid escalation, not the default.
- `deletion_allowed=true` is set only on the per-person keys, and the erasure job hard-deletes them. Soft-delete is disabled for those paths by not calling it.
- The volume under OpenBao is LUKS-encrypted. Core dumps are disabled. Swap is encrypted. This is the practical answer to "the key was in RAM and RAM was swapped."

`age` is a good tool for an offline file the client already has. It is a poor key-management system: it has no audit log of who decrypted, and no hard-delete API that an auditor can read. It is not the primary design. It can wrap an air-gapped copy of the *unseal* shares if the client wants them offline. It must not wrap DEKs.

## 7. Audit logging, access control, runtime

Article 5(2) accountability and Article 30 records need a log of who did what. Article 32 needs the ability to know that an access happened. ISO/IEC 27001:2022 Annex A controls that map onto this, and that a SOC 2 reviewer recognises under different names, are:

- A.5.15 and A.5.16, A.5.18: access control, identity, access rights
- A.8.2 and A.8.3: privileged access, information access restriction
- A.8.10: information deletion
- A.8.11: data masking (the redaction step)
- A.8.15 and A.8.16: logging, monitoring
- A.8.24: use of cryptography
- A.5.24 to A.5.28: incident management
- A.5.19 to A.5.23: supplier relationships (empty, on purpose, in the client-hosted mode)

OWASP ASVS level 2 is the application checklist: authentication, session, access control on every route, validation, errors that do not echo content, logging of security events without the data, and dependencies that are reviewed. The current code already has pieces of this (JWT verification, rate limits, secret boot checks in `services/secrets.py`, error scrubbing in `utils/errors.py`). The enterprise profile has to hold the line on logs, because `services/llm.py` currently writes model output into the log.

Runtime protection, without a commercial RASP licence:

- **Falco** (Apache 2.0) on the host, watching for a shell in a container, a write outside the data volume, and an unexpected outbound connection. That is the detection half of what RASP products sell.
- **Coraza** (OWASP, Apache 2.0) as a WAF in front of Caddy, with the OWASP core rule set, for the blocking half at the edge.
- Default-deny egress after the image is built. A model that cannot open a socket cannot leak a prompt. This is the control that makes "self-hosted" true rather than "self-hosted but pip install at runtime".
- Unprivileged containers, read-only root filesystems, no Docker socket mounted into the app.
- `pip-audit` and `npm audit` in CI, plus an OS patch schedule. These are already the kind of check the repo runs; they stay.

A named RASP agent inside the Python process is the paid escalation. It is not required to show Art. 32 or ASVS if Falco, Coraza, egress deny, and the log review are actually operated. "Operated" is the word the auditor will test: a rule with no one looking at the alerts is a document.

## 8. Hosting and transfers

Chapter V (Art. 44 and following) applies when personal data is transferred to a third country. The clean way to satisfy a strict reading is to transfer nothing: the machine, the disks, the replicas, the logs and the keys are in the EEA, and the process has no route out.

Hetzner Online GmbH (Germany, with a region in Finland, which is also EEA) is the fallback when the client will not house the machine. Hetzner is then a processor and needs a DPA. Germany and Finland are not third countries. A Hetzner dedicated server in Falkenstein, Helsinki or a German site meets residency. Confirm the site at order time. The April 2026 price list put the AX42 class at €57.30 per month in Germany and €52.30 in Finland, excluding VAT, and the GEX44 GPU box at €212.30 in Germany. The GEX44 order page said the product was not available when this study was written; a reviewer quoted a successor in the same price band. Prices are evidence of scale, not a quote.

Hetzner published a price adjustment effective 1 April 2026. The figures above are taken from that table (AX42 class, GEX44). The GEX44 order page said the product was not available on the day of this study. Re-check the live Robot price and the site before ordering; the numbers are a scale, not a quotation.

Cloudflare as a proxy in front of the host would terminate TLS and become a processor in the United States. The design does not put Cloudflare, Vercel, or Railway in the path. DNS hosting can sit anywhere because DNS does not see the body. Certificate issuance through Let's Encrypt reveals the hostname, not the content; an internal CA is even quieter and is the default (Caddy's internal CA, or a smallstep CA).

## 9. Workplace audio, specifically

The Polish Labour Code regulates image monitoring (art. 22²) and email monitoring (art. 22³). Article 22² is about registration of an image, for a closed list of purposes, kept at most three months. It does not say "and the sound". Article 22³ is about work email, and it forbids violating the secrecy of correspondence. Commentary treats hidden audio as a different and harder problem, under the Constitution's secrecy of communication (art. 49), the Civil Code's protection of personal rights (art. 23–24), and, in a bad case, the Criminal Code.

- Art. 22² text: <https://volumina-legum.pl/akt/du/1974/141/art-22-2>

This study does not turn that into a processing basis. It records that the client, if they are the employer, has a legal question the software cannot close, and that the DPIA has to contain the answer before a microphone is opened. If the "meetings" are recordings the participants make of their own sessions and upload, the basis is different from a microphone the employer hid in a room. The design assumes upload by a person who has been told, not ambient capture. Ambient capture is out of scope until counsel writes a basis for it.

## 10. Decisions this research closed

| Option | Closed because |
|---|---|
| Stay on Supabase Cloud and pay for Team plus PITR | Lengthens the copy, adds a US processor, does not give the client a key they can destroy |
| OpenAI Zero Data Retention | Still a third-party model, still not a key the client holds, still a 30-day story on endpoints and safety records that are not covered |
| Call Presidio output "anonymous" and drop GDPR controls on the analysis store | Contradicts Recital 26 and EDPB 01/2025. A transcript with tokens still isolates the speaker |
| Snapshot OpenBao nightly "for safety" | Resurrects destroyed keys. Replication is the availability control |
| Commercial RASP as a default | Falco, Coraza, egress deny and ASVS cover the control. A named product is a checklist item, not a missing control |
| Fine-tune on the client's meetings | Creates a copy erasure cannot reach |
| One shared database for this client and the public product | The service-role key and the backup would mix two controllers' data |
