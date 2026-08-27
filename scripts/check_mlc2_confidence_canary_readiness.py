#!/usr/bin/env python3
"""Read-only production readiness check for the founder Confidence canary."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from config import Config  # noqa: E402
from migrate import CannotRun, connect  # noqa: E402
from services.mlc2_confidence_readiness import (  # noqa: E402
    assess_confidence_canary_readiness,
)


def _health(connection, founder_principal_id: str | None) -> dict:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT public.get_mlc2_confidence_canary_readiness_v1(%s::uuid)",
            (founder_principal_id or None,),
        )
        row = cursor.fetchone()
    payload = row[0] if row else None
    return dict(payload) if isinstance(payload, dict) else {}


def _notify_sentry(report: dict) -> None:
    if report.get("ready") or not Config.SENTRY_DSN:
        return
    try:
        import sentry_sdk

        sentry_sdk.init(dsn=Config.SENTRY_DSN, default_integrations=False)
        sentry_sdk.set_context("mlc2_confidence_canary_readiness", report)
        sentry_sdk.capture_message(
            "MLC-2 Confidence canary readiness blocked",
            level="error",
        )
        sentry_sdk.flush(timeout=5)
    except Exception:
        # Monitoring must report its own failure through exit status/stdout;
        # an alert transport outage may not change product behavior.
        pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--alert", action="store_true")
    args = parser.parse_args(argv)

    try:
        connection = connect()
    except CannotRun as error:
        result = {
            "ready": False,
            "blocker_codes": ["production_database_unavailable"],
            "detail": str(error),
        }
        print(json.dumps(result, sort_keys=True))
        return 2

    try:
        health = _health(
            connection,
            Config.MLC2_CONFIDENCE_CANARY_PRINCIPAL_ID or None,
        )
    finally:
        connection.close()

    report = assess_confidence_canary_readiness(
        health,
        cutover_mode=Config.MLC2_CONFIDENCE_CUTOVER_MODE,
        configured_founder_email=(
            Config.MLC2_CONFIDENCE_CANARY_FOUNDER_EMAIL
        ),
        founder_principal_id=Config.MLC2_CONFIDENCE_CANARY_PRINCIPAL_ID,
        data_foundation_canary_enabled=(
            Config.DATA_FOUNDATION_CANARY_ENABLED
        ),
        monitoring_enabled=Config.MLC2_CONFIDENCE_MONITORING_ENABLED,
        alert_sink_configured=bool(Config.SENTRY_DSN),
        dataset_creation_enabled=Config.MLC2_DATASET_RELEASES_ENABLED,
        training_enabled=Config.MLC2_TRAINING_ENABLED,
        promotion_enabled=Config.MLC2_PROMOTION_ENABLED,
    ).as_dict()
    if args.alert:
        _notify_sentry(report)
    if args.json:
        print(json.dumps(report, sort_keys=True, default=str))
    else:
        status = "READY" if report["ready"] else "BLOCKED"
        print(f"MLC-2 Confidence founder canary: {status}")
        for blocker in report["blocker_codes"]:
            print(f"  BLOCKER {blocker}")
        for warning in report["warning_codes"]:
            print(f"  WARNING {warning}")
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
