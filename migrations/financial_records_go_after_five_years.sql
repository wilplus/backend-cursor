-- 0426 · The founder's bug list leaves the clean-up, and financial records
--        go when their five years end (founder 2026-10-05, the Wave 3
--        sign-off: decisions log N50 item 6 C4 B and item 5 P7; retention
--        schedule v1.3 §1-§2, v1.4 §5.7).
--
-- C4 B. `dev_bugs` is the founder's own bug list (a text, an image, open or
-- shipped; no personal data), not a log, and stays out of the clean-up.
-- retention_log_relations_v1 is re-issued from 0423 without its row, and
-- that is all: everything that reads the log list (the report's rule 3
-- lines, a live run's listing, what a run records as due) follows it. The
-- table, its rows and its grants are untouched.
--
-- P7. v1.3 keeps purchase and token-use records (`token_ledger`,
-- `llm_usage`; rule `financial-evidence-v1`, retention_until_rule
-- `financial_year_end_plus_5_years`) "5 years from the end of the financial
-- year in which the record was made", and said that nothing yet deleted them
-- when the five years end. The clean-up now does, for every account, open
-- or deleted, and counts them first:
--
--   * THE FINANCIAL YEAR is the calendar year, read in Polish time
--     (Europe/Warsaw): the controller is a natural person in Poland
--     (działalność nieewidencjonowana), whose financial year is the calendar
--     year. A row made on 10 March 2026 belongs to 2026, its five years end
--     with 31 December 2031, and it is due from 1 January 2032, 00:00 in
--     Warsaw. Reading the year in Warsaw time means a row made in the last
--     hour of 31 December UTC, already 1 January in Poland, is never taken a
--     year early. Written once, in retention_financial_cut_v1.
--   * AN ERASURE UNDER WAY KEEPS THE CLEAN-UP OUT, as for audio (0423): a
--     row whose account has an unfinished account-wide purge waits for it.
--     That purge counted the account's rows when it froze its inventory, and
--     a resumed purge that counts differently is refused
--     (PURGE_INVENTORY_REPLAY_CONFLICT). The purge itself keeps these rows
--     (disposition `retain`), so once it is done the clean-up takes them
--     when their years end.
--   * RULE 4 of retention_report_v1 counts them, one line per table, so a
--     dry run and scripts/retention_report.sql show them before anything
--     goes. A live run removes them through PostgREST by id, in batches,
--     from these two tables only (services/retention_cleaner.py), behind
--     the same RETENTION_CLEANER_LIVE key, which stays False.
--   * WHAT READS AN OLD ROW. The balance lives on the account
--     (v2_student_details) and is never summed from the ledger; no receipt
--     and no Stripe reconciliation reads it. The readers that look a row up
--     by its reference do so not to act twice: a charge (token_charge), a
--     grant (token_account._already_charged: admin grants, Stripe package
--     deliveries, which Stripe stops repeating after days), a coach-review
--     refund (refund_coach_review_credit_v1, which answers 'not_charged'
--     once the charge row has gone) and the per-arc "already paid" read
--     (charged_actions_for_ref). The one visible effect: a per-arc action
--     ('insights', 'moment_explanation') re-opened on an arc whose charge
--     row has gone is charged again, once, while token pricing is on. The
--     wallet history (token_account.history) loses rows past their years,
--     which is the deletion itself. 0233's conversion guard reads its own
--     rows, but a migration is applied once and never again.
--
-- THE DOOR. The service role may remove rows of the two tables and read
-- only their id and created_at to do it (SELECT (id, created_at), DELETE),
-- as 0423 gave it on the backpressure log; Supabase's defaults may already
-- give it more. Nothing is granted to anyone else. No migration gives
-- either table a guard trigger (the ledger is append-only by convention
-- since 0229, never by trigger) or a foreign key pointing at it. Each grant
-- is guarded on its table existing, as 0425 does.
--
-- Additive and idempotent: four functions re-issued from 0423 (each its
-- text plus its one change: the log list, the counter's keys, the listing's
-- rule 4, the report's rule 4; pinned by
-- tests/test_financial_records_go_after_five_years.py) and five new ones.
-- GRANT is a no-op when held. No row changes, no statement here removes
-- one, and no environment variable is read.

BEGIN;

-- ── C4 B: the log list without the founder's bug list ───────────────────

-- Rule 3. Exactly the four technical logs (the report's list of 2026-10-05
-- without dev_bugs, N50 C4 B), and, for each, the evidence whose rows keep
-- a log row alive: a row that evidence points at is kept, because deleting
-- it would rewrite that evidence (ON DELETE SET NULL on append-only,
-- retained rows).
CREATE OR REPLACE FUNCTION public.retention_log_relations_v1()
RETURNS TABLE (relation text, kept_when_referenced_by text[])
LANGUAGE sql IMMUTABLE SET search_path = public
AS $$
    SELECT * FROM (VALUES
        ('admin_annotations_log', ARRAY[]::text[]),
        ('life_reminder_log', ARRAY[]::text[]),
        ('mlc3_service_backpressure_events', ARRAY[]::text[]),
        ('processing_jobs', ARRAY['processing_stage_runs.processing_job_id',
                                  'processing_transition_events.processing_job_id'])
    ) AS l(relation, kept_when_referenced_by)
$$;

-- ── P7: financial records whose five years have ended ──────────────────

-- The founder's period for financial records (v1.3), and nowhere else: the
-- start of the Warsaw calendar year five years before the run's own year.
-- A row made before it belongs to a financial year that ended at least five
-- years ago.
CREATE OR REPLACE FUNCTION public.retention_financial_cut_v1(p_as_of timestamptz)
RETURNS timestamptz
LANGUAGE sql STABLE SET search_path = public
AS $$
    SELECT (date_trunc('year', p_as_of AT TIME ZONE 'Europe/Warsaw')
            - interval '5 years') AT TIME ZONE 'Europe/Warsaw'
$$;

-- Rule 4. Exactly v1.3's two financial tables, and the column that names
-- the account a row belongs to.
CREATE OR REPLACE FUNCTION public.retention_financial_relations_v1()
RETURNS TABLE (relation text, account_column text)
LANGUAGE sql IMMUTABLE SET search_path = public
AS $$
    SELECT * FROM (VALUES
        ('llm_usage', 'user_id'),
        ('token_ledger', 'user_id')
    ) AS f(relation, account_column)
$$;

-- The WHERE clause over alias t for one table's due rows (the cut is $1):
-- made before the cut, and no unfinished account-wide erasure of the
-- account the row names. NULL where the table or a column it needs is
-- absent: a database without them holds none of it.
CREATE OR REPLACE FUNCTION public.retention_financial_condition_v1(
    p_relation text
) RETURNS text
LANGUAGE plpgsql STABLE SET search_path = public
AS $$
DECLARE account text;
BEGIN
    SELECT f.account_column INTO account
      FROM public.retention_financial_relations_v1() f
     WHERE f.relation = p_relation;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'RETENTION_FINANCIAL_RELATION_UNKNOWN';
    END IF;
    IF NOT (public.retention_column_present_v1(p_relation, 'id')
            AND public.retention_column_present_v1(p_relation, 'created_at')
            AND public.retention_column_present_v1(p_relation, account)) THEN
        RETURN NULL;
    END IF;
    RETURN format(
        't.created_at < $1 AND NOT EXISTS ('
        'SELECT 1 FROM public.owner_principals p '
        'JOIN public.data_purge_requests r ON r.acquisition_principal_id = p.id '
        'WHERE p.user_id::text = t.%I AND r.state <> ''done'' '
        'AND r.project_id IS NULL /* 0378: account-wide purges only */)',
        account);
END;
$$;

CREATE OR REPLACE FUNCTION public.retention_due_financial_v1(p_as_of timestamptz)
RETURNS TABLE (relation text, due bigint)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = public
AS $$
#variable_conflict use_column
DECLARE f record; cut timestamptz; condition text;
BEGIN
    cut := public.retention_financial_cut_v1(p_as_of);
    FOR f IN SELECT * FROM public.retention_financial_relations_v1() r
              ORDER BY r.relation LOOP
        relation := f.relation;
        due := 0;
        condition := public.retention_financial_condition_v1(f.relation);
        IF condition IS NOT NULL THEN
            EXECUTE format('SELECT count(*) FROM public.%I t WHERE %s',
                           f.relation, condition)
               INTO due USING cut;
        END IF;
        RETURN NEXT;
    END LOOP;
END;
$$;

CREATE OR REPLACE FUNCTION public.retention_due_financial_ids_v1(
    p_as_of timestamptz, p_relation text, p_limit integer
) RETURNS TABLE (row_id text)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = public
AS $$
#variable_conflict use_column
DECLARE condition text := public.retention_financial_condition_v1(p_relation);
BEGIN
    IF condition IS NULL THEN
        RETURN;
    END IF;
    RETURN QUERY EXECUTE format(
        'SELECT t.id::text FROM public.%I t WHERE %s '
        'ORDER BY t.created_at, t.id LIMIT %s',
        p_relation, condition, p_limit)
        USING public.retention_financial_cut_v1(p_as_of);
END;
$$;

-- ── Re-issued from 0423 with rule 4 (each its text plus one change) ─────

-- What a run may count: rule 4's keys (financial.<table>) beside the
-- others.
CREATE OR REPLACE FUNCTION public.retention_count_v1(
    p_run_id uuid, p_key text, p_n bigint
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE done_now jsonb;
BEGIN
    IF p_key IS NULL
       OR p_key !~ '^(guests|audio|measurements|logs|financial)\.[a-z0-9_.]+$'
       OR p_n IS NULL OR p_n < 0 THEN
        RAISE EXCEPTION 'RETENTION_COUNTER_INVALID';
    END IF;
    UPDATE public.retention_cleaner_runs
       SET done = jsonb_set(done, ARRAY[p_key],
                            to_jsonb(COALESCE((done ->> p_key)::bigint, 0) + p_n))
     WHERE id = p_run_id AND mode = 'live' AND state = 'running'
    RETURNING done INTO done_now;
    IF done_now IS NULL THEN
        RAISE EXCEPTION 'RETENTION_RUN_NOT_LIVE';
    END IF;
    RETURN done_now;
END;
$$;

-- What a live run works through, in a stable order, at the run's moment:
-- rule 4 lists a financial table's due ids as rule 3 lists a log's.
CREATE OR REPLACE FUNCTION public.list_retention_due_v1(
    p_run_id uuid, p_rule text, p_relation text DEFAULT NULL,
    p_limit integer DEFAULT 100
) RETURNS TABLE (item_id text)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = public
AS $$
#variable_conflict use_column
DECLARE run public.retention_cleaner_runs;
BEGIN
    SELECT * INTO run FROM public.retention_cleaner_runs WHERE id = p_run_id;
    IF run.id IS NULL OR run.mode <> 'live' OR run.state <> 'running' THEN
        RAISE EXCEPTION 'RETENTION_RUN_NOT_LIVE';
    END IF;
    IF p_limit IS NULL OR p_limit < 1 OR p_limit > 1000 THEN
        RAISE EXCEPTION 'RETENTION_LIMIT_INVALID';
    END IF;
    -- Work never tried before comes first, so a guest whose erasure stopped
    -- for review (left for a person), or a recording whose object would not
    -- go (tried again), cannot hold the rest back.
    IF p_rule = 'guests' THEN
        RETURN QUERY SELECT g.principal_id::text
                       FROM public.retention_due_guests_v1(run.as_of) g
                      ORDER BY EXISTS (
                                   SELECT 1 FROM public.data_purge_requests r
                                    WHERE r.acquisition_principal_id = g.principal_id),
                               1
                      LIMIT p_limit;
    ELSIF p_rule = 'audio' THEN
        RETURN QUERY SELECT d.audio_object_id::text
                       FROM public.retention_due_audio_v1(run.as_of) d
                      ORDER BY EXISTS (
                                   SELECT 1 FROM public.retention_cleaner_audio_claims c
                                    WHERE c.audio_object_id = d.audio_object_id),
                               1
                      LIMIT p_limit;
    ELSIF p_rule = 'logs' AND EXISTS (
              SELECT 1 FROM public.retention_log_relations_v1() l
               WHERE l.relation = p_relation) THEN
        RETURN QUERY SELECT x.row_id
                       FROM public.retention_due_log_ids_v1(
                           run.as_of, p_relation, p_limit) x;
    ELSIF p_rule = 'financial' AND EXISTS (
              SELECT 1 FROM public.retention_financial_relations_v1() f
               WHERE f.relation = p_relation) THEN
        RETURN QUERY SELECT x.row_id
                       FROM public.retention_due_financial_ids_v1(
                           run.as_of, p_relation, p_limit) x;
    ELSE
        RAISE EXCEPTION 'RETENTION_RULE_UNKNOWN';
    END IF;
END;
$$;

-- THE REPORT. One row per rule and line, counts only; nothing by person.
-- scripts/retention_report.sql reads exactly this, and so does every run.
-- Rule 4: one line per financial table.
CREATE OR REPLACE FUNCTION public.retention_report_v1(
    p_as_of timestamptz DEFAULT now()
) RETURNS TABLE (rule integer, would_delete text, how_many bigint)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = public
AS $$
#variable_conflict use_column
BEGIN
    RETURN QUERY
    SELECT lines.rule, lines.would_delete, lines.how_many FROM (
        SELECT 1::integer AS rule,
               'unclaimed guests older than 30 days'::text AS would_delete,
               (SELECT count(*) FROM public.retention_due_guests_v1(p_as_of))::bigint
                   AS how_many
        UNION ALL
        SELECT 1, 'their recordings (audio files)',
               (SELECT count(*) FROM public.retention_live_audio_v1() a
                 WHERE a.acquisition_principal_id IN (
                     SELECT g.principal_id
                       FROM public.retention_due_guests_v1(p_as_of) g))::bigint
        UNION ALL
        SELECT 2, 'audio files not used for 12 months',
               (SELECT count(*) FROM public.retention_due_audio_v1(p_as_of))::bigint
        UNION ALL
        SELECT 2, 'voice measurements with that audio: ' || m.store, m.how_many
          FROM public.retention_due_measurements_v1(p_as_of) m
        UNION ALL
        SELECT 3, 'log rows older than 90 days: ' || l.relation, l.due
          FROM public.retention_due_logs_v1(p_as_of) l
        UNION ALL
        SELECT 3, 'log rows older than 90 days kept, deletion evidence points '
                  'at them: ' || l.relation, l.kept
          FROM public.retention_due_logs_v1(p_as_of) l
         WHERE l.kept IS NOT NULL
        UNION ALL
        SELECT 4, 'financial records whose five years have ended: '
                  || f.relation, f.due
          FROM public.retention_due_financial_v1(p_as_of) f
    ) AS lines
    ORDER BY lines.rule, lines.would_delete;
END;
$$;

-- ── The door: rule 4's deletes, for the service role only ──────────────

DO $financial_records_door$
BEGIN
    IF to_regclass('public.llm_usage') IS NOT NULL THEN
        GRANT SELECT (id, created_at), DELETE ON public.llm_usage TO service_role;
    END IF;
    IF to_regclass('public.token_ledger') IS NOT NULL THEN
        GRANT SELECT (id, created_at), DELETE ON public.token_ledger TO service_role;
    END IF;
END
$financial_records_door$;

-- ── Grants: browsers never; the service role as 0423 has it ─────────────

REVOKE ALL ON FUNCTION public.retention_log_relations_v1() FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.retention_financial_cut_v1(timestamptz) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.retention_financial_relations_v1() FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.retention_financial_condition_v1(text) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.retention_due_financial_v1(timestamptz) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.retention_due_financial_ids_v1(timestamptz, text, integer) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.retention_count_v1(uuid, text, bigint) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.list_retention_due_v1(uuid, text, text, integer) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.retention_report_v1(timestamptz) FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION public.retention_log_relations_v1() TO service_role;
GRANT EXECUTE ON FUNCTION public.retention_financial_relations_v1() TO service_role;
GRANT EXECUTE ON FUNCTION public.list_retention_due_v1(uuid, text, text, integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.retention_report_v1(timestamptz) TO service_role;

COMMIT;

NOTIFY pgrst, 'reload schema';
