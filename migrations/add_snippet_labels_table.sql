-- Snippet labels: structured per-axis labels from admin reviewers.
--
-- Independent of the existing stress_snippets.coach_label / charisma_snippets.coach_label
-- columns. This table lets one admin label BOTH charisma and stress on the same clip,
-- supports multi-labeler later via the (snippet_id, labeler_admin_id) unique index,
-- and is the canonical source for the future training-export script.
--
-- v0 scope: clips are drawn from stress_snippets only (the larger candidate pool).
-- A future migration can make this polymorphic across stress_snippets / charisma_snippets
-- by adding a `snippet_source` column and dropping the FK.

create table if not exists public.snippet_labels (
    id uuid primary key default gen_random_uuid(),
    snippet_id uuid not null references public.stress_snippets(id) on delete cascade,
    charisma smallint null check (charisma in (0, 1)),
    stress   smallint null check (stress   in (0, 1)),
    confidence text not null default 'high' check (confidence in ('low', 'high')),
    notes text null,
    labeler_admin_id uuid not null references public.admin_users(id) on delete restrict,
    labeled_at timestamptz not null default now(),
    created_at timestamptz not null default now(),
    constraint snippet_labels_at_least_one_axis check (charisma is not null or stress is not null)
);

create index if not exists idx_snippet_labels_snippet on public.snippet_labels(snippet_id);
create index if not exists idx_snippet_labels_labeler on public.snippet_labels(labeler_admin_id, labeled_at desc);
create unique index if not exists idx_snippet_labels_one_per_labeler
    on public.snippet_labels(snippet_id, labeler_admin_id);

grant all on table public.snippet_labels to service_role;

-- down: drop table if exists public.snippet_labels;
