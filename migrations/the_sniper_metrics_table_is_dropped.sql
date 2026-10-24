-- 0491 · session_sniper_metrics is dropped (founder 2026-10-24).
--
-- WHAT IT WAS. The retired Sniper dartboard's per-session aggregates (wpm,
-- pause_ms, dynamic_db, energy, a stage score and a 1-10 self-rating),
-- written by the client and folded into user_sniper_profile. Nothing in
-- either repo writes or reads it any more: the frontend Sniper code is gone,
-- and the last writer, scripts/backfill_sniper_metrics.py, called a db method
-- that no longer exists and is deleted in the same PR as this file. Prod held
-- 143 rows, the newest 2026-06-02, and no foreign key points at it.
--
-- WHY THE FUNCTION COMES FIRST. 0423 lists the table among a recording's
-- voice-measurement stores (retention_measurement_stores_v1), and the
-- retention cleaner deletes nothing when that list and its own
-- TAKE_MEASUREMENT_ROWS disagree. So the list is re-issued here without the
-- table, in the same transaction as the drop, and the code's list changes in
-- the same PR. Between this running and that deploy, the cleaner refuses
-- with RETENTION_REGISTRY_MISMATCH (it deletes nothing) and the account
-- purge treats the missing table as empty (services/data_purge.py,
-- _missing_relation). Neither loses anything.
--
-- user_sniper_profile is NOT dropped: the founder kept it (2026-10-24).
--
-- DESTRUCTIVE: DROP TABLE. scripts/migrate.py refuses it at boot, and an
-- un-applied destructive file in the manifest blocks every deploy (#359). So
-- it is APPLIED BY HAND in the Supabase SQL editor and recorded in
-- schema_migrations BEFORE the PR that adds it to the manifest merges.
--
-- SAFE TO RUN TWICE: CREATE OR REPLACE and DROP TABLE IF EXISTS.

BEGIN;

CREATE OR REPLACE FUNCTION public.retention_measurement_stores_v1()
RETURNS TABLE (
    store text, relation text, scope text, action text, key_column text,
    columns text[]
)
LANGUAGE sql IMMUTABLE SET search_path = public
AS $$
    SELECT * FROM (VALUES
        ('acoustic_feature_snapshots.features', 'acoustic_feature_snapshots',
         'take', 'wipe', 'evidence_span_id', ARRAY['features']),
        ('arc_part_acoustics', 'arc_part_acoustics',
         'account', 'delete', 'user_id', NULL::text[]),
        ('candidate_windows.metrics', 'candidate_windows',
         'take', 'wipe', 'session_id', ARRAY['metrics']),
        ('dimension_evaluations', 'dimension_evaluations',
         'take', 'delete', 'session_id', NULL::text[]),
        ('snippets.metrics', 'snippets',
         'take', 'wipe', 'session_id', ARRAY['metrics']),
        ('user_acoustic_baseline', 'user_acoustic_baseline',
         'account', 'delete', 'user_id', NULL::text[]),
        ('v2_sessions.voice_measures', 'v2_sessions',
         'take', 'wipe', 'id', ARRAY['global_wpm', 'global_pause_ms',
                                     'global_dynamic_db', 'global_pitch_center',
                                     'global_energy', 'kpi_score'])
    ) AS s(store, relation, scope, action, key_column, columns)
$$;

DROP TABLE IF EXISTS public.session_sniper_metrics;

COMMIT;
