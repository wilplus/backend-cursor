-- Corpus label audit, read-only (2026-10-08).
--
-- Question: how many confidence labels were saved on training-corpus clips
-- while the corpus card had no playable clip?
--
-- How to run: paste the whole file into the Supabase SQL Editor and press Run.
-- It is one SELECT statement and changes nothing. You get one table of results.
--
-- Periods (UTC; Warsaw time is UTC+2):
--   1  before 9 Sep 2026 12:46 UTC: the queue still served each clip's audio.
--   2  9 Sep 12:46 to 30 Sep 22:12 UTC: backend #485 (D5) made the queue
--      canonical-only. A corpus import has no owner and no project, so its
--      queue came back empty.
--   3  from 30 Sep 22:12 UTC (1 Oct 00:12 Warsaw) to now: backend #830 also
--      turned /v2/coach/mlc3 into a 410. The import switch
--      (Config.TRAINING_IMPORT_ENABLED) is still False, so an import's queue is
--      still empty and its clip route still answers 410.
--
-- What the code says to expect: zero labels in periods 2 and 3 (with no queue
-- rows, the corpus card had nothing to label), and 0 on the three "expect 0"
-- checks. A non-zero count in period 2 or 3 means labels arrived some other way,
-- and the per-day query at the bottom shows which rater lane wrote them.

WITH bounds AS (
    SELECT timestamptz '2026-09-09 12:46:30+00' AS d5,
           timestamptz '2026-09-30 22:12:44+00' AS mlc3_off
),
imports AS (
    SELECT s.id, s.owner_principal_id, s.project_id
      FROM public.v2_sessions s
     WHERE s.source = 'training_import'
),
clips AS (
    SELECT c.id AS snippet_id, c.session_id
      FROM public.snippets c
      JOIN imports i ON i.id = c.session_id
),
events AS (
    -- A label row holds one rater's latest answer on one clip.
    SELECT 'a  labels first saved' AS measure, l.created_at AS at,
           l.rater_id, cl.session_id
      FROM public.confidence_labels l
      JOIN clips cl ON cl.snippet_id = l.snippet_id
    UNION ALL
    SELECT 'b  labels changed after their first save', l.updated_at,
           l.rater_id, cl.session_id
      FROM public.confidence_labels l
      JOIN clips cl ON cl.snippet_id = l.snippet_id
     WHERE l.updated_at > l.created_at + interval '1 second'
    UNION ALL
    -- The label history keeps one row per save, so this counts every save.
    SELECT 'c  saves in the label history', r.created_at,
           r.rater_id, cl.session_id
      FROM public.label_revision r
      JOIN clips cl ON cl.snippet_id = r.snippet_id
     WHERE r.origin = 'live'
),
periods AS (
    SELECT CASE
             WHEN e.at < b.d5 THEN '1  before 9 Sep 12:46 UTC'
             WHEN e.at < b.mlc3_off THEN '2  9 Sep 12:46 to 30 Sep 22:12 UTC'
             ELSE '3  since 30 Sep 22:12 UTC (1 Oct 00:12 Warsaw)'
           END AS period,
           e.measure, e.rater_id, e.session_id
      FROM events e CROSS JOIN bounds b
)
SELECT period, measure,
       count(*) AS n,
       count(DISTINCT rater_id) AS raters,
       count(DISTINCT session_id) AS imports
  FROM periods
 GROUP BY period, measure
UNION ALL
SELECT '0  check', 'imports in total', count(*), NULL, NULL
  FROM imports
UNION ALL
SELECT '0  check', 'imports with an owner or a project (expect 0)', count(*),
       NULL, NULL
  FROM imports
 WHERE owner_principal_id IS NOT NULL OR project_id IS NOT NULL
UNION ALL
SELECT '0  check', 'evidence spans on import clips (expect 0)', count(*),
       NULL, NULL
  FROM public.evidence_spans es
  JOIN imports i ON i.id = es.take_id
UNION ALL
SELECT '0  check', 'coach assignments on import evidence (expect 0)', count(*),
       NULL, NULL
  FROM public.evidence_review_assignments a
  JOIN public.evidence_spans es ON es.id = a.evidence_span_id
  JOIN imports i ON i.id = es.take_id
ORDER BY 1, 2;

-- Optional, only if period 2 or 3 is not zero. To see the saves per day and
-- per rater lane, select just the query below (from WITH to the semicolon)
-- and run the selection on its own:
--
-- WITH clips AS (
--     SELECT c.id AS snippet_id
--       FROM public.snippets c
--       JOIN public.v2_sessions s ON s.id = c.session_id
--      WHERE s.source = 'training_import'
-- )
-- SELECT date_trunc('day', r.created_at) AS day, r.lane, r.source,
--        count(*) AS saves, count(DISTINCT r.rater_id) AS raters
--   FROM public.label_revision r
--   JOIN clips cl ON cl.snippet_id = r.snippet_id
--  WHERE r.origin = 'live'
--    AND r.created_at >= timestamptz '2026-09-09 12:46:30+00'
--  GROUP BY 1, 2, 3
--  ORDER BY 1, 2, 3;
