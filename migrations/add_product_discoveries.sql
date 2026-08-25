-- Durable, copy-independent product discovery.
--
-- A user sees a product in the global hamburger only after a persisted bot
-- bubble introduces it through metadata.product_action.  The marker survives
-- Lounge deletion, refreshes, and device changes.  It is navigation state,
-- never an authorization boundary.

CREATE TABLE IF NOT EXISTS public.user_product_discoveries (
    user_id        UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    product        TEXT NOT NULL,
    intent         TEXT NOT NULL,
    source         TEXT NOT NULL,
    schema_version INTEGER NOT NULL CHECK (schema_version > 0),
    discovered_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, product)
);

ALTER TABLE public.user_product_discoveries ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public'
          AND tablename = 'user_product_discoveries'
          AND policyname = 'product_discoveries_owner_select'
    ) THEN
        CREATE POLICY product_discoveries_owner_select
            ON public.user_product_discoveries
            FOR SELECT
            USING (auth.uid() = user_id);
    END IF;
END
$$;

CREATE OR REPLACE FUNCTION public.capture_product_discovery_from_lounge()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    product_action JSONB;
BEGIN
    product_action := NEW.metadata->'product_action';
    IF NEW.role <> 'bot'
       OR jsonb_typeof(product_action) <> 'object'
       OR COALESCE(product_action->>'action', '') <> 'open_product'
       OR COALESCE(product_action->>'product', '')
          NOT IN ('voice_album', 'life_panel')
       OR COALESCE(product_action->>'context_transfer', '') <> 'none'
       OR COALESCE(product_action->>'intent', '') = ''
       OR COALESCE(product_action->>'source', '') = ''
       OR COALESCE(product_action->>'schema_version', '') !~ '^[1-9][0-9]*$'
    THEN
        RETURN NEW;
    END IF;

    INSERT INTO public.user_product_discoveries (
        user_id, product, intent, source, schema_version
    ) VALUES (
        NEW.user_id,
        product_action->>'product',
        product_action->>'intent',
        product_action->>'source',
        (product_action->>'schema_version')::INTEGER
    )
    ON CONFLICT (user_id, product) DO NOTHING;
    RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION public.capture_product_discovery_from_lounge()
    FROM PUBLIC;
REVOKE ALL ON FUNCTION public.capture_product_discovery_from_lounge()
    FROM anon;
REVOKE ALL ON FUNCTION public.capture_product_discovery_from_lounge()
    FROM authenticated;

DROP TRIGGER IF EXISTS lounge_product_discovery_trigger
    ON public.lounge_messages;
CREATE TRIGGER lounge_product_discovery_trigger
    AFTER INSERT OR UPDATE OF metadata ON public.lounge_messages
    FOR EACH ROW
    EXECUTE FUNCTION public.capture_product_discovery_from_lounge();

-- Normalize the already-issued Voice Album introduction into the canonical
-- action.  This is a data-shape migration, not a legacy runtime branch.
UPDATE public.lounge_messages
SET metadata = COALESCE(metadata, '{}'::jsonb) || jsonb_build_object(
    'product_action', jsonb_build_object(
        'action', 'open_product',
        'product', 'voice_album',
        'intent', 'open_album',
        'source', 'voice_album_introduction',
        'context_transfer', 'none',
        'schema_version', 1
    )
)
WHERE role = 'bot'
  AND (
      metadata->>'note' = 'voice_album_ready'
      OR metadata->>'voice_album_ready' = 'true'
  )
  AND NOT (metadata ? 'product_action');

-- A cleared Lounge must not re-hide a product already introduced under the
-- previous durable Voice Album marker.
INSERT INTO public.user_product_discoveries (
    user_id, product, intent, source, schema_version, discovered_at
)
SELECT
    user_id,
    'voice_album',
    'open_album',
    'voice_album_introduction',
    1,
    voice_album_introduced_at
FROM public.user_settings
JOIN auth.users ON auth.users.id = public.user_settings.user_id
WHERE voice_album_introduced_at IS NOT NULL
ON CONFLICT (user_id, product) DO NOTHING;

NOTIFY pgrst, 'reload schema';
