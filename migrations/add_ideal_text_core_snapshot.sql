-- Ideal Text cold-open boundary.
--
-- The immutable snapshot is the complete, actor-scoped document read model.
-- Optional feedback/enrichment never lives here and can neither delay nor
-- invalidate it.  A mutable head contains only the pointer to the current
-- immutable snapshot.  Service code writes through the RPC so publication and
-- the head swap are one transaction.

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- A source mutation advances this value in the mutation's own transaction.
-- Readers accept only a snapshot frozen at the current value, so an old head
-- becomes unreadable at mutation commit even though materialisation follows.
CREATE TABLE IF NOT EXISTS public.ideal_text_document_generations (
    arc_id TEXT PRIMARY KEY,
    generation BIGINT NOT NULL DEFAULT 0 CHECK (generation >= 0),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE OR REPLACE FUNCTION public.advance_ideal_text_document_generation_v1()
RETURNS trigger LANGUAGE plpgsql SET search_path=public AS $$
DECLARE changed_arc TEXT;
BEGIN
  IF TG_TABLE_NAME='v2_sessions' THEN
    -- A spoken Take becomes part of the Ideal Text source set only at the
    -- processing -> ready boundary.  Advance in that same transaction so the
    -- previous document head is unreadable at commit, even if publication is
    -- delivered later by the durable sweeper.
    IF TG_OP='INSERT' THEN
      IF NEW.analysis_state IS DISTINCT FROM 'ready'
         OR COALESCE(NEW.recording_kind,'spoken')<>'spoken'
         OR NEW.paired_session_id IS NOT NULL
         OR NULLIF(trim(NEW.arc_id),'') IS NULL
      THEN RETURN NEW; END IF;
    ELSIF TG_OP='UPDATE' THEN
      IF NEW.analysis_state IS DISTINCT FROM 'ready'
         OR OLD.analysis_state IS NOT DISTINCT FROM 'ready'
         OR COALESCE(NEW.recording_kind,'spoken')<>'spoken'
         OR NEW.paired_session_id IS NOT NULL
         OR NULLIF(trim(NEW.arc_id),'') IS NULL
      THEN RETURN NEW; END IF;
    ELSE
      RETURN OLD;
    END IF;
  END IF;
  IF TG_TABLE_NAME='user_arc_ideal_notes' THEN
    IF TG_OP='INSERT' AND NEW.user_text IS NULL THEN RETURN NEW; END IF;
    IF TG_OP='UPDATE'
       AND NEW.user_text IS NOT DISTINCT FROM OLD.user_text
       AND NEW.user_text_version IS NOT DISTINCT FROM OLD.user_text_version
    THEN RETURN NEW; END IF;
    IF TG_OP='DELETE' AND OLD.user_text IS NULL THEN RETURN OLD; END IF;
  END IF;
  changed_arc:=CASE WHEN TG_OP='DELETE' THEN OLD.arc_id ELSE NEW.arc_id END;
  INSERT INTO public.ideal_text_document_generations(
    arc_id,generation,updated_at)
  VALUES(changed_arc,1,clock_timestamp())
  ON CONFLICT (arc_id) DO UPDATE
    SET generation=ideal_text_document_generations.generation+1,
        updated_at=clock_timestamp();
  IF TG_OP='DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS coach_ideal_text_advances_document_generation
  ON public.coach_arc_ideal_text;
CREATE TRIGGER coach_ideal_text_advances_document_generation
AFTER INSERT OR UPDATE OR DELETE ON public.coach_arc_ideal_text
FOR EACH ROW EXECUTE FUNCTION public.advance_ideal_text_document_generation_v1();

DROP TRIGGER IF EXISTS user_ideal_edit_advances_document_generation
  ON public.user_arc_ideal_notes;
CREATE TRIGGER user_ideal_edit_advances_document_generation
AFTER INSERT OR UPDATE OR DELETE ON public.user_arc_ideal_notes
FOR EACH ROW EXECUTE FUNCTION public.advance_ideal_text_document_generation_v1();

DROP TRIGGER IF EXISTS ideal_text_part_advances_document_generation
  ON public.ideal_text_part;
CREATE TRIGGER ideal_text_part_advances_document_generation
AFTER INSERT OR UPDATE OR DELETE ON public.ideal_text_part
FOR EACH ROW EXECUTE FUNCTION public.advance_ideal_text_document_generation_v1();

DROP TRIGGER IF EXISTS ready_take_advances_ideal_text_document_generation
  ON public.v2_sessions;
CREATE TRIGGER ready_take_advances_ideal_text_document_generation
AFTER INSERT OR UPDATE OF analysis_state ON public.v2_sessions
FOR EACH ROW EXECUTE FUNCTION public.advance_ideal_text_document_generation_v1();

CREATE TABLE IF NOT EXISTS public.ideal_text_document_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    arc_id TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    acquisition_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    project_id UUID NOT NULL REFERENCES public.projects(id) ON DELETE RESTRICT,
    source_take_session_id UUID NOT NULL
        REFERENCES public.v2_sessions(id) ON DELETE RESTRICT,
    version INTEGER NOT NULL CHECK (version >= 1),
    source_generation BIGINT NOT NULL CHECK (source_generation >= 0),
    source_fingerprint_sha256 TEXT NOT NULL
        CHECK (source_fingerprint_sha256 ~ '^[0-9a-f]{64}$'),
    payload_sha256 TEXT NOT NULL CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
    payload JSONB NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    enrichment_seed JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(enrichment_seed) = 'object'),
    supersedes_id UUID NULL
        REFERENCES public.ideal_text_document_snapshots(id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (arc_id, actor_id, source_generation, source_fingerprint_sha256)
);

CREATE INDEX IF NOT EXISTS ideal_text_document_snapshot_lookup
    ON public.ideal_text_document_snapshots (arc_id, actor_id, created_at DESC);

CREATE TABLE IF NOT EXISTS public.ideal_text_document_heads (
    arc_id TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    snapshot_id UUID NOT NULL
        REFERENCES public.ideal_text_document_snapshots(id) ON DELETE RESTRICT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (arc_id, actor_id)
);

CREATE OR REPLACE FUNCTION public.reject_ideal_text_snapshot_mutation_v1()
RETURNS trigger LANGUAGE plpgsql SET search_path=public AS $$
BEGIN
  RAISE EXCEPTION 'IDEAL_TEXT_DOCUMENT_SNAPSHOT_IMMUTABLE';
END $$;

DROP TRIGGER IF EXISTS ideal_text_document_snapshots_immutable
    ON public.ideal_text_document_snapshots;
CREATE TRIGGER ideal_text_document_snapshots_immutable
BEFORE UPDATE OR DELETE ON public.ideal_text_document_snapshots
FOR EACH ROW EXECUTE FUNCTION public.reject_ideal_text_snapshot_mutation_v1();

ALTER TABLE public.ideal_text_document_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ideal_text_document_heads ENABLE ROW LEVEL SECURITY;

CREATE OR REPLACE FUNCTION public.publish_ideal_text_document_snapshot_v1(
    p_arc_id TEXT,
    p_actor_id TEXT,
    p_acquisition_principal_id UUID,
    p_project_id UUID,
    p_source_take_session_id UUID,
    p_version INTEGER,
    p_source_generation BIGINT,
    p_source_fingerprint_sha256 TEXT,
    p_payload JSONB,
    p_enrichment_seed JSONB
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE
  existing public.ideal_text_document_snapshots;
  previous UUID;
  created public.ideal_text_document_snapshots;
  payload_hash TEXT;
  current_generation BIGINT;
BEGIN
  IF NULLIF(trim(p_arc_id),'') IS NULL OR NULLIF(trim(p_actor_id),'') IS NULL
     OR p_version < 1 OR p_source_generation < 0
     OR p_source_fingerprint_sha256 !~ '^[0-9a-f]{64}$'
     OR jsonb_typeof(p_payload) <> 'object'
     OR jsonb_typeof(p_enrichment_seed) <> 'object'
  THEN RAISE EXCEPTION 'IDEAL_TEXT_DOCUMENT_SNAPSHOT_INVALID'; END IF;

  IF NOT (p_payload ?& ARRAY[
       'arc_id','version','status','title','updated_at',
       'latest_take_session_id','take_count','can_record_take','text',
       'presentation_ref','slide_titles','pieces','parts','user_edited'
     ])
     OR p_payload - ARRAY[
       'arc_id','version','status','title','updated_at',
       'latest_take_session_id','take_count','can_record_take','text',
       'presentation_ref','slide_titles','pieces','parts','user_edited'
     ] <> '{}'::jsonb
     OR p_payload->>'arc_id' IS DISTINCT FROM p_arc_id
     OR (p_payload->>'version')::integer IS DISTINCT FROM p_version
     OR p_payload->>'latest_take_session_id'
        IS DISTINCT FROM p_source_take_session_id::text
     OR NULLIF(trim(p_payload->>'text'),'') IS NULL
     OR p_payload->>'status' NOT IN ('verified','unverified')
     OR jsonb_typeof(p_payload->'slide_titles') <> 'array'
     OR jsonb_typeof(p_payload->'pieces') <> 'array'
     OR jsonb_typeof(p_payload->'parts') NOT IN ('array','null')
     OR jsonb_typeof(p_payload->'can_record_take') <> 'boolean'
     OR jsonb_typeof(p_payload->'user_edited') <> 'boolean'
  THEN RAISE EXCEPTION 'IDEAL_TEXT_DOCUMENT_CORE_CONTRACT_INVALID'; END IF;

  IF NOT EXISTS (
    SELECT 1 FROM public.v2_sessions session
    WHERE session.id=p_source_take_session_id
      AND session.arc_id=p_arc_id
      AND session.project_id=p_project_id
      AND session.owner_principal_id=p_acquisition_principal_id
      AND COALESCE(session.analysis_state,'ready')='ready'
      AND COALESCE(session.recording_kind,'spoken')='spoken'
      AND session.paired_session_id IS NULL
  ) OR NOT EXISTS (
    SELECT 1 FROM public.owner_principals owner
    WHERE owner.id=p_acquisition_principal_id
      AND (owner.user_id::text=p_actor_id OR owner.id::text=p_actor_id)
  ) THEN RAISE EXCEPTION 'IDEAL_TEXT_DOCUMENT_SOURCE_INVALID'; END IF;

  payload_hash:=encode(digest(p_payload::text,'sha256'),'hex');
  PERFORM pg_advisory_xact_lock(
    hashtextextended('ideal-text-document:'||p_arc_id||':'||p_actor_id,0));

  INSERT INTO public.ideal_text_document_generations(arc_id)
  VALUES(p_arc_id) ON CONFLICT (arc_id) DO NOTHING;
  SELECT generation INTO current_generation
  FROM public.ideal_text_document_generations
  WHERE arc_id=p_arc_id FOR UPDATE;
  IF current_generation IS DISTINCT FROM p_source_generation THEN
    RAISE EXCEPTION 'IDEAL_TEXT_DOCUMENT_SOURCE_STALE';
  END IF;

  SELECT snapshot.* INTO existing
  FROM public.ideal_text_document_snapshots snapshot
  WHERE snapshot.arc_id=p_arc_id AND snapshot.actor_id=p_actor_id
    AND snapshot.source_generation=p_source_generation
    AND snapshot.source_fingerprint_sha256=p_source_fingerprint_sha256;
  IF existing.id IS NOT NULL THEN
    IF existing.payload_sha256 IS DISTINCT FROM payload_hash
       OR existing.payload IS DISTINCT FROM p_payload
       OR existing.enrichment_seed IS DISTINCT FROM p_enrichment_seed
    THEN RAISE EXCEPTION 'IDEAL_TEXT_DOCUMENT_SNAPSHOT_CONFLICT'; END IF;
    INSERT INTO public.ideal_text_document_heads(arc_id,actor_id,snapshot_id)
    VALUES(p_arc_id,p_actor_id,existing.id)
    ON CONFLICT (arc_id,actor_id) DO UPDATE
      SET snapshot_id=EXCLUDED.snapshot_id,updated_at=clock_timestamp();
    RETURN jsonb_build_object('id',existing.id,'payload_sha256',payload_hash,
      'replayed',true);
  END IF;

  SELECT head.snapshot_id INTO previous
  FROM public.ideal_text_document_heads head
  WHERE head.arc_id=p_arc_id AND head.actor_id=p_actor_id FOR UPDATE;
  INSERT INTO public.ideal_text_document_snapshots(
    arc_id,actor_id,acquisition_principal_id,project_id,
    source_take_session_id,version,source_generation,
    source_fingerprint_sha256,payload_sha256,
    payload,enrichment_seed,supersedes_id)
  VALUES(p_arc_id,p_actor_id,p_acquisition_principal_id,p_project_id,
    p_source_take_session_id,p_version,p_source_generation,
    p_source_fingerprint_sha256,payload_hash,
    p_payload,p_enrichment_seed,previous)
  RETURNING * INTO created;
  INSERT INTO public.ideal_text_document_heads(arc_id,actor_id,snapshot_id)
  VALUES(p_arc_id,p_actor_id,created.id)
  ON CONFLICT (arc_id,actor_id) DO UPDATE
    SET snapshot_id=EXCLUDED.snapshot_id,updated_at=clock_timestamp();
  RETURN jsonb_build_object('id',created.id,'payload_sha256',payload_hash,
    'replayed',false);
END $$;

CREATE OR REPLACE FUNCTION public.read_ideal_text_document_generation_v1(
    p_arc_id TEXT
) RETURNS BIGINT
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE result BIGINT;
BEGIN
  IF NULLIF(trim(p_arc_id),'') IS NULL THEN
    RAISE EXCEPTION 'IDEAL_TEXT_DOCUMENT_ARC_REQUIRED';
  END IF;
  INSERT INTO public.ideal_text_document_generations(arc_id)
  VALUES(p_arc_id) ON CONFLICT (arc_id) DO NOTHING;
  SELECT generation INTO result
  FROM public.ideal_text_document_generations WHERE arc_id=p_arc_id;
  RETURN result;
END $$;

CREATE OR REPLACE FUNCTION public.list_pending_ideal_text_document_publications_v1(
    p_limit INTEGER DEFAULT 100
) RETURNS TABLE(arc_id TEXT,generation BIGINT)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public AS $$
  SELECT source.arc_id,source.generation
  FROM public.ideal_text_document_generations source
  WHERE EXISTS (
    SELECT 1 FROM public.v2_sessions session
    WHERE session.arc_id=source.arc_id
      AND COALESCE(session.analysis_state,'ready')='ready'
      AND COALESCE(session.recording_kind,'spoken')='spoken'
      AND session.paired_session_id IS NULL
  ) AND NOT EXISTS (
    SELECT 1
    FROM public.ideal_text_document_heads head
    JOIN public.ideal_text_document_snapshots snapshot
      ON snapshot.id=head.snapshot_id
    WHERE head.arc_id=source.arc_id
      AND snapshot.arc_id=source.arc_id
      AND snapshot.source_generation=source.generation
  )
  ORDER BY source.updated_at,source.arc_id
  LIMIT LEAST(GREATEST(COALESCE(p_limit,100),1),500)
$$;

CREATE OR REPLACE FUNCTION public.read_ideal_text_document_core_v1(
    p_arc_id TEXT,
    p_actor_id TEXT
) RETURNS JSONB
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public AS $$
  SELECT to_jsonb(snapshot)
  FROM public.ideal_text_document_heads head
  JOIN public.ideal_text_document_snapshots snapshot
    ON snapshot.id=head.snapshot_id
  WHERE head.arc_id=p_arc_id
    AND head.actor_id=p_actor_id
    AND snapshot.arc_id=p_arc_id
    AND snapshot.actor_id=p_actor_id
    AND EXISTS (
      SELECT 1 FROM public.ideal_text_document_generations generation
      WHERE generation.arc_id=p_arc_id
        AND generation.generation=snapshot.source_generation
    )
    AND EXISTS (
      SELECT 1
      FROM public.v2_sessions session
      JOIN public.owner_principals owner
        ON owner.id=session.owner_principal_id
      WHERE session.arc_id=p_arc_id
        AND session.project_id=snapshot.project_id
        AND session.owner_principal_id=snapshot.acquisition_principal_id
        AND (owner.user_id::text=p_actor_id OR owner.id::text=p_actor_id)
    )
  LIMIT 1
$$;

ALTER TABLE public.ideal_text_document_generations ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.ideal_text_document_generations FROM PUBLIC, anon, authenticated;
REVOKE ALL ON public.ideal_text_document_snapshots FROM PUBLIC, anon, authenticated;
REVOKE ALL ON public.ideal_text_document_heads FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.advance_ideal_text_document_generation_v1()
  FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.reject_ideal_text_snapshot_mutation_v1()
  FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.publish_ideal_text_document_snapshot_v1(
  TEXT,TEXT,UUID,UUID,UUID,INTEGER,BIGINT,TEXT,JSONB,JSONB)
  FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.read_ideal_text_document_generation_v1(TEXT)
  FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.list_pending_ideal_text_document_publications_v1(
  INTEGER) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.read_ideal_text_document_core_v1(TEXT,TEXT)
  FROM PUBLIC, anon, authenticated;
GRANT SELECT ON public.ideal_text_document_generations TO service_role;
GRANT SELECT ON public.ideal_text_document_snapshots TO service_role;
GRANT SELECT ON public.ideal_text_document_heads TO service_role;
GRANT EXECUTE ON FUNCTION public.publish_ideal_text_document_snapshot_v1(
  TEXT,TEXT,UUID,UUID,UUID,INTEGER,BIGINT,TEXT,JSONB,JSONB)
  TO service_role;
GRANT EXECUTE ON FUNCTION public.read_ideal_text_document_generation_v1(TEXT)
  TO service_role;
GRANT EXECUTE ON FUNCTION public.list_pending_ideal_text_document_publications_v1(
  INTEGER) TO service_role;
GRANT EXECUTE ON FUNCTION public.read_ideal_text_document_core_v1(TEXT,TEXT)
  TO service_role;

COMMIT;
