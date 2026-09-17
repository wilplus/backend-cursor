-- Phase-1 retention schedule: the legal artifact + the rules that reference it.
-- Control version: phase1-retention-schedule-v1
--
-- ─────────────────────────────────────────────────────────────────────────────
-- WHY THIS FILE IS IN migrations/pending/ AND NOT IN manifest.txt
--
-- MIGRATE_ON_BOOT=1: merging a manifest entry RUNS it in production during
-- container start. This migration needs the object_key and sha256 of the SIGNED
-- retention schedule PDF, and that document is not signed
-- (legal/phase1-2026.1/06-retention-schedule-v1.0-DRAFT.md §4 holds it open on
-- OpenAI's own retention window). Inventing those two values would write a
-- record asserting that a document exists and was approved, into an append-only
-- table that cannot be corrected afterwards.
--
-- The CONFIG-FIRST rule's own escape hatch applies: keep the migration out of
-- manifest.txt until the document lands. A migration that RAISED on placeholder
-- values would be the wrong protection — under MIGRATE_ON_BOOT a raising
-- migration fails container start, so an accidental merge would take production
-- down rather than merely not seed a table.
--
-- TO SHIP: fill the two values below from the signed PDF, move this file to
-- migrations/, append it to manifest.txt, and re-run scripts/local_ci.sh
-- --with-rehearsal.
--
-- ─────────────────────────────────────────────────────────────────────────────
-- WHY A MIGRATION AND NOT A SECURITY DEFINER RPC
--
-- data_retention_rules.legal_artifact_id is NOT NULL into
-- processing_legal_artifacts, which (a) carries the append-only
-- BEFORE UPDATE OR DELETE trigger installed by
-- add_phase1_processing_boundary.sql and (b) grants service_role SELECT only.
-- The artifact and the rules must therefore land in ONE transaction, and the
-- writer must be the owner.
--
-- Migrations run as owner and bypass the grant, so a migration needs no new
-- capability. An RPC would need INSERT on an append-only evidence table —
-- a standing, callable write path into the table whose whole value is that
-- almost nothing can write to it, created to be used once. The narrower tool
-- that already exists wins.
--
-- (register_phase1_policy_v1 inserts the other three artifact kinds this way
-- because it must accept them at call time from an operator. A retention
-- schedule has no such caller: it is seeded once with the rules it anchors.)
--
-- ─────────────────────────────────────────────────────────────────────────────
-- ⚠️ THE CATEGORY VOCABULARY IS NOT THE ONE IN DOC 06 §2
--
-- services/data_purge.py:231 resolves a rule by matching
-- data_retention_rules.evidence_category against
-- PurgeDependency.retention_category — and ONLY for dependencies whose
-- disposition is 'retain' (services/data_purge.py:295). Everything else is
-- deleted outright and never consults this table at all.
--
-- Doc 06 §2's `evidence_category` column holds target_kind values
-- (r2_object, transcript, cache, coach_packet, …). Those are a different
-- column of a different table (data_purge_targets.target_kind) and match no
-- retention_category anywhere in the registry. Seeding doc 06 verbatim would
-- create twelve active rows that resolve nothing, leave all sixteen
-- retain-dependencies on RETENTION_RULE_UNRESOLVED, and — because
-- resolve_targets is all-or-nothing ("Unknown inventory means zero deletion",
-- services/data_purge.py:720) — still delete nothing for anyone, while the
-- table now looks populated.
--
-- The five rows below are the complete set of retention_category values in
-- services/data_purge_registry.py::DEPENDENCIES. tests/test_phase1_retention_
-- schedule_seed.py asserts that set against this file, so a sixth category
-- added later fails CI instead of silently reintroducing the same outage.
-- ─────────────────────────────────────────────────────────────────────────────

DO $$
DECLARE
    -- [[FOUNDER: from the signed PDF — storage path]]
    v_object_key TEXT := 'legal/phase1-2026.1/06-retention-schedule-v1.0.pdf';
    -- [[FOUNDER: sha256sum of the signed PDF, lowercase hex]]
    v_sha256 TEXT := NULL;
    v_authority TEXT := NULL;      -- [[FOUNDER: named person or firm]]
    v_approved_at TIMESTAMPTZ := NULL;  -- [[FOUNDER: signature timestamp, UTC]]
    v_artifact_id UUID;
BEGIN
    -- Degrade gracefully: if the Phase-1 boundary has not been applied yet
    -- there is nothing to seed, and this must not be the migration that fails.
    IF to_regclass('public.data_retention_rules') IS NULL
       OR to_regclass('public.processing_legal_artifacts') IS NULL THEN
        RAISE NOTICE 'Phase-1 boundary absent; retention schedule not seeded.';
        RETURN;
    END IF;

    IF v_sha256 IS NULL OR v_authority IS NULL OR v_approved_at IS NULL THEN
        RAISE NOTICE
            'Retention schedule unsigned; nothing seeded. Fill the [[FOUNDER]] '
            'values before adding this file to manifest.txt.';
        RETURN;
    END IF;

    -- Idempotent by (artifact_kind, version), which the table already makes
    -- UNIQUE. Re-applying finds the existing row rather than inserting a
    -- second one — and never UPDATEs it, because the append-only trigger
    -- rejects that even from the owner.
    SELECT id INTO v_artifact_id
      FROM public.processing_legal_artifacts
     WHERE artifact_kind = 'retention_schedule' AND version = '1.0';

    IF v_artifact_id IS NULL THEN
        INSERT INTO public.processing_legal_artifacts (
            artifact_kind, version, approving_authority, approved_at,
            object_key, sha256, metadata
        ) VALUES (
            'retention_schedule', '1.0', v_authority, v_approved_at,
            v_object_key, v_sha256,
            jsonb_build_object(
                'control_version', 'phase1-retention-schedule-v1',
                'source_document',
                'legal/phase1-2026.1/06-retention-schedule-v1.0.md'
            )
        ) RETURNING id INTO v_artifact_id;
    ELSIF NOT EXISTS (
        SELECT 1 FROM public.processing_legal_artifacts
         WHERE id = v_artifact_id AND sha256 = v_sha256
           AND object_key = v_object_key
    ) THEN
        -- A different document already occupies this version. Silently reusing
        -- it would anchor the rules to bytes nobody reviewed.
        RAISE EXCEPTION
            'RETENTION_SCHEDULE_VERSION_CONFLICT: retention_schedule 1.0 '
            'already exists with different bytes. Bump the version.';
    END IF;

    -- ── the rules ────────────────────────────────────────────────────────
    -- One row per retention_category the orchestrator can encounter.
    -- rule_code is UNIQUE, so ON CONFLICT DO NOTHING makes re-application a
    -- no-op without touching a row that is already live.

    INSERT INTO public.data_retention_rules (
        rule_code, evidence_category, retention_until_rule,
        legal_artifact_id, active
    ) VALUES
        -- APPROVED BY THE FOUNDER 2026-09-17, from doc 06 §2.
        ('authorization-evidence-v1', 'authorization_evidence',
         'accountability_need_ends', v_artifact_id, true),
        ('billing-record-5y-v1', 'financial_evidence',
         'financial_year_end + 5 years', v_artifact_id, true),
        ('provider-operation-with-parent-v1', 'processor_evidence',
         'parent_recording_retention', v_artifact_id, true),

        -- ⚠️ PROPOSED, NOT YET APPROVED. Doc 06 §2 gives no rule for these two
        -- categories, because its table was written against target_kind rather
        -- than retention_category. Both cover append-only evidence tables whose
        -- purpose is to prove that something happened — the same shape as
        -- authorization_evidence — so the same trigger is proposed. THE FOUNDER
        -- MUST CONFIRM THESE TWO AND DOC 06 §2 MUST BE CORRECTED TO MATCH
        -- before this file ships; the database and the published schedule
        -- disagreeing is the exact drift this whole scheme exists to prevent.
        --
        --   deletion_evidence   → processing_audio_objects,
        --                         processing_audio_object_deletion_events,
        --                         processing_recording_attempts,
        --                         processing_service_blocks, owner_principals,
        --                         owner_claim_events
        --   transparency_evidence → ai_transparency_exposures
        ('deletion-evidence-v1', 'deletion_evidence',
         'accountability_need_ends', v_artifact_id, true),
        ('transparency-evidence-v1', 'transparency_evidence',
         'accountability_need_ends', v_artifact_id, true)
    ON CONFLICT (rule_code) DO NOTHING;

    -- DELIBERATELY ABSENT: dataset_lineage, model_lineage and unknown.
    -- No Phase-2 processing is authorised, so neither lineage kind should ever
    -- appear as a target; if one does, that is a bug and fail-closed is the
    -- correct outcome. A catch-all row would convert "we do not know what this
    -- is" into "we have handled it", which is the failure the boundary exists
    -- to prevent. Do not add one for coverage.
END;
$$;
