"""The admin's person page shows Confident Voice practice progress: how many
practices were offered and how many were completed (founder 2026-10-18)."""
from services import admin_person


class _Query:
    def __init__(self, rows):
        self.rows = rows

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a):
        return self

    def execute(self):
        return type("R", (), {"data": self.rows})()


class _Client:
    def __init__(self, rows):
        self.rows = rows

    def table(self, name):
        assert name == "confident_voice_practice"
        return _Query(self.rows)


def test_counts_completed_out_of_offered(monkeypatch):
    monkeypatch.setattr(admin_person.db, "client", _Client(
        [{"status": "completed"}, {"status": "completed"}, {"status": "open"},
         {"status": "dismissed"}, {"status": "completed"}]), raising=False)
    assert admin_person.practice("u1") == {"offered": 5, "done": 3}


def test_no_practice_yet(monkeypatch):
    monkeypatch.setattr(admin_person.db, "client", _Client([]), raising=False)
    assert admin_person.practice("u1") == {"offered": 0, "done": 0}
