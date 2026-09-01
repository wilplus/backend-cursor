\set ON_ERROR_STOP on
SELECT public.publish_ideal_text_document_snapshot_v1(
  'arc-core',
  '10000000-0000-4000-8000-000000000001',
  '20000000-0000-4000-8000-000000000001',
  '30000000-0000-4000-8000-000000000001',
  '40000000-0000-4000-8000-000000000001',
  1,
  0,
  repeat('a',64),
  jsonb_build_object(
    'arc_id','arc-core','version',1,'status','unverified','title','Test',
    'updated_at',NULL,'latest_take_session_id','40000000-0000-4000-8000-000000000001',
    'take_count',1,'can_record_take',true,'text','Exact text.',
    'presentation_ref',NULL,'slide_titles','[]'::jsonb,
    'pieces','[]'::jsonb,'parts','null'::jsonb,'user_edited',false
  ),
  '{}'::jsonb
);

DO $$
DECLARE owner_read JSONB; foreign_read JSONB;
BEGIN
  owner_read:=public.read_ideal_text_document_core_v1(
    'arc-core','10000000-0000-4000-8000-000000000001');
  foreign_read:=public.read_ideal_text_document_core_v1(
    'arc-core','10000000-0000-4000-8000-000000000002');
  IF owner_read->'payload'->>'text' <> 'Exact text.' THEN
    RAISE EXCEPTION 'owner core read failed';
  END IF;
  IF foreign_read IS NOT NULL THEN
    RAISE EXCEPTION 'cross-owner core read leaked';
  END IF;
END $$;

-- In-progress session creation has NULL analysis_state and often no arc yet;
-- it must never invalidate a current document or make Take creation fail.
INSERT INTO public.v2_sessions(
  id,user_id,owner_principal_id
) VALUES(
  '40000000-0000-4000-8000-000000000009',
  '10000000-0000-4000-8000-000000000001',
  '20000000-0000-4000-8000-000000000001'
);
DELETE FROM public.v2_sessions
WHERE id='40000000-0000-4000-8000-000000000009';

DO $$ BEGIN
  UPDATE public.ideal_text_document_snapshots SET version=2;
  RAISE EXCEPTION 'immutable snapshot updated';
EXCEPTION WHEN raise_exception THEN
  IF SQLERRM <> 'IDEAL_TEXT_DOCUMENT_SNAPSHOT_IMMUTABLE' THEN RAISE; END IF;
END $$;

-- A Take becoming ready invalidates the prior head in the same transaction.
-- The nested exception rolls the probe back so later cases retain generation 0.
DO $$
DECLARE before_generation BIGINT;
BEGIN
  SELECT generation INTO before_generation
  FROM public.ideal_text_document_generations WHERE arc_id='arc-core';
  BEGIN
    UPDATE public.v2_sessions SET analysis_state='processing'
    WHERE id='40000000-0000-4000-8000-000000000001';
    IF (SELECT generation FROM public.ideal_text_document_generations
        WHERE arc_id='arc-core') IS DISTINCT FROM before_generation
    THEN RAISE EXCEPTION 'non-ready transition advanced generation'; END IF;

    UPDATE public.v2_sessions SET analysis_state='ready'
    WHERE id='40000000-0000-4000-8000-000000000001';
    IF (SELECT generation FROM public.ideal_text_document_generations
        WHERE arc_id='arc-core') IS DISTINCT FROM before_generation+1
    THEN RAISE EXCEPTION 'ready transition did not advance generation'; END IF;
    IF public.read_ideal_text_document_core_v1(
      'arc-core','10000000-0000-4000-8000-000000000001') IS NOT NULL
    THEN RAISE EXCEPTION 'ready transition left stale head readable'; END IF;
    RAISE EXCEPTION 'ROLLBACK_READY_TRANSITION_PROBE';
  EXCEPTION WHEN raise_exception THEN
    IF SQLERRM <> 'ROLLBACK_READY_TRANSITION_PROBE' THEN RAISE; END IF;
  END;
  IF (SELECT generation FROM public.ideal_text_document_generations
      WHERE arc_id='arc-core') IS DISTINCT FROM before_generation
  THEN RAISE EXCEPTION 'ready-transition probe did not roll back'; END IF;
END $$;

DO $$ BEGIN
  SET LOCAL ROLE service_role;
  INSERT INTO public.ideal_text_document_snapshots(
    arc_id,actor_id,acquisition_principal_id,project_id,
    source_take_session_id,version,source_generation,
    source_fingerprint_sha256,payload_sha256,
    payload,enrichment_seed
  ) VALUES(
    'forbidden','10000000-0000-4000-8000-000000000001',
    '20000000-0000-4000-8000-000000000001',
    '30000000-0000-4000-8000-000000000001',
    '40000000-0000-4000-8000-000000000001',1,0,
    repeat('b',64),repeat('c',64),
    '{}'::jsonb,'{}'::jsonb
  );
  RAISE EXCEPTION 'service role direct write succeeded';
EXCEPTION WHEN insufficient_privilege THEN NULL;
END $$;

SELECT public.publish_ideal_text_document_snapshot_v1(
  'arc-core',
  '10000000-0000-4000-8000-000000000001',
  '20000000-0000-4000-8000-000000000001',
  '30000000-0000-4000-8000-000000000001',
  '40000000-0000-4000-8000-000000000001',
  1,0,repeat('a',64),
  jsonb_build_object(
    'arc_id','arc-core','version',1,'status','unverified','title','Test',
    'updated_at',NULL,'latest_take_session_id','40000000-0000-4000-8000-000000000001',
    'take_count',1,'can_record_take',true,'text','Exact text.',
    'presentation_ref',NULL,'slide_titles','[]'::jsonb,
    'pieces','[]'::jsonb,'parts','null'::jsonb,'user_edited',false
  ),'{}'::jsonb
);

DO $$ BEGIN
  IF (SELECT count(*) FROM public.ideal_text_document_snapshots) <> 1 THEN
    RAISE EXCEPTION 'idempotent replay created a duplicate';
  END IF;
END $$;

-- A canonical source mutation invalidates the previous head at commit.
INSERT INTO public.coach_arc_ideal_text(arc_id,text)
VALUES('arc-core','Changed source.');

DO $$ BEGIN
  IF public.read_ideal_text_document_core_v1(
    'arc-core','10000000-0000-4000-8000-000000000001') IS NOT NULL
  THEN RAISE EXCEPTION 'stale head remained readable after source mutation';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM public.list_pending_ideal_text_document_publications_v1(10)
    WHERE arc_id='arc-core' AND generation=1
  ) THEN RAISE EXCEPTION 'durable publication retry was not discoverable';
  END IF;
END $$;

DO $$ BEGIN
  PERFORM public.publish_ideal_text_document_snapshot_v1(
    'arc-core','10000000-0000-4000-8000-000000000001',
    '20000000-0000-4000-8000-000000000001',
    '30000000-0000-4000-8000-000000000001',
    '40000000-0000-4000-8000-000000000001',1,0,repeat('d',64),
    jsonb_build_object(
      'arc_id','arc-core','version',1,'status','unverified','title','Test',
      'updated_at',NULL,
      'latest_take_session_id','40000000-0000-4000-8000-000000000001',
      'take_count',1,'can_record_take',true,'text','Stale build.',
      'presentation_ref',NULL,'slide_titles','[]'::jsonb,
      'pieces','[]'::jsonb,'parts','null'::jsonb,'user_edited',false
    ),'{}'::jsonb);
  RAISE EXCEPTION 'stale source generation published';
EXCEPTION WHEN raise_exception THEN
  IF SQLERRM <> 'IDEAL_TEXT_DOCUMENT_SOURCE_STALE' THEN RAISE; END IF;
END $$;

SELECT public.publish_ideal_text_document_snapshot_v1(
  'arc-core','10000000-0000-4000-8000-000000000001',
  '20000000-0000-4000-8000-000000000001',
  '30000000-0000-4000-8000-000000000001',
  '40000000-0000-4000-8000-000000000001',1,1,repeat('e',64),
  jsonb_build_object(
    'arc_id','arc-core','version',1,'status','unverified','title','Test',
    'updated_at',NULL,
    'latest_take_session_id','40000000-0000-4000-8000-000000000001',
    'take_count',1,'can_record_take',true,'text','Changed source.',
    'presentation_ref',NULL,'slide_titles','[]'::jsonb,
    'pieces','[]'::jsonb,'parts','null'::jsonb,'user_edited',false
  ),'{}'::jsonb);

DO $$ BEGIN
  IF (public.read_ideal_text_document_core_v1(
    'arc-core','10000000-0000-4000-8000-000000000001')
      ->'payload'->>'text') <> 'Changed source.'
  THEN RAISE EXCEPTION 'current generation was not published';
  END IF;
  IF EXISTS (
    SELECT 1 FROM public.list_pending_ideal_text_document_publications_v1(10)
    WHERE arc_id='arc-core'
  ) THEN RAISE EXCEPTION 'published generation remained pending';
  END IF;
END $$;

