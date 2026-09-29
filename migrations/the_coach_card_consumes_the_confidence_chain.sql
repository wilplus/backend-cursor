-- 0392 · The coach card consumes the confidence chain (Q2, founder 2026-09-29).
--
-- The canonical blind packet, render acknowledgement, judgment and reveal
-- RPCs of the confidence chain (0302, 0304) had no application caller: the
-- only judgment path was the D5 inline batch, behind its own flag, which
-- writes its packets to exercise_blind_packets rather than the table the
-- canary readiness counts. This migration gives the legacy coach card, the
-- queue coaches use today, its own three SECURITY DEFINER wrappers:
--
--   prepare_mlc2_confidence_coach_packet_v1   one selected, eligible candidate
--                                             of the Take's own snippet → the
--                                             blind packet (idempotent per
--                                             candidate and reviewer)
--   ack_mlc2_confidence_coach_render_v1       the browser's visible-render
--                                             receipt, bound to that packet
--   submit_mlc2_confidence_coach_judgment_v1  the coach's five-state answer as
--                                             an immutable blind_coach
--                                             judgment, and the reveal in the
--                                             same transaction, because the
--                                             legacy card releases the words
--                                             in the same response as the
--                                             saved label
--
-- The packet carries audio identity only (0304 builds it; #759 pins that no
-- transcript, prediction, score, rank or selection hint is in it). A coach
-- reviewing their own Take gets no packet: the owner is not a peer. Nothing
-- here reads or writes a legacy learning store, and nothing activates: the
-- application calls these only while MLC2_CONFIDENCE_CUTOVER_MODE is
-- founder_canary, and the writer state stays dark.
--
-- Additive: three new functions, same grants shape as 0304, the search path
-- 0307 set. No table changes, no rows touched, no environment variable.

BEGIN;

CREATE OR REPLACE FUNCTION public.prepare_mlc2_confidence_coach_packet_v1(
    p_take_id UUID,
    p_snippet_id UUID,
    p_reviewer_principal_id UUID,
    p_delivery_mode TEXT
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = extensions, public
AS $$
DECLARE
    candidate         public.ml_candidates%ROWTYPE;
    speaker_principal UUID;
    packet            JSONB;
BEGIN
    IF p_delivery_mode NOT IN ('canary', 'production') THEN
        RAISE EXCEPTION 'coach packet delivery mode invalid';
    END IF;
    IF p_take_id IS NULL OR p_snippet_id IS NULL
       OR p_reviewer_principal_id IS NULL THEN
        RAISE EXCEPTION 'coach packet identity incomplete';
    END IF;

    -- The frame factory writes one candidate per snippet with clip_id = the
    -- snippet id; the selected, eligible one of the latest set on this Take
    -- is the moment the blind card asks about.
    SELECT candidate_row.* INTO candidate
      FROM public.ml_candidates candidate_row
      JOIN public.ml_candidate_sets candidate_set
        ON candidate_set.id = candidate_row.candidate_set_id
     WHERE candidate_row.clip_id = p_snippet_id
       AND candidate_set.take_id = p_take_id
       AND candidate_row.selected
       AND candidate_row.eligible
     ORDER BY candidate_row.created_at DESC, candidate_row.id DESC
     LIMIT 1;
    IF candidate.id IS NULL THEN
        RETURN NULL;
    END IF;

    SELECT candidate_set.acquisition_principal_id INTO speaker_principal
      FROM public.ml_candidate_sets candidate_set
     WHERE candidate_set.id = candidate.candidate_set_id;
    IF speaker_principal = p_reviewer_principal_id THEN
        -- The owner is not a peer (founder 2026-08-11): a coach reviewing
        -- their own Take is a self-report, never a blind judgment.
        RETURN NULL;
    END IF;

    packet := public.create_mlc2_confidence_blind_packet_v1(
        candidate.id, p_reviewer_principal_id, 'coach', 'conf-q-v2',
        'coach-card-blind-v1', p_delivery_mode,
        'coach-card:' || candidate.id::text || ':'
            || p_reviewer_principal_id::text
    );
    RETURN packet || jsonb_build_object('candidate_id', candidate.id);
END;
$$;

CREATE OR REPLACE FUNCTION public.ack_mlc2_confidence_coach_render_v1(
    p_review_assignment_id UUID,
    p_presentation_id UUID,
    p_acknowledgement_token UUID,
    p_reviewer_principal_id UUID,
    p_render_instance_id UUID,
    p_client_rendered_at TIMESTAMPTZ,
    p_client_version TEXT,
    p_visible_payload_sha256 TEXT,
    p_idempotency_key TEXT
) RETURNS public.ml_rendered_exposures
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = extensions, public
AS $$
DECLARE
    result public.ml_rendered_exposures;
BEGIN
    IF NOT EXISTS (
        SELECT 1
          FROM public.ml_confidence_blind_packets packet
          JOIN public.ml_presentations presentation
            ON presentation.id = p_presentation_id
           AND presentation.review_assignment_id = packet.review_assignment_id
           AND presentation.actor_principal_id = p_reviewer_principal_id
         WHERE packet.review_assignment_id = p_review_assignment_id
           AND packet.reviewer_principal_id = p_reviewer_principal_id
           AND packet.reviewer_role = 'coach'
           AND packet.visible_packet_sha256 = p_visible_payload_sha256
    ) THEN
        RAISE EXCEPTION 'COACH_CARD_BLIND_RENDER_IDENTITY_INVALID';
    END IF;
    SELECT * INTO STRICT result FROM public.ack_mlc2_rendered_exposure_v1(
        p_presentation_id, p_acknowledgement_token,
        p_reviewer_principal_id, p_render_instance_id,
        p_client_rendered_at, p_client_version,
        p_visible_payload_sha256, p_idempotency_key
    );
    RETURN result;
END;
$$;

CREATE OR REPLACE FUNCTION public.submit_mlc2_confidence_coach_judgment_v1(
    p_review_assignment_id UUID,
    p_reviewer_principal_id UUID,
    p_exposure_id UUID,
    p_decision TEXT,
    p_decided_at TIMESTAMPTZ,
    p_idempotency_key TEXT
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = extensions, public
AS $$
DECLARE
    result       JSONB;
    reveal_event public.ml_review_assignment_events;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM public.ml_confidence_blind_packets packet
         WHERE packet.review_assignment_id = p_review_assignment_id
           AND packet.reviewer_principal_id = p_reviewer_principal_id
           AND packet.reviewer_role = 'coach'
    ) THEN
        RAISE EXCEPTION 'COACH_CARD_BLIND_JUDGMENT_IDENTITY_INVALID';
    END IF;
    -- The owner-only judgment writer (0325 revoked it from service_role) is
    -- reached only through this exact-identity wrapper, as D5 reaches it
    -- through its own.
    result := public.submit_mlc2_confidence_blind_judgment_v1(
        p_review_assignment_id, p_reviewer_principal_id, p_exposure_id,
        p_decision, p_decided_at, p_idempotency_key
    );
    -- The legacy card releases the transcript in the same response as the
    -- saved label, so the canonical reveal is recorded here, in the same
    -- transaction as the judgment. A replayed judgment replays the reveal.
    SELECT * INTO reveal_event FROM public.reveal_mlc2_confidence_review_v1(
        p_review_assignment_id, p_reviewer_principal_id,
        p_idempotency_key || ':reveal'
    );
    RETURN result || jsonb_build_object(
        'reveal_event_id', reveal_event.id,
        'revealed', true
    );
END;
$$;

REVOKE ALL ON FUNCTION public.prepare_mlc2_confidence_coach_packet_v1(
    UUID, UUID, UUID, TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.prepare_mlc2_confidence_coach_packet_v1(
    UUID, UUID, UUID, TEXT
) TO service_role;

REVOKE ALL ON FUNCTION public.ack_mlc2_confidence_coach_render_v1(
    UUID, UUID, UUID, UUID, UUID, TIMESTAMPTZ, TEXT, TEXT, TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.ack_mlc2_confidence_coach_render_v1(
    UUID, UUID, UUID, UUID, UUID, TIMESTAMPTZ, TEXT, TEXT, TEXT
) TO service_role;

REVOKE ALL ON FUNCTION public.submit_mlc2_confidence_coach_judgment_v1(
    UUID, UUID, UUID, TEXT, TIMESTAMPTZ, TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.submit_mlc2_confidence_coach_judgment_v1(
    UUID, UUID, UUID, TEXT, TIMESTAMPTZ, TEXT
) TO service_role;

NOTIFY pgrst, 'reload schema';
COMMIT;
