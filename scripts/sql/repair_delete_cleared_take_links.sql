-- willab — REPAIR: take links cleared by the old delete helper.
-- Written 2026-09-25. Run by hand in the Supabase SQL editor. Nothing runs
-- this automatically, and the UPDATE only runs on session ids you paste in.
--
-- WHAT HAPPENED. Before #653, db.takes.v2_delete_session first set
-- v2_sessions.report_id and recording_1_id to NULL (committed on its own),
-- then DELETEd the row. For a canonical Take the DELETE is refused (ON DELETE
-- RESTRICT lineage, manifest 0296/0297/0315/0327), so the Take survived with
-- both links cut. That hit the project delete (#647, live 08:36-09:08 UTC on
-- 2026-09-25) and every earlier trainings-page delete of such a Take.
--
-- WHY IT IS REPAIRABLE. The delete never happened, so nothing that pointed AT
-- the Take moved: v2_reports.session_v2_id and recordings.session_v2_id still
-- name it. The link can be rebuilt from those rows.
--
-- WHICH TAKES. The helper logged each refused Take. Search the Railway logs of
-- the web service for
--     presentation delete: session delete failed sid=
-- and paste every sid into the `affected` list in steps 2 and 3. Step 1 also
-- lists candidates found by shape alone. A NULL link can be legitimate (a take
-- that never had a report), so a candidate is not repaired unless you paste
-- its id.
--
-- AC-9: internal audit surface. No output here reaches a user.

-- ── STEP 1 · Candidates by shape (read-only) ────────────────────────────────
-- Takes with a NULL link that some row still points back to.
SELECT s.id                              AS session_id,
       s.user_id,
       s.created_at,
       s.report_id                       AS report_id_now,
       (SELECT r.id FROM v2_reports r
         WHERE r.session_v2_id = s.id
         ORDER BY r.created_at DESC NULLS LAST, r.id
         LIMIT 1)                        AS report_id_candidate,
       s.recording_1_id                  AS recording_1_id_now,
       (SELECT rec.id FROM recordings rec
         WHERE rec.session_v2_id = s.id
         ORDER BY rec.created_at ASC NULLS LAST, rec.id
         LIMIT 1)                        AS recording_1_id_candidate
  FROM v2_sessions s
 WHERE (s.report_id IS NULL
        AND EXISTS (SELECT 1 FROM v2_reports r WHERE r.session_v2_id = s.id))
    OR (s.recording_1_id IS NULL
        AND EXISTS (SELECT 1 FROM recordings rec WHERE rec.session_v2_id = s.id))
 ORDER BY s.created_at DESC;

-- ── STEP 2 · Preview the repair for the pasted ids (read-only) ─────────────
-- Replace the example id with the sids from the logs, one per row.
WITH affected(session_id) AS (
    VALUES ('00000000-0000-0000-0000-000000000000'::uuid)
),
plan AS (
    SELECT s.id AS session_id,
           s.report_id AS report_id_now,
           COALESCE(s.report_id,
               (SELECT r.id FROM v2_reports r
                 WHERE r.session_v2_id = s.id
                 ORDER BY r.created_at DESC NULLS LAST, r.id
                 LIMIT 1)) AS report_id_after,
           s.recording_1_id AS recording_1_id_now,
           COALESCE(s.recording_1_id,
               (SELECT rec.id FROM recordings rec
                 WHERE rec.session_v2_id = s.id
                 ORDER BY rec.created_at ASC NULLS LAST, rec.id
                 LIMIT 1)) AS recording_1_id_after
      FROM v2_sessions s
      JOIN affected a ON a.session_id = s.id
)
SELECT * FROM plan
 WHERE report_id_after IS DISTINCT FROM report_id_now
    OR recording_1_id_after IS DISTINCT FROM recording_1_id_now;

-- ── STEP 3 · Apply (writes) ─────────────────────────────────────────────────
-- Same list as step 2. It only fills links that are NULL now, never
-- overwrites one. Check the row count against step 2, then COMMIT, or
-- ROLLBACK if it differs.
BEGIN;

WITH affected(session_id) AS (
    VALUES ('00000000-0000-0000-0000-000000000000'::uuid)
)
UPDATE v2_sessions s
   SET report_id = COALESCE(s.report_id,
           (SELECT r.id FROM v2_reports r
             WHERE r.session_v2_id = s.id
             ORDER BY r.created_at DESC NULLS LAST, r.id
             LIMIT 1)),
       recording_1_id = COALESCE(s.recording_1_id,
           (SELECT rec.id FROM recordings rec
             WHERE rec.session_v2_id = s.id
             ORDER BY rec.created_at ASC NULLS LAST, rec.id
             LIMIT 1))
  FROM affected a
 WHERE a.session_id = s.id
   AND (s.report_id IS NULL OR s.recording_1_id IS NULL);

-- COMMIT;
-- ROLLBACK;
