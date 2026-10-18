-- a_green_moment_says_why (0476)
--
-- WHY. A green moment told the speaker that it landed but not why
-- (founder 2026-10-18, in a Claude Code session: "on that screen we need
-- to explain why it was a good take; every confident moment should have
-- something like this"; prototype https://claude.ai/artifact/Wdaznuffm9SJEkkjPEuSaR
-- version 4, approved "ok; dev it"). GPT now writes, once per green clip,
-- up to three short paragraphs from that clip's own evidence: what the
-- speaker said, the voice cues against their own usual, and the word
-- signals (services/praise_reason.py).
--
-- WHAT. One new table, one row per clip and reason version. `paragraphs`
-- is the text the walk shows; an EMPTY array means GPT was asked and its
-- reply failed the checks, so the walk shows the signed cue lines instead
-- and nobody asks again for that version. `quote` is the speaker's own
-- words the reason quotes, drawn in orange. No score, number or read is
-- stored here (AC-9): only words.
--
-- DELETION. The speaker's words about their own Take: the row goes with
-- the Take (services/data_purge_registry.py, `green_moment_reasons`).
--
-- Idempotent and additive: nothing is dropped or altered. Needs no
-- environment variable. Safe to run before the app that writes it.

CREATE TABLE IF NOT EXISTS public.green_moment_reasons (
    snippet_id       TEXT        NOT NULL CHECK (length(snippet_id) > 0),
    take_session_id  TEXT        NOT NULL CHECK (length(take_session_id) > 0),
    reason_version   TEXT        NOT NULL CHECK (length(reason_version) > 0),
    paragraphs       JSONB       NOT NULL
        CHECK (jsonb_typeof(paragraphs) = 'array'
               AND jsonb_array_length(paragraphs) <= 3),
    quote            TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (snippet_id, reason_version)
);

CREATE INDEX IF NOT EXISTS green_moment_reasons_take_idx
    ON public.green_moment_reasons (take_session_id);

ALTER TABLE public.green_moment_reasons ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.green_moment_reasons FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.green_moment_reasons TO service_role;

COMMENT ON TABLE public.green_moment_reasons IS
    'Why a green moment landed, in words, one row per clip and version (0476).';
