-- The owner's own note at the end of a Voice Album moment (founder
-- 2026-09-18: "at the bottom you have a one click where you can add your
-- note at the end of each confident voice").
--
-- PROVENANCE: this is the owner writing to themselves. It is not a rating,
-- not a routing signal, and not a label. Nothing in training, calibration,
-- quorum, evaluation, SFT, DPO or Voice Album admission reads this table —
-- a note can never move a moment into or out of the Album (L3).
--
-- `moment_key` is the Album's own moment identity as the read surface
-- serves it: a snippet id for a Take moment, or `practice:<attempt_id>`
-- for an admitted practice attempt. It is deliberately TEXT and carries no
-- foreign key, because the two kinds live in two different tables and the
-- Album is a mirror — a moment that stops aligning disappears from the read
-- while the note it carried stays owned by the user who wrote it.

CREATE TABLE IF NOT EXISTS public.voice_album_notes (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    arc_id        TEXT NOT NULL,
    moment_key    TEXT NOT NULL,
    owner_user_id UUID NOT NULL,
    body          TEXT NOT NULL CHECK (length(btrim(body)) BETWEEN 1 AND 2000),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE public.voice_album_notes ENABLE ROW LEVEL SECURITY;

CREATE INDEX IF NOT EXISTS idx_voice_album_notes_moment
    ON public.voice_album_notes (arc_id, moment_key, created_at);
CREATE INDEX IF NOT EXISTS idx_voice_album_notes_owner
    ON public.voice_album_notes (owner_user_id, created_at DESC);

COMMENT ON TABLE public.voice_album_notes IS
    'Owner-authored notes on a Voice Album moment. Personal recall only: excluded from training, quorum, calibration, evaluation, SFT, DPO and Album admission.';

GRANT ALL ON TABLE public.voice_album_notes TO service_role;

NOTIFY pgrst, 'reload schema';
