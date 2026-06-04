-- Persist Whisper-detected language on the parent recording.
--
-- Activates multilingual filler detection in services/stress_snippet_service.py:
-- candidate generation reads recordings.transcription_language to pick the right
-- filler list (see utils/filler_words.py).
--
-- Nullable; older rows stay valid and fall back to English in the lookup.
-- ISO 639-1 codes (e.g. "en", "pl", "es", "de").

alter table public.recordings
    add column if not exists transcription_language text null;

create index if not exists idx_recordings_transcription_language
    on public.recordings(transcription_language)
    where transcription_language is not null;

-- down:
--   alter table public.recordings drop column if exists transcription_language;
