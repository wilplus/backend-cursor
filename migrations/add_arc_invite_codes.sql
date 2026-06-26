-- willab — Paid Audits, founding free-pass codes (BE chunk A4).
--
-- Invite codes that grant a 'founding_pass' arc_purchase (kind='founding_pass',
-- source='invite_code') without payment — existing/early users' free audit.
-- Redeemed via POST /v2/arc/<arc_id>/redeem {code}: an active code with
-- uses < max_uses mints a purchase for the arc and increments uses.
--
-- Idempotent; safe to re-run.
CREATE TABLE IF NOT EXISTS arc_invite_codes (
    code        TEXT PRIMARY KEY,
    max_uses    INTEGER NOT NULL DEFAULT 1,
    uses        INTEGER NOT NULL DEFAULT 0,
    active      BOOLEAN NOT NULL DEFAULT TRUE,
    note        TEXT,                                  -- optional human label
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Rollback (manual):
--   DROP TABLE IF EXISTS arc_invite_codes;
