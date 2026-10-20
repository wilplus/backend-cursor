"""
STORY    As a speaker, I want my Take processed without a long wait when
         there is nothing to praise structurally, so that I get to my
         feedback sooner.
OUTCOME
  O1  With no device anywhere, the praise pass asks the model about at most
      three waves of three pieces (nine calls), in document order, then
      stops; nothing is stored.
  O2  A Take whose first pieces carry devices stores exactly those pieces,
      without asking about the rest.
PROVES   O1 -> test_a_take_with_no_device_stops_after_three_waves
         O2 -> test_the_first_pieces_with_devices_are_stored_as_before
WHY      Founder 2026-10-14 (the wait). Driven through the public
         generate_praise_for_session; only the provider call (chat_complete),
         the Take's readout and the cross-Take baseline are faked.
"""
from __future__ import annotations

from types import SimpleNamespace

import services.moment_suggestions as ms

PIECES = 30


class _Db:
    """The Take: thirty pieces, no history, no ledger; records the stars."""

    def __init__(self):
        self.stored = []
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

    def upsert_moment_suggestion(self, snip_id, arc_id, kind, repl, quote, device):
        self.stored.append((snip_id, kind, device))
        return True


def _praise(monkeypatch, found):
    asked = []

    def chat_complete(*, user, **_kw):
        asked.append(user)
        hit = found(user)
        return SimpleNamespace(parsed={"device": "contrast", "quote": user} if hit else {})

    readout = {"snippets": [{"id": f"s{i}", "transcript": f"piece {i}", "features": {}}
                            for i in range(PIECES)]}
    monkeypatch.setattr("services.llm.chat_complete", chat_complete)
    monkeypatch.setattr("services.lab_recording.build_readout_from_session",
                        lambda *_a, **_k: readout)
    # The speaker's cross-Take cue baseline reads other Takes; none here.
    monkeypatch.setattr("services.voice_confidence.resolve_confidence_baseline",
                        lambda *_a, **_k: (None, "none"))
    monkeypatch.setenv("STRUCTURAL_STARS_ENABLED", "1")
    monkeypatch.setenv("STRUCTURAL_STARS_MAX_PER_TAKE", "3")
    monkeypatch.setenv("DELIVERY_STARS_ENABLED", "0")
    database = _Db()
    stored = ms.generate_praise_for_session("take-1", "arc-1", database=database)
    return stored, asked, database.stored


def test_a_take_with_no_device_stops_after_three_waves(monkeypatch):
    stored, asked, rows = _praise(monkeypatch, lambda t: False)
    assert stored == 0 and rows == []
    assert len(asked) == 9
    # One wave's calls run in parallel, so only the wave boundaries are
    # fixed; the waves walk the Take in document order.
    assert [set(asked[at:at + 3]) for at in range(0, 9, 3)] == [
        {f"piece {i}" for i in range(w * 3, w * 3 + 3)} for w in range(3)]


def test_the_first_pieces_with_devices_are_stored_as_before(monkeypatch):
    stored, asked, rows = _praise(
        monkeypatch, lambda t: t in ("piece 1", "piece 4", "piece 7"))
    assert stored == 3
    assert rows == [("s1", "structure", "contrast"), ("s4", "structure", "contrast"),
                    ("s7", "structure", "contrast")]
    assert len(asked) <= 9
    assert not any(t in asked for t in (f"piece {i}" for i in range(9, PIECES)))

