"""
STORY    As the founder, I want each Take on a person's admin page to show its
         willfidence, so I can read how a speaker's Takes are going.
OUTCOME
  O1  A Take row carries `willfidence`: the mean of its pieces' willfidence in
      whole percent, counting only pieces with a sound read; none when no piece
      has one (never the middle of the scale made up).
PROVES   O1 -> test_a_take_row_carries_its_willfidence_in_percent
WHY      Founder 2026-10-21 (N105): "add the willfidence column here (in the
         ceo panel but only here)".
"""
from __future__ import annotations

from services import admin_takes
from services.voice_confidence import _VERSION


class _Takes:
    @staticmethod
    def list_sessions_for_user_admin(_uid):
        return [{"id": "t1"}, {"id": "t2"}]


class _Db:
    takes = _Takes()
    client = None

    @staticmethod
    def get_snippets_by_sessions(_ids):
        heard = {"voice_confidence": {"version": _VERSION, "score": 1.0}}
        return {"t1": [{"transcript": "We grew in every region.", "metrics": heard}],
                "t2": [{"transcript": "We grew in every region.", "metrics": {}}]}


def test_a_take_row_carries_its_willfidence_in_percent(monkeypatch):
    monkeypatch.setattr(admin_takes, "db", _Db)
    monkeypatch.setattr(admin_takes, "_ai_clips", lambda _uid: {})
    monkeypatch.setattr(admin_takes, "_projects", lambda _ids: {})
    rows = {r["id"]: r for r in admin_takes.takes("u1")["takes"]}
    assert isinstance(rows["t1"]["willfidence"], int) and 0 < rows["t1"]["willfidence"] <= 100
    assert rows["t2"]["willfidence"] is None
