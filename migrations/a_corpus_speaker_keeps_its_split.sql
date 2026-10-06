-- 0433 · a corpus speaker keeps its split (founder 2026-10-06, panel answer
-- CO1 A, decisions log N56.4: "switch the training corpus on and build it
-- properly")
--
-- WHY. N56.4: "Labels are split by speaker: 80% to learn from, 20% held out
-- for testing, decided by a fixed hash and never re-shuffled." The hash is
-- code (services/corpus_split.py, SPLIT_SALT and SPLIT_VERSION); this table
-- is what makes "never re-shuffled" true. A speaker's first assignment is
-- stored, and the stored row wins over any later computation, so editing
-- the salt one day moves no speaker who already has a split.
--
-- WHAT. One row per corpus speaker: the SHA-256 digest of the speaker key
-- (the import's normalised "Whose voice this is", or import:<session_id>
-- for an import with no speaker name), never the name itself; its split
-- ('train' or 'test'); the version of the rule that assigned it; when.
-- No user id, no principal, no recording: a grouping key for licensed
-- corpus audio, not data about an account (purge registry: non-subject).
--
-- INSERT-ONCE. The app writes ON CONFLICT DO NOTHING and reads back; a
-- trigger refuses every UPDATE and DELETE, so no code path can re-shuffle a
-- speaker. Retiring a split rule is a new forward migration, not an edit.
--
-- NOTHING TRAINS ON IT. Dataset releases, training, evaluation and
-- promotion stay closed in config.py; this table only says which side of
-- the line each speaker is on. Additive; idempotent; no env var (the
-- import's switch is the code constant Config.TRAINING_IMPORT_ENABLED,
-- False until the founder flips it).
--
-- Rollback (a new forward migration): drop the trigger, its function and
-- the table.

BEGIN;

CREATE TABLE IF NOT EXISTS public.corpus_speaker_splits (
    speaker_key_sha256 text        PRIMARY KEY,
    split              text        NOT NULL,
    split_version      text        NOT NULL,
    assigned_at        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT corpus_speaker_splits_digest_shape
        CHECK (speaker_key_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT corpus_speaker_splits_split_check
        CHECK (split IN ('train', 'test')),
    CONSTRAINT corpus_speaker_splits_version_present
        CHECK (char_length(btrim(split_version)) > 0)
);
ALTER TABLE public.corpus_speaker_splits ENABLE ROW LEVEL SECURITY;
COMMENT ON TABLE public.corpus_speaker_splits IS
    'The learn/test split of each training-corpus speaker (0433, N56.4): '
    '80/20 by a fixed salted SHA-256 of the speaker key, stored on first '
    'assignment and never re-shuffled (UPDATE and DELETE are refused). Holds '
    'a digest of the key, never a name, and no user id. Nothing trains on it '
    'while the training doors stay closed.';

CREATE OR REPLACE FUNCTION public.corpus_speaker_splits_never_change()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
BEGIN
    RAISE EXCEPTION 'CORPUS_SPLIT_IMMUTABLE: a corpus speaker keeps its split'
        USING ERRCODE = 'check_violation';
END;
$$;
REVOKE ALL ON FUNCTION public.corpus_speaker_splits_never_change() FROM PUBLIC;
DO $$
DECLARE
    v_role text;
BEGIN
    FOREACH v_role IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = v_role) THEN
            EXECUTE format(
                'REVOKE ALL ON FUNCTION public.corpus_speaker_splits_never_change() FROM %I',
                v_role);
        END IF;
    END LOOP;
END $$;

DROP TRIGGER IF EXISTS corpus_speaker_splits_never_change
    ON public.corpus_speaker_splits;
CREATE TRIGGER corpus_speaker_splits_never_change
    BEFORE UPDATE OR DELETE ON public.corpus_speaker_splits
    FOR EACH ROW EXECUTE FUNCTION public.corpus_speaker_splits_never_change();

-- Browser roles get nothing, whatever default privileges the schema
-- carries: RLS with no policy already returns no row, and this makes the
-- boundary explicit. The app reads and writes with the service key.
DO $$
DECLARE
    v_role text;
BEGIN
    REVOKE ALL ON TABLE public.corpus_speaker_splits FROM PUBLIC;
    FOREACH v_role IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = v_role) THEN
            EXECUTE format('REVOKE ALL ON TABLE public.corpus_speaker_splits FROM %I',
                           v_role);
        END IF;
    END LOOP;
END $$;

COMMIT;
