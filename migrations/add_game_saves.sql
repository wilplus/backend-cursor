-- willab — Engine 5, daily-practice repository (founder 2026-07-11,
-- backlog 3.3). Saving a game session stores it under its date; the Game
-- tab lists these as the user's key-moments archive. Rounds are
-- re-derived from coach truth on open (never frozen here) — one row is
-- just the (user, arc, date) bookmark.
--
-- Service-role only (RLS on, no policy); routes owner-gate by user_id.
-- Idempotent — safe to re-run.

CREATE TABLE IF NOT EXISTS game_saves (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL,
    arc_id      UUID NOT NULL,
    saved_date  DATE NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, arc_id, saved_date)
);

CREATE INDEX IF NOT EXISTS idx_game_saves_user
    ON game_saves (user_id, saved_date DESC);

ALTER TABLE game_saves ENABLE ROW LEVEL SECURITY;

-- Rollback (manual):
--   DROP TABLE IF EXISTS game_saves;
