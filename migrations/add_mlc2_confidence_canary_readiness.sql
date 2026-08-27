-- 0305 · MLC-2 Slice 6 founder-canary readiness evidence.
--
-- Aggregate-only, service-role-only monitoring.  This migration activates no
-- producer, worker, legacy cutover, dataset, training or promotion capability.

BEGIN;

CREATE OR REPLACE FUNCTION public.get_mlc2_confidence_canary_readiness_v1(
    p_founder_principal_id UUID DEFAULT NULL
) RETURNS JSONB
LANGUAGE sql
SECURITY DEFINER
STABLE
SET search_path = public
AS $$
SELECT jsonb_build_object(
    'readiness_contract_version', 'mlc2-confidence-canary-readiness-v1',
    'learning_contract_version', 'MLC-2',
    'data_epoch', 1,
    'learning_surface', 'confidence_classification',
    'founder_principal_configured', p_founder_principal_id IS NOT NULL,
    'active_consent_policy_count', (
        SELECT count(*) FROM ml_consent_policies policy
         WHERE policy.active_from <= now()
           AND (policy.retired_at IS NULL OR policy.retired_at > now())
    ),
    'valid_active_consent_policy_count', (
        SELECT count(*)
          FROM ml_consent_policies policy
          JOIN ml_product_legal_approvals approval
            ON approval.id = policy.product_legal_approval_id
         WHERE policy.active_from <= now()
           AND (policy.retired_at IS NULL OR policy.retired_at > now())
           AND policy.required_for_service
           AND policy.bundled_ui
           AND approval.consent_policy_version = policy.version
           AND approval.article_6_basis = '6(1)(a)'
           AND approval.article_9_treatment IN (
               'not_applicable', '9(2)(a)_when_special_category'
           )
           AND length(approval.approved_copy_sha256) = 64
           AND length(approval.evidence_sha256) = 64
           AND NULLIF(btrim(approval.approval_reference), '') IS NOT NULL
           AND NULLIF(btrim(approval.evidence_object_key), '') IS NOT NULL
    ),
    'founder_active_bundled_consent_grant_count', (
        SELECT count(*)
          FROM ml_consent_events consent_event
          JOIN ml_consent_policies policy
            ON policy.version = consent_event.consent_policy_version
         WHERE p_founder_principal_id IS NOT NULL
           AND consent_event.acquisition_principal_id = p_founder_principal_id
           AND consent_event.event_kind = 'grant'
           AND policy.active_from <= now()
           AND (policy.retired_at IS NULL OR policy.retired_at > now())
           AND NOT EXISTS (
               SELECT 1 FROM ml_consent_events withdrawal
                WHERE withdrawal.event_kind = 'withdraw'
                  AND withdrawal.supersedes_event_id = consent_event.id
                  AND withdrawal.occurred_at <= now()
           )
           AND (
               SELECT count(*) FROM ml_consent_event_purposes purpose
                WHERE purpose.consent_event_id = consent_event.id
                  AND purpose.purpose IN (
                      'personalized_coaching', 'pooled_model_improvement'
                  )
                  AND purpose.article_6_basis = '6(1)(a)'
           ) = 2
    ),
    'founder_producer_receipt_count', (
        SELECT count(*) FROM ml_confidence_producer_receipts receipt
         WHERE p_founder_principal_id IS NOT NULL
           AND receipt.acquisition_principal_id = p_founder_principal_id
    ),
    'nonfounder_producer_receipt_count', (
        SELECT count(*) FROM ml_confidence_producer_receipts receipt
         WHERE p_founder_principal_id IS NULL
            OR receipt.acquisition_principal_id <> p_founder_principal_id
    ),
    'nonfounder_canonical_event_count', (
        SELECT count(*) FROM ml_canonical_events event
         WHERE event.learning_surface_id = 'confidence_classification'
           AND (p_founder_principal_id IS NULL
                OR event.acquisition_principal_id <> p_founder_principal_id)
    ),
    'pending_confidence_outbox_count', (
        SELECT count(*) FROM ml_outbox_events event
         WHERE event.learning_surface_id = 'confidence_classification'
           AND event.event_type = 'confidence_take_ready'
           AND event.processed_at IS NULL
    ),
    'failed_confidence_outbox_count', (
        SELECT count(*) FROM ml_outbox_events event
         WHERE event.learning_surface_id = 'confidence_classification'
           AND event.event_type = 'confidence_take_ready'
           AND event.processed_at IS NULL
           AND event.last_error_code IS NOT NULL
    ),
    'oldest_pending_confidence_outbox_at', (
        SELECT min(event.created_at) FROM ml_outbox_events event
         WHERE event.learning_surface_id = 'confidence_classification'
           AND event.event_type = 'confidence_take_ready'
           AND event.processed_at IS NULL
    ),
    'receipt_without_outbox_count', (
        SELECT count(*) FROM ml_confidence_producer_receipts receipt
         WHERE NOT EXISTS (
             SELECT 1 FROM ml_outbox_events event
              WHERE event.id = receipt.outbox_event_id
         )
    ),
    'processed_without_frame_count', (
        SELECT count(*) FROM ml_confidence_producer_receipts receipt
        JOIN ml_outbox_events event ON event.id = receipt.outbox_event_id
         WHERE event.processed_at IS NOT NULL
           AND NOT EXISTS (
               SELECT 1 FROM ml_canonical_events canonical
               JOIN ml_candidate_sets candidate_set
                 ON candidate_set.canonical_event_id = canonical.id
                WHERE canonical.source_outbox_event_id = event.id
           )
    ),
    'blind_assignment_without_packet_count', (
        SELECT count(*) FROM ml_review_assignments assignment
         WHERE assignment.learning_surface_id = 'confidence_classification'
           AND NOT EXISTS (
               SELECT 1 FROM ml_confidence_blind_packets packet
                WHERE packet.review_assignment_id = assignment.id
           )
    ),
    'revealed_without_judgment_count', (
        SELECT count(*) FROM ml_review_assignment_events assignment_event
         WHERE assignment_event.event_kind = 'revealed'
           AND NOT EXISTS (
               SELECT 1 FROM ml_judgments judgment
                WHERE judgment.review_assignment_id =
                      assignment_event.review_assignment_id
           )
    ),
    'dataset_creation_enabled', false,
    'training_enabled', false,
    'promotion_enabled', false
);
$$;

REVOKE ALL ON FUNCTION public.get_mlc2_confidence_canary_readiness_v1(UUID)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.get_mlc2_confidence_canary_readiness_v1(UUID)
    TO service_role;

COMMENT ON FUNCTION public.get_mlc2_confidence_canary_readiness_v1(UUID) IS
    'Aggregate-only Slice 6 evidence; never activates the Confidence producer or exposes recording content.';

COMMIT;
