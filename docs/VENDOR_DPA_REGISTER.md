# Vendor / sub-processor register (Art. 28 + Art. 30 support)

Status of processor paperwork and the facts a supervisory authority or customer
would ask for. **Keep this in sync with `frontend-cursor/src/app/privacy/page.tsx`
(sub-processor table) — a vendor in one and not the other is a defect.**

Last updated: 2026-09-17

## Legend

`SIGNED` executed and countersigned PDF filed · `BY-REF` incorporated by
reference into accepted terms, no signature needed · `REQUESTED` asked, awaiting
reply · `TODO` not started

## Register

| Vendor | Role | What it holds | DPA | Date | Transfer basis | Region | Evidence file |
|---|---|---|---|---|---|---|---|
| OpenAI | Processor | API inputs/outputs: audio, transcripts, feedback text | REQUESTED | 2026-09-17 | SCCs; EU contracting entity to be confirmed | US | |
| Cloudflare (R2) | Processor | The voice/video objects themselves | TODO | | SCCs | default jurisdiction — **not EU-pinned** | |
| Supabase | Processor | Accounts, transcripts, feedback, auth | TODO | | | **UNVERIFIED — claimed EU** | |
| Railway | Processor | Compute + Redis queue payloads | REQUESTED | 2026-09-17 | | | |
| Resend | Processor | Email addresses + rendered session-result content | TODO | | | | |
| Sentry | Processor | Error telemetry (PII suppressed — see below) | TODO | | | | |
| Vercel | Processor | Frontend hosting + internal email render endpoint | TODO | | | | |
| Stripe | Independent controller (payments) | Card/payment data | N/A — controller | | Stripe's own terms | | |

## Processing surface — OpenAI (code-derived, 2026-09-17)

The only OpenAI endpoints called from `services/`:

| Call | Purpose | Count |
|---|---|---|
| `chat.completions.create` | Ideal Text, Manager feedback, copilot | 6 |
| `audio.transcriptions.create` | Whisper transcription (F1 core) | 3 |
| `images.generate` | Journal images (`gpt-image-1`) | 1 |
| `files.retrieve` / `files.delete` | Fine-tuning file management | 2 |

No Responses API usage; no hosted tools (web search, file search, code
interpreter, MCP) are invoked. All five hosted-tool permissions disabled at the
org level 2026-09-17.

## Account configuration evidence

| Control | State | Date | Where |
|---|---|---|---|
| OpenAI — share inputs/outputs for training | Disabled | 2026-09-17 | Data controls → Sharing |
| OpenAI — share evaluation/fine-tuning data | Disabled | 2026-09-17 | Data controls → Sharing |
| OpenAI — share model feedback | Disabled | 2026-09-17 | Data controls → Sharing |
| OpenAI — hosted tools (5) | Disabled | 2026-09-17 | Data controls → Hosted tools |
| OpenAI — container network mode | Disabled | 2026-09-17 | Data controls → Hosted tools |
| OpenAI — API call logging | TODO → set Disabled | | Data controls → Data retention |
| OpenAI — audit logging | TODO → enable | | Data controls → Data retention |
| OpenAI — input/output retention | 30 days, fixed on current plan | 2026-09-17 | Not configurable |
| Sentry — `send_default_pii` | `False` | verified 2026-09-17 | `app.py:42`, `worker.py:119` |
| Sentry — `max_request_body_size` | `"never"` | verified 2026-09-17 | `app.py:43`, `worker.py:120` |
| OpenAI — `store` on API calls | never `True`; explicit `False` | verified 2026-09-17 | `services/life_engine.py:243` |

## Requests in flight

| Vendor | Sent | To | Asked for |
|---|---|---|---|
| Railway | 2026-09-17 | support/legal | DPA, sub-processor list, region availability |
| OpenAI | 2026-09-17 | privacy@openai.com | DPA execution route, confirmation that OpenAI Ireland Limited is the EU contracting entity, retention period on current plan, sub-processor list |

## Open items

1. **Supabase region unverified.** `privacy/page.tsx` claims EU region hosting for
   the primary datastore in two places (sub-processor table and § 12 Security).
   Confirm from Project Settings → General → Region, or correct the copy.
2. **R2 buckets are not EU-jurisdiction.** `services/r2_client.py` builds the
   default endpoint `https://{account}.r2.cloudflarestorage.com`. Jurisdiction is
   fixed at bucket creation and cannot be changed in place. Voice recordings are
   therefore not EU-pinned.
3. **Historic training exposure.** Optional data sharing with OpenAI was enabled
   (complimentary-tokens enrolment) until 2026-09-17 while the privacy policy
   stated inputs/outputs were not used for training. Disabling is forward-only.
   Start date unestablished — audit logging was not on.
4. **Retention rules may be unenforced.** `services/data_purge.py:231` resolves
   rules from the `data_retention_rules` table and no-ops with
   `RETENTION_RULE_UNRESOLVED` when a category has none;
   `scripts/run_phase1_data_purge.py:48` gates execution on
   `PHASE1_PURGE_EXECUTION_ENABLED`. Verify both in prod.
