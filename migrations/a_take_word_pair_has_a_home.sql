-- a_take_word_pair_has_a_home (0479; founder 2026-10-19, decisions log N79)
--
-- WHY. A coach's Take word becomes a (draft, final) training pair when the
-- coach changes the model's draft (C5-a, 0411). 0411 added
-- feedback_pairs.take_word_id and widened feedback_pairs_surface_check to
-- coach_take_word, but 0402's feedback_pairs_one_home
-- (request_id IS NOT NULL OR exercise_id IS NOT NULL) was never widened, so
-- Postgres has refused every Take-word pair since 0411 (23514), and
-- record_pair logged and swallowed it. 0459's note "feedback_pairs already
-- holds all five (0411)" checked the surface CHECK only; that applied file
-- stays as it is (its checksum is recorded) and this header corrects it.
--
-- WHAT.
--   1. A Take word is a pair's home, for the coach_take_word surface only.
--   2. THE LATEST VERSION TEACHES (founder, 2026-10-19): when a coach edits
--      a Take word, the newer pair replaces the older one for training.
--      Nothing is deleted or rewritten: the older pair gets superseded_at,
--      and the app's readers of pairs (services/db.py: release, training,
--      the golden pool, the counts) read only pairs with superseded_at NULL.
--      A version that is no pair retires the older one too. For the other
--      four surfaces superseded_at stays NULL, so nothing changes for them.
--      KNOWN GAP, closed before coach_take_word is reopened: the SQL mark
--      functions (mark_feedback_pairs_released_v1, _trained_v1) and the
--      refresh's releasable_waiting count do not yet look at superseded_at.
--      Harmless while the surface leaves by no door (#1130).
--   3. One current pair per Take word and final kind ('final', 'transcript'),
--      kept by a partial unique index, and written by one SECURITY DEFINER
--      function that supersedes and inserts in the same transaction. The
--      same words saved again leave the current pair as it is.
--   4. What coach_take_words still holds is recovered: per word, (current
--      draft, latest text) and (current draft, transcript), only where the
--      draft came before that final, the two differ, and the coach is not the
--      Take's owner (L3). Consent is left at its defaults ('unknown', not
--      releasable): the weekly refresh_feedback_pair_consent_v1 reads the
--      speaker's yes, so this fails closed. Earlier versions of a word were
--      overwritten in place and cannot be recovered.
--
-- The coach_take_word surface leaves by no door until the founder reopens
-- it (config.py, N79), so nothing recovered or written here is released,
-- trained on or served until then.
--
-- Idempotent: DROP CONSTRAINT IF EXISTS + ADD (the 0411 idiom for a CHECK
-- swap), ADD COLUMN / CREATE INDEX IF NOT EXISTS, CREATE OR REPLACE, and the
-- recovery is ON CONFLICT DO NOTHING on the current-pair index. It drops no
-- table, column or row and needs no env var. Every existing row passes the
-- wider CHECK. Locks: feedback_pairs takes ACCESS EXCLUSIVE from the swap
-- until COMMIT: its validating scan, the index build and the recovery
-- INSERT, whose join reads v2_sessions in full (the ids are compared as
-- text, so no index is used; coach_take_words is small). Pair writes,
-- deletion requests and consent stops that touch feedback_pairs wait for
-- it; the speaker's record, process, Ideal Text loop never touches it.
-- Merge away from the Monday 06:00 UTC weekly job, whose consent refresh
-- updates feedback_pairs. Deploy window: until the new web code serves,
-- the old code inserts Take-word pairs plainly; one that meets a recovered
-- current pair is refused by the index and logged, and the next save under
-- the new code writes it.
--
-- Before merging: the outside review (GPT or Grok); on production,
--   SELECT count(*) FROM feedback_pairs WHERE take_word_id IS NOT NULL;
-- is expected to be 0 (the CHECK refused them all).
-- Released rehearsal lane only: the recovery reads coach_take_words.draft_prompt (0459).

BEGIN;

-- 1. A Take word is a home, for its own surface only. The explicit
--    IS NOT NULL matters: a CHECK that evaluates to NULL passes, and a row
--    with no home at all must not.
ALTER TABLE public.feedback_pairs DROP CONSTRAINT IF EXISTS feedback_pairs_one_home;
ALTER TABLE public.feedback_pairs ADD CONSTRAINT feedback_pairs_one_home CHECK (
    request_id IS NOT NULL
    OR exercise_id IS NOT NULL
    OR (surface = 'coach_take_word'
        AND take_word_id IS NOT NULL
        AND btrim(take_word_id) <> ''));

-- 2. A pair a newer version of the same Take word replaced.
ALTER TABLE public.feedback_pairs
    ADD COLUMN IF NOT EXISTS superseded_at timestamptz NULL;
COMMENT ON COLUMN public.feedback_pairs.superseded_at IS
    'Set when a newer pair for the same Take word and final kind replaced this '
    'one (0479; founder 2026-10-19, the latest version teaches). Readers of '
    'pairs read only rows where it is NULL. Never set on the other surfaces.';

-- 3. One current pair per Take word and final kind.
CREATE UNIQUE INDEX IF NOT EXISTS feedback_pairs_one_current_per_take_word
    ON public.feedback_pairs (take_word_id, final_kind)
    WHERE take_word_id IS NOT NULL AND superseded_at IS NULL;

-- The writer, called for every saved version of a Take word: it supersedes
-- the current pair and inserts the new one in one transaction, so there are
-- never two current pairs. The same draft and final as the current pair
-- return NULL (nothing new). A version that is no pair (the draft kept as
-- it was, or no final) returns NULL after retiring the older pair, so an
-- outdated version never keeps teaching. The columns are the ones
-- services.feedback_pairs.record_pair writes; the consent columns default
-- as the table does when absent.
CREATE OR REPLACE FUNCTION public.record_take_word_pair_v1(p_row jsonb)
RETURNS public.feedback_pairs
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_word    text := btrim(COALESCE(p_row->>'take_word_id', ''));
    v_kind    text := COALESCE(p_row->>'final_kind', 'final');
    v_draft   text := btrim(regexp_replace(COALESCE(p_row->>'draft_text', ''), '\s+', ' ', 'g'));
    v_final   text := btrim(regexp_replace(COALESCE(p_row->>'final_text', ''), '\s+', ' ', 'g'));
    v_current public.feedback_pairs;
    stored    public.feedback_pairs;
BEGIN
    IF COALESCE(p_row->>'surface', '') <> 'coach_take_word' OR v_word = ''
       OR v_kind NOT IN ('final', 'transcript') THEN
        RAISE EXCEPTION 'TAKE_WORD_PAIR_INPUT_INVALID';
    END IF;
    -- One writer per word and kind at a time.
    PERFORM pg_advisory_xact_lock(hashtext('take-word-pair:' || v_word || ':' || v_kind));
    SELECT * INTO v_current FROM public.feedback_pairs
     WHERE take_word_id = v_word AND final_kind = v_kind AND superseded_at IS NULL
     FOR UPDATE;
    -- The same words again: nothing new (NULL), the current pair stands.
    IF FOUND
       AND btrim(regexp_replace(v_current.draft_text, '\s+', ' ', 'g')) = v_draft
       AND btrim(regexp_replace(v_current.final_text, '\s+', ' ', 'g')) = v_final THEN
        RETURN NULL;
    END IF;
    -- A newer version: the older pair stops teaching.
    IF FOUND THEN
        UPDATE public.feedback_pairs SET superseded_at = now() WHERE id = v_current.id;
    END IF;
    -- A version that is no pair (no draft, no final, or the draft kept as it
    -- was, the C5 rule) only retires the older one.
    IF v_draft = '' OR v_final = '' OR v_draft = v_final THEN
        RETURN NULL;
    END IF;
    INSERT INTO public.feedback_pairs (
        surface, final_kind, draft_text, final_text, draft_model_version,
        pattern_key, coach_id, owner_user_id, take_session_id, snippet_id,
        take_word_id, owner_principal_id, consent_state,
        consent_grant_event_id, consent_policy_version, releasable,
        passage_text, prompt_context)
    SELECT 'coach_take_word', v_kind, btrim(r.draft_text), btrim(r.final_text),
           r.draft_model_version, r.pattern_key, r.coach_id, r.owner_user_id,
           r.take_session_id, r.snippet_id, v_word, r.owner_principal_id,
           COALESCE(r.consent_state, 'unknown'), r.consent_grant_event_id,
           r.consent_policy_version, COALESCE(r.releasable, false),
           r.passage_text, r.prompt_context
      FROM jsonb_to_record(p_row) AS r(
           draft_text text, final_text text, draft_model_version text,
           pattern_key text, coach_id text, owner_user_id text,
           take_session_id text, snippet_id text, owner_principal_id uuid,
           consent_state text, consent_grant_event_id uuid,
           consent_policy_version text, releasable boolean,
           passage_text text, prompt_context jsonb)
    RETURNING * INTO stored;
    RETURN stored;
END;
$$;

REVOKE ALL ON FUNCTION public.record_take_word_pair_v1(jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.record_take_word_pair_v1(jsonb) FROM anon, authenticated;
GRANT EXECUTE ON FUNCTION public.record_take_word_pair_v1(jsonb) TO service_role;

-- 4. Recover what coach_take_words still holds (see the header).
INSERT INTO public.feedback_pairs (
    surface, final_kind, draft_text, final_text, draft_model_version,
    coach_id, owner_user_id, owner_principal_id, take_session_id, take_word_id,
    passage_text, prompt_context, created_at)
SELECT 'coach_take_word', f.final_kind,
       btrim(f.draft), btrim(f.final),
       NULLIF(btrim(COALESCE(w.draft_model_version, '')), ''),
       btrim(w.coach_id), s.user_id::text, p.id, w.take_session_id, w.id::text,
       CASE WHEN k.ok THEN btrim(regexp_replace(w.draft_prompt->>'passage_text', '\s+', ' ', 'g')) END,
       CASE WHEN k.ok THEN w.draft_prompt->'prompt_context' END,
       f.at
  FROM public.coach_take_words w
  JOIN public.v2_sessions s ON s.id::text = w.take_session_id
  LEFT JOIN public.owner_principals p ON p.user_id::text = s.user_id::text
  CROSS JOIN LATERAL (VALUES
        ('final',      w.draft_text, w.text,       w.updated_at),
        ('transcript', w.draft_text, w.transcript, w.transcribed_at)
  ) AS f(final_kind, draft, final, at)
  CROSS JOIN LATERAL (SELECT
        jsonb_typeof(w.draft_prompt->'prompt_context') = 'object'
        AND btrim(COALESCE(w.draft_prompt->>'passage_text', '')) <> '' AS ok) k
 WHERE btrim(COALESCE(f.draft, '')) <> ''
   AND btrim(COALESCE(f.final, '')) <> ''
   AND btrim(regexp_replace(f.draft, '\s+', ' ', 'g'))
       <> btrim(regexp_replace(f.final, '\s+', ' ', 'g'))
   AND btrim(f.draft) <> btrim(f.final)
   AND w.drafted_at IS NOT NULL AND f.at IS NOT NULL AND w.drafted_at < f.at
   AND btrim(w.coach_id) <> ''
   AND (s.user_id IS NULL OR s.user_id::text <> btrim(w.coach_id))
ON CONFLICT (take_word_id, final_kind)
   WHERE take_word_id IS NOT NULL AND superseded_at IS NULL
   DO NOTHING;

COMMENT ON COLUMN public.feedback_pairs.take_word_id IS
    'The coach_take_words row a coach_take_word pair hangs on (0411; a home '
    'since 0479). One current pair per word and final kind: a newer version '
    'supersedes the older (superseded_at), the latest teaches.';

COMMIT;
