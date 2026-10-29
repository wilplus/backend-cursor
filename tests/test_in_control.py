"""
STORY    As a speaker who worries before a talk, I want Will to sort the worry
         once into what is mine and what is not, and end on one thing I can
         do, so that I spend the evening on what I control.
OUTCOME
  O1  A note that worries about something out of my hands gets Will's two or
      three lines under its "Noted.", ending on one thing I control, from
      Will's signed guide (N241 O1, N258).
  O2  The same worry is not sorted twice: Will may ask once whether the one
      thing happened, then says nothing more about it.
  O3  A note that is no worry, a crisis note, or anyone without the ring row
      gets only "Noted." (N258 R1).
PROVES   O1 -> test_a_worry_is_sorted_once_and_ends_on_one_thing
         O2 -> test_the_same_worry_is_not_sorted_twice
         O3 -> test_no_worry_no_ring_or_a_crisis_gets_only_noted
WHY      Linear WIL-113; Will's guide signed 2026-10-29 (N258).
"""
import pytest

from services import in_control as ic


class _Db:
    def __init__(self):
        self.thread = {}
        self.notes = []

    def insert_lounge_messages(self, user_id, rows):
        for r in rows:
            self.thread.setdefault((user_id, r["client_id"]), {**r, "user_id": user_id})
        return [self.thread[(user_id, r["client_id"])] for r in rows]

    def get_lounge_messages_page(self, user_id, limit=50):
        mine = [r for (u, _), r in self.thread.items() if u == user_id]
        return list(reversed(mine))[:limit]

    def list_voice_notes(self, user_id, limit=20):
        return [n for n in self.notes if n["user_id"] == user_id][-limit:]

    def note(self, text):
        self.notes.append({"id": f"n{len(self.notes) + 1}", "user_id": "u", "text_clean": text})


@pytest.fixture
def will(monkeypatch):
    """The ring row on for "u", nobody onboarded, and the model's answers
    queued; each call's earlier worries are kept for the test to read."""
    monkeypatch.setattr("services.rings.feature_is_on_for_user",
                        lambda feature, user, database=None: feature == ic.FEATURE and user == "u")
    monkeypatch.setattr("services.plan_flow.onboarding", lambda database, user: False)
    answers, seen = [], []

    def model(note, earlier, user_id):
        seen.append([w["about"] for w in earlier])
        return answers.pop(0)

    monkeypatch.setattr(ic, "_model", model)
    return answers, seen


HOTEL = {"worry": True, "same": None, "about": "the hotel",
         "lines": ["The hotel is a variable.",
                   "Your opening line is a constant: say it out loud twice tonight, then sleep."]}


def test_a_worry_is_sorted_once_and_ends_on_one_thing(will):
    answers, seen = will
    db = _Db()
    db.note("# This hotel is awful. Loud street, tiny desk, and I'm on at 9 tomorrow")
    answers.append(HOTEL)
    rows = ic.after_note(db, "u")
    assert [r["body"] for r in rows] == HOTEL["lines"]
    assert all(r["role"] == "bot" and r["metadata"]["in_control"] == "the hotel" for r in rows)
    assert seen == [[]]
    assert "What Will never does" in ic.GUIDE  # the signed guide rides in full


def test_the_same_worry_is_not_sorted_twice(will):
    answers, seen = will
    db = _Db()
    db.note("# This hotel is awful")
    answers.append(HOTEL)
    ic.after_note(db, "u")

    db.note("# Still can't sleep, the street is so loud")
    answers.append({"worry": True, "same": 1, "lines": ["Did you say your opening out loud?"]})
    again = ic.after_note(db, "u")
    assert [r["body"] for r in again] == ["Did you say your opening out loud?"]
    assert seen[-1] == ["the hotel"]

    db.note("# The street again")
    answers.append({"worry": True, "same": 1, "lines": ["Did you sleep?"]})
    assert ic.after_note(db, "u") == []


def test_no_worry_no_ring_or_a_crisis_gets_only_noted(will):
    answers, seen = will
    db = _Db()
    db.note("# Booked the train to Warsaw for Thursday")
    answers.append({"worry": False})
    assert ic.after_note(db, "u") == []

    db.note("# I want to die before this talk")
    assert ic.after_note(db, "u") == []  # the safety reply, never a sort

    other = _Db()
    other.notes.append({"id": "x", "user_id": "someone", "text_clean": "# The hotel is awful"})
    assert ic.after_note(other, "someone") == []
    assert len(seen) == 1 and not db.thread and not other.thread
