-- 0443 · a share records the words the speaker saw (founder 2026-10-06, CM2
-- B, decisions log N53.2; 2026-10-07, Q-B6 A, N62; build plan D-FW-6)
--
-- WHY. CM2 B: "build now and switch on at once ... sharing switches on with
-- the sharing screen, under the founder's own words for it, without waiting
-- for counsel. The consent stays per Take and revocable, and is stamped with
-- the version of the words the speaker saw." Q-B6 A: "Sharing names the
-- current Privacy/Terms, and each share records the words the speaker saw;
-- 'None' takes the share back." A share row (take_shares, 0432) already
-- carries consent_version, the Phase-1 policy version (Privacy/Terms) the
-- speaker's authorization was on when they shared. The words on the sharing
-- screen are a second thing with its own life: the founder's own choices and
-- messages (signed, N54 WQ5 A / WQ6 A), which counsel may later change
-- without the Privacy/Terms changing. A consent is only as good as the words
-- it was given under, so each share records which words those were.
--
-- WHAT. One nullable column on take_shares:
--
--   take_shares.share_words_version   the version id of the sharing screen's
--                                     words the speaker saw when they ticked
--                                     the choice, as the screen sent it;
--                                     NULL on a row written before this file
--                                     and on nothing after it (the share
--                                     route refuses a share without one).
--
-- "None" still revokes with no version: a revocation stamps revoked_at and
-- reads no words. The live view community_clips_live is unchanged, so a
-- revoked share leaves every queue as before. take_shares is a 0432 table
-- that has never taken a write in production (COMMUNITIES_ENABLED is False):
-- the ALTER takes its lock on an empty, dark table, never on a busy one.
--
-- WHAT DOES NOT CHANGE. Grants: 0432 revoked the browser roles and PUBLIC on
-- take_shares and left the service key its privileges; a new column changes
-- no ACL, and the door is restated below so the file is self-describing. No
-- row is written or rewritten. Nothing reaches a listener: the queue reads
-- the view, which does not carry this column.
--
-- Idempotent: ADD COLUMN IF NOT EXISTS; applied twice it changes nothing.
--
-- Rollback (a new forward migration): ALTER TABLE public.take_shares DROP
-- COLUMN share_words_version. Nothing else reads it.

BEGIN;

ALTER TABLE public.take_shares
    ADD COLUMN IF NOT EXISTS share_words_version text NULL;

COMMENT ON COLUMN public.take_shares.share_words_version IS
    'The version of the sharing screen''s words the speaker saw when they '
    'shared (0443; CM2 B, N53.2; Q-B6 A, N62), as the screen sent it. '
    'Beside consent_version (the Privacy/Terms version). NULL only on a row '
    'written before 0443; a revocation stamps revoked_at and reads no words.';

-- ── The door, restated (0432) ────────────────────────────────────────────
-- Browser roles and PUBLIC hold nothing on take_shares; the app reads and
-- writes it with the service key. Roles are guarded: they exist on Supabase,
-- not on a bare Postgres.
REVOKE ALL ON TABLE public.take_shares FROM PUBLIC;
DO $$
DECLARE
    v_role text;
BEGIN
    FOREACH v_role IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = v_role) THEN
            EXECUTE format('REVOKE ALL ON TABLE public.take_shares FROM %I', v_role);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.take_shares TO service_role;
    END IF;
END $$;

COMMIT;
