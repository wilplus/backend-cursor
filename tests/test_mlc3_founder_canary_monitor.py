from pathlib import Path

from services.mlc3_founder_canary_monitor import (
    REQUIRED_SIGNAL_CODES,
    assess_founder_canary_monitor,
)


ROOT = Path(__file__).resolve().parents[1]


def _health(**changes):
    value = {
        "contract_state": "disabled",
        "exact_active_allowlist_count": 0,
        "foreign_active_allowlist_count": 0,
        "authorization_or_deletion_violation_count": 0,
        "feedback_offer_or_practice_failure_count": 0,
        "blind_review_or_reveal_failure_count": 0,
        "coach_guidance_or_inline_authoring_failure_count": 0,
        "unresolved_practice_media_write_count": 0,
        "unresolved_coach_media_write_count": 0,
    }
    value.update(changes)
    return value


def test_disabled_pre_activation_monitor_is_healthy_at_exact_zero_state():
    report = assess_founder_canary_monitor(
        _health(), expected_contract_state="disabled",
    )
    assert report.healthy is True
    assert report.signal_codes == ()


def test_active_monitor_requires_exactly_one_founder_allowlist_row():
    report = assess_founder_canary_monitor(
        _health(contract_state="active", exact_active_allowlist_count=1),
        expected_contract_state="active",
    )
    assert report.healthy is True
    foreign = assess_founder_canary_monitor(
        _health(
            contract_state="active", exact_active_allowlist_count=1,
            foreign_active_allowlist_count=1,
        ),
        expected_contract_state="active",
    )
    assert foreign.signal_codes == (
        "service_contract_or_allowlist_violation",
    )


def test_every_required_operational_signal_fails_closed():
    fields = (
        "authorization_or_deletion_violation_count",
        "feedback_offer_or_practice_failure_count",
        "blind_review_or_reveal_failure_count",
        "coach_guidance_or_inline_authoring_failure_count",
        "unresolved_practice_media_write_count",
        "unresolved_coach_media_write_count",
    )
    observed = {"service_contract_or_allowlist_violation"}
    contract = assess_founder_canary_monitor(
        _health(contract_state="active"), expected_contract_state="disabled",
    )
    observed.update(contract.signal_codes)
    for field in fields:
        report = assess_founder_canary_monitor(
            _health(**{field: 1}), expected_contract_state="disabled",
        )
        assert report.healthy is False
        observed.update(report.signal_codes)
    assert observed == set(REQUIRED_SIGNAL_CODES)


def test_missing_or_non_numeric_aggregate_fails_closed():
    missing = _health()
    missing.pop("unresolved_practice_media_write_count")
    assert not assess_founder_canary_monitor(
        missing, expected_contract_state="disabled",
    ).healthy


def test_railway_monitor_is_recurring_aggregate_only_and_alerting():
    script = (ROOT / "scripts" / "monitor_mlc3_founder_canary.py").read_text()
    cron = (
        ROOT / "bin" / "railway-mlc3-founder-canary-monitor.sh"
    ).read_text()
    assert "*/5 * * * *" in cron
    assert "monitor_mlc3_founder_canary.py" in cron
    assert "sentry_sdk.capture_message" in script
    assert "exercise_practice_upload_recoveries" in script
    assert "coach_guidance_upload_permits" in script
    for forbidden in ("transcript_text", "exact_passage", "audio_bytes"):
        assert forbidden not in script
    assert not assess_founder_canary_monitor(
        _health(unresolved_coach_media_write_count=True),
        expected_contract_state="disabled",
    ).healthy
