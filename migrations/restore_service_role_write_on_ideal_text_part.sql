-- 0336 — restore the backend's write grant on the paragraph-identity tables.
--
-- PRODUCTION WAS BROKEN FROM 2026-09-13. Deploy log, 2026-09-17:
--
--   WARNING services.db: replace_ideal_text_parts failed
--   arc=b39d2833-...: {'code': '42501',
--   'message': 'permission denied for table ideal_text_part'}
--
-- and, in the app, "Couldn't lock this in. Try again." /
-- "Couldn't keep this paragraph evolving." on every attempt.
--
-- WHAT DID IT. add_confident_moment_coaching_bundle_v1.sql (#490, merged
-- 2026-09-13) closed the Confident Moment provenance chain by forcing writes
-- through authorized SQL functions. Among its lockdowns:
--
--   REVOKE INSERT,UPDATE,DELETE,TRUNCATE ON TABLE public.user_arc_ideal_notes,
--    public.ideal_text_part, public.ideal_text_part_revision
--    FROM PUBLIC,anon,authenticated,service_role;
--
-- Those three tables are NOT Confident Moment tables. They are F1: paragraph
-- identity, its revision chain, and the speaker's own notes. Their live
-- writers — `set_ideal_text_part_lock` and `replace_ideal_text_parts` in
-- services/db.py — write the tables DIRECTLY through the Supabase client, and
-- have always done so. No function was added for them, because none was
-- intended: they were collateral in a list.
--
-- It went unseen for four days because the feature that migration serves ships
-- gates-default-off, so nothing exercised the new lanes — while the lock, which
-- is on the F1 critical path and runs on every paragraph a speaker settles, ran
-- straight into the revoke. The gates being off is exactly why the damage
-- landed somewhere else entirely.
--
-- WHY RE-GRANTING IS NOT UNDOING THE SECURITY WORK. The revoke names four
-- grantees. Three of them are the security boundary: PUBLIC, `anon` and
-- `authenticated` are reachable from a browser with a user's JWT, and they stay
-- revoked here. `service_role` is the server's own key — it never leaves the
-- backend, it already bypasses RLS by design, and it is the identity every
-- other F1 write on these same rows already runs as. Restoring it returns the
-- three tables to exactly the posture they had on 2026-09-12, and leaves every
-- browser-reachable grantee locked down as #490 left them.
--
-- SCOPE IS DELIBERATELY THE THREE TABLES THE REVOKE NAMED. Nothing else that
-- migration revoked is touched: every Confident Moment table, every function
-- grant and every FORCE ROW LEVEL SECURITY stays exactly as it is. RLS is not
-- the blocker and is not altered — 42501 is a privilege error, not a policy
-- refusal, and `service_role` carries BYPASSRLS regardless.
--
-- Idempotent: GRANT is a no-op when the privilege is already held, and each
-- statement is guarded on the table existing so a fresh database that has not
-- yet created them applies this without error.

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'public' AND table_name = 'ideal_text_part'
  ) THEN
    GRANT INSERT, UPDATE, DELETE ON TABLE public.ideal_text_part TO service_role;
  END IF;

  IF EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'public' AND table_name = 'ideal_text_part_revision'
  ) THEN
    GRANT INSERT, UPDATE, DELETE
      ON TABLE public.ideal_text_part_revision TO service_role;
  END IF;

  IF EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'public' AND table_name = 'user_arc_ideal_notes'
  ) THEN
    GRANT INSERT, UPDATE, DELETE
      ON TABLE public.user_arc_ideal_notes TO service_role;
  END IF;
END $$;

-- The sequence the revision chain's identity column draws from. Without it an
-- INSERT still fails, with a different and more confusing message.
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.sequences
    WHERE sequence_schema = 'public'
      AND sequence_name = 'ideal_text_part_revision_id_seq'
  ) THEN
    GRANT USAGE, SELECT
      ON SEQUENCE public.ideal_text_part_revision_id_seq TO service_role;
  END IF;
END $$;

-- TRUNCATE is deliberately NOT restored. `replace_ideal_text_parts` deletes by
-- (arc_id, user_id) and never truncates; nothing in the F1 path needs it, and a
-- privilege nobody uses is a privilege that can only be misused.
