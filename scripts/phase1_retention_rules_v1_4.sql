-- Register retention schedule v1.4 and seed its two new rules: product
-- records are deleted with the account or the project, and job evidence is
-- kept 12 months (founder 2026-10-05, "Q15 A"; decisions log N48.4). The
-- schedule itself is signed as a PDF
-- (legal/phase1-2026.1/20-retention-schedule-v1.4-product-records-and-job-evidence-DRAFT.md).
--
-- WHY IT MATTERS. services/data_purge_registry.py names these two rules on
-- the dependencies v1.4 decides (`ruled_by`). Until a row with each
-- rule_code is ACTIVE, those dependencies act exactly as they did before
-- v1.4: a matching row stops the erasure for review (EXPLICIT_RESOLVER_
-- REQUIRED) and nothing is deleted, because resolve_targets is
-- all-or-nothing. Once both rows are active the purge acts on them by
-- itself: product records are deleted (the three append-only feedback
-- tables through the governed trigger of
-- migrations/a_purge_deletes_the_product_records_it_froze.sql), job
-- evidence is kept under job-evidence-v1. Running this script is what
-- switches that on, which is why it runs only after the purge change is
-- deployed (below).
--
-- ⚠ RUN BY HAND, ONCE, IN THE SUPABASE SQL EDITOR (service role), AFTER the
-- signed PDF is uploaded to its object_key. Nothing here runs on merge: this
-- file is deliberately absent from migrations/manifest.txt, as the v1.2 and
-- v1.3 scripts are. It refuses to run while either placeholder is in the
-- file.
--
-- ⚠ AND ONLY AFTER 0424 AND 0425 ARE DEPLOYED. 0424
-- (migrations/a_purge_deletes_the_product_records_it_froze.sql) and the
-- purge code with it are what act on these rules; 0425
-- (migrations/the_purge_can_delete_job_plumbing.sql) lets the purge delete
-- the three job tables it deletes with the account
-- (phase1_processing_outbox, processing_job_carryovers,
-- processing_orphan_objects), on which the phase-1 boundary migration left
-- the service role SELECT alone. With these rules active an erasure of
-- someone who recorded no longer stops for review at the feedback tables;
-- without 0425 it would reach those three tables and stop part-way, after
-- the audio is gone.
--
-- The hash and the day are those of legal/phase1-2026.1/SIGNED-ARTIFACTS.md
-- (row 06 v1.4): signed 2026-10-05 20:05:07 UTC (PAdES), 127,109 bytes.
-- Check the uploaded object's sha256 against v_sha256 before running; the
-- guard stays for a future version.

DO $$
DECLARE
    v_object_key TEXT := 'phase1-2026.1/legal/retention-schedule-v1.4.pdf';
    v_sha256 TEXT := 'f3a19127bd586913ebe5c0a1f2a97c5e24646c8e1fb44e3fef312346200afee6';
    v_authority TEXT := 'Artur Willoński';
    -- The day the controller decided the rule, as the document records it.
    v_approved_at_text TEXT := '2026-10-05';
    v_approved_at TIMESTAMPTZ;
    v_artifact_id UUID;
BEGIN
    IF to_regclass('public.data_retention_rules') IS NULL
       OR to_regclass('public.processing_legal_artifacts') IS NULL THEN
        RAISE EXCEPTION 'Phase-1 boundary absent; nothing to seed.';
    END IF;

    IF v_sha256 LIKE '[[%' OR v_approved_at_text LIKE '[[%' THEN
        RAISE EXCEPTION
            'RETENTION_SCHEDULE_V1_4_UNSIGNED: fill the sha256 and the '
            'signing day from SIGNED-ARTIFACTS.md first; nothing seeded.';
    END IF;
    IF v_sha256 !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'RETENTION_SCHEDULE_V1_4_BAD_HASH: % is not a sha256.',
            v_sha256;
    END IF;
    v_approved_at := (v_approved_at_text || ' 00:00:00+00')::timestamptz;

    -- Idempotent by (artifact_kind, version): a re-run finds the row and
    -- never UPDATEs it (the append-only trigger rejects that anyway).
    SELECT id INTO v_artifact_id
      FROM public.processing_legal_artifacts
     WHERE artifact_kind = 'retention_schedule' AND version = '1.4';

    IF v_artifact_id IS NULL THEN
        INSERT INTO public.processing_legal_artifacts (
            artifact_kind, version, approving_authority, approved_at,
            object_key, sha256, metadata
        ) VALUES (
            'retention_schedule', '1.4', v_authority, v_approved_at,
            v_object_key, v_sha256,
            jsonb_build_object(
                'control_version', 'phase1-retention-schedule-v1.4',
                'source_document',
                'legal/phase1-2026.1/20-retention-schedule-v1.4-product-records-and-job-evidence-DRAFT.md',
                'signature_reference', 'WILLAB-PHASE1-2026.1-RET-v1.4',
                'approved_at_precision', 'day',
                'supersedes', '1.3 (signed 2026-10-05)',
                'decided', '2026-10-05 in chat ("Q15 A"); N48.4'
            )
        ) RETURNING id INTO v_artifact_id;
    ELSIF NOT EXISTS (
        SELECT 1 FROM public.processing_legal_artifacts
         WHERE id = v_artifact_id AND sha256 = v_sha256
           AND object_key = v_object_key
    ) THEN
        RAISE EXCEPTION
            'RETENTION_SCHEDULE_VERSION_CONFLICT: retention_schedule 1.4 '
            'already exists with different bytes; nothing seeded. A signed '
            'artifact is superseded, never edited (04 §5): bump to 1.5.';
    END IF;

    -- v1.4 §2. The dependencies under each category are listed in the
    -- schedule and named `ruled_by` in services/data_purge_registry.py.
    INSERT INTO public.data_retention_rules (
        rule_code, evidence_category, retention_until_rule,
        legal_artifact_id, active
    ) VALUES
        ('product-records-v1', 'product_records',
         'deleted_with_account_or_project', v_artifact_id, true),
        ('job-evidence-v1', 'job_evidence',
         'recorded_plus_12_months', v_artifact_id, true)
    ON CONFLICT (rule_code) DO NOTHING;
END;
$$;

-- ── verify ──────────────────────────────────────────────────────────────
-- Expect two rows, both active, both pointing at retention_schedule 1.4.
SELECT r.rule_code, r.evidence_category, r.retention_until_rule, r.active,
       a.version AS schedule_version
  FROM public.data_retention_rules r
  JOIN public.processing_legal_artifacts a ON a.id = r.legal_artifact_id
 WHERE r.rule_code IN ('product-records-v1', 'job-evidence-v1')
 ORDER BY r.rule_code;
