-- Fix: Allow NULL user_id on charisma_snippets
-- During the multi-turn interview flow, snippets are created before the guest
-- signs up (no real user_id yet). The FK to auth.users rejects a placeholder
-- UUID that doesn't exist, causing all per-turn snippet inserts to fail silently.
--
-- Solution: make user_id nullable. On claim, update_snippets_user_id() already
-- handles NULL → real user_id migration.

-- 1. Drop the NOT NULL constraint
ALTER TABLE charisma_snippets ALTER COLUMN user_id DROP NOT NULL;

-- 2. Drop the FK constraint to auth.users (the column name might vary)
-- We re-add it as ON DELETE SET NULL instead of ON DELETE CASCADE
-- so unclaimed snippets aren't accidentally deleted.
DO $$
DECLARE
  fk_name TEXT;
BEGIN
  SELECT conname INTO fk_name
    FROM pg_constraint
   WHERE conrelid = 'charisma_snippets'::regclass
     AND contype = 'f'
     AND EXISTS (
       SELECT 1 FROM unnest(conkey) k
       JOIN pg_attribute a ON a.attrelid = conrelid AND a.attnum = k
       WHERE a.attname = 'user_id'
     )
   LIMIT 1;

  IF fk_name IS NOT NULL THEN
    EXECUTE format('ALTER TABLE charisma_snippets DROP CONSTRAINT %I', fk_name);
  END IF;
END
$$;

-- Re-add FK with ON DELETE SET NULL (allows NULL + gentler cleanup)
ALTER TABLE charisma_snippets
  ADD CONSTRAINT charisma_snippets_user_id_fkey
  FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE SET NULL;
