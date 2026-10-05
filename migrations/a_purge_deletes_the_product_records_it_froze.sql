-- 0424. A purge deletes the product records it froze (retention schedule
-- v1.4, founder 2026-10-05, decisions log N48.4 Q15 A: "product records are
-- deleted with the account or the project").
--
-- THE PROBLEM. Three tables hold what a Take showed, the speaker's own
-- answers and every version of a Paragraph: take_feedback_exposure,
-- take_feedback_self_report and ideal_text_part_revision (0293). They are
-- append-only: reject_immutable_feedback_mutation() refuses every UPDATE and
-- DELETE. So the purge could never delete them, and every real erasure of
-- anyone with feedback stopped for review on them (N14.3, N14.5).
--
-- THE RULE (v1.4). They are product records, deleted with the account or
-- the project, under the signed rule product-records-v1, which
-- scripts/phase1_retention_rules_v1_4.sql seeds once the founder signs.
--
-- HOW, WITHOUT OPENING THE TABLES. The trigger allows one governed DELETE,
-- proved from the purge's own sealed rows, never from a setting a caller can
-- choose:
--   * only on these three tables (the shadow frames and the detector
--     reconciliation, which share the function, stay closed);
--   * only while a purge request is `in_progress` with a sealed inventory;
--   * only of a row that request's frozen inventory names: a `pending`
--     target for this relation, disposition `delete`, whose frozen locator
--     values (checked by the freeze against the subject graph the server
--     resolves) hold the row's own selector value;
--   * only under an ACTIVE rule of category `product_records`, which that
--     target names in its metadata.
-- service_role may read those purge rows but never write them (0310); the
-- freeze, a SECURITY DEFINER function, is their only writer. Until the
-- founder runs the v1.4 script no such rule exists, the branch never opens,
-- and every DELETE still raises exactly as before.
--
-- No row is touched by running this file, and it holds no row removal: the
-- purge deletes through its own reviewed path (services/data_purge.py), at
-- purge time, for a request a person made.
--
-- ADDITIVE AND IDEMPOTENT. CREATE OR REPLACE FUNCTION only; the refusal and
-- its message are unchanged for every other case. Not a D11 writer.

BEGIN;

CREATE OR REPLACE FUNCTION public.reject_immutable_feedback_mutation()
RETURNS trigger LANGUAGE plpgsql SET search_path = public AS $$
DECLARE
    row_data JSONB;
BEGIN
    -- Retention schedule v1.4: a running, frozen purge may delete exactly
    -- the rows its inventory names, under the active product-records rule.
    IF TG_OP = 'DELETE' AND TG_TABLE_NAME IN (
        'take_feedback_exposure', 'take_feedback_self_report',
        'ideal_text_part_revision'
    ) THEN
        row_data := to_jsonb(OLD);
        IF EXISTS (
            SELECT 1
              FROM public.data_purge_requests purge
              JOIN public.data_purge_inventory_manifests manifest
                ON manifest.purge_request_id = purge.id
              JOIN public.data_purge_targets target
                ON target.purge_request_id = purge.id
              JOIN public.data_retention_rules rule
                ON rule.id::text = target.metadata ->> 'retention_rule_id'
             WHERE purge.state = 'in_progress'
               AND target.state = 'pending'
               AND target.target_ref =
                   'dependency:' || (target.metadata ->> 'dependency_code')
               AND target.metadata ->> 'relation' = TG_TABLE_NAME
               AND target.metadata ->> 'disposition' = 'delete'
               AND rule.active
               AND rule.evidence_category = 'product_records'
               AND jsonb_typeof(target.metadata -> 'locator_values') = 'array'
               AND (target.metadata -> 'locator_values') ?
                   (row_data ->> (target.metadata ->> 'selector_column'))
        ) THEN
            RETURN OLD;
        END IF;
    END IF;
    RAISE EXCEPTION 'immutable feedback evidence cannot be changed';
END;
$$;

REVOKE ALL ON FUNCTION public.reject_immutable_feedback_mutation()
    FROM PUBLIC, anon, authenticated;

COMMIT;
