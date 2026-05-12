-- Phase 9 of the snippet-CTA learning loop: admin override of the inferred profile.
--
-- The inferred_learner_profile (Phase 3) is derived deterministically
-- from the user's last 10 coaching attempts. For some users that
-- aggregate is the wrong story — maybe the user had a rough week,
-- maybe a one-off snippet skewed the average. An admin watching the
-- coaching needs an escape hatch: "yes I see the data, but this
-- user is actually XYZ — coach them that way."
--
-- This column is that escape hatch. When set, the coaching system
-- prompt augmenter prefers this blob over the inferred one. When
-- unset (NULL), behaviour is unchanged from Phase 3.
--
-- Shape
-- -----
-- The override is read by the same format_profile_for_prompt path
-- as the inferred profile, so its top-level shape matches:
--
--   {
--     "version": "override-v1",
--     "set_by": "<admin_user_id>",
--     "set_at": "...",
--     "note": "Optional admin rationale shown in diagnostics",
--     "attempts_analyzed": 999,   # set high enough to pass the
--                                  # sample-size injection gate;
--                                  # admins know what they're doing
--     "traits": { ... }            # same trait schema as Phase 3
--   }
--
-- The admin sets only the traits they want to change; the augmenter
-- prefers override traits when present and falls back to inferred
-- ones field-by-field (handled in Python, not SQL).
--
-- Idempotent.

ALTER TABLE user_settings
    ADD COLUMN IF NOT EXISTS admin_profile_override JSONB,
    ADD COLUMN IF NOT EXISTS admin_profile_override_set_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS admin_profile_override_set_by UUID;

COMMENT ON COLUMN user_settings.admin_profile_override IS
    'Phase 9 — admin-set override for the inferred learner profile. '
    'When present, the coaching prompt augmenter prefers traits from '
    'this blob over the inferred profile. Same shape as '
    'inferred_learner_profile.traits; unset (NULL) is the default.';
COMMENT ON COLUMN user_settings.admin_profile_override_set_at IS
    'When the override was last set/edited. NULL while no override is in effect.';
COMMENT ON COLUMN user_settings.admin_profile_override_set_by IS
    'auth.users id of the admin who set the override. Used for audit + '
    'per-admin annotation-throughput counters.';
