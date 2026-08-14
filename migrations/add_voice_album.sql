-- THE VOICE ALBUM (founder re-lock 2026-08-13/14). The entry rule,
-- verbatim: "Acoustic data indicates a great moment -> User agrees ->
-- Coach agrees = This moment lands in the Voice Album." One row per
-- aligned snippet; a MIRROR of current alignment (founder ruling
-- 2026-08-14: a reverted approval REMOVES the entry — never a
-- graveyard of changed minds); NEVER a ranking term (the quorum bonus
-- died with _W_B). Capture only — the read surface ships separately
-- with founder-signed copy.
CREATE TABLE IF NOT EXISTS public.voice_album (
  arc_id          uuid        NOT NULL,
  snippet_id      text        NOT NULL,
  take_session_id text        NULL,
  slide_index     integer     NULL,
  entered_at      timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (arc_id, snippet_id)
);
COMMENT ON TABLE public.voice_album IS
  'Album entries: acoustic emphasize + user approved + coach strong (published). Mirror of current alignment (SPEC F2 / founder 2026-08-14).';

-- House rule (test_migration_security_rules): every new public table
-- enables RLS in its own migration. Access is service-role only (the
-- backend); no user-facing policies until the read surface ships with
-- founder-signed copy.
ALTER TABLE public.voice_album ENABLE ROW LEVEL SECURITY;
