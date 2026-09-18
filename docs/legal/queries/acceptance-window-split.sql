-- ---------------------------------------------------------------------------
-- Did the 2026-06-06 rebrand split the acceptance window across two Terms?
--
-- WHY THIS EXISTS. `accepted-versions/README.md` recorded that the rebrand
-- commit 9815b7a2 "changed styling only" and that one document was therefore in
-- force for the whole acceptance window (8 May - 16 Jul 2026). That is true of
-- the Privacy Policy and FALSE of the Terms: two of the four changed lines are
-- body text a user read, and both name the counterparty --
--
--   "By creating an account or recording a voice sample on Willab|WillpowerLab,
--    you agree to these Terms of Use..."
--   "You must be at least 18 years old to use Willab|WillpowerLab."
--
-- Both texts are now recorded, as terms-as-published-2026-05-07.txt and
-- terms-as-published-2026-06-06.txt. What is NOT established is whether any
-- acceptance actually fell on the later side. A straddled window is not a
-- proven split.
--
-- WHAT TURNS ON THE ANSWER. If every acceptance predates 6 June, this is a
-- correction to one file's reasoning and nothing else. If not, users agreed to
-- two different documents naming two different counterparties, and counsel
-- question Q-E in 09-counsel-cover-note.md -- which is written about ONE
-- accepted Terms -- has to be rewritten before the pack is sent.
--
-- READ-ONLY. Four SELECTs, no DDL, no writes. Safe to run against production.
--
-- RUN IT:  psql "$DATABASE_URL" -f docs/legal/queries/acceptance-window-split.sql
-- ---------------------------------------------------------------------------

\echo ''
\echo '== 1. Acceptances either side of the rebrand boundary =================='
\echo ''

-- THE BOUNDARY IS THE DEPLOY, NOT THE COMMIT. 9815b7a2 is dated 6 June; the
-- rebrand reached users whenever that commit deployed, which is at or after
-- that date. Query 3 below lists anything close enough to the line for the
-- difference to matter.
SELECT CASE WHEN terms_accepted_at < TIMESTAMPTZ '2026-06-06'
            THEN 'terms-as-published-2026-05-07'
            ELSE 'terms-as-published-2026-06-06' END AS accepted_document,
       COUNT(*)                  AS acceptances,
       COUNT(DISTINCT user_id)   AS users,
       MIN(terms_accepted_at)    AS first,
       MAX(terms_accepted_at)    AS last
FROM user_consents
GROUP BY 1
ORDER BY 1;

\echo ''
\echo '== 2. The same split, by the terms_version the row claims =============='
\echo ''

-- The record says all 26 rows carry terms_version 1.0. If a row disagrees, the
-- version column and the timestamps are telling different stories and BOTH go
-- to counsel -- do not reconcile them here.
--
-- terms_accepted_at and created_at are separate columns and may disagree; both
-- are shown so a discrepancy is visible rather than averaged away.
SELECT terms_version,
       CASE WHEN terms_accepted_at < TIMESTAMPTZ '2026-06-06'
            THEN 'pre-rebrand' ELSE 'post-rebrand' END AS side,
       COUNT(*)                AS acceptances,
       COUNT(DISTINCT user_id) AS users,
       MIN(terms_accepted_at)  AS first_accepted,
       MAX(terms_accepted_at)  AS last_accepted,
       MIN(created_at)         AS first_row,
       MAX(created_at)         AS last_row,
       COUNT(*) FILTER (
         WHERE terms_accepted_at::date <> created_at::date
       )                       AS rows_where_the_two_dates_disagree
FROM user_consents
GROUP BY 1, 2
ORDER BY 1, 2;

\echo ''
\echo '== 3. Anything within 48h of the boundary -- needs the deploy time ====='
\echo ''

-- If this returns rows, STOP and get the actual deploy time of 9815b7a2 before
-- assigning them to a document. A row at 2026-06-06 09:00 belongs to the OLD
-- Terms if the deploy went out at 14:00.
SELECT id, user_id, terms_version, terms_accepted_at, created_at,
       terms_accepted_at - TIMESTAMPTZ '2026-06-06' AS offset_from_boundary
FROM user_consents
WHERE terms_accepted_at BETWEEN TIMESTAMPTZ '2026-06-04'
                            AND TIMESTAMPTZ '2026-06-08'
ORDER BY terms_accepted_at;

\echo ''
\echo '== 4. WP0 q1 -- the user-count discrepancy the cover note flags ========'
\echo ''

-- 09-counsel-cover-note.md tells counsel the settings table holds 7 rows while
-- 25 distinct user identifiers have audio, and asks them not to rely on either
-- number. Every DPIA severity rating assumes the answer. This is the query that
-- settles it.
--
-- NOTE the column is terms_version. user_consents has NO consent_policy_version
-- -- that is an MLC-2 foundation column (add_mlc2_foundation.sql:231), and
-- naming it here fails before returning a row. The brief's original WP0 query
-- did exactly that.
SELECT 'user_settings rows'        AS population, COUNT(*) AS n FROM user_settings
UNION ALL
SELECT 'auth users',                             COUNT(*) FROM auth.users
UNION ALL
SELECT 'distinct users in user_consents',        COUNT(DISTINCT user_id) FROM user_consents
UNION ALL
SELECT 'user_consents rows',                     COUNT(*) FROM user_consents
ORDER BY 1;

\echo ''
\echo '== done. Report all four outputs verbatim -- do not summarise. ========='
\echo ''
