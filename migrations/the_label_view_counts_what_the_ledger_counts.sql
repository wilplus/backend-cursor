-- 0500 · The label view counts what the ledger counts (founder 2026-10-21,
-- decisions log N111, LEARNING-AND-QUORUM.md §3 B1 and C1).
--
-- The view `snippet_label_quorum` (last written by 0289,
-- version_confidence_rating_instrument_v2.sql) and services/label_quorum.py
-- are one truth table written twice. They differed in two places:
--
--   B1  the view counted answers with `blind = false` (the rater had seen the
--       clip's non-blind side first, contract 35g-11). The ledger never did.
--       Now the view leaves them out too.
--   C1  two historical v1 `neutral` answers settled a clip as perceptually
--       ambiguous under J4 to J6 (2026-08-14), and K (2026-08-25) kept old
--       rows' meaning; the founder: "they stay settled". The status is
--       `perceptually_ambiguous`: closed, never routed again, never a label
--       (settled, settled_value and gold_eligible stay false, K4). A
--       perceptual quorum still wins; one neutral is still an IDK.
--
-- Same columns in the same order, so CREATE OR REPLACE VIEW keeps every
-- grant. Idempotent: re-running it writes the same view. Nothing dropped.
-- No environment variable needed. Needs its outside review (GPT or Grok)
-- before it merges (CLAUDE.md).

BEGIN;

CREATE OR REPLACE VIEW public.snippet_label_quorum AS
WITH eligible AS (
    SELECT snippet_id, state_id, value, unrateable
      FROM public.confidence_labels
     WHERE lane IN ('coach', 'game_peer')
       AND self_report = false
       -- B1: an answer given after seeing the clip's non-blind side is no
       -- vote (contract 35g-11; label_quorum._eligible).
       AND blind IS NOT FALSE
), counted AS (
    SELECT snippet_id,
           state_id,
           CASE
               WHEN value IN ('not_sure', 'neutral') THEN 'idk'
               ELSE value
           END AS response,
           (value = 'neutral') AS is_v1_neutral
      FROM eligible
     WHERE unrateable IS NOT TRUE
       AND value IN ('yes', 'in_between', 'no', 'not_sure', 'neutral')
), v1_neutral AS (
    -- C1: two historical v1 neutral answers keep J6's meaning.
    SELECT snippet_id, state_id, COUNT(*) AS n_v1_neutral
      FROM counted
     WHERE is_v1_neutral
     GROUP BY snippet_id, state_id
), technical AS (
    SELECT snippet_id, state_id, COUNT(*) AS n_audio_unclear
      FROM eligible
     WHERE unrateable IS TRUE OR value = 'audio_unclear'
     GROUP BY snippet_id, state_id
), ledger_keys AS (
    SELECT snippet_id, state_id FROM counted
    UNION
    SELECT snippet_id, state_id FROM technical
), tallied AS (
    SELECT snippet_id, state_id, response, COUNT(*) AS n
      FROM counted
     GROUP BY snippet_id, state_id, response
), agg AS (
    SELECT snippet_id,
           state_id,
           SUM(n) AS n_responses,
           MAX(n) AS modal_n,
           COALESCE(SUM(n) FILTER (WHERE response = 'idk'), 0) AS n_idk
      FROM tallied
     GROUP BY snippet_id, state_id
), perceptual_peak AS (
    SELECT snippet_id, state_id, MAX(n) AS modal_n
      FROM tallied
     WHERE response <> 'idk'
     GROUP BY snippet_id, state_id
), perceptual_modal AS (
    SELECT t.snippet_id,
           t.state_id,
           p.modal_n,
           COUNT(*) AS modal_ties,
           MIN(t.response) AS modal_response
      FROM tallied t
      JOIN perceptual_peak p
        ON p.snippet_id = t.snippet_id AND p.state_id = t.state_id
     WHERE t.response <> 'idk' AND t.n = p.modal_n
     GROUP BY t.snippet_id, t.state_id, p.modal_n
), self_reports AS (
    SELECT snippet_id, state_id, COUNT(*) AS n_self_report
      FROM public.confidence_labels
     WHERE self_report = true
       AND (
           unrateable IS TRUE
           OR value IN (
               'yes', 'in_between', 'no', 'not_sure',
               'audio_unclear', 'neutral'
           )
       )
     GROUP BY snippet_id, state_id
)
SELECT k.snippet_id,
       k.state_id,
       CASE
           WHEN COALESCE(t.n_audio_unclear, 0) >= 2
                THEN 'audio_quarantined'
           WHEN COALESCE(a.n_responses, 0) = 0
                AND COALESCE(t.n_audio_unclear, 0) = 1
                THEN 'audio_retry'
           WHEN COALESCE(a.n_responses, 0) = 1 THEN 'singleton'
           WHEN COALESCE(pm.modal_n, 0) >= 2 AND pm.modal_ties = 1
                THEN 'quorum'
           WHEN COALESCE(vn.n_v1_neutral, 0) >= 2
                THEN 'perceptually_ambiguous'
           WHEN COALESCE(a.n_responses, 0) < 3 THEN 'needs_third'
           ELSE 'unresolved'
       END AS status,
       CASE
           WHEN COALESCE(t.n_audio_unclear, 0) < 2
                AND COALESCE(pm.modal_n, 0) >= 2 AND pm.modal_ties = 1
                THEN pm.modal_response
           ELSE NULL
       END AS settled_value,
       (COALESCE(t.n_audio_unclear, 0) < 2
        AND COALESCE(pm.modal_n, 0) >= 2
        AND pm.modal_ties = 1) AS settled,
       (COALESCE(t.n_audio_unclear, 0) < 2
        AND COALESCE(pm.modal_n, 0) >= 2
        AND pm.modal_ties = 1) AS gold_eligible,
       (COALESCE(t.n_audio_unclear, 0) < 2
        AND COALESCE(a.n_responses, 0) = 1) AS weak_supervision_only,
       COALESCE(a.n_responses, 0) AS n_responses,
       (COALESCE(a.n_responses, 0) - COALESCE(a.n_idk, 0)) AS n_definite,
       COALESCE(a.n_idk, 0) AS n_idk,
       CASE
           WHEN COALESCE(a.n_responses, 0) > 0
                THEN ROUND(a.modal_n::numeric / a.n_responses, 4)
           ELSE 0::numeric
       END AS agreement,
       COALESCE(sr.n_self_report, 0) AS n_self_report,
       0 AS machine_votes,
       COALESCE(t.n_audio_unclear, 0) AS n_audio_unclear
  FROM ledger_keys k
  LEFT JOIN agg a
         ON a.snippet_id = k.snippet_id AND a.state_id = k.state_id
  LEFT JOIN perceptual_modal pm
         ON pm.snippet_id = k.snippet_id AND pm.state_id = k.state_id
  LEFT JOIN technical t
         ON t.snippet_id = k.snippet_id AND t.state_id = k.state_id
  LEFT JOIN self_reports sr
         ON sr.snippet_id = k.snippet_id AND sr.state_id = k.state_id
  LEFT JOIN v1_neutral vn
         ON vn.snippet_id = k.snippet_id AND vn.state_id = k.state_id;

COMMENT ON VIEW public.snippet_label_quorum IS
    'Confidence label ledger v2 (0500, N111). yes/in_between/no are '
    'perceptual positions; two matching independent blind perceptual '
    'ratings settle. not_sure and one legacy v1 neutral route a third but '
    'never settle; two legacy v1 neutrals close the artifact as '
    'perceptually_ambiguous, never a label. A non-blind answer is no vote. '
    'One independent audio_unclear/legacy unrateable report routes one '
    'retry; two quarantine the artifact from labeling and training. Three '
    'valid responses without a perceptual quorum are unresolved and '
    'excluded from gold. Machine proposals never vote.';

COMMIT;
