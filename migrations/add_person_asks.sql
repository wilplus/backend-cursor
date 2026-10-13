-- Asks to one person (founder 2026-10-13, step 2 of the admin plan).
--
-- The admin asks one person, from their profile, for a missing answer: their
-- WhatsApp number, adding the app to their home screen, or a consent. The ask
-- appears in that person's app after their next Take, in the footer slot the
-- app's own offers already use, one at a time.
--
--   waiting   sent, not seen yet
--   shown     the person saw it after a Take
--   opened    they opened the page it points to (consent asks)
--   answered  the answer arrived (number saved, app opened from the home screen)
--
-- Idempotent and additive: IF NOT EXISTS everywhere, nothing dropped.

CREATE TABLE IF NOT EXISTS public.person_asks (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      UUID NOT NULL,
    kind         TEXT NOT NULL,
    consent_key  TEXT,
    status       TEXT NOT NULL DEFAULT 'waiting',
    created_by   UUID,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    shown_at     TIMESTAMPTZ,
    resolved_at  TIMESTAMPTZ,
    CONSTRAINT person_asks_kind_check CHECK (kind IN ('whatsapp', 'home_screen', 'consent')),
    CONSTRAINT person_asks_status_check CHECK (status IN ('waiting', 'shown', 'opened', 'answered')),
    CONSTRAINT person_asks_consent_key_check CHECK ((kind = 'consent') = (consent_key IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS person_asks_user_status_idx
    ON public.person_asks (user_id, status, created_at);

ALTER TABLE public.person_asks ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.person_asks FROM anon, authenticated;
