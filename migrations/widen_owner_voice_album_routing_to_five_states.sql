-- The owner's answer outside a Take review keeps all FIVE states
-- (founder 2026-09-18, "Practice new").
--
-- WHY THIS TABLE AND NOT THE OTHER ONE. There are two places an owner's
-- Confident Voice answer can land, and they are not interchangeable:
--
--   * `take_feedback_self_report` is the answer given to a CARD the Manager
--     exposed inside a Take review. Its write validates against that Take's
--     frozen feedback membership, so it can only ever record an answer to a
--     card that exists.
--   * `owner_voice_album_routing` is the answer given to a CLIP, with no card
--     in front of it. It is routing-only by construction and already the
--     Album's legacy USER leg.
--
-- "Practice new" asks about clips with no card — a card only exists once the
-- Take's review has been opened — so the answer belongs here. Minting cards
-- outside the review to reuse the other table would change what counts as
-- exposed for the Manager's budget (L2); this does not touch the Manager at
-- all.
--
-- WHAT CHANGES. Only the accepted vocabulary. The contract's five states
-- (§29) are stored WHOLE: in-between, not-sure and audio-unclear are distinct
-- self-reports, not softer ways of saying no, and collapsing them into
-- `neutral` on the way in would destroy the distinction the instrument exists
-- to capture.
--
-- `neutral` and `unrateable` stay ACCEPTED so historical rows remain valid —
-- they are audit-only and receive no new writes. Nothing is rewritten and no
-- row is dropped.
--
-- ADMISSION IS UNCHANGED. Only `yes` satisfies the Album's USER leg, exactly
-- as before; this migration cannot move any moment into or out of the Album.
-- The table stays excluded from training, quorum, calibration, evaluation,
-- SFT and DPO.

ALTER TABLE public.owner_voice_album_routing
    DROP CONSTRAINT IF EXISTS owner_voice_album_routing_response_check;

ALTER TABLE public.owner_voice_album_routing
    DROP CONSTRAINT IF EXISTS owner_voice_album_routing_response;

ALTER TABLE public.owner_voice_album_routing
    ADD CONSTRAINT owner_voice_album_routing_response CHECK (
        response IN (
            -- The five states the instrument asks for today.
            'yes', 'in_between', 'no', 'not_sure', 'audio_unclear',
            -- Legacy, audit-only: accepted so existing rows stay valid.
            'neutral', 'unrateable'
        )
    );

COMMENT ON COLUMN public.owner_voice_album_routing.response IS
    'Owner self-report on an exact clip, five states (SPEC §29). neutral and '
    'unrateable are legacy audit-only values that receive no new writes. Only '
    'yes satisfies the Voice Album USER leg. Excluded from training, quorum, '
    'calibration, evaluation, SFT and DPO.';

NOTIFY pgrst, 'reload schema';
