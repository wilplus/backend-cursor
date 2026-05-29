-- Migration: user_uploaded_files.deleted_at
--
-- Adds a soft-delete column for the admin Tab 4 (Files) DELETE
-- endpoint shipped alongside Task 9. NULL = live, non-NULL =
-- soft-deleted (timestamp of the delete).
--
-- Why soft-delete instead of DROP ROW:
--   - GDPR Art. 17 (right-to-erasure) still requires the bytes to
--     leave R2, but a row-level audit trail of when admin clicked
--     "Delete" is useful for ops review. A weekly hard-delete cron
--     does the R2 + row cleanup; until then the row sits with
--     deleted_at set, hidden from the admin Files list.
--   - Lets us recover from accidental clicks during the soft-
--     delete window without a backup restore.
--   - Foreign-key references from other tables (charisma_snippets,
--     recordings) stay intact during the gap — hard deletes would
--     cascade or break those.
--
-- The admin Files GET endpoint and every other consumer filters
-- on deleted_at IS NULL; soft-deleted rows are invisible to the
-- API surface until the cron actually purges them.
--
-- Idempotent.

ALTER TABLE user_uploaded_files
    ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;

-- Index for the "find soft-deleted rows older than N days" query
-- the cleanup cron runs. Partial index keeps it tiny — only
-- soft-deleted rows are indexed, which is a small fraction of
-- the table in steady state.
CREATE INDEX IF NOT EXISTS idx_user_uploaded_files_deleted_at
    ON user_uploaded_files (deleted_at)
    WHERE deleted_at IS NOT NULL;

COMMENT ON COLUMN user_uploaded_files.deleted_at IS
    'Soft-delete timestamp. NULL = live, non-NULL = scheduled '
    'for hard-delete by the weekly purge cron. The API surface '
    '(/v2/admin/users/<id>/files GET) filters these out so the '
    'admin never sees soft-deleted files in the list. Recovery '
    'window is until the next cron run.';

NOTIFY pgrst, 'reload schema';
