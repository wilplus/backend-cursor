-- 0440 · a speaker may change a judgement; the first answer stays (build
-- plan D-FW-9; founder QA1 A, decisions log N51.5; journey Q3; the
-- Feedback walk lock, flow 10).
--
-- WHY. QA1 A: the speaker can go back and change a judgement. The first
-- answer is a self-report with its own provenance (L3) in
-- take_feedback_self_report, append-only under its immutable trigger, one
-- row per (Take, owner, item); a different second answer was refused as
-- RESPONSE_ALREADY_FINAL. The change must be kept BESIDE the first, never
-- over it: the Album, coach routing and every reader of the speaker's side
-- take the latest answer, and the first stays auditable.
--
-- WHAT.
--   * take_feedback_self_report_revision: one row per later answer to a
--     Confident Voice judgement, numbered from 1, pointing at the first
--     answer's row (ON DELETE CASCADE where that table is present).
--     Same provenance (user_self_report), the same five answers. Its
--     trigger refuses UPDATE: a revision is never edited, a newer one is
--     added. DELETE is left to the purge and the cascade.
--   * revise_take_feedback_response_v1(p_take, p_owner, p_feedback_id,
--     p_response): under a lock on the first answer's row, 'not_answered'
--     without a first answer, 'not_revisable' for any family but
--     confident_voice (a rewrite's answer writes the Paragraph, L1; it is
--     not reopened here), 'replayed' when the latest answer already is
--     this one, else 'revised' with the new revision. Its row is the first
--     answer's row with `response` set to the latest and `first_response`
--     beside it.
-- The function reads take_feedback_self_report at call time (plpgsql), so
-- a database without it still takes this file.
--
-- PRIVATE. RLS on with no policy; the browser roles hold nothing on the
-- table or the function; the app calls it with the service key. A product
-- record like the first answer: purged with the Take under the same rule
-- (services/data_purge_registry.py, feedback_self_report_revision).
-- Nothing here is a score or a label (AC-9, L3).
--
-- Additive; idempotent; no env var. The foreign key is added last, NOT
-- VALID, then validated against the empty new table.
-- Rollback (a new forward migration): drop the function, the trigger, its
-- function and the table.

BEGIN;

CREATE TABLE IF NOT EXISTS public.take_feedback_self_report_revision (
    id              bigserial   PRIMARY KEY,
    report_id       bigint      NOT NULL,
    take_session_id uuid        NOT NULL,
    owner_user_id   uuid        NOT NULL,
    feedback_id     text        NOT NULL,
    response        text        NOT NULL,
    revision        integer     NOT NULL,
    provenance      text        NOT NULL DEFAULT 'user_self_report',
    created_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT take_feedback_self_report_revision_once UNIQUE (report_id, revision),
    CONSTRAINT take_feedback_self_report_revision_number CHECK (revision >= 1),
    CONSTRAINT take_feedback_self_report_revision_provenance CHECK (
        provenance = 'user_self_report'),
    CONSTRAINT take_feedback_self_report_revision_response CHECK (
        response IN ('yes', 'in_between', 'no', 'not_sure', 'audio_unclear'))
);
CREATE INDEX IF NOT EXISTS take_feedback_self_report_revision_take_idx
    ON public.take_feedback_self_report_revision (take_session_id);
ALTER TABLE public.take_feedback_self_report_revision ENABLE ROW LEVEL SECURITY;
COMMENT ON TABLE public.take_feedback_self_report_revision IS
    'A later answer to a Confident Voice judgement (0440, D-FW-9; QA1 A), '
    'kept beside the first in take_feedback_self_report and never over it. '
    'Readers take the highest revision as the latest answer; the first stays '
    'auditable. Self-report provenance (L3). Purged with the Take.';


CREATE OR REPLACE FUNCTION public.take_feedback_self_report_revision_never_changes()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
BEGIN
    RAISE EXCEPTION 'A JUDGEMENT REVISION IS NEVER EDITED';
END;
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
         WHERE tgname = 'take_feedback_self_report_revision_never_changes'
           AND tgrelid = 'public.take_feedback_self_report_revision'::regclass
    ) THEN
        CREATE TRIGGER take_feedback_self_report_revision_never_changes
            BEFORE UPDATE ON public.take_feedback_self_report_revision
            FOR EACH ROW EXECUTE FUNCTION public.take_feedback_self_report_revision_never_changes();
    END IF;
END $$;

CREATE OR REPLACE FUNCTION public.revise_take_feedback_response_v1(
    p_take_session_id text, p_owner_user_id text, p_feedback_id text,
    p_response text
) RETURNS jsonb
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
DECLARE
    v_uuid   constant text := '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$';
    v_first  record;
    v_latest text;
    v_number integer;
    v_row    record;
BEGIN
    IF p_take_session_id IS NULL OR p_take_session_id !~* v_uuid
       OR p_owner_user_id IS NULL OR p_owner_user_id !~* v_uuid
       OR COALESCE(btrim(p_feedback_id), '') = ''
       OR p_response IS NULL
       OR p_response NOT IN ('yes', 'in_between', 'no', 'not_sure', 'audio_unclear') THEN
        RAISE EXCEPTION 'JUDGEMENT_REVISION_INPUT_INVALID';
    END IF;
    SELECT * INTO v_first
      FROM public.take_feedback_self_report r
     WHERE r.take_session_id = p_take_session_id::uuid
       AND r.owner_user_id = p_owner_user_id::uuid
       AND r.feedback_id = p_feedback_id
       FOR UPDATE;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('outcome', 'not_answered');
    END IF;
    IF v_first.feedback_family <> 'confident_voice' THEN
        RETURN jsonb_build_object('outcome', 'not_revisable');
    END IF;
    SELECT rev.response, rev.revision INTO v_latest, v_number
      FROM public.take_feedback_self_report_revision rev
     WHERE rev.report_id = v_first.id
     ORDER BY rev.revision DESC
     LIMIT 1;
    IF COALESCE(v_latest, v_first.response) = p_response THEN
        RETURN jsonb_build_object(
            'outcome', 'replayed',
            'row', to_jsonb(v_first) || jsonb_build_object(
                'response', p_response, 'first_response', v_first.response,
                'revision', COALESCE(v_number, 0)));
    END IF;
    INSERT INTO public.take_feedback_self_report_revision (
        report_id, take_session_id, owner_user_id, feedback_id, response, revision)
    VALUES (v_first.id, v_first.take_session_id, v_first.owner_user_id,
            v_first.feedback_id, p_response, COALESCE(v_number, 0) + 1)
    RETURNING * INTO v_row;
    RETURN jsonb_build_object(
        'outcome', 'revised',
        'row', to_jsonb(v_first) || jsonb_build_object(
            'response', v_row.response, 'first_response', v_first.response,
            'revision', v_row.revision, 'revised_at', v_row.created_at));
END;
$$;

DO $$
DECLARE
    v_role text;
BEGIN
    REVOKE ALL ON TABLE public.take_feedback_self_report_revision FROM PUBLIC;
    REVOKE ALL ON SEQUENCE public.take_feedback_self_report_revision_id_seq FROM PUBLIC;
    REVOKE ALL ON FUNCTION public.revise_take_feedback_response_v1(text, text, text, text) FROM PUBLIC;
    REVOKE ALL ON FUNCTION public.take_feedback_self_report_revision_never_changes() FROM PUBLIC;
    FOREACH v_role IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = v_role) THEN
            EXECUTE format('REVOKE ALL ON TABLE public.take_feedback_self_report_revision FROM %I', v_role);
            EXECUTE format('REVOKE ALL ON SEQUENCE public.take_feedback_self_report_revision_id_seq FROM %I', v_role);
            EXECUTE format('REVOKE ALL ON FUNCTION public.revise_take_feedback_response_v1(text, text, text, text) FROM %I', v_role);
            EXECUTE format('REVOKE ALL ON FUNCTION public.take_feedback_self_report_revision_never_changes() FROM %I', v_role);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT EXECUTE ON FUNCTION public.revise_take_feedback_response_v1(text, text, text, text) TO service_role;
        GRANT SELECT, INSERT, DELETE ON TABLE public.take_feedback_self_report_revision TO service_role;
        GRANT USAGE, SELECT ON SEQUENCE public.take_feedback_self_report_revision_id_seq TO service_role;
        -- The function locks the first answer's row (SELECT ... FOR UPDATE)
        -- as the app's role, which needs UPDATE on the parent. 0293 granted
        -- ALL; it is stated here so this file does not lean on it
        -- (GPT-0440 blocker).
        IF to_regclass('public.take_feedback_self_report') IS NOT NULL THEN
            GRANT SELECT, UPDATE ON TABLE public.take_feedback_self_report TO service_role;
        END IF;
    END IF;
END $$;

-- The foreign key goes last, so the share lock it takes on the live
-- take_feedback_self_report is held only for the moment before COMMIT
-- (GPT-0440 should-fix). It is added NOT VALID (no scan) and then
-- validated: the new table is empty, and validating takes only a light
-- lock on the parent.
DO $$
BEGIN
    IF to_regclass('public.take_feedback_self_report') IS NOT NULL
       AND NOT EXISTS (
           SELECT 1 FROM pg_constraint
            WHERE conname = 'take_feedback_self_report_revision_report_fkey'
       ) THEN
        ALTER TABLE public.take_feedback_self_report_revision
            ADD CONSTRAINT take_feedback_self_report_revision_report_fkey
            FOREIGN KEY (report_id) REFERENCES public.take_feedback_self_report (id)
            ON DELETE CASCADE NOT VALID;
        ALTER TABLE public.take_feedback_self_report_revision
            VALIDATE CONSTRAINT take_feedback_self_report_revision_report_fkey;
    ELSIF to_regclass('public.take_feedback_self_report') IS NULL THEN
        RAISE NOTICE 'take_feedback_self_report_revision: take_feedback_self_report is not here; the foreign key waits for it';
    END IF;
END $$;

COMMIT;
