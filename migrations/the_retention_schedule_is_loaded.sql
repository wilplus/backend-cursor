-- Phase-1 retention schedule: the legal artifact + the rules that reference it.
-- Control version: phase1-retention-schedule-v1
--
-- ─────────────────────────────────────────────────────────────────────────────
-- 0381. LOADED ON THE FOUNDER'S DECISION (2026-09-26, decisions log N13).
--
-- MIGRATE_ON_BOOT=1: merging this manifest entry RUNS it in production during
-- container start. It registers retention schedule v1.0 by the coordinates in
-- legal/phase1-2026.1/SIGNED-ARTIFACTS.md row 06 and seeds the rules that
-- reference it. Nothing is deleted by it; the purge still needs an operator.
--
-- The founder chose to load it BEFORE the signed PDF is in storage at its
-- object_key ("Not yet, turn on anyway"). Until the founder uploads it, the
-- artifact row names a file storage does not hold yet. The sha256 is the
-- founder's registered fingerprint of the signed bytes, not a guess.
--
-- It was parked in migrations/pending/ while unsigned. The unsigned gate below
-- is kept: if the values were ever emptied it would RAISE NOTICE and seed
-- nothing, rather than fail container start.
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
-- There are FIVE retention_category values in
-- services/data_purge_registry.py::DEPENDENCIES. Four are seeded below; the
-- fifth, financial_evidence, is deliberately left open pending doc 06 §3 and
-- the reason sits beside the omission. tests/test_phase1_retention_schedule_
-- seed.py asserts that split against the registry, so a sixth category added
-- later fails CI instead of silently reintroducing the same outage, and
-- re-adding a default for financial_evidence fails too.
-- ─────────────────────────────────────────────────────────────────────────────

DO $$
DECLARE
    -- The signed PDF as registered in legal/phase1-2026.1/SIGNED-ARTIFACTS.md
    -- (row 06). Signed 19 September 2026 by Artur Willoński (doc 06 §5,
    -- reference WILLAB-PHASE1-2026.1-RET-2026-09-19). The document records the
    -- date, not a time, so approved_at is that day and metadata says so.
    v_object_key TEXT := 'phase1-2026.1/legal/retention-schedule-v1.0.pdf';
    v_sha256 TEXT :=
        '73d078ea110c4419fc1c8b5322f90881716e66141cac5fa3a4221f0aa72a0c69';
    v_authority TEXT := 'Artur Willoński';
    v_approved_at TIMESTAMPTZ := '2026-09-19 00:00:00+00';
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
            'Retention schedule unsigned; nothing seeded. It needs the '
            'signed PDF''s key, sha256, authority and date.';
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
                'legal/phase1-2026.1/06-retention-schedule-v1.0-DRAFT.md',
                'signature_reference', 'WILLAB-PHASE1-2026.1-RET-2026-09-19',
                'approved_at_precision', 'day',
                'section_3b_confirmed', 'founder 2026-09-26, decisions log N13'
            )
        ) RETURNING id INTO v_artifact_id;
    ELSIF NOT EXISTS (
        SELECT 1 FROM public.processing_legal_artifacts
         WHERE id = v_artifact_id AND sha256 = v_sha256
           AND object_key = v_object_key
    ) THEN
        -- A different document already occupies this version. Silently reusing
        -- it would anchor the rules to bytes nobody reviewed. Under
        -- MIGRATE_ON_BOOT a RAISE here would stop production from starting,
        -- so it seeds nothing and says so instead; the purge then keeps
        -- stopping at review, which is the safe side.
        RAISE NOTICE
            'RETENTION_SCHEDULE_VERSION_CONFLICT: retention_schedule 1.0 '
            'already exists with different bytes; nothing seeded.';
        RETURN;
    END IF;

    -- ── the rules ────────────────────────────────────────────────────────
    -- One row per retention_category the orchestrator can encounter.
    -- rule_code is UNIQUE, so ON CONFLICT DO NOTHING makes re-application a
    -- no-op without touching a row that is already live.

    INSERT INTO public.data_retention_rules (
        rule_code, evidence_category, retention_until_rule,
        legal_artifact_id, active
    ) VALUES
        -- ALL FOUR APPROVED BY THE FOUNDER 2026-09-17, and matching doc 06
        -- §2 rule-for-rule (rule_code, evidence_category and
        -- retention_until_rule all verified against that table, as corrected
        -- in c0d1f70). deletion_evidence and transparency_evidence were
        -- proposed by analogy in an earlier revision of this file and are now
        -- confirmed; the "PROPOSED / unapproved" markers are removed.
        --
        -- All four hold records whose entire purpose is to prove something
        -- happened — that processing was authorised, that a deletion was
        -- performed, what was sent to a provider, that the AI notice was
        -- shown. Retaining them past an erasure request is the Art 17(3) /
        -- Art 5(2) accountability argument, and they hold identifiers,
        -- timestamps and hashes rather than content.
        --
        --   authorization_evidence → receipts, authorization snapshots,
        --                            legacy consent rows (4 deps)
        --   deletion_evidence      → audio object metadata and its deletion
        --                            events, recording boundary, service
        --                            blocks, owner identity and claim
        --                            events (7 deps)
        --   processor_evidence     → provider permits and terminal operation
        --                            events (2 deps)
        --   transparency_evidence  → AI-notice exposure records (1 dep)
        ('authorization-evidence-v1', 'authorization_evidence',
         'accountability_need_ends', v_artifact_id, true),
        ('deletion-evidence-v1', 'deletion_evidence',
         'accountability_need_ends', v_artifact_id, true),
        ('processor-evidence-v1', 'processor_evidence',
         'accountability_need_ends', v_artifact_id, true),
        ('transparency-evidence-v1', 'transparency_evidence',
         'accountability_need_ends', v_artifact_id, true)
    ON CONFLICT (rule_code) DO NOTHING;

    -- ⚠️ financial_evidence IS DELIBERATELY NOT SEEDED, AND THE PURGE STAYS
    -- BLOCKED UNTIL IT IS DECIDED.
    --
    -- An earlier revision of this file seeded 'billing-record-5y-v1' with
    -- 'financial_year_end + 5 years', justified by Polish accounting law. Doc
    -- 06 §3 retired that justification: the service is free and takes no
    -- payment, so there are no accounting records to point at. The category
    -- has not gone — token_ledger and llm_usage are per-user usage ledgers
    -- that survive an erasure request today — and §3 puts three options to
    -- counsel (detach the user reference; bound the period; change the
    -- disposition to delete). Engineering must not pick one, so nothing is
    -- seeded here.
    --
    -- THE CONSEQUENCE, STATED PLAINLY SO IT IS NOT DISCOVERED LATER:
    -- resolve_targets is all-or-nothing ("Unknown inventory means zero
    -- deletion", services/data_purge.py:720). With financial_evidence
    -- unresolved, its two dependencies land on RETENTION_RULE_UNRESOLVED and
    -- a full-account purge deletes NOTHING — for anyone. Seeding the four
    -- rules above is necessary and not yet sufficient. The purge begins
    -- working when counsel answers §3, not when this file merges.

    -- DELIBERATELY ABSENT: dataset_lineage, model_lineage and unknown.
    -- No Phase-2 processing is authorised, so neither lineage kind should ever
    -- appear as a target; if one does, that is a bug and fail-closed is the
    -- correct outcome. A catch-all row would convert "we do not know what this
    -- is" into "we have handled it", which is the failure the boundary exists
    -- to prevent. Do not add one for coverage.
END;
$$;
