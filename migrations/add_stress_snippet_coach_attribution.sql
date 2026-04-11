-- Add explicit coach attribution columns for stress snippet labels.
-- Keep legacy labeled_by for backward compatibility.

alter table if exists public.stress_snippets
    add column if not exists labeled_by_admin_id uuid null references auth.users(id) on delete set null;

alter table if exists public.stress_snippets
    add column if not exists labeled_by_admin_email text null;

create index if not exists idx_stress_snippets_labeled_by_admin_id
    on public.stress_snippets(labeled_by_admin_id);

