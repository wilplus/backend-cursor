-- Register retention schedule v1.3 and seed its one new rule: financial
-- records are kept five years (founder 2026-10-05, "It should be kept for 5
-- years"; decisions log N43). The schedule itself is signed as a PDF
-- (legal/phase1-2026.1/19-retention-schedule-v1.3-financial-records-DRAFT.md).
--
-- WHY IT MATTERS. services/data_purge.py resolves every `retain` dependency
-- through an active rule for its retention_category, and resolve_targets is
-- all-or-nothing. With financial_evidence unseeded, an account with any
-- token_ledger or llm_usage row erases NOTHING. Once this row is active the
-- purge completes: everything else is deleted and those rows are kept under
-- this rule.
--
-- ⚠ RUN BY HAND, ONCE, IN THE SUPABASE SQL EDITOR (service role), AFTER the
-- signed PDF is uploaded to its object_key. Nothing here runs on merge: this
-- file is deliberately absent from migrations/manifest.txt, as v1.2's script
-- is. It refuses to run while either placeholder is in the file.
--
-- The hash and the day are those of legal/phase1-2026.1/SIGNED-ARTIFACTS.md
-- (row 06 v1.3): signed 2026-10-05 13:42:28 UTC (PAdES), 110,851 bytes. A
-- first run with the placeholder still in the file stopped at the guard, as
-- designed. Check the uploaded object's sha256 against v_sha256 before
-- running; the guard stays for a future version.

DO $$
DECLARE
    v_object_key TEXT := 'phase1-2026.1/legal/retention-schedule-v1.3.pdf';
    v_sha256 TEXT := '59a25f9409e85e2289e8484baa4cc0fc74d5c6ed98dca2d22be443175473cfb4';
    v_authority TEXT := 'Artur Willoński';
    -- The day the controller decided the period, as the document records it.
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
            'RETENTION_SCHEDULE_V1_3_UNSIGNED: fill the sha256 and the '
            'signing day from SIGNED-ARTIFACTS.md first; nothing seeded.';
    END IF;
    IF v_sha256 !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'RETENTION_SCHEDULE_V1_3_BAD_HASH: % is not a sha256.',
            v_sha256;
    END IF;
    v_approved_at := (v_approved_at_text || ' 00:00:00+00')::timestamptz;

    -- Idempotent by (artifact_kind, version): a re-run finds the row and
    -- never UPDATEs it (the append-only trigger rejects that anyway).
    SELECT id INTO v_artifact_id
      FROM public.processing_legal_artifacts
     WHERE artifact_kind = 'retention_schedule' AND version = '1.3';

    IF v_artifact_id IS NULL THEN
        INSERT INTO public.processing_legal_artifacts (
            artifact_kind, version, approving_authority, approved_at,
            object_key, sha256, metadata
        ) VALUES (
            'retention_schedule', '1.3', v_authority, v_approved_at,
            v_object_key, v_sha256,
            jsonb_build_object(
                'control_version', 'phase1-retention-schedule-v1.3',
                'source_document',
                'legal/phase1-2026.1/19-retention-schedule-v1.3-financial-records-DRAFT.md',
                'signature_reference', 'WILLAB-PHASE1-2026.1-RET-v1.3',
                'approved_at_precision', 'day',
                'supersedes', '1.2 (signed 2026-10-02)',
                'decided', '2026-10-05 in chat ("kept for 5 years"); N43'
            )
        ) RETURNING id INTO v_artifact_id;
    ELSIF NOT EXISTS (
        SELECT 1 FROM public.processing_legal_artifacts
         WHERE id = v_artifact_id AND sha256 = v_sha256
           AND object_key = v_object_key
    ) THEN
        RAISE EXCEPTION
            'RETENTION_SCHEDULE_VERSION_CONFLICT: retention_schedule 1.3 '
            'already exists with different bytes; nothing seeded. A signed '
            'artifact is superseded, never edited (04 §5): bump to 1.4.';
    END IF;

    -- v1.3 §2. The two dependencies under this category, token_ledger and
    -- llm_usage, keep their `retain` disposition; this row is what lets the
    -- purge resolve them instead of stopping the whole erasure.
    INSERT INTO public.data_retention_rules (
        rule_code, evidence_category, retention_until_rule,
        legal_artifact_id, active
    ) VALUES
        ('financial-evidence-v1', 'financial_evidence',
         'financial_year_end_plus_5_years', v_artifact_id, true)
    ON CONFLICT (rule_code) DO NOTHING;
END;
$$;

-- ── verify ──────────────────────────────────────────────────────────────
-- Expect one row, active, pointing at retention_schedule 1.3.
SELECT r.rule_code, r.evidence_category, r.retention_until_rule, r.active,
       a.version AS schedule_version
  FROM public.data_retention_rules r
  JOIN public.processing_legal_artifacts a ON a.id = r.legal_artifact_id
 WHERE r.rule_code = 'financial-evidence-v1';
