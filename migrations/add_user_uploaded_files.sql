-- Tracks user-uploaded media files (audio + video) that land in
-- Cloudflare R2 via POST /v2/user/upload-media. Distinct from the
-- `recordings` table (which carries live-recorded session audio
-- and is tightly coupled to the recording-1 pipeline). This table
-- is the source of truth for the admin "Files" tab.
--
-- One row per upload — append-only. The admin reviews each file
-- like any other session artifact; deletes are out-of-scope for v1
-- (the row stays even if the R2 object is later purged, so the
-- audit trail of what the user uploaded is preserved).
--
-- Run in Supabase SQL Editor. Idempotent.

CREATE TABLE IF NOT EXISTS user_uploaded_files (
    id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Owner of the file. ON DELETE CASCADE so a user deletion
    -- garbage-collects their uploads without orphaning rows.
    user_id         UUID         NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,

    -- The session this file was uploaded against. NULL when the
    -- file was uploaded outside any session context (rare; the
    -- chat flow always associates with a session). ON DELETE SET
    -- NULL so deleting a session doesn't drop the file metadata.
    session_id      UUID         REFERENCES v2_sessions(id) ON DELETE SET NULL,

    -- Where the bytes live. We store bucket + key separately so
    -- the read path can re-build either a public URL (if the
    -- bucket is public) or a fresh signed URL (private bucket)
    -- without re-parsing a stored URL.
    r2_bucket       TEXT         NOT NULL,
    r2_key          TEXT         NOT NULL,

    -- Cached public URL when available — set at upload time only
    -- if R2_PUBLIC_BASE_URL is configured. NULL means "resolve at
    -- read time via signed URL". Reading this column directly is
    -- fine for public buckets, but the admin endpoint should
    -- always go through the resolve helper so private buckets
    -- still serve playable URLs.
    r2_url          TEXT         DEFAULT NULL,

    -- User-facing file name (the upload's original filename, not
    -- the R2 key). Shown in the admin Files-tab UI.
    file_name       TEXT         NOT NULL,

    -- High-level type. Either 'audio' or 'video' — the upload
    -- endpoint computes this from the content-type MIME prefix
    -- and rejects anything else.
    file_type       TEXT         NOT NULL
        CHECK (file_type IN ('audio', 'video')),

    -- Raw MIME so the admin player picks the right element/codec
    -- without re-sniffing the bytes.
    content_type    TEXT         DEFAULT NULL,

    -- Bytes count from the upload — used for analytics + a
    -- "too large to play inline" guard in the admin UI.
    file_size_bytes BIGINT       DEFAULT NULL,

    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Owner lookup pattern: "all files for user X, newest first" —
-- the admin /files endpoint's hot path. DESC index inline so the
-- planner doesn't have to reverse-scan.
CREATE INDEX IF NOT EXISTS idx_user_uploaded_files_user_created
    ON user_uploaded_files(user_id, created_at DESC);

-- Session-scoped lookup ("all files this user uploaded against
-- this session") — admin session-detail view uses this. Partial
-- index since most files might be unattached.
CREATE INDEX IF NOT EXISTS idx_user_uploaded_files_session
    ON user_uploaded_files(session_id, created_at DESC)
    WHERE session_id IS NOT NULL;

COMMENT ON TABLE user_uploaded_files IS
    'User-uploaded media files stored in Cloudflare R2. Backs the '
    'admin Files tab and any future user-side "your uploads" view.';

COMMENT ON COLUMN user_uploaded_files.r2_url IS
    'Cached public URL set at upload time when the bucket has '
    'R2_PUBLIC_BASE_URL configured. NULL means the read path '
    'should mint a signed URL on each request.';
