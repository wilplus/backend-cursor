-- Training copies are copies (SPEC-training-corpus-and-project-purge §4,
-- phase P3; founder locks C2, C3, Q1, Q2, 2026-09-25).
--
-- A training corpus item is its own row, and for audio its own storage
-- object under `training-corpus/`. It is never a pointer into product data:
-- no column here is a foreign key to a product table (SPEC §10 invariant 4).
-- A product delete can therefore never be blocked by a corpus row, and a
-- corpus purge can never touch product data. Lineage is kept by value: the
-- source ids as plain text, and the source content's SHA-256.
--
-- ONE DEPARTURE FROM THE SPEC'S TABLE, on purpose. §4.2 proposes a
-- `consent_snapshot_id` FK to `ml_consent_snapshots`. That table references
-- `takes`, `projects` and `recording_attempts` ON DELETE RESTRICT, so a corpus
-- row pointing at a snapshot would block exactly the product delete §4.1
-- forbids. The consent state at copy time is stored here by value instead:
-- the reader's own answer and its SHA-256.
--
-- DARK, THREE TIMES OVER. (1) Nobody can hold a training yes: no
-- `training_only` policy exists (0373). (2) `record_training_corpus_item_v1`
-- refuses unless the `training_corpus` retention rule exists AND is active,
-- and none exists (P5). (3) The copy job is behind a code constant,
-- `Config.MLC2_TRAINING_CORPUS_COPY_ENABLED = False`.
--
-- Additive and idempotent. No backfill (SPEC §1: the corpus starts empty).

BEGIN;

CREATE TABLE IF NOT EXISTS public.training_corpus_items (
    id                        UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    acquisition_principal_id  UUID        NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    training_grant_event_id   UUID        NOT NULL
        REFERENCES public.ml_consent_events(id) ON DELETE RESTRICT,
    consent_state             JSONB       NOT NULL
        CHECK (jsonb_typeof(consent_state) = 'object'
               AND consent_state ->> 'active' = 'true'),
    consent_state_sha256      TEXT        NOT NULL
        CHECK (consent_state_sha256 ~ '^[0-9a-f]{64}$'),
    -- Lineage BY VALUE. Plain text, never a foreign key.
    source_project_id         TEXT        NOT NULL CHECK (length(source_project_id) > 0),
    source_take_id            TEXT        NOT NULL CHECK (length(source_take_id) > 0),
    source_ref                TEXT        NOT NULL CHECK (length(source_ref) > 0),
    source_sha256             TEXT        NOT NULL CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
    item_kind                 TEXT        NOT NULL
        CHECK (item_kind IN ('audio_segment', 'transcript_span', 'coach_label')),
    -- One provenance per row, never mixed (L3). Source material (audio, the
    -- words) carries none; a label carries exactly the one it came from.
    label_provenance          TEXT        NULL
        CHECK (label_provenance IS NULL OR label_provenance IN
               ('machine', 'owner_routing', 'blind_peer', 'coach', 'detector')),
    content                   JSONB       NULL
        CHECK (content IS NULL OR jsonb_typeof(content) = 'object'),
    storage_provider          TEXT        NULL
        CHECK (storage_provider IS NULL OR storage_provider IN ('r2', 'supabase')),
    bucket                    TEXT        NULL,
    storage_key               TEXT        NULL
        CHECK (storage_key IS NULL OR storage_key LIKE 'training-corpus/%'),
    object_sha256             TEXT        NULL
        CHECK (object_sha256 IS NULL OR object_sha256 ~ '^[0-9a-f]{64}$'),
    retention_rule_id         UUID        NOT NULL
        REFERENCES public.data_retention_rules(id) ON DELETE RESTRICT,
    state                     TEXT        NOT NULL DEFAULT 'active'
        CHECK (state IN ('active', 'purge_pending', 'purged')),
    created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    state_changed_at          TIMESTAMPTZ NULL,
    CONSTRAINT training_corpus_item_shape_check CHECK (
        (item_kind = 'audio_segment'
         AND label_provenance IS NULL AND content IS NULL
         AND storage_provider IS NOT NULL AND bucket IS NOT NULL
         AND storage_key IS NOT NULL AND object_sha256 IS NOT NULL)
        OR
        (item_kind = 'transcript_span'
         AND label_provenance IS NULL AND content ? 'text'
         AND storage_key IS NULL AND object_sha256 IS NULL)
        OR
        (item_kind = 'coach_label'
         AND label_provenance = 'coach' AND content ? 'value'
         AND storage_key IS NULL AND object_sha256 IS NULL)
    )
);

-- One copy of one source per grant: a re-run of the job adds nothing.
CREATE UNIQUE INDEX IF NOT EXISTS uq_training_corpus_item_source
    ON public.training_corpus_items
       (training_grant_event_id, item_kind, source_ref);
CREATE INDEX IF NOT EXISTS idx_training_corpus_items_principal
    ON public.training_corpus_items (acquisition_principal_id, state);
CREATE UNIQUE INDEX IF NOT EXISTS uq_training_corpus_item_object
    ON public.training_corpus_items (storage_provider, bucket, storage_key)
    WHERE storage_key IS NOT NULL;

ALTER TABLE public.training_corpus_items ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.training_corpus_items FROM PUBLIC, anon, authenticated;
REVOKE ALL ON public.training_corpus_items FROM service_role;
GRANT SELECT, DELETE ON public.training_corpus_items TO service_role;

-- The content of a copy never changes. Only its purge state moves, forward:
-- active -> purge_pending -> purged.
CREATE OR REPLACE FUNCTION public.guard_training_corpus_item_update_v1()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path = public
AS $$
BEGIN
    IF (to_jsonb(NEW) - 'state' - 'state_changed_at')
       IS DISTINCT FROM (to_jsonb(OLD) - 'state' - 'state_changed_at') THEN
        RAISE EXCEPTION 'TRAINING_CORPUS_ITEM_IMMUTABLE';
    END IF;
    IF NOT ((OLD.state = 'active' AND NEW.state IN ('active', 'purge_pending', 'purged'))
            OR (OLD.state = 'purge_pending' AND NEW.state IN ('purge_pending', 'purged'))
            OR (OLD.state = 'purged' AND NEW.state = 'purged')) THEN
        RAISE EXCEPTION 'TRAINING_CORPUS_STATE_CANNOT_GO_BACK';
    END IF;
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION public.guard_training_corpus_item_update_v1()
    FROM PUBLIC, anon, authenticated;

DROP TRIGGER IF EXISTS training_corpus_item_guard ON public.training_corpus_items;
CREATE TRIGGER training_corpus_item_guard
    BEFORE UPDATE ON public.training_corpus_items
    FOR EACH ROW EXECUTE FUNCTION public.guard_training_corpus_item_update_v1();

-- The only door in. It re-asks the one reader (0373) inside the write, so a
-- copy can never outlive the yes it was made under by a race: a withdrawal
-- committed before this runs makes it refuse.
CREATE OR REPLACE FUNCTION public.record_training_corpus_item_v1(
    p_acquisition_principal_id UUID,
    p_training_grant_event_id UUID,
    p_source_project_id TEXT,
    p_source_take_id TEXT,
    p_source_ref TEXT,
    p_source_sha256 TEXT,
    p_item_kind TEXT,
    p_label_provenance TEXT,
    p_content JSONB,
    p_storage_provider TEXT,
    p_bucket TEXT,
    p_storage_key TEXT,
    p_object_sha256 TEXT
) RETURNS public.training_corpus_items
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    consent JSONB;
    rule public.data_retention_rules;
    existing public.training_corpus_items;
    created public.training_corpus_items;
BEGIN
    consent := public.get_mlc2_training_consent_status_v2(p_acquisition_principal_id);
    IF consent ->> 'active' IS DISTINCT FROM 'true'
       OR consent ->> 'grant_event_id' IS DISTINCT FROM p_training_grant_event_id::text THEN
        RAISE EXCEPTION 'TRAINING_CORPUS_NO_ACTIVE_YES';
    END IF;
    SELECT * INTO rule FROM public.data_retention_rules
     WHERE rule_code = 'training_corpus' AND active;
    IF rule.id IS NULL THEN
        RAISE EXCEPTION 'TRAINING_CORPUS_RETENTION_RULE_INACTIVE';
    END IF;

    SELECT * INTO existing FROM public.training_corpus_items
     WHERE training_grant_event_id = p_training_grant_event_id
       AND item_kind = p_item_kind AND source_ref = p_source_ref;
    IF FOUND THEN
        IF existing.source_sha256 IS DISTINCT FROM p_source_sha256 THEN
            RAISE EXCEPTION 'TRAINING_CORPUS_SOURCE_CHANGED';
        END IF;
        RETURN existing;
    END IF;

    INSERT INTO public.training_corpus_items (
        acquisition_principal_id, training_grant_event_id, consent_state,
        consent_state_sha256, source_project_id, source_take_id, source_ref,
        source_sha256, item_kind, label_provenance, content, storage_provider,
        bucket, storage_key, object_sha256, retention_rule_id
    ) VALUES (
        p_acquisition_principal_id, p_training_grant_event_id, consent,
        encode(extensions.digest(convert_to(consent::text, 'UTF8'), 'sha256'), 'hex'),
        p_source_project_id, p_source_take_id, p_source_ref, p_source_sha256,
        p_item_kind, p_label_provenance, p_content, p_storage_provider,
        p_bucket, p_storage_key, p_object_sha256, rule.id
    ) RETURNING * INTO created;
    RETURN created;
END;
$$;

REVOKE ALL ON FUNCTION public.record_training_corpus_item_v1(
    UUID, UUID, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, JSONB, TEXT, TEXT, TEXT, TEXT)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.record_training_corpus_item_v1(
    UUID, UUID, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, JSONB, TEXT, TEXT, TEXT, TEXT)
    TO service_role;

COMMENT ON TABLE public.training_corpus_items IS
    'Separate training copies (audio segments, transcript spans, coach '
    'labels), made only under an active training-only yes. No FK to product '
    'rows. Dark until P5 (SPEC-training-corpus-and-project-purge).';

COMMIT;
