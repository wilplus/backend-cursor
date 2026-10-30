"""
STORY    As a speaker with a goal, I want my why, my vision and how I want to
         treat people kept in my own words, and my why waiting for me once
         each day, so that I remember what I am doing this for.
OUTCOME
  O1  After my first life goal, the next open of the Lounge asks once for my
      why with Not now | Start; a second Not now and it waits for me to ask
      ("#why" or my own words) (N255 Q3).
  O2  Will drafts each line only from my answers and quotes them; a skipped
      question gets no line; all three skipped, nothing is drafted (Q2).
  O3  Kept, the Lounge says "Noted. Your why is set." and each day, the
      first time it opens, my why waits in my words with "Where will it show
      today?", once that day (Q4).
  O4  A changed line keeps the earlier words, dated; Will reads all three
      before it chats (Q5, Q6).
  O5  Without the ring row, or while onboarded, nothing of it appears.
PROVES   O1 -> test_the_ask_comes_after_the_first_goal_twice_at_most
         O2 -> test_will_drafts_only_from_my_words
         O3 -> test_my_why_waits_once_a_day
         O4 -> test_a_changed_line_keeps_its_history_and_will_reads_all_three
         O5 -> test_without_the_ring_nothing_appears
WHY      Founder 2026-10-29 ("what about the reminder daily reminder about my
         goals? Like raison d'être"), N255; words signed N258.
"""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from services import your_why as yw


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

    def get_voice_notebook_consent(self, user_id):
        return {"decision": "yes", "time_zone": "Europe/Warsaw"}

    def bodies(self):
        return [r["body"] for r in self.thread.values()]


class _Store:
    def __init__(self):
        self.goals, self.why, self.versions = [], {}, []

    def list_goals(self, user_id, status="active"):
        return list(self.goals)

    def get_why(self, user_id):
        return dict(self.why)

    def save_why(self, user_id, fields):
        self.why.update(fields)
        return dict(self.why)

    def insert_why_version(self, user_id, *, line, before, after):
        self.versions.append({"line": line, "before_text": before, "after_text": after,
                              "created_at": "2026-10-29T08:00:00"})
        return self.versions[-1]

    def why_versions(self, user_id):
        return list(self.versions)


@pytest.fixture
def me(monkeypatch):
    store = _Store()
    for name in ("list_goals", "get_why", "save_why", "insert_why_version", "why_versions"):
        monkeypatch.setattr(f"services.life_store.{name}", getattr(store, name))
    monkeypatch.setattr("services.rings.feature_is_on_for_user",
                        lambda feature, user, database=None: user == "u")
    monkeypatch.setattr("services.plan_flow.onboarding", lambda database, user: False)
    calls = []

    def model(**kw):
        calls.append(kw)
        if "Decide whether" in kw["system"]:
            return SimpleNamespace(parsed={"asks": "purpose" in kw["user"]})
        return SimpleNamespace(parsed={
            "why": {"line": "To give people the belief someone once gave me.",
                    "quote": "someone believed in me before I did"},
            "vision": {"line": "A world where shy people get heard first.", "quote": "made up"},
            "treat": None})
    monkeypatch.setattr("services.llm.chat_complete", model)
    return store, calls


def test_the_ask_comes_after_the_first_goal_twice_at_most(me):
    store, _ = me
    db = _Db()
    assert yw.today(db, "u") == []  # no goal yet
    store.goals.append({"id": "g1"})
    rows = yw.today(db, "u")
    assert [r["body"] for r in rows] == [yw.COPY["ask"], yw.COPY["ask_more"]]
    assert rows[-1]["metadata"]["offer"] == "your_why"
    assert yw.today(db, "u") == []  # still open in the thread
    yw.answer_ask(db, "u", "not_now")
    assert db.bodies()[-2:] == ["Not now", "Noted."]
    assert len(yw.today(db, "u")) == 2  # once more
    yw.answer_ask(db, "u", "not_now")
    assert yw.today(db, "u") == []  # then it waits for me to ask
    assert yw.chat_turn(db, "u", "#why")["row_metadata"] == {"your_why_open": True}
    assert yw.chat_turn(db, "u", "what is my purpose here?")["answer"] == yw.COPY["ask_more"]
    assert yw.chat_turn(db, "u", "how do I open my talk?") is None
    assert yw.chat_turn(db, "u", "# a note about my purpose") is None  # a note stays a note


def test_will_drafts_only_from_my_words(me):
    _, calls = me
    db = _Db()
    drafts = yw.draft(db, "u", {"why": "Because someone believed in me before I did.",
                                "vision": "Shy people get heard first.", "treat": ""})
    assert drafts["why"] == {"line": "To give people the belief someone once gave me.",
                             "quote": "someone believed in me before I did"}
    assert drafts["vision"]["quote"] == "Shy people get heard first."  # never a made-up quote
    assert drafts["treat"] is None
    calls.clear()
    assert yw.draft(db, "u", {}) == {"why": None, "vision": None, "treat": None}
    assert not calls  # nothing to draft from: no model call


def test_my_why_waits_once_a_day(me):
    store, _ = me
    db = _Db()
    store.goals.append({"id": "g1"})
    rows = yw.save(db, "u", {"why": "To give people the belief someone once gave me.",
                             "vision": "", "treat": "Straight and warm."})
    assert [r["body"] for r in rows] == [yw.COPY["set"], yw.COPY["every_day"]]
    first = yw.today(db, "u", now=datetime(2026, 10, 30, 6, 0, tzinfo=timezone.utc))
    assert [r["body"] for r in first] == ["🔥 To give people the belief someone once gave me.",
                                         yw.COPY["daily_q"]]
    assert yw.today(db, "u", now=datetime(2026, 10, 30, 18, 0, tzinfo=timezone.utc)) == []
    assert len(yw.today(db, "u", now=datetime(2026, 10, 31, 6, 0, tzinfo=timezone.utc))) == 2
    with pytest.raises(yw.WhyError):
        yw.save(db, "u", {"why": " ", "vision": None})


def test_a_changed_line_keeps_its_history_and_will_reads_all_three(me):
    store, _ = me
    db = _Db()
    yw.save(db, "u", {"why": "To give belief.", "vision": "Shy people heard.", "treat": "Warm."})
    state = yw.change(db, "u", "why", "To give people the belief someone once gave me.")
    assert state["lines"]["why"] == "To give people the belief someone once gave me."
    assert state["changes"]["why"]["earlier"] == "To give belief."
    assert db.bodies()[-1].startswith("Noted. Changed on ")
    assert yw.change(db, "u", "why", "To give people the belief someone once gave me.") == state
    lines = yw.prompt_lines(db, "u")
    assert "Their why: To give people the belief" in lines and "Their vision" in lines
    with pytest.raises(yw.WhyError):
        yw.change(db, "u", "mission", "x")


def test_without_the_ring_nothing_appears(me, monkeypatch):
    store, _ = me
    db = _Db()
    store.goals.append({"id": "g1"})
    assert yw.today(db, "someone") == [] and yw.prompt_lines(db, "someone") == ""
    assert yw.chat_turn(db, "someone", "#why") is None
    monkeypatch.setattr("services.plan_flow.onboarding", lambda database, user: True)
    assert yw.today(db, "u") == [] and yw.chat_turn(db, "u", "#why") is None
    with pytest.raises(yw.WhyError):
        yw.state(db, "someone")
