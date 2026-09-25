-- 0363 · Practice made for people who never ticked the box.
--
-- FOUNDER 2026-09-25, decision 1: "delete the practice recordings made for
-- people who never ticked the box" — after a preview of the exact list is
-- approved. This file only LISTS. Nothing here deletes, and nothing runs on
-- boot but the definition. The erasure is scripts/erase_practice_without_the_tick.py,
-- run by hand, and only against the list the operator approved (its hash).
--
-- WHY THE DATA EXISTS. The optional "Personalised practice" tick (0357) was
-- recorded and read by nothing until 0361/#654: a person who left it empty
-- still had exercises chosen from their recordings. #654 stopped new practice
-- for them; what was already made stayed, because the switch deletes only
-- when someone turns practice off, and these people never turned anything off.
--
-- THREE GROUPS, AND ONLY ONE IS ERASED.
--   unticked    has accepted, and no receipt of theirs ever carried the tick
--               (every optional purpose of its policy, 0361's rule), and they
--               never turned it on afterwards.
--               THIS is the founder's group.
--   ticked      said yes at some point. Never touched here.
--   no_receipt  never accepted any policy (made before the acceptance screen
--               existed). They were never asked, so they did not "leave it
--               empty". Reported only; their fate is a separate decision.
-- "Ever ticked" is read across the whole person — every principal the purge
-- graph joins (a guest who signed up is one person) — so a yes given as a
-- guest keeps a later account's practice.
--
-- ADDITIVE AND IDEMPOTENT. One read-only function, service_role only.

CREATE OR REPLACE FUNCTION public.list_practice_without_the_tick_v1()
RETURNS TABLE (principal_id UUID, category TEXT, practice_count INTEGER)
LANGUAGE plpgsql SECURITY DEFINER STABLE SET search_path = public
AS $$
DECLARE
    candidate UUID;
    person TEXT[];
    practices TEXT[];
BEGIN
    FOR candidate IN
        SELECT DISTINCT owner.id
          FROM public.confident_voice_practice practice
          JOIN public.owner_principals owner
            ON owner.user_id = practice.owner_user_id
        UNION
        SELECT DISTINCT session.owner_principal_id
          FROM public.confident_voice_practice practice
          JOIN public.v2_sessions session
            ON session.id = practice.take_session_id
         WHERE session.owner_principal_id IS NOT NULL
    LOOP
        SELECT ARRAY(SELECT jsonb_array_elements_text(graph->'principal_ids')),
               ARRAY(SELECT jsonb_array_elements_text(graph->'practice_ids'))
          INTO person, practices
          FROM (SELECT public.resolve_phase1_purge_subject_graph_v2(candidate)
                       AS graph) resolved;
        principal_id := candidate;
        practice_count := COALESCE(cardinality(practices), 0);
        -- A receipt carries the tick when it names every optional purpose of
        -- its own policy — the rule get_phase1_consent_choices_v1 (0361)
        -- applies, so "ticked" means here what it means on the page.
        IF EXISTS (
            SELECT 1 FROM public.processing_authorization_receipts receipt
             WHERE receipt.acquisition_principal_id::text = ANY(person)
               AND EXISTS (
                   SELECT 1 FROM public.processing_policy_purposes pp
                    WHERE pp.policy_id = receipt.policy_id
                      AND NOT pp.required_for_core_service)
               AND NOT EXISTS (
                   SELECT 1 FROM public.processing_policy_purposes pp
                    WHERE pp.policy_id = receipt.policy_id
                      AND NOT pp.required_for_core_service
                      AND NOT EXISTS (
                          SELECT 1
                            FROM public.processing_authorization_receipt_purposes rp
                           WHERE rp.receipt_id = receipt.id
                             AND rp.purpose_id = pp.purpose_id))
        ) OR EXISTS (
            SELECT 1 FROM public.processing_consent_choice_events event
             WHERE event.acquisition_principal_id::text = ANY(person)
               AND event.choice = 'personalised_practice'
               AND event.event_kind = 'grant'
        ) THEN
            category := 'ticked';
        ELSIF EXISTS (
            SELECT 1 FROM public.processing_authorization_receipts receipt
             WHERE receipt.acquisition_principal_id::text = ANY(person)
        ) THEN
            category := 'unticked';
        ELSE
            category := 'no_receipt';
        END IF;
        RETURN NEXT;
    END LOOP;
END;
$$;
REVOKE ALL ON FUNCTION public.list_practice_without_the_tick_v1()
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.list_practice_without_the_tick_v1()
    TO service_role;
