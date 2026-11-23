SET LOCAL lock_timeout = '5s';

ALTER TABLE public.owner_chat_section_turns ADD COLUMN IF NOT EXISTS artifact jsonb;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'public.owner_chat_section_turns'::regclass
          AND conname = 'owner_chat_section_turns_artifact'
    ) THEN
        ALTER TABLE public.owner_chat_section_turns
            ADD CONSTRAINT owner_chat_section_turns_artifact CHECK (
                artifact IS NULL OR (question IS NOT NULL AND jsonb_typeof(artifact) = 'object')
            ) NOT VALID;
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION public.owner_chat_linked_principals_v1(p_user uuid)
RETURNS uuid[] LANGUAGE sql STABLE SET search_path = '' AS $$
    WITH RECURSIVE linked(id) AS (
        SELECT id FROM public.owner_principals WHERE user_id = p_user
        UNION
        SELECT CASE WHEN event.source_owner_principal_id = linked.id
                    THEN event.target_owner_principal_id ELSE event.source_owner_principal_id END
        FROM linked JOIN public.owner_claim_events event
          ON linked.id IN (event.source_owner_principal_id, event.target_owner_principal_id)
    )
    SELECT ARRAY(SELECT id FROM linked ORDER BY id);
$$;

REVOKE ALL ON FUNCTION public.owner_chat_linked_principals_v1(uuid) FROM PUBLIC, anon, authenticated, service_role;

CREATE OR REPLACE FUNCTION public.owner_chat_may_write_v1(p_user uuid)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE principals uuid[] := public.owner_chat_linked_principals_v1(p_user);
BEGIN
    IF cardinality(principals) = 0 THEN
        -- A first chat can precede the canonical product owner. The auth
        -- row's lock makes creating or claiming that owner wait. If one
        -- appeared while we waited, retry without the auth lock first.
        PERFORM 1 FROM auth.users WHERE id = p_user AND deleted_at IS NULL FOR UPDATE;
        RETURN FOUND AND cardinality(public.owner_chat_linked_principals_v1(p_user)) = 0;
    END IF;

    -- Follow the erasure graph and take guest locks before the account lock,
    -- as the guest claim does. Recheck on a fresh statement snapshot in
    -- case a claim committed while this writer was waiting.
    PERFORM 1 FROM public.owner_principals owner
    WHERE owner.id = ANY(principals)
    ORDER BY owner.user_id NULLS FIRST, owner.id FOR UPDATE OF owner;
    RETURN principals = public.owner_chat_linked_principals_v1(p_user)
      AND EXISTS (SELECT 1 FROM auth.users WHERE id = p_user AND deleted_at IS NULL)
      AND NOT EXISTS (
        SELECT 1 FROM public.account_deletion_requests
        WHERE acquisition_principal_id = ANY(principals) AND state IN ('pending', 'started', 'done')
      )
      AND NOT EXISTS (
        SELECT 1 FROM public.data_purge_requests
        WHERE acquisition_principal_id = ANY(principals) AND project_id IS NULL
      );
END;
$$;

REVOKE ALL ON FUNCTION public.owner_chat_may_write_v1(uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.owner_chat_may_write_v1(uuid) TO service_role;

-- Turn contents and attachments are cleared together. The retained key
-- keeps a retried delivery from recreating a deleted turn.
CREATE OR REPLACE FUNCTION public.write_owner_chat_structure_v1(
    p_user uuid, p_expected integer, p_document jsonb, p_removed text[]
) RETURNS boolean LANGUAGE plpgsql SET search_path = public AS $$
BEGIN
    IF NOT public.owner_chat_may_write_v1(p_user) THEN RETURN false; END IF;
    INSERT INTO owner_chat_structures(user_id) VALUES (p_user) ON CONFLICT DO NOTHING;
    UPDATE owner_chat_structures SET revision = p_expected + 1, document = p_document
    WHERE user_id = p_user AND revision = p_expected;
    IF NOT FOUND THEN RETURN false; END IF;
    UPDATE owner_chat_section_turns SET question = NULL, answer = NULL, artifact = NULL
    WHERE user_id = p_user AND section_id = ANY(p_removed);
    RETURN true;
END;
$$;

CREATE OR REPLACE FUNCTION public.append_owner_chat_section_v2(
    p_user uuid, p_section text, p_client uuid, p_question text, p_answer text, p_artifact jsonb
) RETURNS boolean LANGUAGE plpgsql SET search_path = public AS $$
DECLARE layout jsonb;
BEGIN
    IF NOT public.owner_chat_may_write_v1(p_user) THEN RETURN false; END IF;
    INSERT INTO owner_chat_structures(user_id) VALUES (p_user) ON CONFLICT DO NOTHING;
    SELECT document INTO layout FROM owner_chat_structures WHERE user_id = p_user FOR UPDATE;
    IF coalesce(layout->>'builder', 'active') <> 'active' OR (p_section <> coalesce(layout->>'main_chat_id', 'main') AND NOT EXISTS (
        SELECT 1 FROM jsonb_array_elements(coalesce(layout->'subchats','[]'::jsonb)) AS item
        WHERE item->>'id' = p_section AND NOT coalesce((item->>'archived')::boolean, false)
    )) THEN RETURN false; END IF;
    INSERT INTO owner_chat_section_turns AS kept(user_id, section_id, client_id, question, answer, artifact)
    VALUES (p_user, p_section, p_client, p_question, p_answer, p_artifact)
    ON CONFLICT (user_id, section_id, client_id) DO UPDATE SET artifact = EXCLUDED.artifact
    WHERE kept.artifact IS NULL AND EXCLUDED.artifact IS NOT NULL
      AND kept.question = EXCLUDED.question AND kept.answer = EXCLUDED.answer;
    RETURN p_artifact IS NULL OR EXISTS (
        SELECT 1 FROM owner_chat_section_turns
        WHERE user_id = p_user AND section_id = p_section AND client_id = p_client
          AND question = p_question AND answer = p_answer AND artifact = p_artifact
    );
END;
$$;

REVOKE ALL ON FUNCTION public.append_owner_chat_section_v2(uuid, text, uuid, text, text, jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.append_owner_chat_section_v2(uuid, text, uuid, text, text, jsonb) TO service_role;

CREATE OR REPLACE FUNCTION public.append_owner_chat_section_v1(
    p_user uuid, p_section text, p_client uuid, p_question text, p_answer text
) RETURNS boolean LANGUAGE sql SET search_path = '' AS $$
    SELECT public.append_owner_chat_section_v2(p_user, p_section, p_client, p_question, p_answer, NULL);
$$;

CREATE OR REPLACE FUNCTION public.delete_owner_speaking_chat_v1(
    p_user uuid, p_principal uuid, p_expected integer, p_projects uuid[]
) RETURNS boolean LANGUAGE plpgsql SET search_path = public AS $$
DECLARE layout jsonb; version integer; actual uuid[]; project uuid;
BEGIN
    IF NOT public.owner_chat_may_write_v1(p_user) THEN RETURN false; END IF;
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
    UPDATE lounge_messages SET body = '', metadata = NULL, chat_erased = true
    WHERE user_id = p_user AND kind = 'text'
        AND metadata->>'place' = 'speaking' AND metadata->>'arc_id' IS NULL;
    UPDATE owner_chat_structures SET document = layout || '{"coach":"deleted"}'::jsonb,
        revision = p_expected + 1 WHERE user_id = p_user;
    RETURN true;
END;
$$;

NOTIFY pgrst, 'reload schema';
