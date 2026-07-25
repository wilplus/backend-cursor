# RLS audit — public-schema tables without row level security

Raised while reviewing the Journal migration (2026-07-25). The Journal review
surfaced a HIGH-severity class of problem, and it is not specific to the
Journal.

## The exposure

The FE ships `NEXT_PUBLIC_SUPABASE_ANON_KEY` inlined into the browser bundle
(`NEXT_PUBLIC_*` is compile-time inlined by Next). Any visitor can read it out
of the JS and call PostgREST directly:

```
GET https://<project>.supabase.co/rest/v1/<table>?select=*
     apikey: <anon key from the bundle>
```

With RLS **off** on a `public` table, Supabase's default grants to `anon` /
`authenticated` make that read succeed — and often `POST`/`PATCH`/`DELETE` too.
This bypasses Flask entirely, so **no amount of API-side owner checking or
`published_only` filtering defends it.** RLS is the only control on that path.

## Why enabling it is safe here

Verified before recommending:

- The backend connects with `SUPABASE_SERVICE_ROLE_KEY` (`services/db.py`),
  which **bypasses RLS** — enabling RLS does not restrict the API.
- The backend never uses the anon key at runtime (only `get_token.py`, a dev
  script, and archived files under `docs/` mention it).
- The FE performs **no direct table reads**: its only `.from()` calls are
  `supabase.storage.from(bucket)`. The one `.from("v2_sessions")` occurrence is
  inside a comment describing a previous version that now routes through Flask.

So `ENABLE ROW LEVEL SECURITY` with **zero policies** is the right shape:
`anon` can do nothing, the backend keeps full access.

## Status

| Table | State |
|---|---|
| `journal_post` | ✅ RLS enabled (`add_journal_posts.sql`) |
| `arc_context_documents` | ✅ RLS enabled (`add_rls_arc_context_documents.sql`) — holds users' uploaded document text |
| the 57 below | 🟡 covered by the sweep (`add_rls_all_public_tables.sql`) — **not yet run in prod** |

**⚠️ The list below is derived from the migration FILES, not the live database.**
RLS may have been enabled manually in the Supabase dashboard for some of these.
The authoritative check is Supabase → **Advisors → Security Advisor → "RLS
disabled in public"**. Confirm there before acting.

### Highest sensitivity (user content / PII)

`charisma_snippets` (per-snippet transcripts), `v2_sessions`, `v2_reports`,
`recording_reviews`, `recording_review_annotations`, `recording_feelings`,
`user_consents`, `user_consent_events`, `user_uploaded_files`, `user_audits`,
`user_settings`, `student_profile`, `v2_speaker_profiles`,
`v2_student_coaching_memory`, `user_sniper_profile`, `session_sniper_metrics`,
`coaching_sessions`, `coaching_attempts`, `coaching_attempt_annotations`,
`best_presentation_edits`, `best_presentation_cache`, `arc_purchases`,
`arc_invite_codes`, `rejected_takes`, `candidate_windows`

### Internal / operational

`acoustic_labels`, `admin_annotation_events`, `admin_annotation_export_runs`,
`admin_annotations_log`, `admin_session_overrides`, `admin_student_send_drafts`,
`admin_uploaded_reference_videos`, `copilot_reference_upload_jobs`,
`model_training_runs`, `runtime_config`, `coaching_directives_queue`,
`content_exposures`, `funnel_config`

### Content pools (low sensitivity, but writable without RLS)

`casual_voice_benchmarks`, `chat_question_pool`, `dad_jokes`, `v2_exercises`,
`v2_focus_question_pool`, `v2_focus_questions`, `v2_focus_task_pool`,
`v2_focus_tasks`, `v2_metric_definitions`, `v2_metric_questions`,
`v2_metric_questions_pool`, `v2_post_recording_questions`,
`v2_post_recording_questions_pool`, `v2_student_overrides`,
`v2_student_post_recording_questions`, `v2_tasks`, `v2_universal_questions`,
`v2_warm_up_task_pool`, `v2_warm_up_tasks`, `session_command_options`

## The fix — `migrations/add_rls_all_public_tables.sql`

Founder go-ahead 2026-07-25 ("security is non-negotiable, especially with EU
voice and transcript data"). One idempotent sweep enabling RLS, **no policies**,
on every public table that does not already have it.

**Dynamic, not a fixed list.** It sweeps what the LIVE database reports
(`pg_class.relrowsecurity`) rather than the file-derived list above, which can be
stale, can miss a table created in the dashboard, and can name tables that never
shipped. So it is also self-healing: re-run it after any future migration and it
catches whatever slipped through.

Guards: skips tables that already have RLS (re-runs are true no-ops); skips
**extension-owned** tables via `pg_depend` (enabling RLS on e.g. PostGIS's
`spatial_ref_sys` would break the extension — only `pgcrypto` and `uuid-ossp` are
installed today and neither creates tables, but the guard survives that
changing); covers partitioned tables (`relkind IN ('r','p')`); `RAISE NOTICE` per
table plus a summary, so the run is auditable.

**Dry-run it first.** DDL is transactional in Postgres:

```
BEGIN;
\i migrations/add_rls_all_public_tables.sql
-- read the NOTICE lines
ROLLBACK;      -- nothing changed; re-run with COMMIT when satisfied
```

⚠️ The SQL has **not been executed against any database** — there is no local
Postgres or Docker in the dev environment to validate it against. Structure was
verified statically (block/quote/placeholder balance) only. Do the dry run.

### Residual risk, stated plainly

Every consumer I can see is service-role. A reader I **cannot** see — a Supabase
Edge Function, a Retool/Metabase dashboard, a Zapier/n8n integration, an
external script using the anon key — would start returning empty rather than
erroring loudly. If any of those exist, grant them the service-role key or add
an explicit policy; do not turn RLS back off.

### Was this ever actually exploited?

Worth establishing, not assuming. The exposure is a *default-grants* question, so
confirm empirically **before** running the sweep — this is also how you prove the
sweep worked:

```
curl -s "https://<project>.supabase.co/rest/v1/charisma_snippets?select=id&limit=1" \
     -H "apikey: <ANON key>" -H "Authorization: Bearer <ANON key>"
```

Rows back ⇒ the data was world-readable to anyone who opened the site's JS.
Given this is EU voice and transcript data, that is a GDPR-relevant finding and
may warrant a breach assessment — worth a look at Supabase's PostgREST request
logs for anon-key reads of these tables from unexpected origins. I am not a
lawyer; flagging it so the call is yours and informed.

## Standing rule going forward

**Every new `public`-schema table gets `ENABLE ROW LEVEL SECURITY` in the same
migration that creates it.** Adding it later is a separate migration that has to
be run separately, and until it is, the table is world-readable.
