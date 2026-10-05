-- Retention report: what the cleaner WOULD delete. Read-only; changes nothing.
-- Founder 2026-10-05 (decisions log N45): "Q3b 30 days", "Q4 yes as
-- recommended" — the cleaner shows the list before its first real run, and
-- the real run waits for the founder's word.
--
-- RUN IN THE SUPABASE SQL EDITOR. Every statement is a SELECT. One row per
-- rule; nothing is listed by person.
--
-- THE THREE RULES
--   1. An unclaimed guest's recordings go 30 days after the guest was created
--      (a guest who signed up is claimed and is never counted).
--   2. Audio goes 12 months after last use. NOTHING RECORDS "LAST USE": no
--      column says when a recording was last opened or played. Until the
--      founder confirms a definition, this report uses the later of
--        (a) when the recording was made, and
--        (b) the last change to any project of its owner
--      (a claimed guest's recordings count under the account that claimed
--      them). Only recordings in processing_audio_objects are counted: the
--      older tables that hold audio without its fingerprint (recordings,
--      snippets, practice attempts, uploads) are not covered yet.
--   3. Technical logs go 90 days after creation. Only these tables, named
--      one by one: processing_jobs, dev_bugs, life_reminder_log,
--      admin_annotations_log, mlc3_service_backpressure_events. Evidence
--      tables (authorization, deletion, provider operations, claims) and the
--      financial records kept five years (token_ledger, llm_usage, N43) are
--      never on this list.

WITH cut AS (
    SELECT now() - interval '30 days'  AS guest_cut,
           now() - interval '12 months' AS audio_cut,
           now() - interval '90 days'  AS log_cut
),
old_guests AS (
    SELECT p.id
      FROM public.owner_principals p, cut
     WHERE p.user_id IS NULL
       AND p.guest_secret_hash IS NOT NULL
       AND p.claimed_at IS NULL
       AND p.created_at < cut.guest_cut
       AND NOT EXISTS (SELECT 1 FROM public.owner_claim_events e
                        WHERE e.source_owner_principal_id = p.id)
),
live_audio AS (
    SELECT o.id, o.created_at,
           COALESCE(op.claimed_by_owner_principal_id, op.id) AS owner_id
      FROM public.processing_audio_objects o
      JOIN public.owner_principals op ON op.id = o.acquisition_principal_id
     WHERE o.deleted_at IS NULL
),
unused_audio AS (
    SELECT a.id
      FROM live_audio a, cut
     WHERE a.created_at < cut.audio_cut
       AND NOT EXISTS (SELECT 1 FROM public.projects pr
                        WHERE pr.owner_principal_id = a.owner_id
                          AND pr.updated_at >= cut.audio_cut)
)
SELECT 1 AS rule, 'unclaimed guests older than 30 days' AS would_delete,
       (SELECT count(*) FROM old_guests) AS how_many
UNION ALL
SELECT 1, 'their recordings (audio files)',
       (SELECT count(*) FROM public.processing_audio_objects o
          JOIN old_guests g ON g.id = o.acquisition_principal_id
         WHERE o.deleted_at IS NULL)
UNION ALL
SELECT 2, 'audio files not used for 12 months',
       (SELECT count(*) FROM unused_audio)
UNION ALL
SELECT 3, 'log rows older than 90 days: processing_jobs',
       (SELECT count(*) FROM public.processing_jobs, cut WHERE created_at < cut.log_cut)
UNION ALL
SELECT 3, 'log rows older than 90 days: dev_bugs',
       (SELECT count(*) FROM public.dev_bugs, cut WHERE created_at < cut.log_cut)
UNION ALL
SELECT 3, 'log rows older than 90 days: life_reminder_log',
       (SELECT count(*) FROM public.life_reminder_log, cut WHERE created_at < cut.log_cut)
UNION ALL
SELECT 3, 'log rows older than 90 days: admin_annotations_log',
       (SELECT count(*) FROM public.admin_annotations_log, cut WHERE created_at < cut.log_cut)
UNION ALL
SELECT 3, 'log rows older than 90 days: mlc3_service_backpressure_events',
       (SELECT count(*) FROM public.mlc3_service_backpressure_events, cut WHERE created_at < cut.log_cut)
ORDER BY 1, 2;
