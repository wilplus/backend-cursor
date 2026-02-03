-- Speaker profile (admin-editable per student): goals, notes, coach notes.
-- Used by admin panel "Speaker Profile" section.
-- Backend uses this exact table name and columns: services/db.py v2_get_speaker_profile, v2_upsert_speaker_profile.
-- Schema: public (default). Run in Supabase SQL Editor; reload schema cache if table still not found.
CREATE TABLE IF NOT EXISTS v2_speaker_profiles (
  user_id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  main_goal TEXT,
  motivation TEXT,
  strong_points TEXT,
  weak_points TEXT,
  charismatic_traits TEXT,
  hobbies_interests TEXT,
  personality_type TEXT,
  coach_notes TEXT,
  updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_v2_speaker_profiles_updated ON v2_speaker_profiles(updated_at);
