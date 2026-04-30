-- =============================================================================
-- Curiosity Gate funnel: anonymous-first acquisition flow
-- =============================================================================
-- Context:
--   Visitors record a 15s clip BEFORE signing up. The audio is stored against
--   a v2_sessions row whose user_id is NULL until the visitor authenticates and
--   "claims" the session via POST /v2/public/shaky-voice/claim. At that point
--   the row is bound to auth.uid() and the analysis pipeline is enqueued.
--
--   We deliberately do NOT run paid Whisper / OpenAI calls before the claim,
--   so an anonymous upload is cheap (storage + a row).
--
--   recording_origin = 'guest_funnel' tags these so:
--     * homework_completion can skip the credit charge on first analysis
--     * the admin Training Studio can filter / surface them distinctly
--     * the daily cleanup job can purge unclaimed rows >24h old
-- =============================================================================

BEGIN;

-- 1) Allow user_id to be NULL until claim. Existing FK / cascade semantics
--    remain in force for non-NULL rows.
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'v2_sessions'
      AND column_name = 'user_id'
      AND is_nullable = 'NO'
  ) THEN
    ALTER TABLE public.v2_sessions ALTER COLUMN user_id DROP NOT NULL;
  END IF;
END $$;

-- 2) Audit column: when did the guest session get bound to a real user?
ALTER TABLE public.v2_sessions
  ADD COLUMN IF NOT EXISTS guest_claimed_at TIMESTAMPTZ NULL;

COMMENT ON COLUMN public.v2_sessions.guest_claimed_at IS
  'Timestamp the anonymous "Curiosity Gate" session was claimed by an authenticated user. NULL for non-funnel rows and for unclaimed-and-pending guest rows.';

-- 3) Partial index for the daily cleanup job (delete unclaimed rows >24h old).
--    Keeping it partial avoids bloating the main user_id index for the 99% case.
CREATE INDEX IF NOT EXISTS idx_v2_sessions_unclaimed_guest
  ON public.v2_sessions (created_at)
  WHERE user_id IS NULL;

-- 4) Recording-origin tagging on the `recordings` table: existing column
--    accepts arbitrary strings; the new value 'guest_funnel' is recognized by
--    homework_completion (skip credit charge) and the admin Training Studio
--    (surface as funnel sessions). No DDL change required here.

-- PostgREST schema cache (Supabase)
NOTIFY pgrst, 'reload schema';

COMMIT;
