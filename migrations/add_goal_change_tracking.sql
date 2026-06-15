-- Goal-change tracking (willab Prompt A §6 C4 follow-up).
--
-- When a user updates their coaching goal from the chat ("change my goal
-- to X"), the coach needs to see BOTH what the goal is now AND what it was
-- before — without that, the overwrite silently loses the prior goal. We
-- keep the LAST change (old value + when) alongside the live goal:
--
--   profile_goal            TEXT         — the CURRENT/new goal (existing).
--   profile_goal_previous   TEXT         — the value before the last change
--                                          (NULL until the goal is changed).
--   profile_goal_changed_at TIMESTAMPTZ  — when the goal last changed.
--
-- One level of history (last change) is what the coach surface needs:
-- "goal: NEW (changed from PREVIOUS on DATE)". Idempotent; safe to re-run.
ALTER TABLE user_settings
    ADD COLUMN IF NOT EXISTS profile_goal_previous TEXT,
    ADD COLUMN IF NOT EXISTS profile_goal_changed_at TIMESTAMPTZ;
