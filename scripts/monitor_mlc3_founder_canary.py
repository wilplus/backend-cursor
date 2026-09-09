#!/usr/bin/env python3
"""Read-only aggregate monitor for the MLC-3 founder canary."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from config import Config  # noqa: E402
from migrate import CannotRun, connect  # noqa: E402
from services.mlc3_founder_canary_monitor import (  # noqa: E402
    assess_founder_canary_monitor,
)


def _aggregate_health(connection, principal_id: str) -> dict:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT jsonb_build_object(
              'contract_state', (
                SELECT state FROM public.mlc3_service_contracts
                 WHERE contract_version='mlc3-first-client-service-v1'),
              'exact_active_allowlist_count', (
                SELECT count(*) FROM public.mlc3_service_principal_allowlist
                 WHERE acquisition_principal_id=%s::uuid
                   AND contract_version='mlc3-first-client-service-v1'
                   AND state='active' AND revoked_at IS NULL),
              'foreign_active_allowlist_count', (
                SELECT count(*) FROM public.mlc3_service_principal_allowlist
                 WHERE acquisition_principal_id<>%s::uuid
                   AND contract_version='mlc3-first-client-service-v1'
                   AND state='active' AND revoked_at IS NULL),
              'authorization_or_deletion_violation_count', (
                SELECT (SELECT count(*) FROM public.processing_service_blocks
                         WHERE acquisition_principal_id=%s::uuid
                           AND effective_at<=clock_timestamp())
                     + (SELECT count(*) FROM public.data_purge_requests
                         WHERE acquisition_principal_id=%s::uuid
                           AND state<>'done')),
              'feedback_offer_or_practice_failure_count', (
                SELECT (SELECT count(*)
                          FROM public.exercise_practice_transcription_runs
                         WHERE acquisition_principal_id=%s::uuid
                           AND status IN ('uncertain','failed'))
                     + (SELECT count(*) FROM public.exercise_practice_attempts
                         WHERE acquisition_principal_id=%s::uuid
                           AND operation_mode='allowlisted_service'
                           AND state='quarantined')),
              'blind_review_or_reveal_failure_count', (
                SELECT count(*)
                  FROM public.exercise_service_blind_reveal_grants grant_row
                  JOIN public.exercise_service_blind_review_sets review_set
                    ON review_set.id=grant_row.review_set_id
                 WHERE grant_row.acquisition_principal_id=%s::uuid
                   AND (grant_row.source_judgment_id IS NULL
                        OR grant_row.practice_judgment_id IS NULL)),
              'coach_guidance_or_inline_authoring_failure_count', (
                SELECT count(*)
                  FROM public.coach_guidance_publication_invalidations
                 WHERE source_acquisition_principal_id=%s::uuid),
              'unresolved_practice_media_write_count', (
                SELECT count(*)
                  FROM public.exercise_practice_upload_recoveries
                 WHERE acquisition_principal_id=%s::uuid
                   AND operation_mode='allowlisted_service'
                   AND status NOT IN ('attached','deleted')
                   AND created_at<clock_timestamp()-interval '15 minutes'),
              'unresolved_coach_media_write_count', (
                SELECT count(*) FROM public.coach_guidance_upload_permits permit
                 WHERE permit.acquisition_principal_id=%s::uuid
                   AND permit.operation_mode='allowlisted_service'
                   AND permit.created_at<clock_timestamp()-interval '15 minutes'
                   AND NOT EXISTS (
                     SELECT 1 FROM public.coach_guidance_upload_events event
                      WHERE event.upload_permit_id=permit.id
                        AND event.event_kind IN ('finalized','abandoned')))
            )
            """,
            (principal_id,) * 10,
        )
        row = cursor.fetchone()
    return dict(row[0]) if row and isinstance(row[0], dict) else {}


def _notify_sentry(report: dict, *, rehearsal: bool) -> str | None:
    if not Config.SENTRY_DSN:
        return None
    try:
        import sentry_sdk

        sentry_sdk.init(dsn=Config.SENTRY_DSN, default_integrations=False)
        sentry_sdk.set_context("mlc3_founder_canary_monitor", report)
        event_id = sentry_sdk.capture_message(
            "MLC-3 founder canary monitor rehearsal"
            if rehearsal else "MLC-3 founder canary integrity blocked",
            level="warning" if rehearsal else "error",
        )
        sentry_sdk.flush(timeout=5)
        return str(event_id) if event_id else None
    except Exception:  # noqa: BLE001 - alert failure is itself a failed run
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--principal-id", required=True)
    parser.add_argument(
        "--expected-contract-state", choices=("disabled", "active"),
        required=True,
    )
    parser.add_argument("--rehearse-alert", action="store_true")
    args = parser.parse_args(argv)
    try:
        connection = connect()
    except CannotRun as error:
        print(json.dumps({"healthy": False, "detail": str(error)}))
        return 2
    try:
        health = _aggregate_health(connection, args.principal_id)
    finally:
        connection.close()
    report = assess_founder_canary_monitor(
        health, expected_contract_state=args.expected_contract_state,
    ).as_dict()
    event_id = None
    if args.rehearse_alert or not report["healthy"]:
        event_id = _notify_sentry(report, rehearsal=args.rehearse_alert)
        report["sentry_event_id"] = event_id
        if event_id is None:
            report["healthy"] = False
            report["signal_codes"].append("sentry_delivery_failed")
    print(json.dumps(report, sort_keys=True, default=str))
    return 0 if report["healthy"] and not args.rehearse_alert else (
        0 if args.rehearse_alert and event_id else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
