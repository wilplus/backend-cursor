# Supabase Schema Requirements for Recordings Table

This document lists all columns required by the Flask backend for the `recordings` table.

## Required Columns

Run this SQL in Supabase SQL Editor to ensure all columns exist:

```sql
-- Add all missing columns for recordings table
ALTER TABLE public.recordings
ADD COLUMN IF NOT EXISTS classification TEXT,
ADD COLUMN IF NOT EXISTS confidence TEXT,
ADD COLUMN IF NOT EXISTS duration_seconds NUMERIC,
ADD COLUMN IF NOT EXISTS storage_path TEXT,
ADD COLUMN IF NOT EXISTS transcription_text TEXT,
ADD COLUMN IF NOT EXISTS coaching_report TEXT,
ADD COLUMN IF NOT EXISTS trend_sentence TEXT;

-- Verify all columns exist
SELECT 
    column_name, 
    data_type, 
    is_nullable
FROM information_schema.columns
WHERE table_schema = 'public' 
  AND table_name = 'recordings'
ORDER BY column_name;
```

## Column Details

### Required (NOT NULL)
- `id` (UUID, PRIMARY KEY)
- `user_id` (UUID, NOT NULL)
- `audio_url` (TEXT, NOT NULL) - Public URL to audio file
- `duration` (INTEGER, NOT NULL) - Duration in seconds (rounded)

### Optional but Used by Backend
- `session_id` (UUID) - Links to recording_sessions table
- `transcription_text` (TEXT) - Full transcript from Whisper
- `duration_seconds` (NUMERIC) - Precise duration (can be float)
- `words_per_minute` (NUMERIC) - Calculated WPM
- `filler_words_count` (JSONB) - `{"total": int, "breakdown": {...}}`
- `classification` (TEXT) - Speech classification (e.g., "confident", "uncertain")
- `confidence` (TEXT) - Confidence level (e.g., "high", "medium", "low")
- `storage_path` (TEXT) - Path in Supabase Storage bucket
- `coaching_report` (TEXT) - Final coaching report generated after post-answers
- `trend_sentence` (TEXT) - Trend analysis sentence
- `created_at` (TIMESTAMP)
- `updated_at` (TIMESTAMP)

## Notes

- `duration` is INTEGER (required)
- `duration_seconds` is NUMERIC (optional, for precision)
- `confidence` is TEXT, not NUMERIC
- `classification` is TEXT
- `coaching_report` and `trend_sentence` are added when post-answers are submitted
