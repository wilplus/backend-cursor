-- Arc batch delivery marker (founder 2026-07-13) — the explicit coach
-- "Publish arc" action: one row per arc, stamped when the coach delivers the
-- WHOLE training (all takes' labelled snippets + the finalized ideal text) to
-- the student as ONE batch. The per-take publish path is unchanged and
-- coexists; this row only says "the batch went out".
--
-- Idempotent; safe to re-run. RLS ON with no policies = service-role only
-- (the app reads/writes through the backend, never the client).

CREATE TABLE IF NOT EXISTS public.arc_batch_deliveries (
    arc_id       TEXT PRIMARY KEY,
    user_id      UUID NULL,
    coach_id     UUID NULL,
    published_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE public.arc_batch_deliveries ENABLE ROW LEVEL SECURITY;

-- Trainings-list lookup ("which of my arcs are batch-verified").
CREATE INDEX IF NOT EXISTS idx_arc_batch_deliveries_user
    ON public.arc_batch_deliveries (user_id);
