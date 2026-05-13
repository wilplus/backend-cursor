-- Fix Bug #2: RLS / GRANT denial on user_settings.
--
-- Symptom: get_email_pref_publish_results in services/db.py was
-- logging "permission denied for table user_settings" and falling
-- back to True (the safe default — never silently drop email).
-- That fallback meant the unsubscribe link looked like it worked
-- (the endpoint returned 200) but every subsequent publish still
-- sent because the pref-read kept defaulting open.
--
-- Root cause: user_settings was created with RLS enabled but
-- without an explicit policy granting the service_role bypass.
-- The Python client DOES use SUPABASE_SERVICE_ROLE_KEY when
-- constructing the Supabase client (verified in
-- services/db.py::DatabaseService.__init__) — but service_role
-- only bypasses RLS when (a) it has Postgres-level privileges on
-- the table AND (b) a policy or DISABLE keeps it un-blocked.
-- Both fixes below, idempotent.
--
-- Why both GRANT + POLICY
-- ------------------------
-- GRANT covers the table-level privilege — without SELECT here,
-- "permission denied for table" fires before RLS even runs.
-- POLICY covers the row-level filter — service_role with SELECT
-- privilege but no matching RLS policy still gets zero rows back.
-- Defence-in-depth: install both so neither half can silently
-- regress on a future migration that flips RLS settings.
--
-- Other Phase 12-14 columns on user_settings are already being
-- read/written successfully (private_admin_notes,
-- inferred_learner_profile, etc.) — so this is specifically a
-- recent introduction OR a privilege that was granted before the
-- email-prefs column landed and didn't auto-extend. The catch-all
-- below makes the answer "all columns" so this can't bite the
-- next new field either.
--
-- Idempotent.

GRANT SELECT, INSERT, UPDATE, DELETE ON public.user_settings TO service_role;

-- Belt-and-braces RLS policy: service_role gets unfiltered access.
-- Created only if a policy with the same name doesn't already
-- exist so re-running this migration is a no-op.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_policies
        WHERE schemaname = 'public'
          AND tablename = 'user_settings'
          AND policyname = 'service_role_full_access'
    ) THEN
        CREATE POLICY service_role_full_access
            ON public.user_settings
            AS PERMISSIVE
            FOR ALL
            TO service_role
            USING (true)
            WITH CHECK (true);
    END IF;
END $$;

NOTIFY pgrst, 'reload schema';
