-- The Life Panel — schema + RLS (founder-directed, 2026-07-26).
--
-- Spec of record: PROMPT-life-panel.md · build prompt: PROMPT-BE-life-panel.md
--
-- A personal life-governance surface (principles engine, strategy documents,
-- daily card, timeline) absorbed into willpowerlab as a gated feature. It is
-- SCAFFOLDING under the decision filter: it moves neither F1 load-bearing piece
-- (per-slide transcription, best-per-slide ranking) nor F2, and it ships on
-- founder direction plus hard isolation from the record -> transcribe -> coach
-- -> read loop. No life_* table is ever joined to a product table.
--
-- RUN THIS IN THE SUPABASE SQL EDITOR. Idempotent: every statement is
-- IF NOT EXISTS / guarded, so re-running is a no-op. Nothing is dropped.
--
-- ─────────────────────────────────────────────────────────────────────────
-- ROW LEVEL SECURITY IS PART OF THIS FILE, NOT A FOLLOW-UP SWEEP (N1)
-- ─────────────────────────────────────────────────────────────────────────
-- This is not neutral productivity data. The corpus being migrated in
-- contains addiction, sexual behaviour, confession-shaped religious material,
-- named third parties, and financial history — moved from a device-local
-- store into a multi-tenant product database. The July 2026 audit found 57
-- exposed public tables (see add_rls_arc_context_documents.sql); this class of
-- data must not be number 58.
--
-- The FE ships NEXT_PUBLIC_SUPABASE_ANON_KEY inlined into the browser bundle,
-- so anyone can read it out of the JS and call PostgREST directly. With RLS
-- off, the default public-schema grants to `anon` would allow
--     GET /rest/v1/life_cases?select=*
-- returning every reflection in the corpus — bypassing Flask entirely, so the
-- API's own user_id filter cannot defend it.
--
-- No policies are added ON PURPOSE: with RLS enabled and zero policies, `anon`
-- and `authenticated` can do nothing at all, while the backend — which
-- connects with SUPABASE_SERVICE_ROLE_KEY (services/db.py) — bypasses RLS and
-- keeps full access. Every read/write is therefore served ONLY through
-- /v2/life/*, where the consent gate and the owner filter apply.
--
-- ─────────────────────────────────────────────────────────────────────────
-- WHY TEN TABLES AND NOT THE SPEC'S SIX
-- ─────────────────────────────────────────────────────────────────────────
--   life_consent      L-6 requires consent BEFORE any life row is written, and
--                     the acceptance has to be auditable (version + time).
--   life_setup        §6.2 makes setup a hard gate with save-and-resume. Eight
--                     horizons is long enough that people get interrupted
--                     partway; without a resume row an interruption is an
--                     abandonment and the gate has no second door.
--   life_proposals    This table IS L-2b. The one-per-day budget is a QUERY
--                     over surfaced_on, not a counter in application code — a
--                     counter drifts across processes and restarts.
--   life_applications L-5's application log. Append-only, so load-bearing
--                     principles separate from decorative ones over months.
--
-- Sized for one user today; indexed for many.

-- ═════════════════════════════════════════════════════════════════════════
-- 1. CONSENT (L-6) — nothing else may be written until a row exists here
-- ═════════════════════════════════════════════════════════════════════════
-- One row per (user, consent_version): re-accepting the same version is a
-- no-op, and accepting a NEW version keeps the old acceptance as history.
-- `ip` is the acceptance record, not analytics — never used for anything else.
CREATE TABLE IF NOT EXISTS life_consent (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         uuid        NOT NULL,
    consent_version text        NOT NULL,
    accepted_at     timestamptz NOT NULL DEFAULT now(),
    ip              text,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS life_consent_user_version_uniq
    ON life_consent (user_id, consent_version);

ALTER TABLE life_consent ENABLE ROW LEVEL SECURITY;

-- ═════════════════════════════════════════════════════════════════════════
-- 2. SETUP (§6.2) — the eight-horizon form, saved partially, resumable
-- ═════════════════════════════════════════════════════════════════════════
-- `answers` is the raw form state (jsonb so the FE can evolve its fields
-- without a migration). `completed_at` is the hard gate: NULL means a typed
-- `#` note is KEPT (life_notes.pending_replay) and replayed on completion,
-- never run through the engine and never dropped.
CREATE TABLE IF NOT EXISTS life_setup (
    user_id      uuid PRIMARY KEY,
    answers      jsonb       NOT NULL DEFAULT '{}'::jsonb,
    completed_at timestamptz,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE life_setup ENABLE ROW LEVEL SECURITY;

-- ═════════════════════════════════════════════════════════════════════════
-- 3. NOTES — raw capture, append-only, never edited, never deleted
-- ═════════════════════════════════════════════════════════════════════════
-- Every note lands here regardless of tag; capture never fails and never
-- blocks. `tag` is the parsed hashtag (NULL = untagged, surfaced in the weekly
-- untagged review). `pending_replay` marks a note typed before setup
-- completed — §6.2's "the typed note is kept, not dropped".
CREATE TABLE IF NOT EXISTS life_notes (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        uuid        NOT NULL,
    body           text        NOT NULL DEFAULT '',
    source         text        NOT NULL DEFAULT 'chat',
    tag            text,
    pending_replay boolean     NOT NULL DEFAULT false,
    replayed_at    timestamptz,
    created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS life_notes_user_created_idx
    ON life_notes (user_id, created_at DESC);
-- The replay sweep on setup completion: oldest-first over one user's pending
-- notes. Partial index — the pending set is tiny next to the note history.
CREATE INDEX IF NOT EXISTS life_notes_pending_replay_idx
    ON life_notes (user_id, created_at)
    WHERE pending_replay;

ALTER TABLE life_notes ENABLE ROW LEVEL SECURITY;

-- ═════════════════════════════════════════════════════════════════════════
-- 4. CASES — the Dalio reflection, five slots, one row
-- ═════════════════════════════════════════════════════════════════════════
-- `reflections` is written ONLY from request input (N5 / L-1). The system
-- never authors reflective prose — it proposes the category and the principle
-- one-liner, and retrieves which existing principles bore on the case.
--
-- `category` is an ARRAY: multi-category cases exist in the corpus (the
-- scooter/drift case carries Wishful thinking + Hubris). `category_proposed`
-- holds the model's suggestion until approved — propose, never commit.
--
-- `occurred_on` is nullable: most cases carry no date, a few do ("03/01/2026").
-- Undated cases render at created_at.
CREATE TABLE IF NOT EXISTS life_cases (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id            uuid        NOT NULL,
    case_at_hand       text        NOT NULL DEFAULT '',
    category           text[]      NOT NULL DEFAULT '{}',
    category_proposed  text[]      NOT NULL DEFAULT '{}',
    principles_applied text        NOT NULL DEFAULT '',
    reflections        text        NOT NULL DEFAULT '',
    occurred_on        date,
    status             text        NOT NULL DEFAULT 'draft',
    origin_note_id     uuid,
    -- Import provenance: an unmapped category string is parked here for a
    -- human review queue rather than being silently coerced into one of the
    -- fixed six (BE-3). NULL for anything typed in-app.
    import_category_raw text,
    external_id        text,
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS life_cases_user_created_idx
    ON life_cases (user_id, created_at DESC);
-- Import idempotency: re-running the importer must update, never duplicate.
CREATE UNIQUE INDEX IF NOT EXISTS life_cases_user_external_uniq
    ON life_cases (user_id, external_id)
    WHERE external_id IS NOT NULL;

ALTER TABLE life_cases ENABLE ROW LEVEL SECURITY;

-- ═════════════════════════════════════════════════════════════════════════
-- 5. ITEMS — everything else, discriminated by kind
-- ═════════════════════════════════════════════════════════════════════════
-- kind ∈ { principle, win, phrase, bet, goal, task, habit, distraction, event }
--
-- `status='proposed'` is the triage state: a derived principle waits here
-- until approved. A bad prompt day cannot silently corrupt sixty principles
-- earned over four years.
--
-- `order_key` carries the manual drag-to-reorder state for principles AND the
-- RANK for bets (1 = 🟢 The Life, 2 = 🔵 The Company, 3 = 🟣 The Dream). The
-- bet rank is immutable core (L-2a) — see life_proposals.
--
-- `due_label` is free text copied verbatim from the founder's own notation
-- ("[NOW]", "[Aug]", "[Jul '27]", "2035") and is the SOURCE OF TRUTH;
-- `due_at` is the parse, nullable where the label is ambiguous.
--
-- `collection` tags phrases ("2022-24", "2025", "2026", "wall").
CREATE TABLE IF NOT EXISTS life_items (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        uuid        NOT NULL,
    kind           text        NOT NULL,
    title          text        NOT NULL DEFAULT '',
    body           text        NOT NULL DEFAULT '',
    status         text        NOT NULL DEFAULT 'active',
    order_key      double precision NOT NULL DEFAULT 0,
    horizon        text,
    due_label      text,
    due_at         date,
    bet_id         uuid,
    parent_id      uuid,
    collection     text,
    origin_note_id uuid,
    origin_case_id uuid,
    external_id    text,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS life_items_user_kind_order_idx
    ON life_items (user_id, kind, order_key);
CREATE INDEX IF NOT EXISTS life_items_user_kind_status_idx
    ON life_items (user_id, kind, status);
CREATE INDEX IF NOT EXISTS life_items_origin_case_idx
    ON life_items (origin_case_id)
    WHERE origin_case_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS life_items_user_external_uniq
    ON life_items (user_id, external_id)
    WHERE external_id IS NOT NULL;

ALTER TABLE life_items ENABLE ROW LEVEL SECURITY;

-- ═════════════════════════════════════════════════════════════════════════
-- 6. STRATEGY — the document set, versioned, NEVER overwritten
-- ═════════════════════════════════════════════════════════════════════════
-- One row per (user, horizon, version). An approved proposal INSERTS a new
-- row at version+1; the prior version stays readable forever. That is what
-- makes L-2's "every change is gated" auditable after the fact — you can see
-- exactly what the 20-year document said eight months and forty approvals ago.
--
-- horizon ∈ { daily, weekly, monthly, quarterly, yearly, five_year, ten_year,
--             twenty_year }
CREATE TABLE IF NOT EXISTS life_strategy (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     uuid        NOT NULL,
    horizon     text        NOT NULL DEFAULT 'weekly',
    body        text        NOT NULL DEFAULT '',
    version     integer     NOT NULL DEFAULT 1,
    reviewed_on date,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS life_strategy_user_horizon_version_uniq
    ON life_strategy (user_id, horizon, version);
CREATE INDEX IF NOT EXISTS life_strategy_user_horizon_idx
    ON life_strategy (user_id, horizon, version DESC);

ALTER TABLE life_strategy ENABLE ROW LEVEL SECURITY;

-- ═════════════════════════════════════════════════════════════════════════
-- 7. PROPOSALS — this table IS the L-2b budget
-- ═════════════════════════════════════════════════════════════════════════
-- status ∈ { queued, surfaced, approved, dismissed, expired }
--
-- The budget is the QUERY "does a row already exist with
-- surfaced_on = today?", not a counter in code. At most one strategy proposal
-- moves to `surfaced` per day; the rest stay `queued` and arrive as a ranked
-- batch of three at the weekly review. Scarcity is what keeps "approve"
-- meaningful — a daily stream of diffs becomes a rubber stamp within three
-- weeks, and the rubber stamp IS the drift.
--
-- `expires_at` implements "unactioned proposals expire after two weeks rather
-- than accumulating".
--
-- `warrant_principle_id` is L-2's hard requirement: every proposed change
-- displays one of the USER'S OWN principles as its warrant. A strategy
-- proposal without a warrant is never created (enforced in code AND by the
-- CHECK below, so a direct SQL insert cannot bypass it).
--
-- kind ∈ { strategy, retire }
--   strategy — a document edit under the daily budget.
--   retire   — "does this new principle retire #12?". Veto is absolute: a
--              `dismissed` retire row is the persisted "no", and the question
--              is never re-asked (BE-7).
CREATE TABLE IF NOT EXISTS life_proposals (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id              uuid        NOT NULL,
    kind                 text        NOT NULL DEFAULT 'strategy',
    target               text        NOT NULL DEFAULT '',
    current              text        NOT NULL DEFAULT '',
    proposed             text        NOT NULL DEFAULT '',
    warrant_principle_id uuid,
    -- The note that triggered it, for the "you noted X" quote in the card.
    origin_note_id       uuid,
    status               text        NOT NULL DEFAULT 'queued',
    rank                 double precision NOT NULL DEFAULT 0,
    surfaced_on          date,
    expires_at           timestamptz,
    decided_at           timestamptz,
    created_at           timestamptz NOT NULL DEFAULT now()
);

-- The budget query: "has a strategy proposal already surfaced today?"
CREATE INDEX IF NOT EXISTS life_proposals_user_surfaced_idx
    ON life_proposals (user_id, kind, surfaced_on);
CREATE INDEX IF NOT EXISTS life_proposals_user_status_idx
    ON life_proposals (user_id, status, rank);
-- The retire lookup: "did they already answer this pair?" — asked on every
-- new principle, so it has to be an index hit, not a scan.
CREATE INDEX IF NOT EXISTS life_proposals_retire_pair_idx
    ON life_proposals (user_id, kind, target);

ALTER TABLE life_proposals ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    -- A strategy proposal MUST carry a warrant. Enforced here as well as in
    -- code because this is the invariant that keeps the system from editing
    -- the founder's own strategy on its own authority.
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'life_proposals_strategy_needs_warrant'
    ) THEN
        ALTER TABLE life_proposals
            ADD CONSTRAINT life_proposals_strategy_needs_warrant
            CHECK (kind <> 'strategy' OR warrant_principle_id IS NOT NULL);
    END IF;
END $$;

-- ═════════════════════════════════════════════════════════════════════════
-- 8. APPLICATIONS (L-5) — append-only citation log
-- ═════════════════════════════════════════════════════════════════════════
-- Every time a principle is cited — in a case, a comparison flag, a conflict
-- pair, a board answer, a lookup, or as the phrase attached to an answer — a
-- row lands here. Over months this is what separates load-bearing principles
-- from decorative ones. Never updated, never deleted (except by the user's own
-- hard delete).
--
-- `principle_id` also carries phrase items: a phrase attach is a citation of
-- the user's own words, and the "no repeat inside a rolling window" rule
-- (BE-5) is a query over this table with context='phrase'.
CREATE TABLE IF NOT EXISTS life_applications (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      uuid        NOT NULL,
    principle_id uuid        NOT NULL,
    context      text        NOT NULL DEFAULT 'case',
    ref_id       uuid,
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS life_applications_user_principle_idx
    ON life_applications (user_id, principle_id, created_at DESC);
-- The no-repeat window scan: one user's recent phrase attaches.
CREATE INDEX IF NOT EXISTS life_applications_user_context_created_idx
    ON life_applications (user_id, context, created_at DESC);

ALTER TABLE life_applications ENABLE ROW LEVEL SECURITY;

-- ═════════════════════════════════════════════════════════════════════════
-- 9. DAYS — the daily card, the template rendered as data
-- ═════════════════════════════════════════════════════════════════════════
-- Generated at 05:00 local and WAITS. No email, no push, no notification
-- (L-4 / N8): generation is scheduled, delivery is not. Not typing means
-- living, not failing.
--
-- The card's FRAME is fixed and its CONTENT is editable: you cannot edit away
-- the fact that there IS a one thing for the day; you can edit what it is, and
-- say why. `edit_why` is that payload — captured as a candidate strategy
-- correction so tomorrow's card is already right.
CREATE TABLE IF NOT EXISTS life_days (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             uuid        NOT NULL,
    day                 date        NOT NULL,
    morning_checks      jsonb       NOT NULL DEFAULT '{}'::jsonb,
    one_thing           text        NOT NULL DEFAULT '',
    focus_blocks        jsonb       NOT NULL DEFAULT '[]'::jsonb,
    distraction_flagged text,
    evening_habits_ran  boolean     NOT NULL DEFAULT false,
    evening_one_thing   boolean     NOT NULL DEFAULT false,
    evening_distraction text,
    evening_line        text,
    edit_why            text,
    generated_at        timestamptz,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS life_days_user_day_uniq
    ON life_days (user_id, day);

ALTER TABLE life_days ENABLE ROW LEVEL SECURITY;

-- ═════════════════════════════════════════════════════════════════════════
-- 10. WEEKS — the Sunday review
-- ═════════════════════════════════════════════════════════════════════════
-- `environmental_change` is load-bearing, not a nice-to-have: Section IV pairs
-- every distraction with a DESIGN response, not with willpower. One new one
-- per week.
CREATE TABLE IF NOT EXISTS life_weeks (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id              uuid        NOT NULL,
    week_start           date        NOT NULL,
    habits_failed        jsonb       NOT NULL DEFAULT '[]'::jsonb,
    goals_moved          jsonb       NOT NULL DEFAULT '[]'::jsonb,
    main_distraction     text,
    environmental_change text,
    becoming_sentence    text,
    reviewed_on          date,
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS life_weeks_user_week_uniq
    ON life_weeks (user_id, week_start);

ALTER TABLE life_weeks ENABLE ROW LEVEL SECURITY;

-- ═════════════════════════════════════════════════════════════════════════
-- VALUE CONSTRAINTS
-- ═════════════════════════════════════════════════════════════════════════
-- CHECKs rather than PG enums: a CHECK can be amended with a plain ALTER
-- later, while adding a value to a PG enum type is a migration hazard (house
-- precedent: the lounge-kind and journal_post CHECKs). Added defensively so
-- re-running against an existing table is a no-op.
--
-- The six-entry mistake taxonomy is NOT constrained here on purpose: an
-- unmapped import category has to survive into a human review queue rather
-- than crash the import (BE-3), so `category` stays free-form at the DB layer
-- and the fixed six are enforced in services/life_panel.py where the review
-- queue exists.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'life_notes_source_check'
    ) THEN
        ALTER TABLE life_notes
            ADD CONSTRAINT life_notes_source_check
            CHECK (source IN ('chat', 'form', 'import'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'life_items_kind_check'
    ) THEN
        ALTER TABLE life_items
            ADD CONSTRAINT life_items_kind_check
            CHECK (kind IN ('principle', 'win', 'phrase', 'bet', 'goal',
                            'task', 'habit', 'distraction', 'event'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'life_items_status_check'
    ) THEN
        ALTER TABLE life_items
            ADD CONSTRAINT life_items_status_check
            CHECK (status IN ('proposed', 'active', 'retired', 'dismissed',
                              'done', 'archived'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'life_items_horizon_check'
    ) THEN
        ALTER TABLE life_items
            ADD CONSTRAINT life_items_horizon_check
            CHECK (horizon IS NULL OR horizon IN
                   ('now', 'month', 'quarter', 'year', 'five_year',
                    'ten_year', 'twenty_year'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'life_cases_status_check'
    ) THEN
        ALTER TABLE life_cases
            ADD CONSTRAINT life_cases_status_check
            CHECK (status IN ('draft', 'active'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'life_strategy_horizon_check'
    ) THEN
        ALTER TABLE life_strategy
            ADD CONSTRAINT life_strategy_horizon_check
            CHECK (horizon IN ('daily', 'weekly', 'monthly', 'quarterly',
                               'yearly', 'five_year', 'ten_year',
                               'twenty_year'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'life_proposals_kind_check'
    ) THEN
        ALTER TABLE life_proposals
            ADD CONSTRAINT life_proposals_kind_check
            CHECK (kind IN ('strategy', 'retire'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'life_proposals_status_check'
    ) THEN
        ALTER TABLE life_proposals
            ADD CONSTRAINT life_proposals_status_check
            CHECK (status IN ('queued', 'surfaced', 'approved', 'dismissed',
                              'expired'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'life_applications_context_check'
    ) THEN
        ALTER TABLE life_applications
            ADD CONSTRAINT life_applications_context_check
            CHECK (context IN ('case', 'diff', 'conflict', 'board', 'lookup',
                               'phrase'));
    END IF;
END $$;

-- ═════════════════════════════════════════════════════════════════════════
-- POST-CONDITION — verify RLS actually landed on all ten tables (N1)
-- ═════════════════════════════════════════════════════════════════════════
-- A migration that silently half-applies is how a table ends up exposed. This
-- raises rather than reporting, so a partial run is a failed run.
DO $$
DECLARE
    unprotected text;
BEGIN
    SELECT string_agg(c.relname, ', ')
      INTO unprotected
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'public'
       AND c.relname LIKE 'life\_%'
       AND c.relkind = 'r'
       AND NOT c.relrowsecurity;

    IF unprotected IS NOT NULL THEN
        RAISE EXCEPTION 'life panel: RLS missing on %', unprotected;
    END IF;
END $$;
