-- 0414 · A guest that only accepted never displaces the account that has its
--        own acceptance (F1 Repair Plan Phase 0.5b, founder 2026-10-04:
--        "Merge now, backend rule next").
--
-- THE CASE. A first-time visitor is now minted a guest identity and shown the
-- Terms before anything else (Phase 0.5). Someone who accepts there and then
-- signs in to an account that already accepted on its own leaves one claim
-- event behind: guest -> account, the guest holding a receipt and having
-- acquired nothing.
--
-- `resolve_phase1_acquisition_principal_v1` (0355) prefers the newest claimed
-- source that holds a receipt. So from that sign-in on, every recording the
-- ACCOUNT makes resolves to the empty guest as its acquirer, and is processed
-- under the guest's acceptance instead of the account's own -- a receipt that
-- authorised nothing that guest ever recorded.
--
-- THE RULE. When the account principal holds its own receipt, a claimed
-- source that holds a receipt but acquired nothing (no
-- `processing_recording_attempts` row) is not a candidate. Everything else is
-- exactly 0355:
--
--   * a source that acquired something stays a candidate, receipt or not;
--   * a source with NO receipt stays a candidate (B-3: the guest who recorded
--     while the gate was off is still the acquirer of what it recorded);
--   * an account with no receipt of its own changes nothing;
--   * ordering is unchanged (receipt holders first, then newest claim).
--
-- Changes no rows. Idempotent.

BEGIN;

CREATE OR REPLACE FUNCTION public.resolve_phase1_acquisition_principal_v1(
    p_product_owner_principal_id UUID,
    p_user_id UUID DEFAULT NULL
) RETURNS UUID
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    resolved UUID;
    account_accepted BOOLEAN;
BEGIN
    IF p_product_owner_principal_id IS NULL THEN
        RAISE EXCEPTION 'PROCESSING_PRINCIPAL_UNRESOLVED';
    END IF;
    account_accepted := EXISTS (
        SELECT 1 FROM public.processing_authorization_receipts receipt
         WHERE receipt.acquisition_principal_id = p_product_owner_principal_id
    );
    -- B-3 (0355): receipt existence is a PREFERENCE, not a filter.
    -- 0414: an acceptance with nothing acquired under it never outranks the
    -- account's own acceptance.
    SELECT event.source_owner_principal_id INTO resolved
      FROM public.owner_claim_events event
     WHERE event.target_owner_principal_id = p_product_owner_principal_id
       AND (p_user_id IS NULL OR event.claimed_user_id = p_user_id)
       AND NOT (
           account_accepted
           AND EXISTS (
               SELECT 1 FROM public.processing_authorization_receipts receipt
                WHERE receipt.acquisition_principal_id =
                      event.source_owner_principal_id
           )
           AND NOT EXISTS (
               SELECT 1 FROM public.processing_recording_attempts attempt
                WHERE attempt.acquisition_principal_id =
                      event.source_owner_principal_id
           )
       )
     ORDER BY EXISTS (
           SELECT 1 FROM public.processing_authorization_receipts receipt
            WHERE receipt.acquisition_principal_id =
                  event.source_owner_principal_id
       ) DESC,
       event.claimed_at DESC, event.id DESC
     LIMIT 1;
    RETURN COALESCE(resolved, p_product_owner_principal_id);
END;
$$;

REVOKE ALL ON FUNCTION public.resolve_phase1_acquisition_principal_v1(UUID,UUID)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.resolve_phase1_acquisition_principal_v1(UUID,UUID)
    TO service_role;

COMMIT;
