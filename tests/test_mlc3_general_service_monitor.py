from __future__ import annotations

from datetime import UTC, datetime, timedelta

from services.mlc3_general_service_monitor import (
    MONITOR_CONTRACT_VERSION,
    assess_general_service_monitor,
)


def _health() -> dict:
    return {
        "monitor_contract_version": MONITOR_CONTRACT_VERSION,
        "rollout_state": "disabled",
        "active_service_rows_without_enrollment": 0,
        "dataset_eligible_rows": 0,
        "active_uploads": 0,
        "maximum_active_uploads_per_principal": 0,
        "outstanding_required_coach_assignments": 0,
        "maximum_outstanding_assignments_per_coach": 0,
        "media_bytes_last_24_hours": 0,
        "unresolved_practice_recoveries": 0,
        "unresolved_coach_recoveries": 0,
        "oldest_unresolved_recovery_at": None,
        "oldest_required_coach_assignment_at": None,
        "service_failure_count": 0,
        "confident_moment_delivery_scanner": {
            "unfinished_over_5s_count": 0,
            "unfinished_set_sha256": None,
            "oldest_started_at": None,
            "skipped_contention_60s_count": 0,
            "hard_stop": False,
        },
        "capacity_policy": {
            "max_concurrent_uploads": 10,
            "max_uploads_per_principal": 2,
            "max_outstanding_assignments": 500,
            "max_assignments_per_coach": 100,
            "max_queue_age_hours": 72,
            "max_media_bytes_per_day": 10 * 1024**3,
            "max_unresolved_recoveries": 25,
            "max_recovery_age_minutes": 15,
        },
    }


def test_disabled_monitor_is_green_only_when_all_gates_are_off():
    report = assess_general_service_monitor(
        _health(), expected_rollout_state="disabled",
        backend_user_gate=False, backend_coach_gate=False,
        frontend_user_gate=False, frontend_coach_gate=False,
    )
    assert report.healthy
    changed = assess_general_service_monitor(
        _health(), expected_rollout_state="disabled",
        backend_user_gate=True, backend_coach_gate=False,
        frontend_user_gate=False, frontend_coach_gate=False,
    )
    assert changed.hard_stop
    assert "deployment_gate_mismatch" in changed.signal_codes


def test_cross_boundary_or_dataset_rows_are_hard_stops():
    value = _health()
    value["active_service_rows_without_enrollment"] = 1
    value["dataset_eligible_rows"] = 1
    report = assess_general_service_monitor(
        value, expected_rollout_state="disabled",
        backend_user_gate=False, backend_coach_gate=False,
        frontend_user_gate=False, frontend_coach_gate=False,
    )
    assert report.hard_stop
    assert "enrollment_lineage_violation" in report.signal_codes
    assert "dataset_boundary_violation" in report.signal_codes


def test_recovery_age_hard_stops_while_queue_age_backpressures():
    now = datetime.now(UTC)
    value = _health()
    value["oldest_unresolved_recovery_at"] = now - timedelta(minutes=16)
    value["oldest_required_coach_assignment_at"] = now - timedelta(hours=73)
    report = assess_general_service_monitor(
        value, expected_rollout_state="disabled",
        backend_user_gate=False, backend_coach_gate=False,
        frontend_user_gate=False, frontend_coach_gate=False, now=now,
    )
    assert report.hard_stop
    assert "stale_recovery_blocked" in report.signal_codes
    assert "coach_queue_backpressure" in report.signal_codes


def test_capacity_thresholds_do_not_become_quality_signals():
    value = _health()
    value["active_uploads"] = 11
    report = assess_general_service_monitor(
        value, expected_rollout_state="disabled",
        backend_user_gate=False, backend_coach_gate=False,
        frontend_user_gate=False, frontend_coach_gate=False,
    )
    assert not report.healthy
    assert not report.hard_stop
    assert report.signal_codes == ("upload_capacity_reached",)
