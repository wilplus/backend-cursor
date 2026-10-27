-- the_sign_up_screen_is_counted (founder 2026-10-26, N207 item 6; N174
-- item 6: "First count how many people leave at the sign-up screen")
--
-- How many people reach the sign-up screen, and how many make an account,
-- by way, so the founder can decide on signing up with WhatsApp. The
-- founder's only: no speaker sees it.
--
--   signup_screen_counts   One row per day (UTC): how many times the
--       sign-up screen was opened that day, once per browser tab. A count
--       and nothing else: no account, no IP address, no device, no cookie.
--   signup_screen_seen_v1()
--       Adds one to today's row. The backend calls it when the sign-up
--       screen opens.
--   signup_counts_v1(p_since)
--       Per day since p_since (UTC): the screen's count (step 'seen', way
--       NULL) and the accounts made (step 'made'), by the way Supabase
--       records in raw_app_meta_data.provider (email, google,
--       linkedin_oidc). The accounts are read from auth.users, so it is
--       SECURITY DEFINER with its search_path pinned, and only the backend
--       (service role) may call it. It answers counts and nothing else.
--
-- Read and written by the backend (service role) only. No environment
-- variable needed. Idempotent and additive: IF NOT EXISTS / CREATE OR
-- REPLACE, nothing dropped. One transaction; explicit grants.

BEGIN;

CREATE TABLE IF NOT EXISTS public.signup_screen_counts (
    day   DATE PRIMARY KEY,
    seen  INTEGER NOT NULL DEFAULT 0,
    CONSTRAINT signup_screen_counts_seen_check CHECK (seen >= 0)
);

ALTER TABLE public.signup_screen_counts ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.signup_screen_counts FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE ON TABLE public.signup_screen_counts TO service_role;

CREATE OR REPLACE FUNCTION public.signup_screen_seen_v1()
RETURNS VOID
LANGUAGE sql SECURITY INVOKER SET search_path = ''
AS $$
    INSERT INTO public.signup_screen_counts AS c (day, seen)
    VALUES ((now() AT TIME ZONE 'utc')::date, 1)
    ON CONFLICT (day) DO UPDATE SET seen = c.seen + 1;
$$;

REVOKE ALL ON FUNCTION public.signup_screen_seen_v1()
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.signup_screen_seen_v1()
    TO service_role;

CREATE OR REPLACE FUNCTION public.signup_counts_v1(
    p_since DATE
) RETURNS TABLE (day DATE, step TEXT, way TEXT, n BIGINT)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = ''
AS $$
    SELECT c.day, 'seen'::text, NULL::text, c.seen::bigint
      FROM public.signup_screen_counts c
     WHERE c.day >= p_since
    UNION ALL
    SELECT (u.created_at AT TIME ZONE 'utc')::date, 'made'::text,
           COALESCE(u.raw_app_meta_data ->> 'provider', 'email'), count(*)
      FROM auth.users u
     WHERE u.created_at >= (p_since::timestamp AT TIME ZONE 'utc')
     GROUP BY 1, 3
     ORDER BY 1, 2, 3;
$$;

REVOKE ALL ON FUNCTION public.signup_counts_v1(DATE)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.signup_counts_v1(DATE)
    TO service_role;

COMMIT;
