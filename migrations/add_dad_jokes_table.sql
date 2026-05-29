-- Ticket 2 — Dad-joke onboarding opener.
--
-- A new user lands in onboarding. Will opens with one randomly-
-- selected joke (setup), waits for the user to reply, drops the
-- punchline, then pivots to real onboarding with the canonical
-- sentence: "Okok, nevermind. Let's focus on public speaking —
-- how can I help you?"
--
-- The pivot line is hardcoded in services/onboarding_opener.py
-- as PIVOT_LINE (Final[str], non-LLM). This table only holds the
-- joke content.
--
-- Schema notes:
--   id        — surrogate UUID so future jokes/edits don't churn an
--               integer sequence
--   setup     — the question-form opener ("How do cows stay up to
--               date?")
--   punchline — the answer ("They read the moos-paper.")
--   emoji     — single emoji landed on the punchline as comic timing
--   locale    — BCP-47 code; English-only seed for v1 because most
--               of these jokes don't translate (especially #10's
--               wordplay). i18n pass can filter by locale.
--   active    — soft-disable lever; admin can flip without a delete
--               if a joke ages badly
--   created_at — audit
--
-- Idempotent migration. Re-running won't re-seed (ON CONFLICT DO
-- NOTHING on the punchline+setup pair, which is the natural key).

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS dad_jokes (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    setup       TEXT NOT NULL,
    punchline   TEXT NOT NULL,
    emoji       TEXT NOT NULL DEFAULT '',
    locale      TEXT NOT NULL DEFAULT 'en',
    active      BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Natural-key uniqueness so the seed below is idempotent across
-- re-runs. The (setup, punchline) pair is the joke identity; the
-- emoji is decoration that could change without it being a "new joke".
CREATE UNIQUE INDEX IF NOT EXISTS dad_jokes_natural_key_uq
    ON dad_jokes (setup, punchline);

-- Random-selection helper: a partial index on active rows lets the
-- ORDER BY random() LIMIT 1 query skip soft-disabled jokes without
-- a full scan. Small table; insurance for future growth.
CREATE INDEX IF NOT EXISTS dad_jokes_active_locale_ix
    ON dad_jokes (locale)
    WHERE active IS TRUE;

-- ── Seed: the 10 v1 jokes ──────────────────────────────────────────
-- Locked verbatim per the product owner. Do NOT reword on
-- re-seeding; admin edits via /admin endpoint (future) once the
-- table has live data.

INSERT INTO dad_jokes (setup, punchline, emoji, locale) VALUES
    ('How do cows stay up to date?',
     'They read the moos-paper.',
     '🐄', 'en'),
    ('What do you call a bear with no teeth?',
     'A gummy bear.',
     '🐻', 'en'),
    ('Did you hear about the accident at the shoe factory?',
     'Many soles were lost.',
     '👞', 'en'),
    ('Who won the neck decorating contest?',
     'It was a tie.',
     '👔', 'en'),
    ('Why did the bicycle fall over?',
     'Because it was two-tired.',
     '🚲', 'en'),
    ('What do you call a dog magician?',
     'A Labracadabrador Retriever.',
     '🐕', 'en'),
    ('What''s the difference between a well-dressed man on a unicycle and a poorly-dressed man on a bicycle?',
     'Attire.',
     '🎩', 'en'),
    ('What''s the difference between Batman and a shoplifter?',
     'Batman can go into a store without Robin.',
     '🦇', 'en'),
    ('What''s the difference between a greedy person and a crayfish?',
     'One is selfish, the other is shellfish.',
     '🦞', 'en'),
    ('What''s the difference between an Italian barber and an angry circus ringmaster?',
     'One''s a shaving Roman, the other''s a raving showman.',
     '🎪', 'en')
ON CONFLICT (setup, punchline) DO NOTHING;

COMMENT ON TABLE dad_jokes IS
    'Ticket 2 — Onboarding opener jokes. Random pick on a new '
    'user''s first onboarding contact; canonical pivot line lives '
    'in services/onboarding_opener.py PIVOT_LINE, not here.';

COMMENT ON COLUMN dad_jokes.active IS
    'Soft-disable lever; admin can retire a joke that ages badly '
    'without losing audit history. Random-pick query filters on '
    'active=TRUE.';

NOTIFY pgrst, 'reload schema';
