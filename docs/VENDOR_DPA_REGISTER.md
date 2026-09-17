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
| Cloudflare (R2) | Processor | The voice/video objects themselves | BY-REF | 2026-09-17 | SCCs | **EEUR** (Eastern Europe) location hint on all buckets; default jurisdiction, not EU-pinned | |
| Supabase | Processor | Accounts, transcripts, feedback, auth | BY-REF | 2026-09-17 | SCCs + UK addendum (in DPA); data at rest in EU | **eu-west-1** — West EU (Ireland), confirmed 2026-09-17 | |
| Railway | Processor | Compute + Redis queue payloads | REQUESTED | 2026-09-17 | | | |
| Resend | Processor | Email addresses + rendered session-result content | TODO | | | | |
| Sentry | Processor | Error telemetry (PII suppressed — see below) | SIGNED — DPA v5.1.0 | 2026-09-17 | EU storage region; SCCs in DPA | **European Union (EU)** | `Sentry_DPA_2026-09-17.pdf` |
| Vercel | Processor | Frontend hosting + internal email render endpoint | BY-REF | 2026-09-17 | SCCs deemed signed on acceptance of ToS | US | `Vercel_DPA_2026-09-17.pdf` |
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
| OpenAI — API call logging | Disabled | 2026-09-17 | Data controls → Data retention |
| OpenAI — audit logging | Enabled | 2026-09-17 | Data controls → Data retention |
| OpenAI — input/output retention | 30 days, fixed on current plan | 2026-09-17 | Not configurable |
| OpenAI — project residency | `Global` (not region-pinned) | 2026-09-17 | Project settings → General |
| Sentry — `send_default_pii` | `False` | verified 2026-09-17 | `app.py:42`, `worker.py:119` |
| Sentry — `max_request_body_size` | `"never"` | verified 2026-09-17 | `app.py:43`, `worker.py:120` |
| Sentry — use of aggregated identifying data | Off | 2026-09-17 | Legal & Compliance → Service data usage |
| Sentry — data storage region | European Union | 2026-09-17 | Legal & Compliance → General |
| OpenAI — `store` on API calls | never `True`; explicit `False` | verified 2026-09-17 | `services/life_engine.py:243` |

All OpenAI account-side controls are now set. What remains for OpenAI is the
DPA itself (requested 2026-09-17) and, optionally, EU project residency.

## Vendor assurance evidence held

Sentry (downloaded 2026-09-17): SOC 2 report, penetration test summary
(Sep 2026), Security Overview, Data Privacy Framework certificate,
ISO 27001:2022 certificate. Filed alongside the DPAs.

## Requests in flight

| Vendor | Sent | To | Asked for |
|---|---|---|---|
| Railway | 2026-09-17 | support/legal | DPA, sub-processor list, region availability |
| OpenAI | 2026-09-17 | privacy@openai.com | DPA execution route, confirmation that OpenAI Ireland Limited is the EU contracting entity, retention period on current plan, sub-processor list; also ask whether EU project residency is available on our plan |

## Standing risk — production stack on free/hobby tiers

Noted 2026-09-17, not a data-protection finding but a continuity one:

| Service | Tier | Exposure |
|---|---|---|
| Supabase | Free | No database backups (see open item 4) |
| Vercel | Hobby | Hobby is for personal, non-commercial use; willpowerlab.com takes payment via Stripe. Suspension would take the frontend down without notice |
| OpenAI | was on complimentary daily tokens | Ended 2026-09-17 when data sharing was disabled; account now runs on paid credit |

The live loop currently depends on services with no contractual obligation
to keep it running.

## Open items

1. ~~Supabase region unverified.~~ **RESOLVED 2026-09-17** — project is in an EU
   region, so the "EU region hosting" claim in the sub-processor table and § 12
   Security is accurate and needs no correction. Region is `eu-west-1`
   (West EU, Ireland). DPA at supabase.com/legal/dpa takes effect on acceptance
   of the terms and incorporates the SCCs and the UK addendum; a Transfer Impact
   Assessment is published alongside it. Save both as dated PDFs.
2. **R2 buckets are in Europe but not EU-jurisdiction.** All buckets report the
   `EEUR` (Eastern Europe) location hint (verified 2026-09-17), so recordings are
   physically stored in Europe. However `services/r2_client.py` builds the default
   endpoint `https://{account}.r2.cloudflarestorage.com` rather than the
   `.eu.r2.cloudflarestorage.com` jurisdiction endpoint, so this is a placement
   hint and not a contractual restriction. Jurisdiction is fixed at bucket creation
   and cannot be changed in place. Transfers are covered by the SCCs in
   Cloudflare's DPA. Priority: low — revisit only if an EU-residency guarantee is
   required. Open question for Cloudflare: which countries the EEUR region covers,
   since Eastern Europe includes non-EEA states.
3. **Historic training exposure.** Optional data sharing with OpenAI was enabled
   (complimentary-tokens enrolment) until 2026-09-17 while the privacy policy
   stated inputs/outputs were not used for training. Disabling is forward-only.
   Start date unestablished — audit logging was not on.
4. **No database backups (Art. 32 resilience gap).** The Supabase project is on
   the Free plan and the dashboard reports "Last backup: No backups"
   (observed 2026-09-17). Art. 32(1)(c) requires the ability to restore
   availability and access to personal data in a timely manner after an
   incident. The production database holds accounts, transcripts and feedback.
   A paid plan enables automated backups. Founder decision 2026-09-17: remain on
   the Free plan for now, so the gap must be closed another way — a scheduled
   `pg_dump` to encrypted off-site storage would satisfy the restore requirement
   without a plan change. Not yet implemented.

5. **Retention rules may be unenforced.** `services/data_purge.py:231` resolves
   rules from the `data_retention_rules` table and no-ops with
   `RETENTION_RULE_UNRESOLVED` when a category has none;
   `scripts/run_phase1_data_purge.py:48` gates execution on
   `PHASE1_PURGE_EXECUTION_ENABLED`. Verify both in prod.
