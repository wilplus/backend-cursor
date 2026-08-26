-- 0289 · Confidence blind-label instrument v2.
--
-- New blind ratings use five explicit values:
--   yes | in_between | no | not_sure | audio_unclear
--
-- `neutral` remains accepted only so conf-q-v1 history stays readable. It is
-- NOT reused by v2: old neutral rows retain their v1 meaning (IDK), while the
-- v2 perceptual middle is `in_between`. `unrateable` likewise remains for old
-- clients and rows; new clients write `audio_unclear` as an explicit value.
--
-- The machine remains a router, never a voter. Its middle proposal becomes
-- `in_between`; historical machine `neutral` stamps remain valid.

BEGIN;

ALTER TABLE public.confidence_labels
    DROP CONSTRAINT IF EXISTS ck_confidence_labels_value;
ALTER TABLE public.confidence_labels
    ADD CONSTRAINT ck_confidence_labels_value
    CHECK (value IS NULL OR value IN (
        'yes', 'in_between', 'no', 'not_sure', 'audio_unclear', 'neutral'
    ));

ALTER TABLE public.confidence_labels
    DROP CONSTRAINT IF EXISTS ck_confidence_labels_machine_value;
ALTER TABLE public.confidence_labels
    ADD CONSTRAINT ck_confidence_labels_machine_value
    CHECK (machine_value IS NULL OR machine_value IN (
        'yes', 'in_between', 'no', 'neutral'
    ));

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
         WHERE table_schema = 'public' AND table_name = 'label_revision'
    ) THEN
        ALTER TABLE public.label_revision
            DROP CONSTRAINT IF EXISTS ck_label_revision_value;
        ALTER TABLE public.label_revision
            ADD CONSTRAINT ck_label_revision_value
            CHECK (value IS NULL OR value IN (
                'yes', 'in_between', 'no', 'not_sure',
                'audio_unclear', 'neutral'
            ));
    END IF;
END$$;

CREATE OR REPLACE VIEW public.snippet_label_quorum AS
WITH eligible AS (
    SELECT snippet_id, state_id, value, unrateable
      FROM public.confidence_labels
     WHERE lane IN ('coach', 'game_peer')
       AND self_report = false
), counted AS (
    SELECT snippet_id,
           state_id,
           CASE
               WHEN value IN ('not_sure', 'neutral') THEN 'idk'
               ELSE value
           END AS response
      FROM eligible
     WHERE unrateable IS NOT TRUE
       AND value IN ('yes', 'in_between', 'no', 'not_sure', 'neutral')
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
         ON sr.snippet_id = k.snippet_id AND sr.state_id = k.state_id;

COMMENT ON VIEW public.snippet_label_quorum IS
    'Confidence label ledger v2. yes/in_between/no are perceptual positions; '
    'two matching independent perceptual ratings settle. not_sure (and '
    'legacy v1 neutral) route a third but never settle. One independent '
    'audio_unclear/legacy unrateable report routes one retry; two quarantine '
    'the artifact from labeling and training. Three valid responses without '
    'a perceptual quorum are unresolved and excluded from gold. Machine '
    'proposals never vote.';

COMMIT;
