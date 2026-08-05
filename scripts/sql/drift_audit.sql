-- willab — DRIFT AUDIT (Appendix G §G.5/§G.7/§G.9, process PM-3).
-- Written 2026-08-05.
--
-- Three steps, in order. Step 0 runs ONCE to mint a reference; steps 1 and 2
-- run weekly. Feed the outputs to services/drift_monitor.py — psi(),
-- p_chart(), triage() — rather than eyeballing them, so the bands and the
-- run rule are applied consistently.
--
-- ══════════════════════════════════════════════════════════════════════════
-- THE GRAIN RULE. Every query aggregates to SESSION grain before computing.
-- Snippets inside a session are NOT independent: one user recording thirty
-- snippets in one sitting contributes thirty correlated rows. Counting them
-- as thirty observations inflates n, narrows the p-chart limits by roughly
-- sqrt(30), and makes PSI confident about a "shift" that is one person having
-- a long day. The monitor would then fire on its own sampling. This is not
-- enforceable in the schema — the query that forgets it still returns a
-- perfectly plausible number.
-- ══════════════════════════════════════════════════════════════════════════
--
-- AC-9: internal audit surface. No output here reaches a user.

-- ─────────────────────────────────────────────────────────────────────────
-- 0 · FREEZE THE REFERENCE  (run once, then never again for this version)
--
-- Mints frozen_v1 from the first 4 complete weeks. reference_distribution
-- blocks UPDATE by trigger: a refit inserts frozen_v2, it never edits v1.
-- A reference recomputed on a rolling window tracks the drift it exists to
-- detect, and PSI reads ~0 forever while looking healthy.
-- ─────────────────────────────────────────────────────────────────────────
INSERT INTO public.reference_distribution
       (version, dimension_id, decile, pct, upper_bound, n_at_freeze)
WITH per_session AS (          -- <- THE GRAIN RULE
    SELECT dimension_id, session_id, avg(raw_value) AS value
    FROM   public.dimension_evaluations
    WHERE  raw_value IS NOT NULL
      AND  NOT insufficient_data
      AND  evaluated_at < now() - interval '0 days'   -- set the freeze cutoff
    GROUP  BY 1, 2
),
bucketed AS (
    SELECT dimension_id, value,
           ntile(10) OVER (PARTITION BY dimension_id ORDER BY value) AS decile
    FROM   per_session
)
SELECT dimension_id,
       decile,
       count(*)::float / sum(count(*)) OVER (PARTITION BY dimension_id) AS pct,
       CASE WHEN decile = 10 THEN NULL ELSE max(value) END AS upper_bound,
       sum(count(*)) OVER (PARTITION BY dimension_id)::int AS n_at_freeze
FROM   bucketed
GROUP  BY dimension_id, decile
ON CONFLICT (version, dimension_id, decile) DO NOTHING;
-- NB: the literal 'frozen_v1' is supplied by the INSERT column list default;
-- set it explicitly if minting a later version.

-- ─────────────────────────────────────────────────────────────────────────
-- 1 · PSI — has the INPUT distribution drifted from the frozen reference?
--
-- Buckets recent session-level values against the frozen CUT POINTS, then
-- returns the histogram. Hand the counts to drift_monitor.psi(); the
-- smoothing for empty buckets lives there, not here, because SQL's ln(0)
-- would take the whole query out.
-- ─────────────────────────────────────────────────────────────────────────
WITH per_session AS (          -- <- THE GRAIN RULE
    SELECT dimension_id, session_id, avg(raw_value) AS value
    FROM   public.dimension_evaluations
    WHERE  raw_value IS NOT NULL
      AND  NOT insufficient_data
      AND  evaluated_at > now() - interval '4 weeks'
    GROUP  BY 1, 2
),
ref AS (
    SELECT dimension_id, decile, upper_bound
    FROM   public.reference_distribution
    WHERE  version = 'frozen_v1'
),
assigned AS (
    SELECT p.dimension_id,
           COALESCE(
               (SELECT min(r.decile) FROM ref r
                 WHERE r.dimension_id = p.dimension_id
                   AND r.upper_bound IS NOT NULL
                   AND p.value <= r.upper_bound),
               10) AS decile          -- above every cut point => top bucket
    FROM   per_session p
)
SELECT dimension_id, decile, count(*) AS n_current
FROM   assigned
GROUP  BY 1, 2
ORDER  BY 1, 2;
-- Pair each dimension's result with:
--   SELECT dimension_id, decile, round(pct * n_at_freeze) AS n_reference
--   FROM public.reference_distribution WHERE version = 'frozen_v1';
-- then: psi(current, reference) -> psi_verdict(value, n_current=<sum>)

-- ─────────────────────────────────────────────────────────────────────────
-- 2 · p-chart — is a threshold's fire rate out of control?
--
-- TWO FILTERS, BOTH LOAD-BEARING:
--   benchmark_tier IN ('T1','T2')  — for CORPUS_REL the fire rate is pinned
--       BY CONSTRUCTION (G.5). A 10th-percentile threshold fails ~10% of the
--       time definitionally, so charting it yields a monitor that can never
--       signal while looking perfectly healthy.
--   fired IS NOT NULL              — a measurement with no benchmark defined
--       is not a decision. Counting it as a non-fire would deflate every
--       rate. Today this filter removes ALL rows, and that is correct: no
--       benchmark has a threshold in code yet, so there is nothing to chart.
-- ─────────────────────────────────────────────────────────────────────────
WITH per_session AS (          -- <- THE GRAIN RULE
    SELECT dimension_id,
           benchmark_version,
           session_id,
           date_trunc('week', min(evaluated_at)) AS wk,
           -- a session counts as FIRED if the dimension fired anywhere in it
           bool_or(fired) AS fired
    FROM   public.dimension_evaluations
    WHERE  benchmark_tier IN ('T1', 'T2')
      AND  fired IS NOT NULL
      AND  NOT insufficient_data
      AND  evaluated_at > now() - interval '26 weeks'
    GROUP  BY 1, 2, 3
)
SELECT dimension_id,
       benchmark_version,        -- group by this: a threshold change is a
                                 -- DISCONTINUITY, not drift
       wk,
       count(*)                                        AS n,
       sum(CASE WHEN fired THEN 1 ELSE 0 END)          AS fired
FROM   per_session
GROUP  BY 1, 2, 3
ORDER  BY 1, 2, 3;
-- Feed rows to drift_monitor.p_chart(weekly) IN CHRONOLOGICAL ORDER — the
-- 8-point run rule depends on the ordering and an unsorted input produces a
-- meaningless run signal.

-- ─────────────────────────────────────────────────────────────────────────
-- 3 · Mantel-Haenszel DIF — DEFERRED, not written here.
-- Unlocks at >= 400 evaluations/dimension AND >= 200 users per subgroup with
-- the flag stored (PM-4: profile_native_language has a column but no UI yet).
-- Specification: docs/PROMPT-irt-dif-deferred.md §3.
-- ─────────────────────────────────────────────────────────────────────────
