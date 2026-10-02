-- Register retention schedule v1.2 and seed its five rules.
-- Founder sign-off of the wording 2026-10-02 (SPEC-DECISIONS-LOG N24); the
-- schedule itself is signed as a PDF (legal/phase1-2026.1/18-retention-
-- schedule-v1.2-blind-check-and-lending-DRAFT.md §4).
--
-- RAN IN PRODUCTION 2026-10-02, by the founder (a first run with the
-- placeholder still in the file stopped at the guard, as designed). The
-- verify query returned five rows, all active, all on retention_schedule
-- 1.2 (shown to the session). Kept as the record of what was seeded.
--
-- ⚠ RUN BY HAND, ONCE, IN THE SUPABASE SQL EDITOR (service role), AFTER the
-- signed PDF is uploaded to its object_key. Nothing here runs on merge: this
-- file is deliberately absent from migrations/manifest.txt. It follows
-- migrations/the_retention_schedule_is_loaded.sql (v1.0) step for step, as a
-- script rather than a migration because its inputs are the signed file's
-- key and hash, which only exist after the founder signs and uploads.
--
-- The hash and the day are those of legal/phase1-2026.1/SIGNED-ARTIFACTS.md
-- (row 06 v1.2): signed 2026-10-02 15:53:48 UTC, 112,482 bytes. Check the
-- uploaded object's sha256 against v_sha256 before running; the guard below
-- stays for a future version.

DO $$
DECLARE
    v_object_key TEXT := 'phase1-2026.1/legal/retention-schedule-v1.2.pdf';
    v_sha256 TEXT := 'b0439d1847e4eff0d5e8eedc8efd3dcbed8317f9731e7319a91ec7abf529f479';
    v_authority TEXT := 'Artur Willoński';
    -- The day of the PAdES signature, as the document records a date.
    v_approved_at TIMESTAMPTZ := '2026-10-02 00:00:00+00';
    v_artifact_id UUID;
BEGIN
    IF to_regclass('public.data_retention_rules') IS NULL
       OR to_regclass('public.processing_legal_artifacts') IS NULL THEN
        RAISE EXCEPTION 'Phase-1 boundary absent; nothing to seed.';
    END IF;

    IF v_sha256 LIKE '[[%' OR v_approved_at::text LIKE '[[%' THEN
        RAISE EXCEPTION
            'RETENTION_SCHEDULE_V1_2_UNSIGNED: fill the sha256 and the '
            'signing day from SIGNED-ARTIFACTS.md first; nothing seeded.';
    END IF;

    -- Idempotent by (artifact_kind, version): a re-run finds the row and
    -- never UPDATEs it (the append-only trigger rejects that anyway).
    SELECT id INTO v_artifact_id
      FROM public.processing_legal_artifacts
     WHERE artifact_kind = 'retention_schedule' AND version = '1.2';

    IF v_artifact_id IS NULL THEN
        INSERT INTO public.processing_legal_artifacts (
            artifact_kind, version, approving_authority, approved_at,
            object_key, sha256, metadata
        ) VALUES (
            'retention_schedule', '1.2', v_authority, v_approved_at,
            v_object_key, v_sha256,
            jsonb_build_object(
                'control_version', 'phase1-retention-schedule-v1.2',
                'source_document',
                'legal/phase1-2026.1/18-retention-schedule-v1.2-blind-check-and-lending-DRAFT.md',
                'signature_reference', 'WILLAB-PHASE1-2026.1-RET-v1.2',
                'approved_at_precision', 'day',
                'supersedes', '1.0 (signed 2026-09-19); 1.1 was never signed',
                'wording_signed', '2026-10-02 (15 §3, 16 §3; N24)'
            )
        ) RETURNING id INTO v_artifact_id;
    ELSIF NOT EXISTS (
        SELECT 1 FROM public.processing_legal_artifacts
         WHERE id = v_artifact_id AND sha256 = v_sha256
           AND object_key = v_object_key
    ) THEN
        RAISE EXCEPTION
            'RETENTION_SCHEDULE_VERSION_CONFLICT: retention_schedule 1.2 '
            'already exists with different bytes; nothing seeded. A signed '
            'artifact is superseded, never edited (04 §5): bump to 1.3.';
    END IF;

    -- ── the rules ────────────────────────────────────────────────────────
    -- rule_code is UNIQUE, so ON CONFLICT DO NOTHING makes a re-run a no-op
    -- without touching a row that is already live.
    INSERT INTO public.data_retention_rules (
        rule_code, evidence_category, retention_until_rule,
        legal_artifact_id, active
    ) VALUES
        -- v1.1 §2, the training rows. `training_corpus` is the exact name
        -- record_training_corpus_item_v1 checks (migration 0375), and it
        -- must be active for a copy to be kept. consent-evidence-v1 is the
        -- erasure exception for ml_consent_events / ml_consent_snapshots once
        -- the registry marks them `retain` under consent_evidence (v1.1 §2;
        -- engineering's change, not this script's).
        ('training_corpus', 'training_corpus',
         'training_consent_withdrawn_or_account_erased', v_artifact_id, true),
        ('consent-evidence-v1', 'consent_evidence',
         'six_years_after_withdrawal_or_erasure', v_artifact_id, true),
        -- v1.2 §2, the three rows signed on 2026-10-02. All three tables are
        -- `delete` dispositions in services/data_purge_registry.py: the
        -- purge deletes them without consulting a rule. The rows are the
        -- signed period each lives under (15 §3, 16 §3).
        ('coach-audit-answers-v1', 'coach_audit_answers',
         'deleted_with_source_recording', v_artifact_id, true),
        ('voice-album-shares-v1', 'share_switch',
         'deleted_with_source_recording', v_artifact_id, true),
        ('listener-answers-v1', 'listener_answers',
         'account_erased', v_artifact_id, true)
    ON CONFLICT (rule_code) DO NOTHING;
END;
$$;

-- ── verify ──────────────────────────────────────────────────────────────
-- Expect five rows, all active, all pointing at retention_schedule 1.2.
SELECT r.rule_code, r.evidence_category, r.retention_until_rule, r.active,
       a.version AS schedule_version
  FROM public.data_retention_rules r
  JOIN public.processing_legal_artifacts a ON a.id = r.legal_artifact_id
 WHERE r.rule_code IN ('training_corpus', 'consent-evidence-v1',
                       'coach-audit-answers-v1', 'voice-album-shares-v1',
                       'listener-answers-v1')
 ORDER BY r.rule_code;
