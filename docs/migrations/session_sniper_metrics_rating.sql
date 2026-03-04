-- Session rating (admin/coach grade) and session_sniper_metrics FK note.
-- Run on your DB (Supabase or wherever v2_sessions and session_sniper_metrics live).
--
-- 1) Ensures v2_sessions has coach_grade (1-10) so PUT .../grade can persist admin_grade.
-- 2) session_sniper_metrics.session_id REFERENCES v2_sessions(id): the BFF or client
--    must only write to session_sniper_metrics for a session_id that already exists in
--    v2_sessions (e.g. created by POST /v2/homework/session/start). Otherwise the upsert
--    will fail on the foreign key.

-- Add coach_grade to v2_sessions if missing (idempotent).
DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'coach_grade'
  ) THEN
    ALTER TABLE v2_sessions ADD COLUMN coach_grade SMALLINT DEFAULT NULL
      CHECK (coach_grade >= 1 AND coach_grade <= 10);
  END IF;
END $$;

COMMENT ON COLUMN v2_sessions.coach_grade IS 'Admin/coach grade for this session (1-10). Set via PUT .../grade with body { admin_grade }. Returned as admin_grade in GET report.';
