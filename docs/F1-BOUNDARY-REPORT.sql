-- F1 — word→slide boundary report (run in Supabase → SQL Editor)
--
-- Answers ONE question: is it worth asking the FE to measure the recorder
-- clock offset exactly (docs/PROMPT-FE-audio-clock-offset.md), or is
-- pause-snap already handling the drift?
--
-- Prerequisites: migrations/add_boundary_metrics.sql has run, and at least a
-- few DECKED takes have been recorded since that deploy. Deckless takes have
-- no slide boundaries and are skipped by design (the metric returns NULL
-- rather than a misleading zero), so an empty result means "no decked takes
-- yet", NOT "no problem".
--
-- Nothing here is user-facing (AC-9) — this is an internal engineering read.

-- ── 1. THE VERDICT ────────────────────────────────────────────────────────
WITH m AS (
    SELECT boundary_metrics AS b
      FROM v2_sessions
     WHERE boundary_metrics IS NOT NULL
), agg AS (
    SELECT
        count(*)                                          AS takes,
        sum((b->>'words_total')::int)                     AS words,
        sum((b->>'words_at_risk')::int)                   AS words_at_risk,
        sum((b->>'words_reassigned')::int)                AS words_snap_moved,
        sum((b->>'boundaries_total')::int)                AS bounds,
        sum((b->>'boundaries_moved')::int)                AS bounds_moved,
        sum(COALESCE((b->>'boundaries_no_pause')::int, 0))        AS bounds_no_pause,
        sum(COALESCE((b->>'boundaries_already_aligned')::int, 0)) AS bounds_aligned,
        max((b->>'shift_ms_max')::int)                    AS shift_max_ms,
        round(avg(NULLIF((b->>'shift_ms_median')::int, 0)))       AS shift_typical_ms
      FROM m
)
SELECT
    takes,
    bounds                                                        AS slide_boundaries,
    -- EXPOSURE: how much of the transcript sits close enough to a tap that
    -- clock drift could move it to the wrong slide.
    round(100.0 * words_at_risk  / NULLIF(words, 0), 1)           AS pct_words_at_risk,
    -- IMPACT: what pause-snap actually changed.
    round(100.0 * words_snap_moved / NULLIF(words, 0), 1)         AS pct_words_snap_moved,
    -- REACH: the decisive one. Boundaries with no pause to snap into are the
    -- ones pause-snap can NEVER fix and a measured offset WOULD.
    round(100.0 * bounds_no_pause / NULLIF(bounds, 0), 1)         AS pct_bounds_snap_cannot_fix,
    round(100.0 * bounds_moved    / NULLIF(bounds, 0), 1)         AS pct_bounds_snap_fixed,
    round(100.0 * bounds_aligned  / NULLIF(bounds, 0), 1)         AS pct_bounds_already_fine,
    shift_typical_ms,
    shift_max_ms,
    CASE
        WHEN takes < 5 THEN
            'NOT ENOUGH DATA — need ~5+ decked takes before trusting this'
        WHEN bounds_no_pause = 0 AND shift_typical_ms IS NULL THEN
            'NO DRIFT DETECTED — boundaries already land in pauses. Do NOT spend FE time.'
        WHEN round(100.0 * bounds_no_pause / NULLIF(bounds, 0), 1) >= 30 THEN
            'PUSH THE FE FIX — pause-snap cannot reach a large share of boundaries'
        WHEN round(100.0 * bounds_no_pause / NULLIF(bounds, 0), 1) >= 10 THEN
            'WORTH IT IF CHEAP — a real minority of boundaries are unreachable'
        ELSE
            'LOW PRIORITY — pause-snap is covering nearly all boundaries'
    END AS verdict
  FROM agg;

-- ── 2. Per-take detail (sanity-check the aggregate; spot one weird take) ──
-- SELECT id,
--        (boundary_metrics->>'slides_total')::int              AS slides,
--        (boundary_metrics->>'boundaries_total')::int          AS bounds,
--        (boundary_metrics->>'boundaries_no_pause')::int       AS cannot_fix,
--        (boundary_metrics->>'boundaries_moved')::int          AS snapped,
--        (boundary_metrics->>'words_reassigned')::int          AS words_moved,
--        (boundary_metrics->>'shift_ms_median')::int           AS typical_shift_ms,
--        (boundary_metrics->>'snap_enabled')::boolean          AS snap_on,
--        created_at
--   FROM v2_sessions
--  WHERE boundary_metrics IS NOT NULL
--  ORDER BY created_at DESC
--  LIMIT 25;

-- ── How to read it ────────────────────────────────────────────────────────
--
-- pct_bounds_snap_cannot_fix is THE number. Those boundaries had no speech
-- pause near the tap — the speaker talked straight through it — so pause-snap
-- has nothing to aim at no matter how it is tuned. A measured clock offset
-- fixes them because it does not depend on finding a silence.
--
-- shift_typical_ms says whether a systematic drift exists at all. Tens of ms
-- is noise; 150ms+ is a real recorder warm-up worth measuring exactly.
--
-- pct_words_at_risk sizes the blast radius. If it is ~1%, the whole issue is
-- small regardless of the other columns, and F1 effort belongs elsewhere.
--
-- CAVEAT, and it matters: none of this is an accuracy rate. There is no ground
-- truth for which slide a word truly belonged to — that is exactly what the
-- drift destroys. These measure EXPOSURE and REACH, not correctness. A high
-- pct_words_snap_moved means pause-snap changed a lot, not that it was right.
