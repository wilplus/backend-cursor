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
| the 57 below | ❌ their migration does not enable RLS |

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

## Recommended fix

One idempotent sweep migration enabling RLS (no policies) on every table the
Security Advisor still flags. Not written yet — it needs a founder go-ahead,
because although every consumer I can see is service-role, a reader I *cannot*
see (a Supabase Edge Function, a Retool/Metabase dashboard, a Zapier or n8n
integration, an external script using the anon key) would start failing
silently. Confirm the Advisor list, confirm no such consumer, then sweep.

## Standing rule going forward

**Every new `public`-schema table gets `ENABLE ROW LEVEL SECURITY` in the same
migration that creates it.** Adding it later is a separate migration that has to
be run separately, and until it is, the table is world-readable.
