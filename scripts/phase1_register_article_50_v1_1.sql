-- Register document 03 v1.1 (article_50_assessment, 1.1) by the signed
-- PDF's key and hash. Founder signed v1.1 on 2026-10-05 (decisions log
-- N48.4 Q22 A; D2 A on the Wave 3 sign-off page).
--
-- ⚠ RUN BY HAND, ONCE, IN THE SUPABASE SQL EDITOR (service role), AFTER the
-- signed PDF is uploaded to its object_key. Not a migration; absent from
-- migrations/manifest.txt. Every policy publish since 23 September carries
-- a provisional reference for this document
-- (scripts/phase1_policy_publish_unbundled.sql and each publish since);
-- this script is the real one. A signed artifact is superseded, never
-- edited (04 §5): v1.0 keeps its place, v1.1 gets its own row.
--
-- The hash is that of legal/phase1-2026.1/SIGNED-ARTIFACTS.md (row 03
-- v1.1): signed 2026-10-05 20:05:07 UTC, 132,605 bytes. approved_at is the
-- day the document records (2026-10-05); the PAdES timestamp is the
-- signature's own. Check the uploaded object's sha256 against v_sha256
-- before running; the guard below stays for a future version.

DO $$
DECLARE
    v_object_key TEXT := 'phase1-2026.1/legal/article-50-assessment-v1.1.pdf';
    v_sha256 TEXT := '97a88b6946957e5849c3fa80b3a39d6c480d35080b7b4fa792d768f85667ad6c';
    v_authority TEXT := 'Artur Willoński';
    -- The day the document records (approved_at: 2026-10-05), ISO-8601 UTC.
    v_approved_at TIMESTAMPTZ := '2026-10-05T00:00:00Z';
    v_id UUID;
BEGIN
    IF v_sha256 LIKE '[[%' OR v_approved_at::text LIKE '[[%' THEN
        RAISE EXCEPTION
            'ARTICLE_50_V1_1_UNSIGNED: fill the sha256 and the signing day '
            'from SIGNED-ARTIFACTS.md first; nothing registered.';
    END IF;

    SELECT id INTO v_id FROM public.processing_legal_artifacts
     WHERE artifact_kind = 'article_50_assessment' AND version = '1.1';

    IF v_id IS NULL THEN
        INSERT INTO public.processing_legal_artifacts (
            artifact_kind, version, approving_authority, approved_at,
            object_key, sha256, metadata
        ) VALUES (
            'article_50_assessment', '1.1', v_authority, v_approved_at,
            v_object_key, v_sha256,
            jsonb_build_object(
                'policy_version', 'phase1-2026.1',
                'ai_notice_version', 'ai-notice-3.1-2026-09-23',
                'counsel_review', 'founder_assessment_not_counsel_signed',
                'counsel_signed_letter', 'pending',
                'source_document',
                'legal/phase1-2026.1/03-article-50-assessment-v1.1-DRAFT.md',
                'signature_reference', 'WILLAB-PHASE1-2026.1-A50-v1.1',
                'supersedes', '1.0 (signed 2026-09-22)'
            )
        );
    ELSIF NOT EXISTS (
        SELECT 1 FROM public.processing_legal_artifacts
         WHERE id = v_id AND sha256 = v_sha256 AND object_key = v_object_key
    ) THEN
        RAISE EXCEPTION
            'ARTICLE_50_VERSION_CONFLICT: article_50_assessment 1.1 '
            'already exists with different bytes; nothing registered. Bump to 1.2.';
    END IF;
END;
$$;

-- ── verify ──────────────────────────────────────────────────────────────
-- Expect the 1.1 row with this hash, beside any provisional rows the
-- policy publishes registered.
SELECT version, approved_at, object_key, sha256
  FROM public.processing_legal_artifacts
 WHERE artifact_kind = 'article_50_assessment'
 ORDER BY version;
