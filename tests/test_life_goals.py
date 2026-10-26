"""
STORY    As the founder, I want Will to ask for my life goals once after my
         first note and walk me through one goal at a time, drafted only from
         my words, so that my notes, my talk and my week answer to the same
         goals, and I can change any step without losing what it said before.
OUTCOME
  O1  After the first # note's "Noted." the two signed bubbles come, the
      second carrying the Not now | Start ask; not again while it waits;
      after a Not now once more after the next note, never a third time;
      nothing once a goal is set, and nothing for anyone else.
  O2  Will's draft keeps only phrases found word for word in my answers;
      with every question skipped there is no goal.
  O3  A set goal leaves the draft, posts its ladder and "Noted. Your career
      goal is set." to the Lounge; a goal it replaces is kept as replaced.
  O4  A changed step keeps the earlier words as a dated version; the talk
      goal changes the setup answer itself; the same words change nothing.
  O5  "#goals" opens my ladders; "can I add another goal? I want to get
      healthier" is answered "Of course, ..." and opens the lens with my
      words; a talk-goal change and anyone else go on as before.
PROVES   O1 -> test_the_ask_comes_after_the_first_note_and_once_more_after_not_now
         O2 -> test_the_draft_quotes_only_my_words
         O3 -> test_a_set_goal_posts_its_ladder_and_keeps_the_one_it_replaces
         O4 -> test_a_changed_step_keeps_its_earlier_words
         O5 -> test_asking_in_my_own_words_opens_the_lens
WHY      Will learning plan, step 3 (founder 2026-10-26, N172: "build the
         life goals now"; rules in the frontend flow page §1 M).
"""
from types import SimpleNamespace

import pytest

from services import life_goals as lg
from services.life_goals import COPY


class _Db:
    def __init__(self):
        self.thread = {}
        self.goal = "They book a demo"
        self.goal_history = []

    def insert_lounge_messages(self, user_id, rows):
        for r in rows:
            self.thread.setdefault((user_id, r["client_id"]), {**r, "user_id": user_id})
        return [self.thread[(user_id, r["client_id"])] for r in rows]

    def get_lounge_messages_page(self, user_id, limit=50):
        mine = [r for (u, _), r in self.thread.items() if u == user_id]
        return list(reversed(mine))[:limit]

    def get_user_profile(self, user_id):
        return {"goal": self.goal}

    def update_user_goal(self, user_id, new, previous):
        self.goal = new
        return True

    def bodies(self, user_id="u"):
        return [r["body"] for r in reversed(self.get_lounge_messages_page(user_id, 500))]


class _Store:
    """The Life Panel store's life goal functions, in memory."""

    def __init__(self):
        self.goals, self.versions, self.asks = {}, [], {}

    def insert_goal(self, user_id, fields):
        goal = {**fields, "id": f"g{len(self.goals) + 1}", "user_id": user_id,
                "created_at": f"2026-10-26T10:0{len(self.goals)}:00"}
        self.goals[goal["id"]] = goal
        return goal

    def update_goal(self, user_id, goal_id, fields):
        self.goals[goal_id].update(fields)
        return self.goals[goal_id]

    def get_goal(self, user_id, goal_id):
        goal = self.goals.get(goal_id)
        return goal if goal and goal["user_id"] == user_id else None

    def list_goals(self, user_id, *, status="active"):
        return [g for g in self.goals.values()
                if g["user_id"] == user_id and g["status"] == status]

    def insert_goal_version(self, user_id, goal_id, *, step, before, after):
        self.versions.append({"user_id": user_id, "goal_id": goal_id, "step": step,
                              "before_text": before, "after_text": after,
                              "created_at": "2026-11-03T09:00:00"})
        return self.versions[-1]

    def goal_versions(self, user_id, goal_id):
        return [v for v in self.versions if v["goal_id"] == goal_id]

    def get_goal_asks(self, user_id):
        return dict(self.asks.get(user_id, {}))

    def save_goal_asks(self, user_id, *, asked, answer):
        self.asks[user_id] = {"asked": asked, "answer": answer}
        return True


@pytest.fixture
def store(monkeypatch):
    memory = _Store()
    for name in ("insert_goal", "update_goal", "get_goal", "list_goals",
                 "insert_goal_version", "goal_versions", "get_goal_asks",
                 "save_goal_asks"):
        monkeypatch.setattr(f"services.life_store.{name}", getattr(memory, name))
    monkeypatch.setattr("services.rings.feature_is_on_for_user",
                        lambda feature, user, database=None: user == "u")
    monkeypatch.setattr("services.goal_history.record_later",
                        lambda database, user, old, new, source: None)
    return memory


def _model(monkeypatch, parsed):
    monkeypatch.setattr("services.llm.chat_complete",
                        lambda **_: SimpleNamespace(text="{}", parsed=dict(parsed)))


CAREER = {"goal": "Make WillpowerLab the place people learn to speak with confidence.",
          "quotes": ["the place people learn to speak with confidence"],
          "horizon": "3y", "horizon_by": "October 2029",
          "steps": {"y1": {"text": "A hundred paying teams.", "by": "October 2027"}},
          "quarter": {"text": "Ten paying teams.", "by": "31 December", "next": False}}


def test_the_ask_comes_after_the_first_note_and_once_more_after_not_now(store):
    db = _Db()
    rows = lg.after_note(db, "u")
    assert [r["body"] for r in rows] == [COPY["ask"], COPY["ask_more"]]
    assert rows[-1]["metadata"]["offer"] == lg.OFFER
    assert lg.after_note(db, "u") == []  # not again while it waits

    lg.answer(db, "u", "not_now")
    assert db.bodies()[-2:] == [COPY["not_now"], COPY["noted"]]
    assert len(lg.after_note(db, "u")) == 2  # once more, after the next note
    lg.answer(db, "u", "not_now")
    assert lg.after_note(db, "u") == []  # never a third time

    assert lg.after_note(db, "someone") == []
    other = _Db()
    store.asks.clear()
    store.insert_goal("u", {"space": "career", "status": "active", "ladder": CAREER})
    assert lg.after_note(other, "u") == []  # a goal is set


def test_the_draft_quotes_only_my_words(store, monkeypatch):
    db = _Db()
    _model(monkeypatch, {"goal": "Make WillpowerLab the place people learn to speak with confidence.",
                         "quotes": ["the place people learn to speak with confidence",
                                    "change the world by 2030"]})
    answers = {"want_most": "To make WillpowerLab the place people learn to speak with confidence.",
               "fulfil": "Seeing someone own the room."}
    drafted = lg.draft(db, "u", "career", answers)
    assert drafted["goal"].startswith("Make WillpowerLab")
    assert drafted["quotes"] == ["the place people learn to speak with confidence"]

    assert lg.draft(db, "u", "career", {}) == {"goal": "", "quotes": []}
    with pytest.raises(lg.GoalsError):
        lg.draft(db, "someone", "career", answers)


def test_a_set_goal_posts_its_ladder_and_keeps_the_one_it_replaces(store):
    db = _Db()
    old = lg.save_draft("u", None, "career", {"goal": "Build a company."})
    lg.finish(db, "u", old["id"])
    new = lg.save_draft("u", None, "career", {**CAREER, "invented": "dropped"})
    assert "invented" not in new["ladder"] and new["status"] == "draft"

    rows = lg.finish(db, "u", new["id"], replaces=old["id"])
    ladder, noted = rows
    assert noted["body"] == "Noted. Your career goal is set."
    assert ladder["metadata"]["life_goal"]["ladder"]["quarter"]["text"] == "Ten paying teams."
    assert "TALK GOAL: They book a demo" in ladder["body"]
    assert store.goals[old["id"]]["status"] == "replaced"
    assert [g["id"] for g in store.list_goals("u")] == [new["id"]]


def test_a_changed_step_keeps_its_earlier_words(store):
    db = _Db()
    goal = lg.save_draft("u", None, "career", CAREER)
    lg.finish(db, "u", goal["id"])

    shown = lg.change_step(db, "u", goal["id"], "quarter", "Twenty paying teams.")
    assert shown["ladder"]["quarter"]["text"] == "Twenty paying teams."
    assert shown["changes"]["quarter"] == {"on": "2026-11-03", "earlier": "Ten paying teams."}

    shown = lg.change_step(db, "u", goal["id"], "talk", "They sign up for a pilot")
    assert db.goal == "They sign up for a pilot" and shown["talk"] == db.goal

    lg.change_step(db, "u", goal["id"], "quarter", "Twenty paying teams.")
    assert len(store.versions) == 2  # the same words change nothing


def test_asking_in_my_own_words_opens_the_lens(store, monkeypatch):
    db = _Db()
    _model(monkeypatch, {"intent": "add", "said": "I want to get healthier", "space": "personal"})
    turn = lg.chat_turn(db, "u", "can I add another goal? I want to get healthier")
    assert turn["answer"] == COPY["of_course"]
    assert turn["row_metadata"] == {"life_goals_open": "add",
                                    "said": "I want to get healthier", "space": "personal"}

    assert lg.chat_turn(db, "u", "#goals")["row_metadata"]["life_goals_open"] == "add"  # none yet
    goal = lg.save_draft("u", None, "career", CAREER)
    lg.finish(db, "u", goal["id"])
    assert lg.chat_turn(db, "u", "#goals")["answer"] == COPY["your_goals"]

    _model(monkeypatch, {"intent": "none", "said": None, "space": None})
    assert lg.chat_turn(db, "u", "change my goal to they book a demo") is None
    assert lg.chat_turn(db, "someone", "can I add another goal?") is None
    assert lg.chat_turn(db, "u", "# a note about my goals") is None  # a note stays a note
