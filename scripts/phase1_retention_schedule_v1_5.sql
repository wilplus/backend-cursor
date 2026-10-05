-- Register retention schedule v1.5: the founder's answers to what v1.4 left
-- open (founder 2026-10-05, decisions log N50 item 5: "P1 A / P2 A / P3 A /
-- P4 A / P5 A / P6 A / P7 A"). The schedule itself is signed as a PDF
-- (legal/phase1-2026.1/22-retention-schedule-v1.5-what-v1.4-left-open-DRAFT.md).
--
-- WHAT IT DOES. It registers the signed document under
-- (retention_schedule, 1.5), and nothing else: v1.5 seeds no rule. Each
-- entry it decides points at a rule an earlier signed version seeded and
-- whose period already says what the founder decided: product-records-v1
-- (v1.4: deleted with the account or the project), consent-evidence-v1
-- (v1.2: six years) and financial-evidence-v1 (v1.3: five years from the end
-- of the financial year).
--
-- WHY IT MATTERS. services/data_purge_registry.py marks v1.5's entries
-- `schedule="1.5"`. The purge acts on such an entry only while its rule is
-- active AND this row exists; until then the entry does exactly what it did
-- before v1.5 (a matching row stops the erasure for review, nothing is
-- deleted). Migration 0429 (migrations/the_purge_reaches_what_v1_5_decided.sql)
-- lets the append-only tables pass a running purge's deletes, and it checks
-- this same row, so the database refuses those deletes too until it exists.
-- Running this script is what switches v1.5 on.
--
-- ⚠ RUN BY HAND, ONCE, IN THE SUPABASE SQL EDITOR (service role), AFTER the
-- signed PDF is uploaded to its object_key. Nothing here runs on merge: this
-- file is deliberately absent from migrations/manifest.txt, as the v1.2,
-- v1.3 and v1.4 scripts are. It refuses to run
--   * while the hash placeholder is in the file;
--   * unless all three rules above are active (run the v1.2, v1.3 and v1.4
--     scripts first: v1.5 decides nothing without them);
--   * unless 0429 is in this database (a migration that fails on boot does
--     not stop the boot, so a deploy alone does not prove it landed).
--
-- The day is the one the controller decided the answers, as the document
-- records it; the hash is the signed PDF's, from SIGNED-ARTIFACTS.md. Check
-- the uploaded object's sha256 against v_sha256 before running.

DO $$
DECLARE
    v_object_key TEXT := 'phase1-2026.1/legal/retention-schedule-v1.5.pdf';
    v_sha256 TEXT := '[[sha256 of the signed PDF, from SIGNED-ARTIFACTS.md]]';
    v_authority TEXT := 'Artur Willoński';
    v_approved_at_text TEXT := '2026-10-05';
    v_approved_at TIMESTAMPTZ;
    v_artifact_id UUID;
    v_rules INTEGER;
BEGIN
    IF to_regclass('public.data_retention_rules') IS NULL
       OR to_regclass('public.processing_legal_artifacts') IS NULL THEN
        RAISE EXCEPTION 'Phase-1 boundary absent; nothing registered.';
    END IF;

    IF v_sha256 LIKE '[[%' OR v_approved_at_text LIKE '[[%' THEN
        RAISE EXCEPTION
            'RETENTION_SCHEDULE_V1_5_UNSIGNED: fill the sha256 from '
            'SIGNED-ARTIFACTS.md first; nothing registered.';
    END IF;
    IF v_sha256 !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'RETENTION_SCHEDULE_V1_5_BAD_HASH: % is not a sha256.',
            v_sha256;
    END IF;

    SELECT count(DISTINCT rule.rule_code) INTO v_rules
      FROM public.data_retention_rules rule
     WHERE rule.active
       AND (rule.rule_code, rule.evidence_category) IN (
           ('product-records-v1', 'product_records'),
           ('consent-evidence-v1', 'consent_evidence'),
           ('financial-evidence-v1', 'financial_evidence'));
    IF v_rules <> 3 THEN
        RAISE EXCEPTION
            'RETENTION_SCHEDULE_V1_5_RULES_MISSING: v1.5 points at '
            'product-records-v1, consent-evidence-v1 and '
            'financial-evidence-v1, and % of the three are active. Run the '
            'v1.2, v1.3 and v1.4 scripts first; nothing registered.', v_rules;
    END IF;

    IF to_regprocedure('public.phase1_purge_names_row_v1(text,jsonb)') IS NULL
       OR to_regprocedure('public.check_phase1_purge_delete_v1('
                          'text,text,text[],integer,jsonb)') IS NULL THEN
        RAISE EXCEPTION
            'RETENTION_SCHEDULE_V1_5_PURGE_NOT_DEPLOYED: migration 0429 '
            '(the_purge_reaches_what_v1_5_decided.sql) is not in this '
            'database; nothing registered.';
    END IF;

    v_approved_at := (v_approved_at_text || ' 00:00:00+00')::timestamptz;

    -- Idempotent by (artifact_kind, version): a re-run finds the row and
    -- never UPDATEs it (the append-only trigger rejects that anyway).
    SELECT id INTO v_artifact_id
      FROM public.processing_legal_artifacts
     WHERE artifact_kind = 'retention_schedule' AND version = '1.5';

    IF v_artifact_id IS NULL THEN
        INSERT INTO public.processing_legal_artifacts (
            artifact_kind, version, approving_authority, approved_at,
            object_key, sha256, metadata
        ) VALUES (
            'retention_schedule', '1.5', v_authority, v_approved_at,
            v_object_key, v_sha256,
            jsonb_build_object(
                'control_version', 'phase1-retention-schedule-v1.5',
                'source_document',
                'legal/phase1-2026.1/22-retention-schedule-v1.5-what-v1.4-left-open-DRAFT.md',
                'signature_reference', 'WILLAB-PHASE1-2026.1-RET-v1.5',
                'approved_at_precision', 'day',
                'supersedes', '1.4 (signed 2026-10-05)',
                'decided', '2026-10-05 on the Wave 3 sign-off page ("P1 A ... P7 A"); N50 item 5',
                'rules_seeded', jsonb_build_array()
            )
        ) RETURNING id INTO v_artifact_id;
    ELSIF NOT EXISTS (
        SELECT 1 FROM public.processing_legal_artifacts
         WHERE id = v_artifact_id AND sha256 = v_sha256
           AND object_key = v_object_key
    ) THEN
        RAISE EXCEPTION
            'RETENTION_SCHEDULE_VERSION_CONFLICT: retention_schedule 1.5 '
            'already exists with different bytes; nothing registered. A '
            'signed artifact is superseded, never edited (04 §5): bump to 1.6.';
    END IF;
END;
$$;

-- ── verify ──────────────────────────────────────────────────────────────
-- Expect one 1.5 row, and the three rules v1.5 points at, all active.
SELECT 'retention_schedule ' || a.version AS registered, a.sha256,
       (SELECT string_agg(r.rule_code || CASE WHEN r.active THEN ' (active)'
                                             ELSE ' (INACTIVE)' END,
                          ', ' ORDER BY r.rule_code)
          FROM public.data_retention_rules r
         WHERE r.rule_code IN ('product-records-v1', 'consent-evidence-v1',
                               'financial-evidence-v1')) AS rules_it_points_at
  FROM public.processing_legal_artifacts a
 WHERE a.artifact_kind = 'retention_schedule' AND a.version = '1.5';
