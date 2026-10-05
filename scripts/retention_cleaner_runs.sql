-- What the scheduled clean-up did: its run records. Read-only.
-- (Migration 0423; services/retention_cleaner.py; decisions log N48.4 Q16 A.)
--
-- RUN IN THE SUPABASE SQL EDITOR. Two SELECTs; counts only, nothing by person.
--
-- 1. The last runs: dry or live, what was asked for, any refusal, how it
--    ended. A dry run deletes nothing. A live run asked for while
--    RETENTION_CLEANER_LIVE is False is `refused`: it only counted. A live
--    run's `done` counts what it did by key; two keys mean it left guests
--    due on purpose: guests.held_purge_execution_off (the guests it would
--    have taken on, held because the web service does not have
--    PHASE1_PURGE_EXECUTION_ENABLED=true, the purge kill switch) and
--    guests.skipped_left_for_a_person (the guest's erasure stopped for
--    review earlier; a person takes it from there). `left_due` (query 2)
--    has the full count still due.

SELECT started_at, finished_at, requested_mode, mode, state, refusal,
       error_code, as_of, cleaner_version, done
  FROM public.retention_cleaner_runs
 ORDER BY started_at DESC
 LIMIT 10;

-- 2. The latest run's lines: what was due when it started (`due`, the same
--    lines as scripts/retention_report.sql at that moment) and, for a live
--    run, what was still due when it ended (`still_due`).

SELECT r.started_at, r.mode, r.state, d.rule, d.would_delete,
       d.how_many AS due, s.how_many AS still_due
  FROM (SELECT * FROM public.retention_cleaner_runs
         ORDER BY started_at DESC LIMIT 1) r
 CROSS JOIN LATERAL jsonb_to_recordset(r.due)
       AS d(rule integer, would_delete text, how_many bigint)
  LEFT JOIN LATERAL jsonb_to_recordset(COALESCE(r.left_due, '[]'::jsonb))
       AS s(rule integer, would_delete text, how_many bigint)
    ON s.rule = d.rule AND s.would_delete = d.would_delete
 ORDER BY d.rule, d.would_delete;
