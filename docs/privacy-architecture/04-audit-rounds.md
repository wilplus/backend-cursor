# Audit rounds

> **Proposal. Not in force.** Three passes. Each pass is written as an external auditor who wants the engagement to fail, against the requirements in the brief: immediate erasure, redaction before analysis, no third-party model, a strict GDPR and security review, and cost. Evidence against the current code is from backend `706bbf96` and frontend `e9a43ba`, and from [01-current-state-inventory.md](01-current-state-inventory.md). The design under test is [03-target-architecture.md](03-target-architecture.md), which already contains the round-3 fixes. Rounds 1 and 2 record the earlier shape, so the fixes are visible.

Severity here means: **critical** — the requirement is missed and a data subject or the auditor can show it; **high** — a required control is absent or can be bypassed; **medium** — a real weakness with a bounded residual; **low** — hygiene. A pass needs no open critical or high, and every medium either mitigated or accepted in writing.

## Round 1 — current code, and a first sketch that only "adds local models and a key"

The first sketch was: keep Supabase, point Whisper and chat at local servers, run Presidio, encrypt rows with a per-person key stored in the same database, keep the seven-day deletion window, and describe the Presidio output as anonymous. It would not have passed.

### Findings

| ID | Sev. | Against | Finding | Evidence |
|---|---|---|---|---|
| R1-1 | Critical | Art. 44, Art. 28, client rule 3 | Raw audio is sent to OpenAI Whisper, and the transcript is sent to OpenAI chat. The browser opens its own websocket to `api.openai.com`. | `services/openai_service.py` 302–318; `services/llm.py` 227–250; `src/lib/willab/liveStream.ts` 20–22 and 215–218; `src/middleware.ts` 84–87 |
| R1-2 | Critical | Art. 17, client rule 1 | Deletion waits seven days, can be disabled with a flag that defaults off, and does not touch OpenAI's logs, backups, Resend, Sentry, Railway logs, or the browser outbox. | `services/account_deletion.py` 1–10; `config.py` 732–735; `services/provider_deletion.py` 69–75; `src/lib/legal/deleteAccountCopy.ts` 19–22; `src/lib/willab/takeOutbox.ts` 17–19 |
| R1-3 | Critical | Art. 5(1)(c), Art. 25, client rule 2 | Nothing redacts the transcript before the model. The first sketch's claim that Presidio output is "anonymous" is wrong under Recital 26 and EDPB 01/2025. | `services/llm.py` 227–235; [02-research.md](02-research.md) §1 |
| R1-4 | Critical | Art. 32, Art. 17 | A per-person key stored in the same Postgres as the ciphertext is copied into every Supabase backup and every PITR WAL segment. Deleting the row does not delete the backup. Paid Supabase keeps those for 7–30 days. | `services/db.py` 267–270; Supabase backup documentation cited in the research notes |
| R1-5 | High | Art. 32, Art. 5(1)(f) | One service-role key reads and writes every tenant. RLS is not the application boundary. | `services/db.py` 267–270 |
| R1-6 | High | Art. 32 | Model output is written into the log (`raw_head` of 200 characters). Failed calls log the exception string. Sentry keeps 1024 characters and has no `before_send`. | `services/llm.py` 326–330 and 254–258; `app.py` 40–46 |
| R1-7 | High | Art. 28, Art. 32 | Homework email sends a transcript excerpt and the person's email to Resend and then to a mailbox. | `services/email_service.py` 60–84 |
| R1-8 | High | Art. 32 | Decks are served from a permanent public R2 URL. Lab audio shares the coach bucket until two environment variables are set. The endpoint is not the EU-jurisdiction R2 endpoint. | `services/user_content_keys.py` 20–27; `services/lab_audio_storage.py` 29–31; `services/r2_client.py` 21–27 |
| R1-9 | High | Art. 5(1)(b), Art. 25 | Training-corpus import, embeddings, and the learning lanes can make another copy of speech, including a fine-tune file at a provider that the purge only deletes when a contract says `api_delete`. | `routes/v2/coach.py` training import; `services/llm.py` `embed()`; `services/provider_deletion.py` 33–48 |
| R1-10 | High | Art. 32, Art. 5(1)(f) | Temp files for audio sit on the worker disk. | `services/lab_audio_storage.py` module text; tempfile use in the concatenation path |
| R1-11 | Medium | Art. 5(2) | Consent events, principal rows, and provider permits are retained with identifiers. That can be lawful. It is not documented as a limit on "delete everything". | `services/data_purge_registry.py` 794–800 and 132–134 |
| R1-12 | Medium | Art. 6, Polish Labour Code | No basis is recorded for an employer processing workplace conversations. The product's basis is a speaker who signed up for coaching. | The legal pack is about that product. Art. 22² KP is image, not audio. |
| R1-13 | Low | Art. 32 | Free-tier Supabase had no backups when the vendor register was written. Availability is the other half of Art. 32, and it is unmet. | `docs/VENDOR_DPA_REGISTER.md` open item 4 |

Round 1 result: **fail.** Four critical, six high.

### What changed after round 1

The sketch was thrown away. The replacement is a single-tenant EEA host, keys only in OpenBao, Presidio output described as pseudonymised personal data, irreversible markers in the prompt, the seven-day window removed for this profile only, third-party model hosts forbidden at boot, and the public product left on its current path.

## Round 2 — the separate-host design, before the key-store and egress rules were tight

This round attacks [03-target-architecture.md](03-target-architecture.md) as it stood before the round-2 fixes (key snapshots still allowed "for a day", egress not denied, soft-delete still available, aggregates stored as a time series, IndexedDB only "discouraged").

### Findings

| ID | Sev. | Against | Finding | Resolution |
|---|---|---|---|---|
| R2-1 | High | Art. 17 | A 24-hour snapshot of OpenBao restores a key that was hard-deleted an hour ago. Crypto-shredding is void if any copy of the key remains. | Snapshots of OpenBao are forbidden. Three-node Raft is the availability mechanism. The erasure ledger is outside the backup and is replayed before serving. |
| R2-2 | High | Art. 17 | OpenBao soft-delete can be restored by anyone who can call the API. | Erasure calls the hard-delete endpoint only. The job does not have permission to call soft-delete or to set `deletion_allowed` on any key but the one it is destroying, and it confirms decrypt fails. |
| R2-3 | High | Art. 44, Art. 32 | "Self-hosted" with a default route to the internet still leaks. pip, a model runtime, a crash reporter, or a misconfigured base URL can open a socket. The browser build can still contain `wss://api.openai.com` if the flag is only on the server. | Default-deny egress after image build. The enterprise frontend build fails CI if `api.openai.com` appears. The server boot-refuses foreign base URLs. |
| R2-4 | High | Art. 17, client rule 1 | IndexedDB still holding audio for seven days means the server's key destruction is not the only copy, and the server cannot wipe a browser that is offline. | Enterprise build does not open the outbox. Upload retries from page memory only. This is a code change in `src/lib/willab/takeOutbox.ts`'s caller, not a change to the public behaviour. |
| R2-5 | High | Art. 5(1)(c), EDPB 02/2026 draft tests | A stored weekly time series of small teams allows subtraction: delete one person, compare the two aggregates, recover their contribution. | Aggregates are recomputed, cells under five are not written, and no fine-grained time series is stored. |
| R2-6 | High | Art. 32 | MinIO versioning keeps a deleted object. Postgres PITR was left as "optional, 7 days" with no statement that keys are absent. | Versioning off. PITR of the database is allowed only because it cannot contain keys. The runbook says a restore is ciphertext plus a ledger replay, and is rehearsed. |
| R2-7 | Medium | Art. 32 | SSD free space can hold a deleted DEK until TRIM, and LUKS only protects that remnant from someone who does not have the volume key. | Accepted. NIST SP 800-88 treats cryptographic erase as the right tool for SSDs. LUKS plus no snapshots plus hard-delete is the control. No further technical layer is available at zero cost. Stated in the DPIA. |
| R2-8 | Medium | Art. 9 / biometric caution | Diarisation and `part_acoustics` could become a voiceprint if embeddings are stored and compared across meetings. | The design forbids storing embeddings and forbids cross-meeting voice match. Diarisation labels are per recording. Accepted only because the forbidden path is a boot-time and review-time check, not a hope. |
| R2-9 | Medium | Art. 5(1)(c) | Presidio will miss Polish diminutives and nicknames. | Fail closed: disagreement or low confidence redacts the sentence and the sentence never reaches the model. Residual is report quality, accepted in the DPIA. |
| R2-10 | Medium | Art. 28 | Mode B makes WillpowerLab a processor and Hetzner a sub-processor. A design diagram does not create a signed DPA. | Processing of real content is forbidden until the DPA and the sub-processor notice exist. This is an organisational prerequisite, not a software gap. |
| R2-11 | Medium | Labour Code, Art. 6 | No lawful basis for workplace audio is produced by the architecture. | Same: content does not load until the controller's counsel has written the basis and the notice. Ambient capture stays out of scope. |
| R2-12 | Low | GPL-3.0 | `pl_core_news_lg` is GPL. Linking it into the Flask process is a licence question the auditor will not care about and a distributor might. | Separate container. The app sees spans, not the library. |

Round 2 result: **fail.** Six high. The mediums had a direction but the highs were real.

### What changed after round 2

Those resolutions were written into [03-target-architecture.md](03-target-architecture.md): no key snapshots, hard-delete only, default-deny egress, no IndexedDB on this profile, aggregate cell size, MinIO versioning off, ledger replay on start, Presidio fail-closed, embeddings forbidden.

## Round 3 — the design as written in the target architecture

The auditor re-reads the design against the same requirements and tries to break the fixes.

| ID | Sev. | Against | Attack | Result |
|---|---|---|---|---|
| R3-1 | — | Art. 17 | Restore yesterday's Postgres backup and yesterday's MinIO backup. | Ciphertext only. The DEK was never in either backup. OpenBao has no snapshot to restore. **Closed.** |
| R3-2 | — | Art. 17 | Restore an old disk image of an OpenBao node taken by the hosting provider outside the design. | Mode A: the client controls the hypervisor, and the runbook forbids images of the key volume. Mode B: the contract with the host forbids snapshots, and LUKS means a stolen image is noise without the volume key, which is not on that image. Residual if the client breaks their own rule: accepted medium, operational, checked in the yearly review. **Mitigated.** |
| R3-3 | — | Art. 17 | Call OpenBao soft-delete, or export the key, using the application's token. | The token used by the erasure job can hard-delete one named key and cannot export, soft-delete, or read other mounts. A second person must have approved `deletion_allowed` as a standing property of the per-person mount, not as a per-call toggle an attacker flips and then undoes. **Closed** if the policy is the one in the runbook. The implementation plan includes a test that the token cannot export. |
| R3-4 | — | Art. 44 | The model runtime downloads a weight on first request, or a log drain is added later. | Egress is denied. Weights are in the image. A new outbound allow is a change control, not a config typo the app can make. Boot refusal covers the known API keys. **Closed.** |
| R3-5 | — | Client rule 2 | A redaction miss puts a name in the prompt. | The sentence with a low-confidence span does not go. A model reply that contains an email or a PESEL-shaped number is dropped. The raw transcript is encrypted and is not in the prompt. Residual miss of a nickname inside a sentence the NER marked clean: **accepted medium**, DPIA, because the alternative is to send nothing to the model at all. |
| R3-6 | — | Art. 5, EDPB anonymity tests | The analysis store is called anonymous in the notice. | The design and the ROPA call it pseudonymised personal data. Only the aggregate is a candidate for anonymity, and only with cell size ≥ 5 and no stored series. **Closed.** |
| R3-7 | — | Art. 32 | The service-role key still reads every row of this client's database. | One client per database. The key is in OpenBao, PostgREST is not on the network, and the rows are ciphertext. Compromise of the app host remains total for *living* keys, which is true of every design that can show a person their own transcript. Detection is Falco plus the access log. **Accepted** as the application-trust boundary, not as a multi-tenant hole. The multi-tenant hole (R1-5) is closed by refusing a shared database. |
| R3-8 | — | Art. 32 | `services/llm.py` still logs `raw_head` if someone turns the profile on without the log patch. | The profile's boot check is not enough; the log lines have to go or be compiled out. The implementation plan makes the enterprise log path drop content even if a caller passes it, and a test feeds a fake transcript and asserts the log line does not contain it. Until that test exists, this would be high. **The plan makes it a merge condition. Treated as closed in the design, open as a build task.** |
| R3-9 | — | Art. 17 | The public product's seven-day window and "within one month" copy leak into this UI. | Separate copy, and no words ship without the founder's OK (the product rule). The enterprise UI does not import `DELETE_ACCOUNT_COPY`. **Closed in the design.** The founder gate is an organisational step before the UI is shown to anyone. |
| R3-10 | — | Art. 33, Art. 28 | No one knows who calls whom when the box is breached. | The incident outline in the compliance pack. Processor notifies the controller without undue delay, target 24 hours in the DPA; the controller notifies the supervisory authority within 72 hours when Art. 33 applies. **Organisational prerequisite.** |
| R3-11 | — | ISO 27001 / SOC 2 | There is no certificate. | The controls are specified so they can be operated and sampled. The certificate is a paid escalation, not a missing control. A client whose policy says "we only buy from certified vendors" cannot use mode B until the certificate exists, and can use mode A on their own certificate. **Stated, not a software high.** |
| R3-12 | — | ASVS, RASP | No commercial runtime agent inside Python. | Falco, Coraza, dependency review, egress deny, unprivileged containers. **Accepted** as the control. A checklist that names a brand is the paid escalation. |
| R3-13 | — | Art. 32(1)(c) | A site loss destroys living keys as well as the node. | Stated RPO. Three nodes reduce a single-disk failure. They do not survive a site loss, and a site-level key backup is rejected because it undoes erasure. The client accepts this in the DPIA or they do not use the deployment. **Accepted medium, written down.** |
| R3-14 | Low | Art. 5(2) | Security logs for 14 days contain IP addresses. | Deleted on request from the live log; not in the content backup; 14-day cap. **Accepted low.** |
| R3-15 | — | Art. 32, Art. 5(1)(c) | Postgres `log_statement=all`, or a PostgREST body log, would keep another copy of whatever was written. | The unit files set `log_statement=ddl` and do not log request bodies. MinIO logs the key, not the object. **Closed** as configuration the rehearsal checks. |

### Round 3 result

**No critical finding. No high finding left in the design.** R3-8 is a build task with a test that blocks the merge; it is not an accepted hole. Mediums R2-7, R2-9, R3-7, R3-13 and R3-14 are accepted with the mitigations named. R2-10, R2-11, R3-10 and R3-11 are organisational or paid, and they gate the loading of real content rather than sitting as open technical gaps.

**Technical design: pass.**

**Processing of this client's content: not authorised by this paper.** It waits on the organisational list in [00-executive-summary.md](00-executive-summary.md).

## What the three rounds changed, in one list

1. Separate deployment, not a flag sprinkled over production Supabase.
2. Keys out of the database and out of every backup; no key snapshots; ledger replay.
3. Hard-delete only; the erasure token cannot export.
4. Pseudonymised, not anonymous, except aggregates with a cell size.
5. Fail-closed redaction; the model never sees the raw transcript.
6. No third-party model, including from the browser; egress denied.
7. No IndexedDB copy; no public object URLs; no versioning.
8. Logs cannot contain content; the test is part of the change.
9. Workplace-audio legality, the DPA, the pen test, and any certificate stay outside the software and in front of go-live.
