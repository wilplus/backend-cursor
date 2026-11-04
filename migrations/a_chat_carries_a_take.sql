-- a_chat_carries_a_take (a Take sent to the people you tick, each as your own
-- message in your chat with them; founder, the Claude Code chat, 4 November
-- 2026, N470 and N479)
--
-- A Take sent from "Record Take N" (or added to from the line under its
-- recording) is one message per chosen person, in the sender's chat with
-- them: a message of its own kind, 'take', which points at the sender's own
-- Take (its meta names it) and carries no bytes of its own; the receiver
-- plays the Take's recording through the backend, after it checks that they
-- are a member of that chat (services/take_sends.py).
--
--   chat_messages.kind   Holds 'take' besides 'emoji', 'text', 'voice',
--                        'photo' and 'file'. The CHECK is swapped, DROP
--                        CONSTRAINT IF EXISTS then ADD CONSTRAINT under the
--                        same name, as a_chat_keeps_its_photos_and_files
--                        (0506) widened it. Every existing row satisfies the
--                        wider CHECK.
--
-- Read and written by the backend (service role) only, as before; no grant
-- changes. No environment variable needed by the migration itself (the code
-- that writes 'take' rows waits for TAKE_SEND_ENABLED, default off).
--
-- Idempotent: the CHECK is swapped by DROP CONSTRAINT IF EXISTS then ADD
-- CONSTRAINT; applied twice it changes nothing. Nothing is dropped but that
-- one CHECK, replaced in the same transaction by a wider one; no row is
-- written, rewritten or removed; no table, column or index is touched. Locks:
-- chat_messages briefly ACCESS EXCLUSIVE for the swap and one validating
-- scan (the chats' messages, a small table). One transaction.
--
-- Rollback (a new forward migration): narrow the CHECK back to the five
-- kinds (refused while a 'take' message exists, which is the point).

BEGIN;

ALTER TABLE public.chat_messages
    DROP CONSTRAINT IF EXISTS chat_messages_kind_check;
ALTER TABLE public.chat_messages
    ADD CONSTRAINT chat_messages_kind_check
    CHECK (kind IN ('emoji', 'text', 'voice', 'photo', 'file', 'take'));

COMMIT;
