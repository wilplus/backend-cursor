"""
STORY    As a speaker, I want my Take's feedback moments to gather what they
         read at once, so that my Ideal Text opens sooner.
OUTCOME
  O1  The Take's pieces, its session, the project's background document and
      its decisions are read at the same time, not one database round trip
      after another.
  O2  The readout the moments are found in is built over those same pieces
      and that same session, so neither is read a second time.
PROVES   O1, O2 -> test_the_takes_inputs_are_read_once_and_together
WHY      2026-11-05, the wait: these reads ran one after another inside the
         feedback moments, before the Ideal Text. Driven through the public
         generate_praise_for_session; only the database, the readout and the
         provider call are faked.
"""
from __future__ import annotations

import threading
from types import SimpleNamespace

import services.moment_suggestions as ms

ROWS = [{"id": f"s{i}", "transcript": f"piece {i}", "metrics": {"wpm": 120 + i}}
        for i in range(3)]
SESSION = {"id": "take-1", "user_id": "speaker-1",
           "intake_context": {"audience": "the board"}}


class _Db:
    """Each of the four first reads answers only once all four are in
    flight: one after another, the first waits out its timeout."""

    def __init__(self):
        self.together = threading.Barrier(4, timeout=5)
        self.takes = SimpleNamespace(get_arc_sessions=lambda _arc: [],
                                     v2_list_user_lab_sessions=lambda *_a, **_k: [])

    def get_snippets_by_session(self, _sid):
        self.together.wait()
        return ROWS

    def v2_get_session_by_id(self, _sid):
        self.together.wait()
        return SESSION

    def get_arc_context_document(self, _arc):
        self.together.wait()
        return {"text": "Quarterly results."}

    def list_ideal_decisions(self, _arc):
        self.together.wait()
        return []

    def upsert_moment_suggestion(self, *_a, **_k):
        return True


def test_the_takes_inputs_are_read_once_and_together(monkeypatch):
    built = []

    def readout(session_id, **kwargs):
        built.append((session_id, kwargs))
        return {"snippets": [{"id": r["id"], "transcript": r["transcript"],
                              "features": {}} for r in ROWS]}

    monkeypatch.setattr("services.lab_recording.build_readout_from_session", readout)
    monkeypatch.setattr("services.llm.chat_complete",
                        lambda **_kw: SimpleNamespace(parsed={}))
    monkeypatch.setenv("DELIVERY_STARS_ENABLED", "0")

    ms.generate_praise_for_session("take-1", "arc-1", database=_Db())

    assert len(built) == 1
    session_id, kwargs = built[0]
    assert session_id == "take-1"
    assert kwargs["snippet_rows"] == ROWS
    assert kwargs["session_row"] == SESSION
