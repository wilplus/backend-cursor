"""Founder-only production-data foundation canary boundary."""
from flask import Flask, request

import routes.v2.lab_recording as lab_recording


app = Flask(__name__)


FOUNDER_PRINCIPAL = "11111111-1111-4111-8111-111111111111"


def _decision(
    *, user_id: str | None, email: str | None,
    owner_principal_id: str | None = FOUNDER_PRINCIPAL,
) -> bool:
    with app.test_request_context():
        request.token_payload = {"email": email} if email else None
        return lab_recording._is_data_foundation_canary_owner(
            user_id, owner_principal_id,
        )


def test_founder_is_the_only_canonical_owner(monkeypatch):
    monkeypatch.setattr(
        lab_recording.config, "DATA_FOUNDATION_CANARY_ENABLED", True,
    )
    monkeypatch.setattr(
        lab_recording.config, "ADMIN_EMAIL", "artur@willonski.com",
    )
    monkeypatch.setattr(
        lab_recording.config, "MLC2_CONFIDENCE_CANARY_FOUNDER_EMAIL",
        "artur@willonski.com",
    )
    monkeypatch.setattr(
        lab_recording.config, "MLC2_CONFIDENCE_CANARY_PRINCIPAL_ID",
        FOUNDER_PRINCIPAL,
    )

    assert _decision(
        user_id="founder-id", email="ARTUR@WILLONSKI.COM",
    ) is True
    assert _decision(
        user_id="ordinary-id", email="student@example.com",
    ) is False
    assert _decision(user_id=None, email="artur@willonski.com") is False
    assert _decision(
        user_id="founder-id",
        email="artur@willonski.com",
        owner_principal_id="22222222-2222-4222-8222-222222222222",
    ) is False


def test_canary_fails_closed_without_exact_principal_or_approved_email(
    monkeypatch,
):
    monkeypatch.setattr(
        lab_recording.config, "DATA_FOUNDATION_CANARY_ENABLED", True,
    )
    monkeypatch.setattr(
        lab_recording.config, "ADMIN_EMAIL", "artur@willonski.com",
    )
    monkeypatch.setattr(
        lab_recording.config, "MLC2_CONFIDENCE_CANARY_FOUNDER_EMAIL",
        "artur@willonski.com",
    )
    monkeypatch.setattr(
        lab_recording.config, "MLC2_CONFIDENCE_CANARY_PRINCIPAL_ID", "",
    )
    assert _decision(
        user_id="founder-id", email="artur@willonski.com",
    ) is False

    monkeypatch.setattr(
        lab_recording.config, "MLC2_CONFIDENCE_CANARY_PRINCIPAL_ID",
        FOUNDER_PRINCIPAL,
    )
    monkeypatch.setattr(
        lab_recording.config, "ADMIN_EMAIL", "other@example.com",
    )
    assert _decision(
        user_id="founder-id", email="artur@willonski.com",
    ) is False


def test_canary_kill_switch_fails_closed(monkeypatch):
    monkeypatch.setattr(
        lab_recording.config, "DATA_FOUNDATION_CANARY_ENABLED", False,
    )
    monkeypatch.setattr(
        lab_recording.config, "ADMIN_EMAIL", "artur@willonski.com",
    )
    monkeypatch.setattr(
        lab_recording.config, "MLC2_CONFIDENCE_CANARY_FOUNDER_EMAIL",
        "artur@willonski.com",
    )
    monkeypatch.setattr(
        lab_recording.config, "MLC2_CONFIDENCE_CANARY_PRINCIPAL_ID",
        FOUNDER_PRINCIPAL,
    )

    assert _decision(
        user_id="founder-id", email="artur@willonski.com",
    ) is False
