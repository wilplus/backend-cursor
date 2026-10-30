-- the_first_visit_is_counted (founder 2026-10-29, N271: "introduce the
-- counting where the people leave!")
--
-- Where people leave between the landing page and their first feedback, so
-- the founder fixes the biggest drop first. The founder's only: no speaker
-- sees it. The sign-up screen and the accounts made keep their own count
-- (the_sign_up_screen_is_counted.sql, N207 item 6); the backend reads both
-- together.
--
--   first_visit_counts   One row per day (UTC) and step: how many times a
--       visitor without an account reached that step that day, once per
--       browser tab. A count and nothing else: no account, no IP address, no
--       device, no cookie.
--   first_visit_step_v1(p_step)
--       Adds one to today's row for a known step. The backend calls it.
--   first_visit_counts_v1(p_since)
--       Per day and step since p_since (UTC).
--
-- Read and written by the backend (service role) only. No environment
-- variable needed. Idempotent and additive: IF NOT EXISTS / CREATE OR
-- REPLACE, nothing dropped. One transaction; explicit grants.

BEGIN;

CREATE TABLE IF NOT EXISTS public.first_visit_counts (
    day   DATE NOT NULL,
    step  TEXT NOT NULL,
    n     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day, step),
    CONSTRAINT first_visit_counts_step_check CHECK (step IN (
        'landing', 'enter', 'agreed', 'recording', 'recorded', 'ready', 'walk'
    )),
    CONSTRAINT first_visit_counts_n_check CHECK (n >= 0)
);

ALTER TABLE public.first_visit_counts ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.first_visit_counts FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE ON TABLE public.first_visit_counts TO service_role;

CREATE OR REPLACE FUNCTION public.first_visit_step_v1(
    p_step TEXT
) RETURNS VOID
LANGUAGE sql SECURITY INVOKER SET search_path = ''
AS $$
    INSERT INTO public.first_visit_counts AS c (day, step, n)
    VALUES ((now() AT TIME ZONE 'utc')::date, p_step, 1)
    ON CONFLICT (day, step) DO UPDATE SET n = c.n + 1;
$$;

REVOKE ALL ON FUNCTION public.first_visit_step_v1(TEXT)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.first_visit_step_v1(TEXT)
    TO service_role;

CREATE OR REPLACE FUNCTION public.first_visit_counts_v1(
    p_since DATE
) RETURNS TABLE (day DATE, step TEXT, n BIGINT)
LANGUAGE sql STABLE SECURITY INVOKER SET search_path = ''
AS $$
    SELECT c.day, c.step, c.n::bigint
      FROM public.first_visit_counts c
     WHERE c.day >= p_since
     ORDER BY 1, 2;
$$;

REVOKE ALL ON FUNCTION public.first_visit_counts_v1(DATE)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.first_visit_counts_v1(DATE)
    TO service_role;

COMMIT;
