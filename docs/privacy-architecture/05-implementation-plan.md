# Implementation plan

> **Proposal. Not in force. Do not implement from this page without a founder decision.** The public loop (record, transcribe, Ideal Text, feedback, next Take) stays on its current processors until someone deliberately builds the enterprise profile. A change that alters that loop when the profile is off is a bug in the change. New words on a screen need the founder's OK before they ship, including words that only the enterprise profile shows.

Nothing in this plan has been coded. Sizes describe how invasive the edit is, not a delivery date.

| Size | Meaning |
|---|---|
| S | One module, behaviour behind the profile flag, a contract test |
| M | A few modules and a new container, still behind the flag |
| L | Cross-cutting, or it touches auth, storage, and deletion together |

Order is the order to build. Later steps assume the earlier boot guard exists, so a half-finished profile cannot be pointed at production by an environment variable typo.

## 0. Guard the profile — backend, size S

Add `PRIVACY_PROFILE` in `config.py`. Values: unset (today's product) or `enterprise`.

When it is `enterprise`, refuse to boot unless every item in the boot list in [03-target-architecture.md](03-target-architecture.md) holds. The check lives next to `services/secrets.py` `enforce_at_boot`, which already stops a bad credential before the process serves.

Tests, in the style of the existing boot tests: enterprise with `OPENAI_API_KEY` set exits; enterprise with no OpenAI key and a local base URL does not; unset profile does not look at the new variables. The unset path must not gain a new required variable.

Do not default the variable to enterprise in any Railway or Vercel environment.

## 1. Stop content reaching a third-party model — backend, size M

| File | Change |
|---|---|
| `services/chat_provider.py` | If the profile is enterprise, the only legal target is a local `base_url` already checked at boot. Ignore `MISTRAL_TEXT_SURFACES`. Do not fall through to `provider="openai"`. |
| `services/openai_service.py` | The transcription client uses that local base URL. Keep `verbose_json`, segments, and words, so callers of `transcribe_audio` do not change shape. Drop the English disfluency prompt only as today's language rules already do; do not retune prompts in this change. |
| `services/llm.py` | On the enterprise path, do not log `raw[:200]`, the exception string, or a clear user id. Log surface, duration, status. Add a test that a transcript planted in a fake response does not appear in the captured log. This is audit item R3-8 and it blocks the merge. |
| `services/journal_image.py`, `services/llm.py` `embed()` | Not called when the profile is enterprise. A test that the import path and the image path refuse. |
| `services/elevenlabs_client.py` | Not constructed. Boot already refuses the key. |

The local servers are containers, not Python imports: faster-whisper behind an OpenAI-compatible HTTP API, and vLLM serving Qwen2.5-14B-Instruct. Pin the image digests. Weights are baked in at image build so runtime does not fetch them.

## 2. Redact before the model — new sidecar, size M

A small new module, `services/redaction.py`, called from the enterprise branch of the analysis worker only. It posts text to the Presidio container and applies the fail-closed rules in the architecture page. The public pipeline does not call it.

The Presidio image contains `pl_core_news_lg`, `en_core_web_lg`, the Polish label map, and checksum recognisers for PESEL, NIP, REGON, Polish phone numbers, and IBAN. It is a separate container because the Polish model is GPL-3.0.

Tests use fixed strings, not a recorded meeting: a Polish name and a PESEL are absent from the bytes that the fake vLLM received; a sentence the recogniser marks low-confidence is absent entirely; an English email is absent. One golden row is enough. Do not build a corpus of real speech for the test.

The raw transcript is still stored for the person's own screen, encrypted in step 3. The module must make it structurally hard to pass the raw string into `chat_complete`: the enterprise analysis function accepts only the redaction result type, not a `str`.

## 3. Encrypt, and keep the keys out of Postgres — size L

This is the invasive step.

| Piece | Change |
|---|---|
| New `services/content_crypto.py` | AES-256-GCM. The DEK comes from OpenBao for one operation and is wiped. Ciphertext is what `put_lab_audio_bytes` and the transcript columns write, on this profile only. |
| `services/r2_client.py` | Enterprise endpoint is MinIO. Refuse a public base URL at boot. |
| `services/lab_audio_storage.py` | Enterprise never calls `lab_audio_public_url`. Scratch space is a tmpfs path, not `tempfile.TemporaryDirectory` on the root disk. |
| `services/user_content_keys.py` | Enterprise treats every key as user content, including `willab_presentations/`. |
| OpenBao policy | Per-person keys, hard-delete, no export, no soft-delete, for the erasure token. Document the policy next to the module. Do not commit a token. |
| Erasure ledger | A local append-only file outside the Postgres data directory. `enforce_at_boot` replays it. |

Unencrypted reads of old rows are a public-product concern and do not arise here, because this database starts empty. Do not write a migration that re-encrypts the production Supabase project. That project is not this deployment.

A contract test: write a transcript, delete the key, assert the row's ciphertext does not contain the plaintext and that decrypt raises.

## 4. Deletion without the seven-day window — size M

`services/account_deletion.py` and `services/deletion_completion.py` implement a founder decision (seven days, then the purge, and only if `PHASE1_PURGE_EXECUTION_ENABLED` is true). Do not change that behaviour when the profile is unset.

When the profile is enterprise:

- The request runs the four steps in the architecture page immediately: ledger line, hard-delete key, existing purge graph, confirmation.
- `PHASE1_PURGE_EXECUTION_ENABLED` is not the safety switch. Boot refuses to start if erasure is not armed. A dry-run default would recreate finding R1-2.
- The purge registry gains the analysis tables. Retained accountability rows must not contain a transcript; the test reads the retained row and asserts the content columns are null.
- Billing tables are absent on this deployment, so the five-year ledger path does not run. If the client later pays an invoice, the invoice lives in a different database.

Project deletion on this profile is the same immediate path, scoped to one project, using `services/project_deletion.py` only for the inventory. The public project's seven-day behaviour stays.

## 5. Frontend, size M

Repository: `wilplus/frontend-cursor`. A build argument `PRIVACY_PROFILE=enterprise` produces a different bundle. The default build is byte-for-byte the current product.

| File | Change |
|---|---|
| `src/lib/willab/liveStream.ts` | Not compiled into the enterprise bundle. The call sites in the voice notebook fall back to the path they already have when the socket cannot open. |
| `src/middleware.ts` | Enterprise CSP does not include `wss://api.openai.com`, `*.supabase.co`, or Stripe, unless that deployment truly uses them. The default middleware is unchanged. |
| `src/lib/willab/takeOutbox.ts` | Enterprise callers do not open IndexedDB. Retry stays in memory for the page. The public outbox, including the seven-day copy and the rule in the recording-screens flow, is unchanged. |
| `src/lib/legal/deleteAccountCopy.ts` | Do not edit these strings. They are signed. The enterprise screen uses a different module, and the words in it are not written here. They need the founder's OK, because a fixed line needs it. Until that OK exists, the enterprise UI shows no deletion sentence of our invention; the button calls the API and the API's confirmation is the founder's later text. |
| `src/lib/funnel/loungeLocalThread.ts` and `src/lib/willab/setupDraft.ts` | Enterprise does not persist thread text or setup drafts to `localStorage`. |
| Guest owner in `src/services/api/projects.ts` | Enterprise build has no guest path. |

CI for the enterprise build greps the client bundle for `api.openai.com`, `sentry.io`, and `supabase.co` and fails on a hit. That is the regression test for R2-3.

Hosting: the Next server runs on the same EU machine as the API. Do not add a Vercel project for this profile.

## 6. Identity, size M

`auth.py` today verifies a Supabase JWT. Enterprise accepts a Keycloak issuer and audience configured at boot, and does not accept the Supabase issuer. MFA is enforced in Keycloak, not in Flask. No WhatsApp, Google, LinkedIn, or Apple buttons in the enterprise bundle (the buttons already exist per provider; the build hides them and the backend rejects those issuers).

This is the step most likely to break a careless merge. The public `verify_supabase_token` path stays the default and has its existing tests run unmodified.

## 7. Runtime and egress, size M, mostly not application code

- Compose or systemd units: Caddy, Coraza, Flask, Next, Presidio, faster-whisper, vLLM, Postgres, PostgREST, MinIO, OpenBao (three nodes), Keycloak, Falco.
- nftables or the host firewall: inbound 443 only; outbound denied. Document the exception for OS updates as a manual, logged window, not a standing allow.
- Core dumps off, swap encrypted, LUKS on data volumes, containers unprivileged, root filesystem read-only where the image allows.
- Journald retention 14 days. No log drain. Postgres `log_statement=ddl`. PostgREST and MinIO do not log bodies. The rehearsal greps a day of logs for a planted sentence and expects no hit.
- A restore rehearsal: load a backup, start the process, watch the ledger replay delete a key that was reintroduced by hand, and see the process refuse to serve until that delete succeeds. The rehearsal uses fake data.

## 8. What not to build

- A migration of production rows out of Supabase. This deployment starts empty.
- A change to the signed privacy text, the ROPA in `docs/legal/`, or the vendor register, until the founder decides the public product is changing. This client's ROPA is the draft in [06-compliance-pack.md](06-compliance-pack.md), for the client, not a replacement of the product's Article 30 record.
- Fine-tuning, the training-corpus UI, ElevenLabs voice clones, life-panel document upload, and coach email of excerpts, on this profile. They stay in the public product.
- Commercial RASP, Supabase Team, and OpenAI Zero Data Retention. The research notes say why.

## 9. Tests that earn their place

The house rule is to test behaviour a person cares about, not private helpers. The tests that belong to this work:

1. Enterprise boot fails closed when a forbidden key is present, and the public boot does not.
2. The bytes the local model server received do not contain a name or a PESEL that was in the recording's transcript.
3. After deletion, the live row is gone, decrypt fails, and a restored ciphertext backup still does not decrypt.
4. The log of a failed model call does not contain the transcript.
5. The public deletion test (`tests/test_account_deletion_starts_postgres.py` and the completion tests) still sees a seven-day window when the profile is unset.

No snapshot test, no test that needs a real GPU, no test that calls a real model. The model and Presidio are faked at the HTTP boundary in CI. A manual rehearsal on the real containers is step 7, done once before any client data, and it is not a unit test.

## 10. Repo rules this plan would otherwise break

- New documents normally need a `Founder-Approved:` line in `README.md`, and `scripts/doc_guard.py` fails a pull request that adds a Markdown file without one. This study was asked for as files under `docs/privacy-architecture/` only, so the README was not edited. CI on the documentation pull request will fail that guard until the founder either accepts the folder with a line in the README or tells us to drop it.
- A product change that follows this plan needs an entry in `docs/SPEC-DECISIONS-LOG.md` and, where it changes a locked flow, a line on the frontend flow page. That entry is not written here, because no product decision has been made.
- `scripts/local_ci.sh` is the check before any later code pull request. This documentation pull request does not change application code, so it does not claim to have run the test suite.
