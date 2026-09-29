"""Whose Takes get a canonical Recording Attempt row: the canonical_take_rows
ring row (rings, 0393), which replaced the data-foundation canary's three
doors (a Railway switch, the founder email, the principal variable)."""
from flask import Flask, request

import routes.v2.lab_recording as lab_recording
from services import rings


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


def test_the_ring_row_decides_who_gets_a_canonical_row(monkeypatch):
    asked: list[tuple[str, str]] = []

    def feature_is_on(feature, principal_id, **_):
        asked.append((feature, principal_id))
        return principal_id == FOUNDER_PRINCIPAL

    monkeypatch.setattr(rings, "feature_is_on", feature_is_on)
    assert _decision(user_id="founder-id", email="ARTUR@WILLONSKI.COM") is True
    assert _decision(
        user_id="ordinary-id", email="student@example.com",
        owner_principal_id="22222222-2222-4222-8222-222222222222",
    ) is False
    assert asked and all(f == rings.CANONICAL_TAKE_ROWS for f, _ in asked)


def test_no_user_or_no_principal_gets_no_canonical_row(monkeypatch):
    monkeypatch.setattr(rings, "feature_is_on", lambda *a, **k: True)
    assert _decision(user_id=None, email="artur@willonski.com") is False
    assert _decision(user_id="founder-id", email="artur@willonski.com",
                     owner_principal_id=None) is False


def test_the_retired_variables_no_longer_decide(monkeypatch):
    """The kill switch is the row's kill and the "who" is the ring; the
    three canary variables are readable for one release and read by
    nothing here."""
    monkeypatch.setattr(rings, "feature_is_on", lambda *a, **k: True)
    monkeypatch.setattr(
        lab_recording.config, "DATA_FOUNDATION_CANARY_ENABLED", False,
    )
    monkeypatch.setattr(lab_recording.config, "ADMIN_EMAIL", "other@example.com")
    monkeypatch.setattr(
        lab_recording.config, "MLC2_CONFIDENCE_CANARY_PRINCIPAL_ID", "",
    )
    assert _decision(user_id="founder-id", email="student@example.com") is True

    monkeypatch.setattr(rings, "feature_is_on", lambda *a, **k: False)
    monkeypatch.setattr(
        lab_recording.config, "DATA_FOUNDATION_CANARY_ENABLED", True,
    )
    assert _decision(user_id="founder-id", email="artur@willonski.com") is False


def test_an_unreachable_ring_table_is_a_closed_door(monkeypatch):
    def unavailable(*_a, **_k):
        raise RuntimeError("db down")

    monkeypatch.setattr(rings, "_rpc", unavailable)
    assert _decision(user_id="founder-id", email="artur@willonski.com") is False
