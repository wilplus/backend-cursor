-- Register document 02 v1.1 (power_score_classification, 1.1) by the signed
-- PDF's key and hash. Founder signed v1.1 on 2026-10-02 (N24).
--
-- NOT YET RUN. When it has run, record the day and the time here.
--
-- ⚠ RUN BY HAND, ONCE, IN THE SUPABASE SQL EDITOR (service role), AFTER the
-- signed PDF is uploaded to its object_key. Not a migration; absent from
-- migrations/manifest.txt. The 3.3 publish (scripts/phase1_policy_publish_
-- 3_3.sql) carries a provisional reference for this document, as 3.2 did;
-- this script is the real one. A signed artifact is superseded, never
-- edited (04 §5): v1.0 keeps its row, v1.1 gets its own.
--
-- Fill the two placeholders from legal/phase1-2026.1/SIGNED-ARTIFACTS.md
-- (row 02 v1.1) and nothing else. The block refuses while either is a
-- placeholder.

DO $$
DECLARE
    v_object_key TEXT := 'phase1-2026.1/legal/power-score-classification-v1.1.pdf';
    v_sha256 TEXT := '[[sha256 of the signed v1.1 PDF, as uploaded]]';
    v_authority TEXT := 'Artur Willoński';
    -- The PAdES timestamp of the signature, ISO-8601 UTC.
    v_approved_at TIMESTAMPTZ := '[[YYYY-MM-DDThh:mm:ssZ]]';
    v_id UUID;
BEGIN
    IF v_sha256 LIKE '[[%' OR v_approved_at::text LIKE '[[%' THEN
        RAISE EXCEPTION
            'POWER_SCORE_V1_1_UNSIGNED: fill the sha256 and the signing time '
            'from SIGNED-ARTIFACTS.md first; nothing registered.';
    END IF;

    SELECT id INTO v_id FROM public.processing_legal_artifacts
     WHERE artifact_kind = 'power_score_classification' AND version = '1.1';

    IF v_id IS NULL THEN
        INSERT INTO public.processing_legal_artifacts (
            artifact_kind, version, approving_authority, approved_at,
            object_key, sha256, metadata
        ) VALUES (
            'power_score_classification', '1.1', v_authority, v_approved_at,
            v_object_key, v_sha256,
            jsonb_build_object(
                'pipeline_version', 'voice-confidence-universal-v3',
                'detector_versions', jsonb_build_object('rushing', 'rules-v1',
                    'word_compression', 'rules-v1', 'ending_compression', 'rules-v1'),
                'biometric_identification', false,
                'sex_gender_inference', false,
                'emotion_intention_inference', false,
                'counsel_review', 'founder_determination_not_counsel_reviewed',
                'condition', 'engaged: a person other than the founder has recorded (v1.1 §9)',
                'source_document',
                'legal/phase1-2026.1/02-power-score-classification-v1.1-DRAFT.md',
                'signature_reference', 'WILLAB-PHASE1-2026.1-PSC-v1.1',
                'supersedes', '1.0 (signed 2026-09-22)'
            )
        );
    ELSIF NOT EXISTS (
        SELECT 1 FROM public.processing_legal_artifacts
         WHERE id = v_id AND sha256 = v_sha256 AND object_key = v_object_key
    ) THEN
        RAISE EXCEPTION
            'POWER_SCORE_VERSION_CONFLICT: power_score_classification 1.1 '
            'already exists with different bytes; nothing registered. Bump to 1.2.';
    END IF;
END;
$$;

-- ── verify ──────────────────────────────────────────────────────────────
-- Expect two rows, 1.0 and 1.1, each with its own hash.
SELECT version, approved_at, object_key, sha256
  FROM public.processing_legal_artifacts
 WHERE artifact_kind = 'power_score_classification'
 ORDER BY version;
