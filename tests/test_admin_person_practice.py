"""
STORY    As the founder, I want each person's admin page to show how many
         practices were offered and how many were completed, so that I can
         see who is practising.
OUTCOME
  O1  Five offered with three completed reads "offered 5, done 3".
  O2  A person with no practice yet reads 0 and 0.
PROVES   O1 -> test_counts_completed_out_of_offered
         O2 -> test_no_practice_yet
WHY      Founder 2026-10-18. Admin only: never shown to a speaker.
"""
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
