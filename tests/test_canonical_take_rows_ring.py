"""
STORY    As the founder, I want canonical Recording Attempt rows created only
         for Takes the canonical_take_rows ring reaches, failing closed, so
         that learning data is written only where the ring is on.
OUTCOME
  O1  No signed-in user, or no owner principal: no canonical row.
  O2  The ring table cannot be read: no canonical row (closed door).
  O3  The ring is on for this owner principal: a canonical row; off: none.
PROVES   O1 -> test_no_user_or_no_principal_gets_no_canonical_row
         O2 -> test_an_unreachable_ring_table_is_a_closed_door
         O3 -> test_the_ring_decides_for_the_owner_principal
NOTE     Calls the upload route's private decision (_is_data_foundation_canary_owner,
         the name is historical) with only the ring RPC faked; driving the whole
         upload route for one boolean would need half the recording stack mocked.
WHY      The data-foundation canary's three doors were retired 2026-09-29 for
         the one canonical_take_rows ring row (rings, 0394).
"""
from flask import Flask

import routes.v2.lab_recording as lab_recording
from services import rings

app = Flask(__name__)

OWNER_PRINCIPAL = "11111111-1111-4111-8111-111111111111"


def _gets_canonical_row(user_id, owner_principal_id=OWNER_PRINCIPAL) -> bool:
    with app.test_request_context():
        return lab_recording._is_data_foundation_canary_owner(
            user_id, owner_principal_id,
        )


def _ring_answers(monkeypatch, answer: bool) -> list:
    asked = []

    def rpc(name, params, **_kwargs):
        asked.append((name, params))
        return answer

    monkeypatch.setattr(rings, "_rpc", rpc)
    return asked


def test_no_user_or_no_principal_gets_no_canonical_row(monkeypatch):
    _ring_answers(monkeypatch, True)
    assert _gets_canonical_row(None) is False
    assert _gets_canonical_row("user-id", owner_principal_id=None) is False


def test_an_unreachable_ring_table_is_a_closed_door(monkeypatch):
    def unavailable(*_a, **_k):
        raise RuntimeError("db down")

    monkeypatch.setattr(rings, "_rpc", unavailable)
    assert _gets_canonical_row("user-id") is False


def test_the_ring_decides_for_the_owner_principal(monkeypatch):
    asked = _ring_answers(monkeypatch, True)
    assert _gets_canonical_row("user-id") is True
    assert asked == [("feature_is_on_v1", {
        "p_feature": rings.CANONICAL_TAKE_ROWS, "p_principal": OWNER_PRINCIPAL,
    })]

    _ring_answers(monkeypatch, False)
    assert _gets_canonical_row("user-id") is False
