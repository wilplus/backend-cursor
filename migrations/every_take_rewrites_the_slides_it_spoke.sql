-- Every Take rewrites the Slides it spoke (contract 8-9, founder 2026-09-25).
--
-- `finalize_ideal_text_take_v1` advances a later Take's review version and
-- deliberately keeps the words. That was L1 until 2026-09-25. v2 is the same
-- boundary with one addition: when the caller passes the rebuilt text (the
-- Slides spoken in this Take rebuilt from its transcript, the others kept),
-- the words, their Slide map and the version snapshot are written in the SAME
-- transaction, and the new words supersede an owner edit and coach-verified
-- text (Q5 A, Q13 A). Both stay readable: the owner edit as `prior_edit`, the
-- earlier body in `ideal_text_versions`.
--
-- With p_auto_text NULL, v2 behaves exactly like v1. v1 is left in place,
-- untouched, so the code running during deploy keeps its own contract.
--
-- An older Take finalizing after a newer one (p_take_index < version) never
-- writes words: a late Take 2 must not overwrite Take 3.
--
-- `ideal_text_versions.document` keeps the Slide map of each version, which
-- the Paragraph history (PR 3c) reads. Additive and idempotent.

BEGIN;

ALTER TABLE public.ideal_text_versions
    ADD COLUMN IF NOT EXISTS document JSONB NULL;

CREATE OR REPLACE FUNCTION public.finalize_ideal_text_take_v2(
    p_arc_id TEXT,
    p_owner_user_id UUID,
    p_take_session_id UUID,
    p_take_index INTEGER,
    p_moments JSONB DEFAULT '[]'::jsonb,
    p_auto_text TEXT DEFAULT NULL,
    p_document JSONB DEFAULT NULL
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    s public.v2_sessions%ROWTYPE;
    ideal public.coach_arc_ideal_text%ROWTYPE;
    old_version INTEGER;
    snapshot_text TEXT;
    owner_text TEXT;
    owner_text_version INTEGER;
    carry_verified BOOLEAN := false;
    rebuilt BOOLEAN := false;
BEGIN
    IF p_take_index IS NULL OR p_take_index < 2 THEN
        RAISE EXCEPTION 'later Take index must be at least 2';
    END IF;

    SELECT * INTO s
      FROM public.v2_sessions
     WHERE id = p_take_session_id
     FOR UPDATE;

    IF s.id IS NULL THEN RAISE EXCEPTION 'Take not found'; END IF;
    IF s.user_id IS DISTINCT FROM p_owner_user_id THEN
        RAISE EXCEPTION 'Take owner mismatch';
    END IF;
    IF s.arc_id::text IS DISTINCT FROM p_arc_id THEN
        RAISE EXCEPTION 'Take Project mismatch';
    END IF;
    IF s.take_index IS DISTINCT FROM p_take_index THEN
        RAISE EXCEPTION 'Take index mismatch';
    END IF;
    IF COALESCE(s.recording_kind, 'spoken') <> 'spoken'
       OR s.paired_session_id IS NOT NULL THEN
        RAISE EXCEPTION 'only a spoken Take can advance Ideal Text review';
    END IF;

    SELECT * INTO ideal
      FROM public.coach_arc_ideal_text
     WHERE arc_id = p_arc_id
     FOR UPDATE;

    IF ideal.arc_id IS NULL THEN
        RAISE EXCEPTION 'canonical Ideal Text is missing';
    END IF;

    old_version := GREATEST(COALESCE(ideal.version, 1), 1);

    SELECT user_text, user_text_version
      INTO owner_text, owner_text_version
      FROM public.user_arc_ideal_notes
     WHERE arc_id = p_arc_id AND user_id = p_owner_user_id
     FOR UPDATE;

    rebuilt := p_take_index >= old_version
               AND NULLIF(trim(COALESCE(p_auto_text, '')), '') IS NOT NULL;

    IF rebuilt THEN
        -- The Paragraph is what was said in this Take (L1, 2026-09-25).
        snapshot_text := p_auto_text;
    ELSIF p_take_index >= old_version
       AND NULLIF(trim(COALESCE(owner_text, '')), '') IS NOT NULL
       AND owner_text_version = old_version THEN
        snapshot_text := owner_text;
    ELSIF p_take_index >= old_version
       AND ideal.verified_version = old_version
       AND NULLIF(trim(COALESCE(ideal.verified_text, '')), '') IS NOT NULL THEN
        snapshot_text := ideal.verified_text;
        carry_verified := true;
    ELSE
        snapshot_text := NULLIF(trim(COALESCE(ideal.auto_text, '')), '');
        IF snapshot_text IS NULL
           AND ideal.updated_by IS NULL
           AND ideal.approved_at IS NULL THEN
            snapshot_text := NULLIF(trim(COALESCE(ideal.text, '')), '');
        END IF;
    END IF;

    IF snapshot_text IS NULL THEN
        RAISE EXCEPTION 'canonical Ideal Text is not readable';
    END IF;

    INSERT INTO public.ideal_text_versions (
        arc_id, version, text, moments, document, created_at, updated_at
    ) VALUES (
        p_arc_id,
        p_take_index,
        snapshot_text,
        COALESCE(p_moments, '[]'::jsonb),
        CASE WHEN rebuilt THEN p_document ELSE ideal.document END,
        now(),
        now()
    ) ON CONFLICT (arc_id, version) DO NOTHING;

    IF rebuilt THEN
        -- The owner edit is NOT carried forward: it stays at its version and
        -- reads back as `prior_edit`. verified_version stays behind, so the
        -- verified body is history too.
        UPDATE public.coach_arc_ideal_text
           SET version = GREATEST(old_version, p_take_index),
               auto_text = p_auto_text,
               document = COALESCE(p_document, document),
               auto_updated_at = now(),
               text = CASE WHEN updated_by IS NULL AND approved_at IS NULL
                           THEN p_auto_text ELSE text END,
               updated_at = now()
         WHERE arc_id = p_arc_id;
    ELSIF p_take_index > old_version THEN
        UPDATE public.user_arc_ideal_notes
           SET user_text_version = p_take_index,
               updated_at = now()
         WHERE arc_id = p_arc_id
           AND user_id = p_owner_user_id
           AND user_text_version = old_version
           AND NULLIF(trim(COALESCE(user_text, '')), '') IS NOT NULL;

        UPDATE public.coach_arc_ideal_text
           SET version = p_take_index,
               auto_text = CASE WHEN carry_verified
                                THEN snapshot_text ELSE auto_text END,
               auto_updated_at = CASE WHEN carry_verified
                                      THEN now() ELSE auto_updated_at END,
               updated_at = now()
         WHERE arc_id = p_arc_id;
    END IF;

    RETURN jsonb_build_object(
        'arc_id', p_arc_id,
        'take_session_id', p_take_session_id,
        'take_index', p_take_index,
        'version', p_take_index,
        'current_version', GREATEST(old_version, p_take_index),
        'advanced', p_take_index > old_version,
        'rebuilt', rebuilt,
        'text_confirmed', true
    );
END;
$$;

REVOKE ALL ON FUNCTION public.finalize_ideal_text_take_v2(
    TEXT, UUID, UUID, INTEGER, JSONB, TEXT, JSONB
) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.finalize_ideal_text_take_v2(
    TEXT, UUID, UUID, INTEGER, JSONB, TEXT, JSONB
) FROM anon, authenticated;
GRANT EXECUTE ON FUNCTION public.finalize_ideal_text_take_v2(
    TEXT, UUID, UUID, INTEGER, JSONB, TEXT, JSONB
) TO service_role;

COMMIT;
