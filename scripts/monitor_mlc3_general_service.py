#!/usr/bin/env python3
"""Aggregate monitor for D4; it cannot activate or broaden a rollout."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import Config  # noqa: E402
from migrate import CannotRun, connect  # noqa: E402
from services.mlc3_general_service_monitor import (  # noqa: E402
    assess_general_service_monitor,
)


def _enabled(name: str) -> bool:
    return (os.getenv(name) or "0").strip().lower() in {"1", "true", "yes", "on"}


def _health(connection) -> dict:
    with connection.cursor() as cursor:
        cursor.execute("SELECT public.get_mlc3_general_service_monitor_v1()")
        row = cursor.fetchone()
    return dict(row[0]) if row and isinstance(row[0], dict) else {}


def _notify_sentry(report: dict) -> str | None:
    if not Config.SENTRY_DSN:
        return None
    try:
        import sentry_sdk

        sentry_sdk.init(dsn=Config.SENTRY_DSN, default_integrations=False)
        sentry_sdk.set_context("mlc3_general_service_monitor", report)
        event_id = sentry_sdk.capture_message(
            "MLC-3 general service monitor blocked", level="error"
        )
        sentry_sdk.flush(timeout=5)
        return str(event_id) if event_id else None
    except Exception:  # noqa: BLE001 - alert failure must fail the run
        return None


def _halt(connection, report: dict) -> bool:
    evidence = hashlib.sha256(
        json.dumps(report, sort_keys=True, default=str).encode()
    ).hexdigest()
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT (public.halt_mlc3_service_rollout_v1(%s,%s)).id",
            ("automatic_integrity_stop", evidence),
        )
        return cursor.fetchone() is not None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--expected-rollout-state",
        required=True,
        choices=("disabled", "explicit_cohort", "generally_available", "halted"),
    )
    parser.add_argument("--halt-on-hard-stop", action="store_true")
    args = parser.parse_args(argv)
    try:
        connection = connect()
    except CannotRun as error:
        print(json.dumps({"healthy": False, "detail": str(error)}))
        return 2
    try:
        health = _health(connection)
        report = assess_general_service_monitor(
            health,
            expected_rollout_state=args.expected_rollout_state,
            backend_user_gate=bool(Config.MLC3_SERVICE_ENABLED),
            backend_coach_gate=bool(Config.MLC3_COACH_INLINE_AUTHORING_ENABLED),
            frontend_user_gate=_enabled("NEXT_PUBLIC_MLC3_SERVICE_UI_ENABLED"),
            frontend_coach_gate=_enabled(
                "NEXT_PUBLIC_MLC3_COACH_INLINE_AUTHORING_ENABLED"
            ),
        ).as_dict()
        if report["hard_stop"] and args.halt_on_hard_stop:
            report["halted"] = _halt(connection, report)
            connection.commit()
        if not report["healthy"]:
            report["sentry_event_id"] = _notify_sentry(report)
            if report["sentry_event_id"] is None:
                report["signal_codes"].append("sentry_delivery_failed")
    finally:
        connection.close()
    print(json.dumps(report, sort_keys=True, default=str))
    return 0 if report["healthy"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
