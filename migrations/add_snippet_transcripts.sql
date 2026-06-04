-- Per-snippet Whisper transcripts.
--
-- Adds transcript, language, words (word-level timestamps), and transcribed_duration_ms
-- to BOTH stress_snippets and charisma_snippets. All nullable so existing rows stay
-- valid; backfill via scripts/backfill_snippet_transcripts.py.
--
-- Unblocks:
--   - accurate per-snippet WPM (today the snippet borrows the parent's WPM)
--   - per-snippet filler density (today filler features come from the parent transcript)
--   - language detection per snippet (prerequisite for multilingual filler lists)
--   - word-level timing features for future text-conditioned models

alter table public.stress_snippets
    add column if not exists transcript text null,
    add column if not exists language text null,
    add column if not exists words jsonb null,
    add column if not exists transcribed_duration_ms integer null;

alter table public.charisma_snippets
    add column if not exists transcript text null,
    add column if not exists language text null,
    add column if not exists words jsonb null,
    add column if not exists transcribed_duration_ms integer null;

create index if not exists idx_stress_snippets_language on public.stress_snippets(language) where language is not null;
create index if not exists idx_charisma_snippets_language on public.charisma_snippets(language) where language is not null;

-- Partial indexes to make "find untranscribed" cheap for the backfill script.
create index if not exists idx_stress_snippets_untranscribed
    on public.stress_snippets(created_at)
    where transcript is null;
create index if not exists idx_charisma_snippets_untranscribed
    on public.charisma_snippets(created_at)
    where transcript is null;

-- down:
--   alter table public.stress_snippets
--     drop column if exists transcript,
--     drop column if exists language,
--     drop column if exists words,
--     drop column if exists transcribed_duration_ms;
--   alter table public.charisma_snippets
--     drop column if exists transcript,
--     drop column if exists language,
--     drop column if exists words,
--     drop column if exists transcribed_duration_ms;
