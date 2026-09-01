-- 0316 · Resolve pgcrypto from Supabase's trusted extensions schema.
--
-- Stock PostgreSQL commonly installs pgcrypto in public, while Supabase keeps
-- it in extensions.  The snapshot publisher is SECURITY DEFINER and pins its
-- search path, so the production location must be explicit.  This migration
-- changes no rows and does not activate any serving or learning gate.

BEGIN;

DO $$
BEGIN
    IF to_regprocedure('extensions.digest(bytea,text)') IS NULL
       OR to_regprocedure('extensions.digest(text,text)') IS NULL THEN
        RAISE EXCEPTION
            'Ideal Text core snapshots require pgcrypto in extensions';
    END IF;
END;
$$;

ALTER FUNCTION public.publish_ideal_text_document_snapshot_v1(
    TEXT, TEXT, UUID, UUID, UUID, INTEGER, BIGINT, TEXT, JSONB, JSONB
) SET search_path = extensions, public;

COMMIT;
