-- 0455 · A failed export voids its release (door 2, ML-9; the revocation
--        promise of ML-8: every copy that left can be voided and swept).
--
-- THE GAP. services/pair_release.py::export_surface wrote the week's
-- pairs.jsonl and manifest.json to the release bucket, then the
-- pair_releases row and its pair_release_owners rows, and only then marked
-- the pairs released (mark_feedback_pairs_released_v1, 0405). The mark
-- refuses the whole set when one pair stopped being releasable in between
-- (a withdrawal, an account or project deletion request):
-- PAIR_RELEASE_PAIRS_NOT_RELEASABLE. The release row then stood LIVE, its
-- file holding those pairs, and no pair pointed at it. The weekly refresh
-- (refresh_feedback_pair_consent_v1, latest 0422) voids only a release that
-- a pair no longer releasable points at, so nothing but an account erasure
-- (through pair_release_owners) could ever void it, and the sweep never
-- deleted its file.
--
-- WHAT THIS DOES. One narrow function, which the export calls when anything
-- after its release row fails: void_failed_pair_release_v1(release) voids
-- that one release with a reason of its own, 'export_failed', apart from
-- the refresh's 'consent_withdrawn' and 'owner_service_ended', and sends
-- every pair that points at it back to waiting, exactly as the refresh does
-- for a voided release (release_id and exported_at cleared: a mark that
-- committed before the failure was seen). The weekly sweep (sweep_voided)
-- then deletes the file and its manifest. A release that another path
-- voided first keeps its reason and its time. Returns whether this call
-- voided it; an unknown release is named (PAIR_RELEASE_UNKNOWN, as 0405's
-- mark names it).
--
-- The code that calls it ships in the same change. The export now writes
-- the release row and its owners BEFORE any object, so the week's one row
-- (UNIQUE (surface, week_start), 0405) is taken before anything is put: a
-- second fire in the same ISO week (services/learning_weekly.py allows
-- one) is refused before it writes, instead of overwriting the standing
-- release's objects so that its manifest and sha256 no longer match them.
--
-- L3: the consent ledger is neither read nor written, and no pair's consent
-- state or releasability changes; only a copy is voided. AC-9: nothing here
-- reaches a speaker or a coach.
--
-- ADDITIVE AND IDEMPOTENT. One CREATE OR REPLACE FUNCTION, its grants and
-- its comment. No table, column, constraint or row is created, dropped or
-- deleted (pair_releases.voided_reason is free text, 0405). Nothing is
-- voided by applying this file. No environment variable is read, so no
-- Railway service needs configuration first.

BEGIN;

-- The one release the failed export wrote is voided ('export_failed'), and
-- every pair pointing at it goes back to waiting, as the refresh sends back
-- a voided release's pairs (0405). A release already voided keeps its own
-- reason and time. True when this call voided it.
CREATE OR REPLACE FUNCTION public.void_failed_pair_release_v1(
    p_release_id UUID
) RETURNS BOOLEAN
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    v_voided BOOLEAN;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM public.pair_releases WHERE id = p_release_id) THEN
        RAISE EXCEPTION 'PAIR_RELEASE_UNKNOWN';
    END IF;
    UPDATE public.pair_releases release
       SET voided_at = now(), voided_reason = 'export_failed'
     WHERE release.id = p_release_id
       AND release.voided_at IS NULL;
    v_voided := FOUND;

    UPDATE public.feedback_pairs pair
       SET release_id = NULL, exported_at = NULL
     WHERE pair.release_id = p_release_id;
    RETURN v_voided;
END;
$$;
REVOKE ALL ON FUNCTION public.void_failed_pair_release_v1(UUID)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.void_failed_pair_release_v1(UUID)
    TO service_role;

COMMENT ON FUNCTION public.void_failed_pair_release_v1(UUID) IS
    '0455: voids the one release a failed door 2 export wrote '
    '(voided_reason export_failed) and sends its pairs back to waiting; '
    'the weekly sweep deletes its objects. A release already voided keeps '
    'its reason. True when this call voided it.';

COMMIT;
