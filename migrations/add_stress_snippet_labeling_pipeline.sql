-- Stress snippet labeling pipeline
-- Stores 10s candidate clips (student + internet imports) and binary coach labels.

create table if not exists public.stress_snippets (
    id uuid primary key default gen_random_uuid(),
    recording_id uuid not null references public.recordings(id) on delete cascade,
    session_id uuid null references public.v2_sessions(id) on delete set null,
    user_id uuid null references auth.users(id) on delete set null,
    source_type text not null check (source_type in ('student', 'internet')),
    scenario text not null check (scenario in ('after_pause', 'before_pause', 'high_filler_density', 'low_filler_density', 'uncertain')),
    start_ms integer not null check (start_ms >= 0),
    end_ms integer not null check (end_ms > start_ms),
    duration_ms integer not null check (duration_ms > 0),
    selection_score numeric(6,5) not null default 0,
    classifier_stress_probability numeric(6,5) null,
    classifier_confidence numeric(6,5) null,
    transcript_excerpt text null,
    storage_path text not null,
    features jsonb not null default '{}'::jsonb,
    coach_label text null check (coach_label in ('stress', 'no_stress')),
    coach_label_notes text null,
    labeled_by uuid null references auth.users(id) on delete set null,
    labeled_at timestamptz null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create unique index if not exists idx_stress_snippets_unique_span
    on public.stress_snippets(recording_id, scenario, start_ms, end_ms);

create index if not exists idx_stress_snippets_recording on public.stress_snippets(recording_id);
create index if not exists idx_stress_snippets_source_created on public.stress_snippets(source_type, created_at desc);
create index if not exists idx_stress_snippets_unlabeled on public.stress_snippets(source_type, coach_label, created_at desc);

grant all on table public.stress_snippets to service_role;
