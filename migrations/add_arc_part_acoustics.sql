-- 0269 · arc_part_acoustics — the moving average per part, and the ratchet.
--
-- Founder 2026-08-12, item 6: "ISOLATE THE WEAKEST LINK. Identify the single
-- most consistently underperforming part. Route all feedback and
-- interventions to that specific part. Suppress feedback everywhere else…
-- The Ratchet: only when that weakest part surpasses the baseline and 'comes
-- onboard' does the system unlock feedback for the next underperforming part."
--
-- Three facts have to survive between takes for that sentence to be
-- implementable: how each part has been doing (the moving average), which
-- part is currently the focus (derived from it), and whether a part has ever
-- come onboard (the latch). Only the first and third are stored — the focus
-- is DERIVED, for the same reason migration 0256 refuses to store `phase`: a
-- stored focus can desync from the measurements that are supposed to imply
-- it, and then two places disagree about where the feedback should go.
--
-- ── WHY THIS IS NOT COLUMNS ON ideal_text_part ─────────────────────────────
--
-- Because that table cannot hold anything that accumulates. Parts are written
-- by db.replace_ideal_text_parts, which is DELETE-THEN-INSERT wholesale (0255
-- explains why: a reorder changes many rows' `ord` at once and a per-row
-- upsert transiently violates uq_ideal_text_part_slot). The insert names
-- seven columns. Every other column on the table silently returns to its
-- DEFAULT on every replace.
--
-- This is not hypothetical — `iteration` (0265) is already losing this way,
-- and the three call sites prove the shape of the hazard: all three carefully
-- read `locked_at` back and thread it through, and none of them mentions
-- `iteration`, because preserving a column is opt-in and forgetting is the
-- default. A part's take history would be wiped by the compose path on the
-- very next GET after a new take.
--
-- So the accumulator lives BESIDE the part, keyed on the part id — which
-- 0255 built to be exactly this: stable, client-minted, and explicitly not
-- version-scoped, so it survives reordering, rewording and version bumps.
--
-- ── EMA, NOT A MEAN OVER ALL TAKES ─────────────────────────────────────────
--
-- "Most consistently underperforming" has to weight recent takes more than
-- the first one, or a part the student has genuinely fixed keeps its early
-- bad takes forever and stays the focus long after it stopped deserving to
-- be. An exponential moving average forgets at a fixed rate and needs one
-- number of state instead of the whole history — which also means this table
-- stays one row per part rather than one row per (part, take).
--
-- ── came_onboard_at IS A TIMESTAMP, AND IT IS THE RATCHET ──────────────────
--
-- Set the first time a part's moving average crosses its baseline; NEVER
-- cleared. That is what makes it a ratchet rather than a threshold: a part
-- that comes onboard and then has one bad take does not re-capture the focus,
-- which is the entire point of the founder's sequencing (fix one thing, keep
-- it, move on). A boolean would work for the latch but could not say WHEN —
-- and the same argument 0256 makes for locked_at applies: a decision taken
-- before a part came onboard and one taken after mean different things.
--
-- ── baseline_id, BECAUSE THE KPI IS A COMPARISON ───────────────────────────
--
-- ema_z is meaningless without the reference it was measured against. Storing
-- the baseline row's id makes every stored average reproducible and makes a
-- regime change VISIBLE (rows pointing at a superseded baseline are readable
-- as such) rather than silently mixing two references into one series.
--
-- Idempotent. Safe to re-run. Non-destructive: new table only.

BEGIN;

CREATE TABLE IF NOT EXISTS public.arc_part_acoustics (
    -- ideal_text_part.id — stable across reorder, reword and version bumps
    -- (0255). No FK: parts are delete-then-inserted wholesale, so a FK would
    -- either cascade this history away or reject the parts write outright.
    part_id           UUID        PRIMARY KEY,

    arc_id            TEXT        NOT NULL,
    user_id           TEXT        NOT NULL,

    -- THE KPI. The part's moving average, expressed in z against the user's
    -- OWN baseline: negative = below where this speaker normally is on this
    -- material, positive = above. Never surfaced (AC-9) — it orders
    -- interventions and routes focus, and nothing else.
    ema_z             DOUBLE PRECISION NOT NULL,

    -- How many takes have folded into ema_z. The evidence behind the number:
    -- a part seen once is not "consistently" anything, and the focus rule
    -- refuses to fire below its own floor.
    n_takes           INTEGER     NOT NULL DEFAULT 0,

    last_take_session_id TEXT     NULL,

    -- THE RATCHET. Set once, when the average first crosses the baseline.
    -- Never cleared — a part that came onboard and then has one bad take must
    -- not re-capture the focus.
    came_onboard_at   TIMESTAMPTZ NULL,

    -- Which reference ema_z was measured against, and under which regime.
    baseline_id       UUID        NULL,
    detector_version  TEXT        NOT NULL,

    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- The read the focus rule performs: "this document's parts, worst first".
CREATE INDEX IF NOT EXISTS idx_arc_part_acoustics_document
    ON public.arc_part_acoustics (arc_id, user_id, ema_z);

-- "Which parts of this document have NOT come onboard yet" — the candidate
-- set the ratchet picks the next focus from. Partial: once a document is
-- going well the open set is the small one.
CREATE INDEX IF NOT EXISTS idx_arc_part_acoustics_open
    ON public.arc_part_acoustics (arc_id, user_id)
    WHERE came_onboard_at IS NULL;

ALTER TABLE public.arc_part_acoustics ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE public.arc_part_acoustics IS
    'Founder 2026-08-12 item 6 — the per-part acoustic moving average and the '
    'single-point-focus ratchet. Lives BESIDE ideal_text_part rather than on '
    'it because that table is delete-then-inserted wholesale and only names '
    'seven columns on insert, so anything accumulating would reset (see '
    'iteration, 0265, which already does). Keyed on the part id, which 0255 '
    'built to survive reorder, reword and version bumps. AC-9: internal — '
    'ema_z orders interventions and routes focus, and never reaches a payload.';

COMMENT ON COLUMN public.arc_part_acoustics.ema_z IS
    'Exponential moving average of the part''s acoustic z against the user''s '
    'OWN baseline. Exponential rather than a flat mean so a part the student '
    'genuinely fixed stops being the focus instead of carrying its first bad '
    'take forever.';

COMMENT ON COLUMN public.arc_part_acoustics.came_onboard_at IS
    'THE RATCHET. Set the first time ema_z crosses the baseline; never '
    'cleared. A part that came onboard and then has one bad take must not '
    're-capture the focus — that is what makes this a ratchet and not a '
    'threshold.';

COMMENT ON COLUMN public.arc_part_acoustics.baseline_id IS
    'The user_acoustic_baseline row ema_z was measured against. The KPI is a '
    'comparison; a comparison whose reference was silently recomputed is not '
    'reproducible.';

COMMIT;
