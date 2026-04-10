-- Voice Pipeline diagnostics: student homework recordings vs stress_snippets
-- Run in Supabase SQL Editor (service role / owner).
--
-- Notes:
-- - Student clips are tied to homework via v2_sessions.recording_1_id = recordings.id.
-- - recording_1_processing_status lives on v2_sessions (not recordings).
-- - Snippet provenance uses stress_snippets.source_type ('student' | 'internet').
-- - Scenario buckets: after_pause, before_pause, high_filler_density, low_filler_density, uncertain.
-- - Optional: public.recordings.recording_origin (admin_import) if migration add_admin_import_fields_to_recordings.sql ran.

-- 1) Recent student recording_1 rows and snippet counts (last 7 days)
SELECT
    r.id AS recording_id,
    r.created_at AS recording_created_at,
    vs.id AS session_id,
    vs.status AS session_status,
    vs.recording_1_processing_status,
    COUNT(s.id) AS snippet_count,
    COUNT(s.id) FILTER (WHERE s.scenario = 'before_pause') AS n_before_pause,
    COUNT(s.id) FILTER (WHERE s.scenario = 'after_pause') AS n_after_pause,
    COUNT(s.id) FILTER (WHERE s.scenario = 'high_filler_density') AS n_high_filler,
    COUNT(s.id) FILTER (WHERE s.scenario = 'low_filler_density') AS n_low_filler,
    COUNT(s.id) FILTER (WHERE s.scenario = 'uncertain') AS n_uncertain,
    COUNT(s.id) FILTER (WHERE s.coach_label IS NULL) AS n_unlabeled
FROM public.recordings r
JOIN public.v2_sessions vs ON vs.recording_1_id = r.id
LEFT JOIN public.stress_snippets s ON s.recording_id = r.id
WHERE r.created_at > NOW() - INTERVAL '7 days'
GROUP BY r.id, r.created_at, vs.id, vs.status, vs.recording_1_processing_status
ORDER BY r.created_at DESC;

-- 2) Completed processing but zero snippets (likely pipeline / migration / auto-extract off)
SELECT
    r.id AS recording_id,
    r.created_at,
    vs.id AS session_id,
    vs.recording_1_processing_status
FROM public.recordings r
JOIN public.v2_sessions vs ON vs.recording_1_id = r.id
LEFT JOIN public.stress_snippets s ON s.recording_id = r.id
WHERE vs.recording_1_processing_status = 'completed'
  AND s.id IS NULL
ORDER BY r.created_at DESC
LIMIT 200;
