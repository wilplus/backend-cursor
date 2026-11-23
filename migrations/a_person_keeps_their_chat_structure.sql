BEGIN;
SET LOCAL lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS public.owner_chat_structures (
    user_id uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    revision integer NOT NULL DEFAULT 0 CHECK (revision >= 0),
    document jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(document) = 'object')
);
CREATE TABLE IF NOT EXISTS public.owner_chat_section_turns (
    user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    section_id text NOT NULL,
    client_id uuid NOT NULL,
    question text NOT NULL CHECK (char_length(question) BETWEEN 1 AND 4000),
    answer text NOT NULL CHECK (char_length(answer) BETWEEN 1 AND 16000),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, section_id, client_id)
);
CREATE INDEX IF NOT EXISTS owner_chat_section_turns_recent
    ON public.owner_chat_section_turns (user_id, section_id, created_at DESC);

ALTER TABLE public.owner_chat_structures ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.owner_chat_section_turns ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.owner_chat_structures, public.owner_chat_section_turns FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.owner_chat_structures, public.owner_chat_section_turns TO service_role;

-- A group lifecycle write and the conversations it removes form one
-- transaction. Resume checks the same locked structure before adding a turn.
CREATE OR REPLACE FUNCTION public.write_owner_chat_structure_v1(
    p_user uuid, p_expected integer, p_document jsonb, p_removed text[]
) RETURNS boolean LANGUAGE plpgsql SET search_path = public AS $$
BEGIN
    INSERT INTO owner_chat_structures(user_id) VALUES (p_user) ON CONFLICT DO NOTHING;
    UPDATE owner_chat_structures SET revision = p_expected + 1, document = p_document
    WHERE user_id = p_user AND revision = p_expected;
    IF NOT FOUND THEN RETURN false; END IF;
    DELETE FROM owner_chat_section_turns
    WHERE user_id = p_user AND section_id = ANY(p_removed);
    RETURN true;
END;
$$;

CREATE OR REPLACE FUNCTION public.append_owner_chat_section_v1(
    p_user uuid, p_section text, p_client uuid, p_question text, p_answer text
) RETURNS boolean LANGUAGE plpgsql SET search_path = public AS $$
DECLARE layout jsonb;
BEGIN
    INSERT INTO owner_chat_structures(user_id) VALUES (p_user) ON CONFLICT DO NOTHING;
    SELECT document INTO layout FROM owner_chat_structures WHERE user_id = p_user FOR UPDATE;
    IF coalesce(layout->>'builder', 'active') <> 'active' OR (p_section <> coalesce(layout->>'main_chat_id', 'main') AND NOT EXISTS (
        SELECT 1 FROM jsonb_array_elements(coalesce(layout->'subchats','[]'::jsonb)) AS item
        WHERE item->>'id' = p_section AND NOT coalesce((item->>'archived')::boolean, false)
    )) THEN RETURN false; END IF;
    INSERT INTO owner_chat_section_turns(user_id, section_id, client_id, question, answer)
    VALUES (p_user, p_section, p_client, p_question, p_answer) ON CONFLICT DO NOTHING;
    RETURN true;
END;
$$;

REVOKE ALL ON FUNCTION public.write_owner_chat_structure_v1(uuid, integer, jsonb, text[]) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.append_owner_chat_section_v1(uuid, text, uuid, text, text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.write_owner_chat_structure_v1(uuid, integer, jsonb, text[]) TO service_role;
GRANT EXECUTE ON FUNCTION public.append_owner_chat_section_v1(uuid, text, uuid, text, text) TO service_role;

CREATE OR REPLACE FUNCTION public.delete_owner_speaking_chat_v1(
    p_user uuid, p_principal uuid, p_expected integer, p_projects uuid[]
) RETURNS boolean LANGUAGE plpgsql SET search_path = public AS $$
DECLARE layout jsonb; version integer; actual uuid[]; project uuid;
BEGIN
    INSERT INTO owner_chat_structures(user_id) VALUES (p_user) ON CONFLICT DO NOTHING;
    SELECT document, revision INTO layout, version FROM owner_chat_structures
    WHERE user_id = p_user FOR UPDATE;
    IF version <> p_expected THEN RETURN false; END IF;
    IF coalesce(layout->>'coach', 'active') = 'deleted' THEN RETURN true; END IF;
    SELECT coalesce(array_agg(id ORDER BY id), ARRAY[]::uuid[]) INTO actual
    FROM projects WHERE owner_principal_id = p_principal AND tombstoned_at IS NULL;
    IF actual <> p_projects THEN RETURN false; END IF;

    FOREACH project IN ARRAY actual LOOP
        PERFORM request_project_deletion_v1(
            p_principal, project, 'speaking-coach:' || p_expected || ':' || project::text
        );
    END LOOP;
    DELETE FROM lounge_messages WHERE user_id = p_user AND kind = 'text'
        AND metadata->>'place' = 'speaking' AND metadata->>'arc_id' IS NULL;
    UPDATE owner_chat_structures SET document = layout || '{"coach":"deleted"}'::jsonb,
        revision = p_expected + 1 WHERE user_id = p_user;
    RETURN true;
END;
$$;

REVOKE ALL ON FUNCTION public.delete_owner_speaking_chat_v1(uuid, uuid, integer, uuid[]) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.delete_owner_speaking_chat_v1(uuid, uuid, integer, uuid[]) TO service_role;

NOTIFY pgrst, 'reload schema';
COMMIT;
