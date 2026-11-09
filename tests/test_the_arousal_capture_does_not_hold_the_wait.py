"""
STORY    As a speaker, I want my Take's feedback moments found without
         waiting on bookkeeping, so that my Ideal Text opens sooner.
OUTCOME
  O1  Every piece with an arousal read still gets that read stored, with
      the same value, before the feedback moments go on.
  O2  The stores go out together, not one database round trip after
      another (a five-minute Take has about thirty pieces).
PROVES   O1, O2 -> test_every_arousal_read_is_stored_and_the_stores_overlap
WHY      2026-11-05, the wait. Driven through the public
         generate_for_session; only the Take's readout and the speaker's
         cross-Take cue baseline are faked, and the store itself.
"""
from __future__ import annotations

import threading
from types import SimpleNamespace

import services.moment_suggestions as ms
from services.delivery_stars import arousal_z, resolve_delivery_baseline

PIECES = 8


def _features(i: int) -> dict:
    return {"wpm": 110.0 + 7 * i, "dynamic_db": 18.0 + (i % 3),
            "f0_sd": 20.0 + 2 * i, "pause_ratio": 0.3 - 0.02 * i}


class _Db:
    """A Take with no history and no ledger; the store needs a partner."""

    def __init__(self):
        self.arousal: dict = {}
        # Two stores must be in flight at once to pass: one after another,
        # the first waits out the timeout and nothing is stored.
        self.both_in_flight = threading.Barrier(2, timeout=5)
        self.takes = SimpleNamespace(get_arc_sessions=lambda _arc: [],
                                     v2_list_user_lab_sessions=lambda *_a, **_k: [])

    def get_snippets_by_session(self, _sid):
        return []

    def v2_get_session_by_id(self, sid):
        return {"id": sid, "user_id": "speaker-1"}

    def get_arc_context_document(self, _arc):
        return None

    def list_ideal_decisions(self, _arc):
        return []

    def upsert_moment_suggestion(self, *_a, **_k):
        return True

    def set_snippet_arousal(self, snippet_id, value):
        self.both_in_flight.wait()
        self.arousal[snippet_id] = value
        return True


def test_every_arousal_read_is_stored_and_the_stores_overlap(monkeypatch):
    readout = {"snippets": [{"id": f"s{i}", "transcript": f"piece {i}",
                             "features": _features(i)} for i in range(PIECES)]}
    monkeypatch.setattr("services.lab_recording.build_readout_from_session",
                        lambda *_a, **_k: readout)
    monkeypatch.setattr("services.voice_confidence.resolve_confidence_baseline",
                        lambda *_a, **_k: (None, "none"))
    monkeypatch.setenv("STRUCTURAL_STARS_ENABLED", "0")
    monkeypatch.setenv("DELIVERY_STARS_ENABLED", "0")
    database = _Db()

    ms.generate_for_session("take-1", "arc-1", database=database)

    baseline = resolve_delivery_baseline(
        "speaker-1", [s["features"] for s in readout["snippets"]],
        database=database)
    expected = {s["id"]: arousal_z(s["features"], baseline)
                for s in readout["snippets"]}
    assert baseline and all(v is not None for v in expected.values())
    assert database.arousal == expected
