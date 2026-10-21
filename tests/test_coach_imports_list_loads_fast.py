"""
STORY    As a coach, I want the training corpus list to open fast and show
         only the imports in languages I speak.
OUTCOME
  O1  An import that declares its language is listed, or withheld when the
      coach does not speak it, without reading its pieces or its recording
      (one read of every piece per import made the list take 15.7 s).
  O2  An import without a declared language takes its language from its
      recording, else its pieces, read once for every such import.
  O3  Each import's labelled count stays right past the database's 1000
      rows a read (600 clips' labels pass it): a done import reads done.
  O4  The list comes in steps (N100): ?limit imports from ?offset, newest
      first, and next_offset leads to the next step, null after the last.
PROVES   O1 -> test_declared_imports_need_no_read_of_their_pieces
         O2 -> test_undeclared_imports_take_their_language_from_one_read
         O3 -> test_labelled_counts_stay_right_past_a_thousand_labels
         O4 -> test_the_list_comes_in_steps
WHY      Founder 2026-10-21 (N99): "please make sure it is smooth that it
         loads fast".
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from routes.v2 import coach as v2_coach
from services.db import DatabaseService
from tests.test_training_import_on import _call

EN, DE, OLD, OLD_DE = ("aaaaaaaa-0000-4000-8000-000000000001", "aaaaaaaa-0000-4000-8000-000000000002",
                       "aaaaaaaa-0000-4000-8000-000000000003", "aaaaaaaa-0000-4000-8000-000000000004")


def _row(sid, language=None):
    ctx = {"topic": sid[-1], **({"language": language} if language else {})}
    return {"id": sid, "arc_id": None, "recording_id": f"rec-{sid[-1]}", "intake_context": ctx,
            "analysis_state": "ready", "created_at": None}


class ListDB:
    def __init__(self, rows, pieces):
        self.rows, self.pieces = rows, pieces
        self.piece_reads: list = []
        self.recording_reads: list = []
        self.takes = SimpleNamespace(list_training_import_sessions=self._page)

    def _page(self, *, user_id=None, limit=200, offset=0):
        return self.rows[offset:offset + limit]

    def get_user_proficient_languages(self, _uid):
        return ["en"]

    def get_snippets_by_session(self, sid, **_):
        raise AssertionError("one read of every piece per import")

    def get_recording(self, _rid):
        raise AssertionError("one read of the recording per import")

    def get_snippets_by_sessions(self, ids, **_):
        self.piece_reads.append(sorted(str(i) for i in ids))
        return {str(i): self.pieces.get(str(i), []) for i in ids}

    def get_recording_languages(self, ids):
        self.recording_reads.append(sorted(str(i) for i in ids))
        return {}

    def count_labelled_snippets_by_session_ids(self, _ids):
        return {}


def _list(db, monkeypatch, query=""):
    monkeypatch.setattr(v2_coach, "db", db)
    status, body = _call(v2_coach.v2_coach_list_training_imports, method="GET",
                         path=f"/v2/coach/training-imports{query}")
    assert status == 200, body
    return body


def _listed(db, monkeypatch):
    return [i["session_id"] for i in _list(db, monkeypatch)["imports"]]


def test_declared_imports_need_no_read_of_their_pieces(monkeypatch):
    db = ListDB([_row(EN, "en"), _row(DE, "de")], {})
    assert _listed(db, monkeypatch) == [EN]
    assert db.piece_reads == []
    assert db.recording_reads in ([], [[]])


def test_undeclared_imports_take_their_language_from_one_read(monkeypatch):
    db = ListDB([_row(EN, "en"), _row(OLD), _row(OLD_DE)], {
        OLD: [{"id": "p1", "session_id": OLD, "language": "english"}],
        OLD_DE: [{"id": "p2", "session_id": OLD_DE, "language": "german"}],
    })
    assert _listed(db, monkeypatch) == [EN, OLD]
    assert db.piece_reads == [sorted([OLD, OLD_DE])]
    assert db.recording_reads == [["rec-3", "rec-4"]]


def test_the_list_comes_in_steps(monkeypatch):
    rows = [_row(EN, "en"), _row(OLD, "en"), _row(OLD_DE, "en")]
    db = ListDB(rows, {})
    first = _list(db, monkeypatch, "?limit=2")
    assert [i["session_id"] for i in first["imports"]] == [EN, OLD]
    assert first["next_offset"] == 2
    last = _list(db, monkeypatch, f"?limit=2&offset={first['next_offset']}")
    assert [i["session_id"] for i in last["imports"]] == [OLD_DE]
    assert last["next_offset"] is None
    # Without ?limit the list reads its first 200, as it always did.
    assert _list(db, monkeypatch)["next_offset"] is None


class _CappedLabels:
    """confidence_labels as PostgREST serves it: at most 1000 rows a read."""

    def __init__(self, rows):
        self.rows, self.ids, self.span = rows, [], (0, 10**9)

    def table(self, _name):
        return self

    def select(self, _cols):
        return self

    def in_(self, _col, ids):
        self.ids = set(ids)
        return self

    def order(self, _col):
        return self

    def range(self, start, end):
        self.span = (start, end)
        return self

    def execute(self):
        rows = sorted((r for r in self.rows if r["session_id"] in self.ids),
                      key=lambda r: (r["session_id"], r["snippet_id"]))
        start, end = self.span
        self.span = (0, 10**9)
        return SimpleNamespace(data=rows[start:end + 1][:1000])


def test_labelled_counts_stay_right_past_a_thousand_labels():
    takes = [f"take-{n:03d}" for n in range(120)]
    # Each Take: 6 pieces, each labelled by 2 coaches -> 1440 label rows.
    rows = [{"session_id": t, "snippet_id": f"{t}-p{p}"} for t in takes
            for p in range(6) for _rater in range(2)]
    db = DatabaseService.__new__(DatabaseService)
    db.client = _CappedLabels(rows)
    counts = db.count_labelled_snippets_by_session_ids(takes)
    assert counts == {t: 6 for t in takes}


if __name__ == "__main__":
    pytest.main([__file__])
