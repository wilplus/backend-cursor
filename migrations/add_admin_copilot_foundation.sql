-- Admin Copilot Inbox + Acoustic Dojo foundation
-- Safe to run multiple times.

-- 1) student_profile (new canonical profile table; replaces legacy user_sniper_profile gradually)
CREATE TABLE IF NOT EXISTS public.student_profile (
  user_id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  session_count INT NOT NULL DEFAULT 0,
  sessions_with_energy_count INT NOT NULL DEFAULT 0,
  baseline_wpm FLOAT,
  baseline_pause_ms FLOAT,
  baseline_dynamic_db FLOAT,
  baseline_emphasis_per_min FLOAT,
  baseline_energy_ratio FLOAT,
  baseline_fatigue_sec FLOAT,
  realtime_level INT NOT NULL DEFAULT 1,
  realtime_step INT NOT NULL DEFAULT 1,
  realtime_pitch_baseline_st FLOAT NULL,
  sessions_with_pitch_count INT NOT NULL DEFAULT 0,
  realtime_last_completed_session_id UUID NULL,
  behavioral_profile TEXT,
  behavioral_profile_justification TEXT,
  coach_override_profile TEXT,
  profile_override_justification TEXT,
  computed_stage INT CHECK (computed_stage BETWEEN 1 AND 5),
  coach_override_stage INT CHECK (coach_override_stage BETWEEN 1 AND 5),
  stage_override_justification TEXT,
  consecutive_below_threshold INT NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Backfill from legacy profile table if present.
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'public' AND table_name = 'user_sniper_profile'
  ) THEN
    INSERT INTO public.student_profile (
      user_id,
      session_count,
      sessions_with_energy_count,
      baseline_wpm,
      baseline_pause_ms,
      baseline_dynamic_db,
      baseline_emphasis_per_min,
      baseline_energy_ratio,
      baseline_fatigue_sec,
      realtime_level,
      realtime_step,
      realtime_pitch_baseline_st,
      sessions_with_pitch_count,
      realtime_last_completed_session_id,
      created_at,
      updated_at
    )
    SELECT
      usp.user_id,
      COALESCE(usp.session_count, 0),
      COALESCE(usp.sessions_with_energy_count, 0),
      usp.baseline_wpm,
      usp.baseline_pause_ms,
      usp.baseline_dynamic_db,
      usp.baseline_emphasis_per_min,
      usp.baseline_energy_ratio,
      usp.baseline_fatigue_sec,
      COALESCE(usp.realtime_level, 1),
      COALESCE(usp.realtime_step, 1),
      usp.realtime_pitch_baseline_st,
      COALESCE(usp.sessions_with_pitch_count, 0),
      usp.realtime_last_completed_session_id,
      COALESCE(usp.created_at, NOW()),
      COALESCE(usp.updated_at, NOW())
    FROM public.user_sniper_profile usp
    ON CONFLICT (user_id) DO NOTHING;
  END IF;
END $$;

-- 2) Extend sessions for insight audit
ALTER TABLE public.v2_sessions
  ADD COLUMN IF NOT EXISTS coach_corrected_insight TEXT,
  ADD COLUMN IF NOT EXISTS is_insight_audited BOOLEAN NOT NULL DEFAULT FALSE;

-- 3) Acoustic labels (audio-only dojo)
CREATE TABLE IF NOT EXISTS public.acoustic_labels (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  clip_source TEXT NOT NULL CHECK (clip_source IN ('student_recording', 'external')),
  recording_id UUID NULL REFERENCES public.recordings(id) ON DELETE CASCADE,
  start_ms INT NOT NULL DEFAULT 0,
  end_ms INT NOT NULL CHECK (end_ms > start_ms),
  external_url TEXT NULL,
  label_stress BOOLEAN NOT NULL,
  label_charisma BOOLEAN NOT NULL,
  confidence INT NULL CHECK (confidence BETWEEN 1 AND 3),
  labeled_by UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  labeled_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_acoustic_labels_recording_id ON public.acoustic_labels(recording_id);
CREATE INDEX IF NOT EXISTS idx_acoustic_labels_labeled_by ON public.acoustic_labels(labeled_by);
CREATE INDEX IF NOT EXISTS idx_acoustic_labels_labeled_at ON public.acoustic_labels(labeled_at DESC);

-- 4) Structured annotation events for DPO pairs
CREATE TABLE IF NOT EXISTS public.admin_annotation_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id UUID NULL REFERENCES public.v2_sessions(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  section_type TEXT NOT NULL,
  field_name TEXT NOT NULL,
  ai_original_text TEXT NULL,
  coach_final_text TEXT NULL,
  reason_chip TEXT NULL,
  custom_reason TEXT NULL,
  created_by UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_admin_annotation_events_session ON public.admin_annotation_events(session_id);
CREATE INDEX IF NOT EXISTS idx_admin_annotation_events_user ON public.admin_annotation_events(user_id);
CREATE INDEX IF NOT EXISTS idx_admin_annotation_events_created_at ON public.admin_annotation_events(created_at DESC);

-- 5) Draft-first cohort staging table
CREATE TABLE IF NOT EXISTS public.admin_student_send_drafts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  session_id UUID NULL REFERENCES public.v2_sessions(id) ON DELETE SET NULL,
  cohort_profile TEXT NOT NULL,
  cohort_stage INT NOT NULL CHECK (cohort_stage BETWEEN 1 AND 5),
  master_task_text TEXT NOT NULL,
  draft_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'ready', 'sent', 'cancelled')),
  approved_by UUID NULL REFERENCES auth.users(id) ON DELETE SET NULL,
  sent_at TIMESTAMPTZ NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_admin_student_send_drafts_user_status
  ON public.admin_student_send_drafts(user_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_admin_student_send_drafts_cohort
  ON public.admin_student_send_drafts(cohort_profile, cohort_stage, status);

-- 6) Grants (service role)
GRANT ALL ON TABLE public.student_profile TO service_role;
GRANT ALL ON TABLE public.acoustic_labels TO service_role;
GRANT ALL ON TABLE public.admin_annotation_events TO service_role;
GRANT ALL ON TABLE public.admin_student_send_drafts TO service_role;
