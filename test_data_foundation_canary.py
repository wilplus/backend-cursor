"""Founder-only production-data foundation canary boundary."""
from flask import Flask, request

import routes.v2.lab_recording as lab_recording


app = Flask(__name__)


def _decision(*, user_id: str | None, email: str | None) -> bool:
    with app.test_request_context():
        request.token_payload = {"email": email} if email else None
        return lab_recording._is_data_foundation_canary_owner(user_id)


def test_founder_is_the_only_canonical_owner(monkeypatch):
    monkeypatch.setattr(
        lab_recording.config, "DATA_FOUNDATION_CANARY_ENABLED", True,
    )
    monkeypatch.setattr(
        lab_recording.config, "ADMIN_EMAIL", "artur@willonski.com",
    )

    assert _decision(
        user_id="founder-id", email="ARTUR@WILLONSKI.COM",
    ) is True
    assert _decision(
        user_id="ordinary-id", email="student@example.com",
    ) is False
    assert _decision(user_id=None, email="artur@willonski.com") is False


def test_canary_kill_switch_fails_closed(monkeypatch):
    monkeypatch.setattr(
        lab_recording.config, "DATA_FOUNDATION_CANARY_ENABLED", False,
    )
    monkeypatch.setattr(
        lab_recording.config, "ADMIN_EMAIL", "artur@willonski.com",
    )

    assert _decision(
        user_id="founder-id", email="artur@willonski.com",
    ) is False
