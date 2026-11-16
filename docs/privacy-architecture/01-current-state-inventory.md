# Current-state inventory

> **Proposal. Not in force.** Evidence for the design study in this folder. It describes the code on backend `main` `706bbf96` and frontend `main` `e9a43ba`. It is not a finding that the public product is unlawful, and it does not amend the signed legal pack. Line numbers are from those commits.

The product this code implements is a speaking coach: a person records a Take, the server transcribes it, writes an Ideal Text, and returns feedback. The client described in the brief wants something stricter and adjacent: the organisation's own audio, meetings and conversations, processed so that patterns can be spotted, with immediate erasure, redaction before analysis, and no third-party model. This page is the map of where personal and client data actually goes today, which is the thing a migration has to leave or replace.

There is no meeting-analytics or "pattern spotting" product in either repository. The closest behaviour is the coaching analysis itself (many model calls over a transcript) and the optional learning and training-corpus paths. Those are the flows the target design re-homes.

## 1. Where data enters

### Backend

| What arrives | Route | Evidence |
|---|---|---|
| Email, password, name, terms acceptance, IP, User-Agent | `POST /auth/signup` | `routes/auth.py` signup handler reads the body and logs consent with `X-Forwarded-For` or `remote_addr`, and User-Agent capped at 512 characters |
| Email and password | `POST /auth/login`, `POST /auth/reset-password` | `routes/auth.py` |
| Google, LinkedIn, Microsoft, Apple identity | Not a backend callback. Supabase Auth completes the OAuth or Apple token exchange; the backend trusts the resulting JWT | `auth.py` `verify_supabase_token`; frontend `src/lib/auth/startOAuth.ts`, `src/lib/auth/nativeSignIn.ts` |
| Phone number and a one-time code | `POST /v2/internal/auth/send-sms` | `routes/v2/login_code.py` calls `services/login_code.py`, which sends the code through Meta's WhatsApp template. The code itself is not logged; the log keeps the last two digits of the phone (`services/login_code.py`) |
| Take audio, topic, slides, strategic context, feelings | `POST /v2/lab/recordings` | `routes/v2/lab_recording.py` (multipart). Feelings tags are read in the same module |
| Deck PDF and its extracted text | `POST /v2/lab/presentation/extract` | `routes/v2/lab_recording.py` |
| Chat text, and chat voice, photo, file | `POST /v2/chats/<thread>/messages` and the voice, photo and file routes | `routes/v2/chats.py` |
| WhatsApp number, and inbound WhatsApp message text | `GET/PUT/DELETE /v2/user/whatsapp`; `POST /v2/whatsapp/webhook` | `routes/v2/user_whatsapp.py`, `routes/v2/whatsapp_webhook.py` |
| Profile, goal, languages, consent flags | `/v2/user/profile`, `/v2/user/sharing-consent` | `routes/v2/user_account.py` writes IP and User-Agent onto `user_consent_events` |
| Plan answers, including audio | `/v2/plan/*` | `routes/v2/plan.py` |
| Life-panel documents and notes | `/v2/life/*`, behind `LIFE_PANEL_ENABLED` | `routes/life_routes.py`, `services/life_engine.py` |
| Training-import audio (coach) | `POST /v2/coach/training-imports` | `routes/v2/coach.py` |
| Account-deletion request | `POST /v2/processing-authorization/terminate` with `trigger_kind=account_deletion` | `routes/v2/processing_authorization.py`; behaviour in `services/account_deletion.py` lines 1–10 |
| Push device token | `routes/v2/push_devices.py` | Apple APNs token |

OAuth provider tokens are not stored by the Flask app. They live in Supabase Auth.

### Frontend

The browser is an ingress of its own.

| What the browser holds or sends | Evidence |
|---|---|
| Supabase session in cookies that are deliberately not `httpOnly`, so the browser client can read them | `src/middleware.ts` around the cookie `setAll` path |
| Anon key in the bundle: `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY` | `src/lib/supabase/client.ts` |
| Take audio in IndexedDB `willab-takes` until the server acknowledges it, or for 7 days | `src/lib/willab/takeOutbox.ts` lines 17–29 |
| Voice-note audio and interim words in an IndexedDB outbox | `src/lib/willab/voiceNoteOutbox.ts` |
| Unsigned lounge thread JSON, including the words typed, for up to an hour | `src/lib/funnel/loungeLocalThread.ts` |
| Setup drafts and deck text (topic, audience, slides) in `localStorage` | `src/lib/willab/setupDraft.ts`, `src/lib/willab/exploreArc.ts` |
| Guest ownership token | `src/services/api/projects.ts` |
| APNs device token `willab.push.token` | `src/lib/nativePush.ts` |
| Chat history (up to 40 screen turns when signed in) posted to the backend | `src/services/api/chatQuery.ts`, `src/components/willab/Lounge.tsx` |
| Live microphone audio streamed from the phone to OpenAI | `src/lib/willab/liveStream.ts` lines 20–22 and 215–218. The socket is `wss://api.openai.com/v1/realtime?intent=transcription`, and the short-lived key is sent as a websocket subprotocol. CSP allows that host in `src/middleware.ts` lines 84–87 |

The service worker does not cache `/api/*` or media (`public/sw.js`). That is one of the few places a copy is deliberately not made.

Account deletion, as the screen tells the speaker, finishes "within one month" (`src/lib/legal/deleteAccountCopy.ts` lines 19–22). Project deletion UI is compiled in and switched off (`PROJECT_DELETE_ENABLED = false` in `src/lib/willab/projectDeletionCopy.ts`).

## 2. Where it is stored

### Postgres, through the service-role key

Every ordinary read and write uses `SUPABASE_SERVICE_ROLE_KEY`:

```267:270:services/db.py
        return create_client(
            config.SUPABASE_URL,
            config.SUPABASE_SERVICE_ROLE_KEY,
        )
```

That key bypasses row-level security. The database is Supabase Cloud, region `eu-west-1` (Ireland), recorded in `docs/VENDOR_DPA_REGISTER.md`. The application does not encrypt column values. A snapshot of the database is a snapshot of the transcripts.

Tables that hold the words, the voice, or the identity, and what a finished purge does with them (from `services/data_purge_registry.py`):

| Store | What it holds | On purge |
|---|---|---|
| `recordings`, `snippets`, `user_transcript_edits` | Transcript text, word timings, edits | Delete (registry around lines 178–190) |
| `recording_feelings` | The feeling named before a Take | Delete (lines 191–192) |
| `ideal_text_blocks`, `ideal_text_saves`, feedback tables | Ideal Text and feedback derived from the words | Delete (lines 206–219 and the `_product_record` block from line 150) |
| `evidence_spans` | Identifiers kept, words cleared | Tombstone, not delete (lines 197–201) |
| Chat tables | Message text, and pointers at chat audio and files | Delete |
| `speaker_memory`, `speaker_memory_events` | The private note Will keeps about the speaker | Deleted with the account (`services/speaker_memory.py`) |
| `user_settings` | Profile and WhatsApp phone | Deleted with the account |
| `user_consents`, `user_consent_events` | Terms acceptance, IP, User-Agent | **Retained** as authorisation evidence (lines 794–798) |
| `owner_principals` | The identity anchor other evidence points at | **Retained** (lines 799–800) |
| `processing_provider_permits`, `processing_provider_operations` | Proof a provider was allowed to run | **Retained** (lines 132–134 and 788–790) |
| `token_ledger`, `llm_usage` | Who was billed, which session, token counts | **Retained five years** (`services/retention_cleaner.py` lines 28–32; registry lines 912–915) |
| `account_deletion_requests` and the purge manifest | The fact of the deletion | Kept, and they are not the subject's words |
| Voice-measurement columns on the recording | Numbers derived from the audio | Removed with the audio by the 12-month cleaner, or with the account purge. The cleaner says measurements go before the object (`services/retention_cleaner.py` lines 16–23) |

`ai_model_example_vectors` stores numeric vectors for model-head training as a Postgres array. There is no separate vector database. Embeddings are requested from OpenAI in `services/llm.py` `embed()` (around lines 354–393) when that path runs.

Job state is a row in `processing_jobs`, not a Redis payload. The queue message is the job id only (`services/pipeline_jobs.py`). The row can carry a storage key, a user id, and `session_context` (domain vocabulary the speaker supplied). Redis on Railway therefore does not hold the transcript, but the job row does hold identifiers and the vocabulary, and Railway's DPA treats some account and usage data as Railway's own controllership (`docs/VENDOR_DPA_REGISTER.md`).

### Object storage

Audio and media go to Cloudflare R2 through the S3 API. The client is built against `https://{account}.r2.cloudflarestorage.com` (`services/r2_client.py` lines 21–27), which is the default endpoint, not the EU-jurisdiction endpoint `.eu.r2.cloudflarestorage.com`. `docs/VENDOR_DPA_REGISTER.md` records the buckets as Eastern Europe (`EEUR`), a placement hint rather than an EU contractual pin, and notes that Eastern Europe is not the same as the EEA.

Lab Takes are supposed to be able to use a separate bucket. Until both `R2_LAB_AUDIO_BUCKET` and `R2_LAB_AUDIO_PUBLIC_BASE_URL` are set, writes fall through to the coach bucket (`services/lab_audio_storage.py` lines 29–31 and 98–111). User-content keys do not receive a public URL (`lab_audio_public_url`, lines 185–192): playback is a presigned GET. Decks under `willab_presentations/` are intentionally left on a permanent public URL, because a seven-day signature made them go dark (`services/user_content_keys.py` lines 20–27). A deck is the speaker's or the client's document. A public URL for it cannot be expired.

Temp files during ffmpeg, concatenation and transcription use `tempfile.TemporaryDirectory` (for example `services/session_concatenation.py`). That is the disk of the Railway worker, unencrypted by the application, and it lives until the directory is cleaned up.

### The browser, again

IndexedDB holds the Take for up to seven days even after a deletion request is only sent to the server. Account deletion does clear the outbox (`src/services/api/accountDeletion.ts`), which covers the happy path on that device. It does not cover a second device, a copied file, or a browser that never comes back.

## 3. Who else receives it

Processors and independent controllers, from the code and from `docs/VENDOR_DPA_REGISTER.md` (last updated there 2026-10-27). "What the code sends" is the column that matters for this study.

| Party | What the code actually sends | Retention the code or the vendor documents | Evidence |
|---|---|---|---|
| **OpenAI** | The audio bytes, file name and content type, to `audio.transcriptions.create` (`model="whisper-1"`). Chat messages that contain the transcript, the prompts and speaker-memory text, to `chat.completions.create`. Embeddings input when that path runs. Journal image prompts to `images.generate`. Fine-tune files through `files.delete` only when a purge contract says `api_delete`. | OpenAI's current data-controls page says abuse-monitoring logs may contain customer content and are kept up to 30 days unless the law requires longer. Zero Data Retention is an approval, not the default, and does not cover every endpoint. The whisper call in this repo does not set a store flag. The vendor register (2026-09-17) already recorded 30-day retention and region `Global`. | `services/openai_service.py` lines 81–84 and 302–318; `services/llm.py` lines 227–250; `services/provider_deletion.py` lines 33–75; [OpenAI data controls](https://developers.openai.com/api/docs/guides/your-data) |
| **OpenAI, from the browser** | Live PCM of a voice note, with a short-lived key | Same organisation. A preview, but the audio still leaves the device. | `src/lib/willab/liveStream.ts` lines 20–22, 215–218 |
| **Mistral** | The same chat text, if the surface is listed in `MISTRAL_TEXT_SURFACES` and the model is the cheap default. Default base URL `https://api.mistral.ai/v1`. | A second model host. Not in the vendor register's main table. | `services/chat_provider.py` lines 31–48 |
| **ElevenLabs** | Voice-clone audio samples and the text to be spoken | DPA on file. The signed privacy notes record that self-serve deletion can wait 180 days of inactivity, and backups follow ElevenLabs' own schedule. | `services/elevenlabs_client.py`; `docs/VENDOR_DPA_REGISTER.md` is supplemented by the privacy 3.6 note in `legal/phase1-2026.1/25-privacy-terms-3.6-new-features-SIGNED-2026-10-15.md` |
| **Supabase** | Accounts, every row above, auth email and phone, and storage when R2 is not configured | Ireland region. Free plan: the vendor register's open item 4 says the dashboard showed no backups on 2026-09-17. Paid plans keep daily backups 7 days (Pro), 14 days (Team) or up to 30 days (Enterprise), and point-in-time recovery is an add-on at roughly $100 per month per 7 days. | `services/db.py` lines 267–270; [Supabase backups](https://supabase.com/docs/guides/platform/backups) |
| **Cloudflare R2** | Audio, video, decks, chat files | DPA by reference. Placement `EEUR`, not the EU jurisdiction endpoint. | `services/r2_client.py` lines 21–27 |
| **Cloudflare upload proxy** | The multipart Take, in transit, when `NEXT_PUBLIC_UPLOAD_PROXY_URL` is set | The worker sees the body. | `frontend-cursor/cloudflare/upload-proxy`, `src/services/api/labRecording.ts` |
| **Railway** | The process, its disk, its logs, and the Redis queue. Log lines can include a user id and, on some failures, text (below). | Processor for what it hosts, and an independent controller for its own account and usage data. | `docs/VENDOR_DPA_REGISTER.md`; `services/logging_setup.py` |
| **Vercel** | The Next.js server. Server components and BFF routes see request bodies, including chat JSON, on the way through. | US company, SCCs. | `src/app/api/v2/chat/query/route.ts`; vendor register |
| **Resend** | Recipient, subject, and HTML. The homework mail includes a transcript excerpt of up to 280 characters and the student's email. | US company, SCCs. The app does not delete the copy Resend already accepted. | `services/email_service.py` lines 60–84 |
| **Sentry** | Exception events. `send_default_pii=False` and `max_request_body_size="never"`. No `before_send` scrubber. Messages are cut at 1024 characters, which is long enough to hold a sentence of a transcript if one was placed in the exception. | EU storage region per the vendor register. The DPA file is marked not yet committed. | `app.py` lines 33–47; `worker.py` lines 158–168 |
| **Stripe** | Checkout identifiers and payment data. Stripe is an independent controller for the card. | Not the speech. A grant row is kept. | `services/token_packages.py`; registry around lines 1692–1695 |
| **Meta (WhatsApp)** | E.164 phone, template parameters, inbound message text | Meta is also a controller for its own service. | `services/whatsapp_notify.py`, `services/login_code.py` |
| **Google, LinkedIn, Microsoft, Apple** | The sign-in. Apple also receives the push token. | Their own accounts. | Frontend auth buttons; `services/push_devices.py` |
| **The coach's inbox** | Whatever Resend sent, including the excerpt above | A mailbox is another store. | `services/email_service.py` |

No PostHog, gtag, Mixpanel, or Meta pixel was found in the frontend `src/` tree or in `package.json` dependencies. Sentry is not in the frontend bundle.

## 4. What a deletion actually does

The speaker can ask, and processing stops at once. **Nothing of theirs is deleted for seven days**, and they may cancel during that window (`services/account_deletion.py` lines 1–10). When the window has passed, a Railway cron calls `POST /v2/internal/deletion/complete-due`. If `PHASE1_PURGE_EXECUTION_ENABLED` is not the string `true`, that run is a dry run and writes nothing (`services/deletion_completion.py` lines 4–6 and 28–30; `config.py` lines 732–735). The flag defaults off.

When a purge does run, it freezes a graph and deletes the product rows and objects it knows, checking byte hashes before an object is removed. It is a serious design, and it is the right foundation to keep. It does not do what this client asked for:

- The seven-day wait is the opposite of "effectively immediately". The screen then allows a further month (`deleteAccountCopy.ts` lines 19–22). The statute's outer bound is one month (GDPR Art. 12(3)); the client's contractual ask is stricter than the statute, and the code follows the statute's outer bound rather than the ask.
- Sign-in is nulled, not dropped. Email, phone and password become NULL, sessions are revoked, the user is banned, and the auth row stays because evidence points at its id (`services/deletion_completion.py` lines 37–44).
- Consent events, the principal row, provider permits, and the tombstoned evidence spans stay, on purpose, as accountability records.
- Billing rows stay five years.
- OpenAI objects are deleted only when the reviewed contract for that call says `api_delete` and the reference looks like a file id. Chat and whisper calls are not files. For those the contract mode `contractual_retention` counts the object as **retained** (`services/provider_deletion.py` lines 69–75). There is no code path that reaches into OpenAI's abuse-monitoring log.
- Supabase backups and point-in-time recovery, if the project is ever upgraded onto them, are outside the application. The free project had no backups at all when the vendor register was written, which fails Art. 32(1)(c) availability in the other direction (`docs/VENDOR_DPA_REGISTER.md` open item 4).
- Resend, Sentry, Railway logs, Vercel logs, the coach's mailbox, Meta, and the browser's IndexedDB are not in the purge graph.
- ElevenLabs clones are deleted when termination starts (`routes/v2/processing_authorization.py`), which is better than the purge's provider path, and still depends on ElevenLabs actually destroying its backups.

Practice audio that was not chosen is deleted 30 days after the practice closes (`services/practice_retention.py`, `RETENTION_DAYS = 30`). Unused Take audio is deleted at 12 months by the cleaner, measurements first. Guest accounts go at 30 days. Technical logs in four tables go at 90 days. None of these is an erasure of a backup.

## 5. Logging and telemetry

The root logger writes to stdout, which on Railway is the platform log (`services/logging_setup.py` lines 35–59). The format is time, level, logger name, request id, message. There is no redaction filter on the message.

What is logged on purpose:

- Whisper logs file name and byte size, not the audio (`services/openai_service.py` line 307). On failure it logs the exception object with a stack (`lines 348–352`) and sends it to Sentry.
- A successful chat call logs surface, provider, model, duration, **user id**, and token counts (`services/llm.py` lines 335–339).
- A chat call whose JSON did not parse logs the **first 200 characters of the model output** (`services/llm.py` lines 326–330, `raw_head`). That output is the model's reading of the speaker's words.
- A failed chat call logs the exception string (`services/llm.py` lines 254–258), which for many HTTP errors includes a slice of the request.
- Resend logs the recipient and the subject (`services/email_service.py`).
- The login code logs the last two digits of the phone.

`utils/errors.py` scrubs keys, JWT-shaped tokens and paths on the error responses the app builds. It does not wrap the logging calls above. Sentry has no `before_send`.

`llm_usage` stores user id, session id and token counts for five years. That is a cost ledger, not a transcript, and it is still an identifier kept long after a deletion.

## 6. Access control

- A valid Supabase JWT is the application gate (`auth.py`).
- The database gate is the service role, shared by the whole deployment.
- Coach routes use `require_admin_or_coach`. Blind review is a real control (`routes/v2/coach.py` and `services/coach_blind_gate`): a coach is not shown the machine's guess before answering. The coach is still shown the speaker's words. That is correct for the coaching product and wrong for a client who said analysis must not see raw data.
- Internal crons use shared secrets (`config.py` `DELETION_COMPLETION_SECRET` and neighbours).
- Provider calls go through `services/authorized_provider.py` and a permit is recorded. That is an authorisation boundary against accidental processing, not an encryption boundary.

## 7. What is absent

Searches for Presidio, a PII recogniser, field-level encryption, Fernet, or an application KMS in the processing path found nothing that encrypts a transcript or an audio object. `services/secrets.py` redacts secrets at boot. `services/coach_pseudonym.py` builds a pseudonym for a coach-facing email subject. `processing_authorization` can store a SHA-256 subject reference. None of these is a redaction step in front of the model.

The model always sees the transcript. `services/llm.py` `chat_complete` sends `system` and `user` as written (lines 227–235). Transcription always sends the bytes (`services/openai_service.py` lines 302–318).

## 8. How this maps onto the client's five requirements

| Requirement | What the code does today |
|---|---|
| Erase at any time, effectively immediately, despite ~30 days of backup retention | Seven-day wait, then a purge that can be switched off, then retained evidence rows, then whatever Supabase, OpenAI, Resend, Sentry, Railway and the browser still hold. Backups are either missing (Art. 32 gap) or, on a paid Supabase plan, kept 7–30 days with no per-subject key to destroy. |
| Anonymise or pseudonymise before analysis | Not implemented. The analysis is the product, and it runs on the raw transcript. |
| No OpenAI and no third-party model seeing raw data | OpenAI is the transcription path and the default chat path. The browser opens its own socket to OpenAI. Mistral is a second optional host. ElevenLabs sees voice samples. |
| Survive a strict GDPR and security audit | There is a real legal pack, a vendor register, a purge orchestrator, private-bucket rules for user content, and Sentry PII defaults off. Those are assets. They were built for a consumer coaching service with named processors, not for this client's test. |
| Prefer zero licence cost | The current stack's processors are paid or free-tier SaaS. The free Supabase tier is the one with no backups. |

The purge registry, the permit log, the private-bucket rule for user-content keys, and the decision to keep deletion evidence without the words are worth keeping. The target design wraps them. It does not throw them away.
