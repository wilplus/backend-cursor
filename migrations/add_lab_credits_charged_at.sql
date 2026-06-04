-- willab beta — per-session credit-charge flag (B = "willab uses credits").
--
-- willab Lab sessions cost credits (5, matching the legacy session cost),
-- deducted SOFTLY (floor 0, never hard-blocks) when the coach PUBLISHES
-- insights — mirroring the old homework completion-charge, but keyed on a
-- willab-specific flag so the two never collide.
--
-- This timestamp IS the idempotency guard: v2_charge_lab_credits_once sets
-- it only when NULL (so a re-publish never double-charges), then deducts;
-- on deduct failure it clears the flag so a retry can succeed.
--
-- Idempotent migration (safe to re-run). NOTE: v2_sessions has no plain
-- `updated_at` column — do not add one here.

ALTER TABLE v2_sessions
    ADD COLUMN IF NOT EXISTS lab_credits_charged_at TIMESTAMPTZ DEFAULT NULL;

COMMENT ON COLUMN v2_sessions.lab_credits_charged_at IS
    'willab: when the Lab session credit charge was applied at publish '
    '(idempotency guard for v2_charge_lab_credits_once). NULL = not yet charged.';
