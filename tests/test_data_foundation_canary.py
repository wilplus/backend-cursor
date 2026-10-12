"""Whose Takes get a canonical Recording Attempt row: the canonical_take_rows
ring row (rings, 0394), which replaced the data-foundation canary's three
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


def test_no_user_or_no_principal_gets_no_canonical_row(monkeypatch):
    monkeypatch.setattr(rings, "feature_is_on", lambda *a, **k: True)
    assert _decision(user_id=None, email="artur@willonski.com") is False
    assert _decision(user_id="founder-id", email="artur@willonski.com",
                     owner_principal_id=None) is False


def test_an_unreachable_ring_table_is_a_closed_door(monkeypatch):
    def unavailable(*_a, **_k):
        raise RuntimeError("db down")

    monkeypatch.setattr(rings, "_rpc", unavailable)
    assert _decision(user_id="founder-id", email="artur@willonski.com") is False
