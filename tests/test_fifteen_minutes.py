"""
STORY    As the founder, I want Will to tell me once a day, after my
         proverbial 15 minutes in the app, to go and live it away from the
         phone, so that the app stays a short training and never a habit.
OUTCOME
  O1  Asked for my day, Will writes the two signed bubbles; asked again the
      same day, nothing more.
  O2  A day far from today is refused, and nobody outside the ring gets
      the line.
PROVES   O1 -> test_the_line_comes_once_a_day
         O2 -> test_a_wrong_day_and_anyone_else_get_nothing
WHY      N180 and N183 (founder 2026-10-26: "learn here the base and then go
         and testing real life").
"""
from datetime import datetime, timedelta, timezone

import pytest

from services import fifteen_minutes as fm


class _Db:
    def __init__(self):
        self.thread = {}

    def insert_lounge_messages(self, user_id, rows):
        for r in rows:
            self.thread.setdefault((user_id, r["client_id"]), {**r, "user_id": user_id})
        return [self.thread[(user_id, r["client_id"])] for r in rows]

    def get_lounge_messages_page(self, user_id, limit=50):
        mine = [r for (u, _), r in self.thread.items() if u == user_id]
        return list(reversed(mine))[:limit]

    def get_lounge_message_by_client_id(self, user_id, client_id):
        return self.thread.get((user_id, client_id))


@pytest.fixture(autouse=True)
def founder(monkeypatch):
    monkeypatch.setattr("services.rings.feature_is_on_for_user",
                        lambda feature, user, database=None: user == "u")


def _today(offset=0):
    return (datetime.now(timezone.utc).date() + timedelta(days=offset)).isoformat()


def test_the_line_comes_once_a_day():
    db = _Db()
    rows = fm.say_enough(db, "u", _today())
    assert [r["body"] for r in rows] == [fm.COPY["enough"], fm.COPY["go"]]
    assert fm.say_enough(db, "u", _today()) == []
    assert len(fm.say_enough(db, "u", _today(1))) == 2  # their tomorrow, already


def test_a_wrong_day_and_anyone_else_get_nothing():
    db = _Db()
    with pytest.raises(fm.FifteenError):
        fm.say_enough(db, "u", _today(5))
    with pytest.raises(fm.FifteenError):
        fm.say_enough(db, "u", "today")
    with pytest.raises(fm.FifteenError) as off:
        fm.say_enough(db, "someone", _today())
    assert off.value.status == 404
