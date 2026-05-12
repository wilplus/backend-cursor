-- Phase 12: admin user-level context fields.
--
-- The admin user view (/admin/users/<id>) ships three editable
-- cards: Private Admin Notes, Global LLM Instructions, Learning
-- Profile. The Instructions field already exists
-- (user_settings.custom_llm_instructions). This migration adds the
-- other two pieces of state:
--
--   private_admin_notes        — internal notes the admin keeps
--                                about the user. Never shown to
--                                the user themselves.
--   queued_override_question   — a specific question the admin
--                                wants the AI to ask in the user's
--                                next contextual /chat. Persists
--                                until consumed (one-shot), then
--                                cleared by the chat flow.
--
-- Both are nullable text on user_settings — no new table — so the
-- existing upsert + get pattern handles them with no plumbing
-- changes beyond column awareness.
--
-- Idempotent.

ALTER TABLE user_settings
    ADD COLUMN IF NOT EXISTS private_admin_notes TEXT,
    ADD COLUMN IF NOT EXISTS queued_override_question TEXT;

COMMENT ON COLUMN user_settings.private_admin_notes IS
    'Phase 12 — admin-only notes about the user. Internal context, '
    'never surfaced to the user. Edited from the Private Admin Notes '
    'card on the admin user view.';
COMMENT ON COLUMN user_settings.queued_override_question IS
    'Phase 12 — one-shot question the admin queued for the AI to ask '
    'next in this user''s contextual chat. Consumed (cleared) by the '
    'chat flow once asked. NULL means no override pending.';

NOTIFY pgrst, 'reload schema';
