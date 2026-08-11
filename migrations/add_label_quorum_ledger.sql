-- THE LABEL LEDGER — quorum, self-report separation, machine-as-router
-- (founder 2026-08-11, four rules). services/label_quorum.py is the twin.
--
-- WHAT CHANGES, AND WHY EACH ONE
--
--   machine_value   RULE 1 — THE MACHINE IS A ROUTER, NOT A RATER. Its
--                   prediction picks WHICH clip a human is asked about; it is
--                   never one of the answers, and quorum is strictly two
--                   humans. So the proposal gets its OWN column BESIDE the
--                   human answer and is never blended into `value`.
--
--                   Why store it at all: without it, "which prediction did
--                   this human disagree with" is unanswerable after the fact,
--                   and that disagreement is the entire active-learning
--                   signal (rule 3). `model_version_at_time` already says
--                   WHICH machine — the pair is what makes a row readable in
--                   a year.
--
--                   Same domain as `value` and a SEPARATE column, so no query
--                   can accidentally union the two into one vote count. It is
--                   stamped SERVER-SIDE at write time: a client-supplied
--                   proposal would mean the value came from the rater's
--                   screen, and I1 (blind stream) turns on that never being
--                   true. `saw_model_output` stays false and stays the audit.
--
--   self_report     RULE 2 — THE OWNER IS NOT A PEER. A rating of one's own
--                   clip is self-assessment: the rater knows what they
--                   intended, which is the one judgment that is not
--                   independent of the thing judged. Marked distinctly,
--                   excluded from quorum, kept for rater calibration.
--
--                   WHY A COLUMN WHEN lane='game_owner' ALREADY IMPLIES IT.
--                   `lane` records which SURFACE the rating came from, not
--                   whose clip it was. A coach rating their own recording
--                   writes lane='coach' and is still a self-report; so is the
--                   owner answering through any future surface. Deriving the
--                   exclusion from lane makes it wrong in exactly the cases
--                   that matter, and unqueryable afterwards. Backfilled from
--                   lane (and, where the session is joinable, from actual
--                   ownership) so history is honest rather than assumed.
--
--   snippet_label_quorum
--                   RULE 3 + RULE 4, as a view: the SETTLED state marked in
--                   the DB, and the routing queue as one query.
--
--                   A VIEW, not a written column, on purpose. The status is a
--                   pure function of the rows; a stored copy would need a
--                   writer on every rating path and would go stale the first
--                   time one of them failed best-effort (they all write
--                   best-effort). A view cannot drift from the rows it reads.
--
-- THE ONE RULE ALL FOUR FOUNDER CASES FALL OUT OF. Count every eligible
-- response, IDK included; settled when one response is STRICTLY modal with
-- at least 2 votes. This table is duplicated verbatim in
-- services/label_quorum.py — the two implementations are kept in step by it:
--
--     (none)                       -> unrated
--     exactly 1 (any)              -> singleton                (weak only)
--     modal >=2, unique, not idk   -> quorum                   (SETTLED)
--     modal >=2, unique, idk       -> perceptually_ambiguous   (SETTLED)
--     >=2 with no unique modal >=2 -> needs_third
--
--   1 definite + 1 idk -> 1/1, no modal >=2 -> needs_third   (founder case B)
--   idk + idk          -> modal idk x2      -> perceptually_ambiguous (case C)
--
-- RULE 4 — IDK IS A RESPONSE, NOT A NULL. `unrateable` is the response this
-- schema stores as a NULL `value`, which is precisely what it must stop
-- being. Two of them is a FINDING (SPEC I10): a detector taught to say
-- "uncertain" where humans are uncertain beats one that fakes confidence
-- there, and this is the only place that class can come from.
--
-- KNOWN WRINKLE, recorded rather than papered over: the arc game writes its
-- third answer as 'neutral' (game_engine._normalise_answer), while
-- `unrateable` is documented as the rater declining — usually unclear audio.
-- So a perceptually_ambiguous row today can be two people who could not HEAR
-- the clip rather than two who heard genuine ambiguity. The fix is a
-- capture-time reason on the abstention (founder call, follow-up); until
-- then the view exposes n_idk / n_definite so the class stays auditable.
--
-- FENCES. AC-9: every column and every view row here is machine-facing —
-- a status is a verdict and never reaches a user payload; "perceptually
-- ambiguous" is a DB state, never a badge. BLIND COACH: machine_value is
-- stored beside the human answer and read only for ROUTING; it is never
-- served into a rating payload.
--
-- Nothing is dropped. Idempotent; safe to re-run. Columns are added to a
-- table that already has RLS enabled (add_state_generic_ratings.sql).

ALTER TABLE public.confidence_labels
    ADD COLUMN IF NOT EXISTS machine_value TEXT NULL,
    ADD COLUMN IF NOT EXISTS self_report   BOOLEAN NOT NULL DEFAULT false;

-- machine_value shares the ternary domain but NEVER the column. Same CHECK
-- shape as ck_confidence_labels_value so a proposal is comparable to an
-- answer without ever being one.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'ck_confidence_labels_machine_value'
    ) THEN
        ALTER TABLE public.confidence_labels
            ADD CONSTRAINT ck_confidence_labels_machine_value
            CHECK (machine_value IS NULL
                   OR machine_value IN ('yes', 'no', 'neutral'));
    END IF;
END$$;

COMMENT ON COLUMN public.confidence_labels.machine_value IS
    'RULE 1 (founder 2026-08-11) — the machine PROPOSAL that routed this clip '
    'to a rater. Beside the human answer, never blended into `value`, never '
    'a vote: quorum is strictly two humans. Stamped server-side; the rater '
    'never saw it (saw_model_output stays false).';
COMMENT ON COLUMN public.confidence_labels.self_report IS
    'RULE 2 (founder 2026-08-11) — the rater is the owner of the clip. '
    'Excluded from the 2-peer quorum ground truth; kept for rater '
    'calibration. Distinct from lane=''game_owner'', which records the '
    'surface rather than the ownership.';

-- BACKFILL 1 — the lane that always meant self-report.
UPDATE public.confidence_labels
   SET self_report = true
 WHERE self_report = false
   AND lane = 'game_owner';

-- BACKFILL 2 — actual ownership, for the rows lane could never catch (a
-- coach, or anyone else, rating a session they own). Guarded on v2_sessions
-- existing so the migration still applies on a schema that predates it.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
         WHERE table_schema = 'public' AND table_name = 'v2_sessions'
    ) THEN
        UPDATE public.confidence_labels cl
           SET self_report = true
          FROM public.v2_sessions s
         WHERE cl.self_report = false
           AND cl.session_id IS NOT NULL
           AND cl.rater_id   IS NOT NULL
           AND s.id      = cl.session_id
           AND s.user_id = cl.rater_id;
    END IF;
END$$;

-- The append-only history gets the same two stamps (I9, full label
-- provenance). The CURRENT row keeps only the latest pair, so without these
-- the proposal a rater actually disagreed with is lost the moment they
-- re-rate — and that row is precisely what rule 3's active learning wants to
-- read back. Guarded on the table existing (it arrives in 0258).
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
         WHERE table_schema = 'public' AND table_name = 'label_revision'
    ) THEN
        ALTER TABLE public.label_revision
            ADD COLUMN IF NOT EXISTS machine_value TEXT NULL,
            ADD COLUMN IF NOT EXISTS self_report   BOOLEAN NOT NULL DEFAULT false;
    END IF;
END$$;

-- The routing queue's read: "which snippets still need a rater", quorum lanes
-- only. Partial on the exclusions so the queue scan never walks self-reports.
CREATE INDEX IF NOT EXISTS idx_confidence_labels_quorum_pull
    ON public.confidence_labels (state_id, snippet_id)
    WHERE self_report = false AND lane IN ('coach', 'game_peer');

-- ── the ledger view ─────────────────────────────────────────────────────────
--
-- One row per (snippet_id, state_id) that has at least one eligible response.
-- A snippet with none is absent, which is the honest encoding of 'unrated':
-- nobody has looked, and the view has nothing to say about it. The Python
-- twin returns status='unrated' for that case because it is handed the
-- snippet; SQL is handed the rows.
CREATE OR REPLACE VIEW public.snippet_label_quorum AS
WITH counted AS (
    -- RULE 1: quorum lanes are human-only, and there is no machine lane a row
    -- could carry. RULE 2: self-reports drop out here, counted separately
    -- below. RULE 4: an abstention becomes the response 'idk', not a NULL.
    SELECT snippet_id,
           state_id,
           CASE WHEN unrateable THEN 'idk' ELSE value END AS response
      FROM public.confidence_labels
     WHERE lane IN ('coach', 'game_peer')
       AND self_report = false
       AND (unrateable OR value IS NOT NULL)
), tallied AS (
    SELECT snippet_id, state_id, response, COUNT(*) AS n
      FROM counted
     GROUP BY snippet_id, state_id, response
), agg AS (
    SELECT snippet_id,
           state_id,
           SUM(n)                                        AS n_responses,
           MAX(n)                                        AS modal_n,
           COALESCE(SUM(n) FILTER (WHERE response = 'idk'), 0) AS n_idk
      FROM tallied
     GROUP BY snippet_id, state_id
), modal AS (
    -- How many responses TIE for the lead, and which one leads when only one
    -- does. The tie count is what separates 'quorum' from 'needs_third'.
    SELECT t.snippet_id,
           t.state_id,
           COUNT(*)         AS modal_ties,
           MIN(t.response)  AS modal_response
      FROM tallied t
      JOIN agg a ON a.snippet_id = t.snippet_id AND a.state_id = t.state_id
     WHERE t.n = a.modal_n
     GROUP BY t.snippet_id, t.state_id
), self_reports AS (
    SELECT snippet_id, state_id, COUNT(*) AS n_self_report
      FROM public.confidence_labels
     WHERE self_report = true
       AND (unrateable OR value IS NOT NULL)
     GROUP BY snippet_id, state_id
)
SELECT a.snippet_id,
       a.state_id,
       CASE
           WHEN a.n_responses = 1 THEN 'singleton'
           WHEN a.modal_n >= 2 AND m.modal_ties = 1 AND m.modal_response = 'idk'
                THEN 'perceptually_ambiguous'
           WHEN a.modal_n >= 2 AND m.modal_ties = 1 THEN 'quorum'
           ELSE 'needs_third'
       END AS status,
       CASE
           WHEN a.modal_n >= 2 AND m.modal_ties = 1 AND m.modal_response = 'idk'
                THEN 'ambiguous'
           WHEN a.modal_n >= 2 AND m.modal_ties = 1 THEN m.modal_response
           ELSE NULL
       END AS settled_value,
       (a.modal_n >= 2 AND m.modal_ties = 1)      AS settled,
       -- RULE 3: a singleton is never gold and never evaluation data.
       (a.modal_n >= 2 AND m.modal_ties = 1)      AS gold_eligible,
       (a.n_responses = 1)                        AS weak_supervision_only,
       a.n_responses,
       (a.n_responses - a.n_idk)                  AS n_definite,
       a.n_idk,
       ROUND(a.modal_n::numeric / a.n_responses, 4) AS agreement,
       COALESCE(sr.n_self_report, 0)              AS n_self_report,
       -- RULE 1, reported rather than asserted: if this is ever non-zero a
       -- machine got a vote and every agreement number below is circular.
       0                                          AS machine_votes
  FROM agg a
  JOIN modal m ON m.snippet_id = a.snippet_id AND m.state_id = a.state_id
  LEFT JOIN self_reports sr
         ON sr.snippet_id = a.snippet_id AND sr.state_id = a.state_id;

COMMENT ON VIEW public.snippet_label_quorum IS
    'The label ledger (founder 2026-08-11) — per-snippet quorum status. '
    'Machine proposals are never votes (rule 1); self-reports are excluded '
    'and counted (rule 2); a singleton is weak supervision, never gold '
    '(rule 3); two IDKs settle as perceptually ambiguous (rule 4). Twin of '
    'services/label_quorum.py. AC-9: machine-facing, never surfaced.';
