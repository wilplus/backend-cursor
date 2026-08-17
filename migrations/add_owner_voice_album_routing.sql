-- The owner's answer on a Confident Voice card is ROUTING, not a label.
--
-- The user has already seen the machine's recognition, so this response is
-- anchored by construction. It decides whether the moment is eligible for
-- the Voice Album's USER leg. No training, quorum, calibration, evaluation,
-- SFT or DPO reader consumes this table.

CREATE TABLE IF NOT EXISTS public.owner_voice_album_routing (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    snippet_id     UUID NOT NULL
                   REFERENCES public.snippets(id) ON DELETE CASCADE,
    owner_user_id  UUID NOT NULL,
    arc_id          TEXT NOT NULL,
    slide_index      INTEGER NULL,
    response        TEXT NOT NULL
                    CHECK (response IN ('yes', 'no', 'neutral', 'unrateable')),
    model_version   TEXT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_owner_voice_album_routing_snippet_owner
        UNIQUE (snippet_id, owner_user_id)
);

ALTER TABLE public.owner_voice_album_routing ENABLE ROW LEVEL SECURITY;

CREATE INDEX IF NOT EXISTS idx_owner_voice_album_routing_arc
    ON public.owner_voice_album_routing (arc_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_owner_voice_album_routing_owner
    ON public.owner_voice_album_routing (owner_user_id, updated_at DESC);

COMMENT ON TABLE public.owner_voice_album_routing IS
    'Routing-only owner response for the Voice Album. Excluded from training, quorum, calibration, evaluation, SFT and DPO.';

GRANT ALL ON TABLE public.owner_voice_album_routing TO service_role;
