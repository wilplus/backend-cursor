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
| the 57 below | ✅ **RLS enabled — sweep RUN IN PROD 2026-07-25** (`add_rls_all_public_tables.sql`) |

**This gap is closed.** The founder ran the sweep in production on 2026-07-25 via
the Supabase SQL Editor, after a read-only preview of exactly which tables it
would touch. The list below is kept as the historical record of what was exposed
and for how the classes of data break down — it is *not* an outstanding to-do.

The list itself was derived from the migration FILES, so treat it as indicative
rather than exact. The authoritative live check is one query (and it should now
return **zero rows**):

```sql
SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = 'public' AND c.relkind IN ('r','p')
   AND c.relrowsecurity = false ORDER BY 1;
```

Or Supabase → **Advisors → Security Advisor → "RLS disabled in public"**, which
should be empty.

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

## The fix — `migrations/add_rls_all_public_tables.sql` ✅ APPLIED

Founder go-ahead 2026-07-25 ("security is non-negotiable, especially with EU
voice and transcript data"), and **run in production the same day**. One
idempotent sweep enabling RLS, **no policies**, on every public table that does
not already have it.

Keep the file: it is **self-healing**. Re-running it after any future migration
costs nothing (already-enabled tables are skipped) and catches anything that
slipped through — which is the cheap backstop for the standing rule at the
bottom of this document.

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

**If you re-run it, preview first.** The read-only query in the Status section
above lists exactly what a run would change, without changing anything. That is
the preview that was used before the production run.

Note for anyone re-running from a dev machine: there is no local Postgres or
Docker here and the founder has no `psql` or `DATABASE_URL`, so the working
channel is **Supabase → SQL Editor → paste → Run**, which executes the file as a
single transaction (a failure applies nothing).

### Residual risk, stated plainly

Every consumer visible in the two repos is service-role. A reader **not** visible
from here — a Supabase Edge Function, a Retool/Metabase dashboard, a Zapier/n8n
integration, an external script using the anon key — now returns **empty rather
than erroring loudly**. Nothing of the kind has been reported since the run, but
that is absence of evidence, not evidence of absence: if some integration
quietly stopped returning rows on 2026-07-25, this sweep is the first thing to
suspect. The fix is to give it the service-role key or an explicit policy —
**not** to turn RLS back off.

### Was the data ever actually readable? — still open, and now harder to answer

**Read this before assuming the matter is settled.** Closing the hole and
establishing whether it was ever exploited are two different questions, and only
the first one is done.

The empirical test — an anon-key `curl` against a sensitive table — had to be run
**before** the sweep to be informative. It was not, so that window has closed.
Running it today:

```
curl -s "https://<project>.supabase.co/rest/v1/charisma_snippets?select=id&limit=1" \
     -H "apikey: <ANON key>" -H "Authorization: Bearer <ANON key>"
```

should return `[]`, which confirms **the fix**, and says nothing about the
**history**. Do not read an empty result as "it was never exposed."

What can still answer it: **Supabase's PostgREST request logs**, checked for
anon-key reads of these tables before 2026-07-25, particularly from origins that
are not the app. Retention limits apply, so the sooner this is looked at the more
there is to look at.

Why it matters beyond tidiness: `charisma_snippets` holds per-snippet
**transcripts** and `v2_sessions` the recording metadata — EU voice data. If it
was in fact readable by anyone who opened the site's JS, that is a
GDPR-relevant finding and may warrant a breach assessment. I am not a lawyer;
this is flagged so the decision is made deliberately rather than by default.

## Standing rule going forward

**Every new `public`-schema table gets `ENABLE ROW LEVEL SECURITY` in the same
migration that creates it.** Adding it later is a separate migration that has to
be run separately, and until it is, the table is world-readable.
