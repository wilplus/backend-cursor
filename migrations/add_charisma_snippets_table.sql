-- Charisma Snippets: Auto-extracted 10-15s segments from guest funnel recordings
-- Admin can add comments and label these snippets, which are then shown to users on /results page

CREATE TABLE IF NOT EXISTS charisma_snippets (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id UUID NOT NULL REFERENCES v2_sessions(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  recording_id UUID NOT NULL REFERENCES recording_1(id) ON DELETE CASCADE,
  -- Timing within the original recording (in milliseconds)
  start_offset_ms INTEGER NOT NULL,
  duration_ms INTEGER NOT NULL,
  -- S3/Supabase Storage path to the extracted snippet audio file
  audio_segment_path TEXT NOT NULL,
  -- Label assigned by admin: charisma (positive), stress (concern), or unlabeled (default)
  snippet_type VARCHAR DEFAULT 'unlabeled' CHECK (snippet_type IN ('charisma', 'stress', 'unlabeled')),
  -- Admin's text feedback on this specific snippet
  admin_comment TEXT,
  -- Who added the comment (admin user)
  admin_user_id UUID REFERENCES admin_users(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_charisma_snippets_user_id ON charisma_snippets(user_id);
CREATE INDEX IF NOT EXISTS idx_charisma_snippets_session_id ON charisma_snippets(session_id);
CREATE INDEX IF NOT EXISTS idx_charisma_snippets_recording_id ON charisma_snippets(recording_id);
-- Partial index: only snippets with admin comments (the ones shown to users)
CREATE INDEX IF NOT EXISTS idx_charisma_snippets_with_comments ON charisma_snippets(session_id)
  WHERE admin_comment IS NOT NULL;
-- Partial index: find unlabeled snippets for admin review
CREATE INDEX IF NOT EXISTS idx_charisma_snippets_unlabeled ON charisma_snippets(user_id, created_at DESC)
  WHERE snippet_type = 'unlabeled';
