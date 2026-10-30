-- the_walk_may_quote_your_notebook (founder 2026-10-29, N268; rules: frontend
-- docs/flows/principles.md §1 R and docs/flows/feedback-walk-and-chat.md C5)
--
-- After a good try on a Clearer version, Will may quote the speaker's own
-- kept words in the walk: a strength, the vision, or a # note naming what is
-- theirs. Ring 5 (people who know it is a test), its own ring row.
--
--   walk_quotes          At most one per Take (UNIQUE user, session): the
--                        sentence it answered, which of their words was
--                        picked (kind, the row it came from) and the words
--                        themselves, copied, so a changed note leaves what
--                        was shown as it was shown; when the walk showed it.
--   walk_quote_settings  One row per person: "Not here" (off) and when the
--                        first quote was shown, so "From your notebook. Only
--                        you and Will see this." comes once.
--   feature_rings row    walk_quotes, ring 5, with its first audit entry.
--
-- Part of the Life Panel's store (services/life_store.py LIFE_TABLES): the
-- Life Panel's export and delete take these rows, and the account purge
-- (services/data_purge_registry.py). Read and written by the backend (service
-- role) only; never by a coach. No environment variable needed. Idempotent
-- and additive: IF NOT EXISTS / ON CONFLICT DO NOTHING everywhere, nothing
-- dropped. One transaction; explicit grants to service_role.

BEGIN;

CREATE TABLE IF NOT EXISTS public.walk_quotes (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL,
    session_id  UUID NOT NULL,
    said        TEXT NOT NULL,
    kind        TEXT NOT NULL,
    source_id   UUID,
    title       TEXT,
    quote       TEXT NOT NULL,
    said_on     DATE,
    shown_at    TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT walk_quotes_one_per_take UNIQUE (user_id, session_id),
    CONSTRAINT walk_quotes_kind_check CHECK (kind IN ('strength', 'vision', 'yours')),
    CONSTRAINT walk_quotes_said_len CHECK (char_length(said) BETWEEN 1 AND 2000),
    CONSTRAINT walk_quotes_title_len CHECK (char_length(title) <= 200),
    CONSTRAINT walk_quotes_quote_len CHECK (char_length(quote) BETWEEN 1 AND 2000)
);

ALTER TABLE public.walk_quotes ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.walk_quotes FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.walk_quotes TO service_role;

CREATE TABLE IF NOT EXISTS public.walk_quote_settings (
    user_id         UUID PRIMARY KEY,
    off             BOOLEAN NOT NULL DEFAULT false,
    first_shown_at  TIMESTAMPTZ,
    changed_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE public.walk_quote_settings ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.walk_quote_settings FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.walk_quote_settings TO service_role;

INSERT INTO public.feature_rings (feature, min_ring, note, changed_by)
VALUES ('walk_quotes', 5,
        'The walk quotes your notebook (N268): after a good try on a Clearer '
        'version, one of the speaker''s own kept words, at most once per Take.',
        'migration:the_walk_may_quote_your_notebook')
ON CONFLICT (feature) DO NOTHING;

-- The row's first entry in its audit trail, as 0394 wrote for its seeds.
INSERT INTO public.feature_ring_changes
    (feature, min_ring, attribute_rule, consent_purpose, killed, one_way, note,
     changed_by, changed_at)
SELECT f.feature, f.min_ring, f.attribute_rule, f.consent_purpose, f.killed,
       f.one_way, f.note, f.changed_by, f.changed_at
  FROM public.feature_rings f
 WHERE f.feature = 'walk_quotes'
   AND NOT EXISTS (SELECT 1 FROM public.feature_ring_changes c
                    WHERE c.feature = f.feature);

COMMIT;
