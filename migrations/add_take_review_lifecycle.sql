-- One durable review version and one immutable feedback set per spoken Take.
--
-- The canonical Ideal Text is created once by Take 1.  Later Takes advance
-- the REVIEW identity (2.0, 3.0, ...) without rebuilding the words behind the
-- owner's back.  The version advance, owner-edit carry-forward, and historical
-- snapshot are one transaction so a worker can never report success between
-- those writes.
--
-- The Feedback Manager also chooses once per Take.  Only stable identities are
-- stored here; playback URLs and other presentation fields are rebuilt on
-- every read.  A decided item can consequently disappear, but no fourth item
-- can take its place on a later GET.

CREATE TABLE IF NOT EXISTS public.ideal_text_feedback_sets (
    arc_id           TEXT        NOT NULL,
    take_session_id  UUID        NOT NULL
        REFERENCES public.v2_sessions(id) ON DELETE CASCADE,
    take_index       INTEGER     NOT NULL CHECK (take_index >= 1),
    review_version   INTEGER     NOT NULL CHECK (review_version >= 1),
    selected_keys    JSONB       NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (arc_id, take_session_id),
    UNIQUE (arc_id, review_version),
    CONSTRAINT ideal_text_feedback_sets_keys_array CHECK (
        jsonb_typeof(selected_keys) = 'array'
        AND jsonb_array_length(selected_keys) BETWEEN 1 AND 3
        AND selected_keys @> '[{"feedback_family":"confident_voice"}]'::jsonb
    )
);

CREATE INDEX IF NOT EXISTS ideal_text_feedback_sets_take_idx
    ON public.ideal_text_feedback_sets (take_session_id);

ALTER TABLE public.ideal_text_feedback_sets ENABLE ROW LEVEL SECURITY;


CREATE OR REPLACE FUNCTION public.finalize_ideal_text_take_v1(
    p_arc_id TEXT,
    p_owner_user_id UUID,
    p_take_session_id UUID,
    p_take_index INTEGER,
    p_moments JSONB DEFAULT '[]'::jsonb
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

    -- Preserve the exact words the owner currently sees.  An owner edit wins;
    -- otherwise a coach-verified body is promoted as the unchanged base for
    -- the new unverified review; otherwise the existing machine copy remains.
    IF p_take_index >= old_version
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

    -- Append-only snapshot.  A retry of the same Take is a read of the same
    -- state, never a rewrite of history.
    INSERT INTO public.ideal_text_versions (
        arc_id, version, text, moments, created_at, updated_at
    ) VALUES (
        p_arc_id,
        p_take_index,
        snapshot_text,
        COALESCE(p_moments, '[]'::jsonb),
        now(),
        now()
    ) ON CONFLICT (arc_id, version) DO NOTHING;

    IF p_take_index > old_version THEN
        -- Keep an owner edit current because the review identity changed, not
        -- the document.  Stale edits from an older document are never revived.
        UPDATE public.user_arc_ideal_notes
           SET user_text_version = p_take_index,
               updated_at = now()
         WHERE arc_id = p_arc_id
           AND user_id = p_owner_user_id
           AND user_text_version = old_version
           AND NULLIF(trim(COALESCE(user_text, '')), '') IS NOT NULL;

        UPDATE public.coach_arc_ideal_text
           SET version = p_take_index,
               -- A verified body remains the exact body shown after the Take,
               -- but verified_version deliberately stays behind: each Take has
               -- a fresh review state without losing the accepted words.
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
        'text_confirmed', true
    );
END;
$$;


CREATE OR REPLACE FUNCTION public.claim_ideal_text_feedback_set_v1(
    p_arc_id TEXT,
    p_owner_user_id UUID,
    p_take_session_id UUID,
    p_take_index INTEGER,
    p_review_version INTEGER,
    p_selected_keys JSONB
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    s public.v2_sessions%ROWTYPE;
    claimed public.ideal_text_feedback_sets%ROWTYPE;
BEGIN
    IF jsonb_typeof(p_selected_keys) <> 'array'
       OR jsonb_array_length(p_selected_keys) NOT BETWEEN 1 AND 3 THEN
        RAISE EXCEPTION 'feedback set must contain between 1 and 3 items';
    END IF;
    IF NOT p_selected_keys
           @> '[{"feedback_family":"confident_voice"}]'::jsonb THEN
        RAISE EXCEPTION 'feedback set requires Confident Voice';
    END IF;
    IF p_review_version IS DISTINCT FROM p_take_index THEN
        RAISE EXCEPTION 'review version must equal Take index';
    END IF;

    SELECT * INTO s
      FROM public.v2_sessions
     WHERE id = p_take_session_id;
    IF s.id IS NULL THEN RAISE EXCEPTION 'Take not found'; END IF;
    IF s.user_id IS DISTINCT FROM p_owner_user_id
       OR s.arc_id::text IS DISTINCT FROM p_arc_id
       OR s.take_index IS DISTINCT FROM p_take_index THEN
        RAISE EXCEPTION 'feedback set provenance mismatch';
    END IF;
    IF COALESCE(s.recording_kind, 'spoken') <> 'spoken'
       OR s.paired_session_id IS NOT NULL THEN
        RAISE EXCEPTION 'feedback set requires a spoken Take';
    END IF;

    SELECT * INTO claimed
      FROM public.ideal_text_feedback_sets
     WHERE arc_id = p_arc_id AND take_session_id = p_take_session_id;
    IF claimed.arc_id IS NULL THEN
        INSERT INTO public.ideal_text_feedback_sets (
            arc_id, take_session_id, take_index, review_version, selected_keys
        ) VALUES (
            p_arc_id, p_take_session_id, p_take_index,
            p_review_version, p_selected_keys
        )
        ON CONFLICT DO NOTHING;

        SELECT * INTO claimed
          FROM public.ideal_text_feedback_sets
         WHERE arc_id = p_arc_id
           AND (take_session_id = p_take_session_id
                OR review_version = p_review_version)
         ORDER BY created_at
         LIMIT 1;
    END IF;

    IF claimed.arc_id IS NULL THEN
        RAISE EXCEPTION 'feedback set could not be claimed';
    END IF;
    IF claimed.take_session_id IS DISTINCT FROM p_take_session_id
       OR claimed.take_index IS DISTINCT FROM p_take_index
       OR claimed.review_version IS DISTINCT FROM p_review_version THEN
        RAISE EXCEPTION 'feedback set claim conflicts with Take provenance';
    END IF;
    RETURN to_jsonb(claimed);
END;
$$;

REVOKE ALL ON FUNCTION public.finalize_ideal_text_take_v1(
    TEXT, UUID, UUID, INTEGER, JSONB
) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.finalize_ideal_text_take_v1(
    TEXT, UUID, UUID, INTEGER, JSONB
) FROM anon, authenticated;
REVOKE ALL ON FUNCTION public.claim_ideal_text_feedback_set_v1(
    TEXT, UUID, UUID, INTEGER, INTEGER, JSONB
) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.claim_ideal_text_feedback_set_v1(
    TEXT, UUID, UUID, INTEGER, INTEGER, JSONB
) FROM anon, authenticated;
GRANT EXECUTE ON FUNCTION public.finalize_ideal_text_take_v1(
    TEXT, UUID, UUID, INTEGER, JSONB
) TO service_role;
GRANT EXECUTE ON FUNCTION public.claim_ideal_text_feedback_set_v1(
    TEXT, UUID, UUID, INTEGER, INTEGER, JSONB
) TO service_role;
