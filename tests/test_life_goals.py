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
  O3  A set goal leaves the draft, posts its ladder, "Noted. Your career
      goal is set." and the line that sends me out to live it (N183) to the
      Lounge; a goal it replaces is kept as replaced.
  O4  A changed step keeps the earlier words as a dated version; the talk
      goal changes the setup answer itself; the same words change nothing.
  O5  "#goals" opens my ladders; "can I add another goal? I want to get
      healthier" is answered "Of course, ..." and opens the lens with my
      words; a talk-goal change and anyone else go on as before.
  O6  Two goals whose words pull against each other are asked "When they
      clash, which wins?" once per pair, before the new goal is set; the
      answer is a step on both ladders, and a changed answer keeps the
      earlier one with its date (N185).
  O7  On the quarter's last day the first opening of the Lounge finds "The
      quarter ends today." and "Did it move?" with Not now | Start, once;
      opened later, "The quarter ended on …"; the review keeps how it went
      in words, quotes only notes that match, and sets the next quarter's
      step with the earlier one kept (N186).
PROVES   O1 -> test_the_ask_comes_after_the_first_note_and_once_more_after_not_now
         O2 -> test_the_draft_quotes_only_my_words
         O3 -> test_a_set_goal_posts_its_ladder_and_keeps_the_one_it_replaces
         O4 -> test_a_changed_step_keeps_its_earlier_words
         O5 -> test_asking_in_my_own_words_opens_the_lens
         O6 -> test_a_clash_is_asked_once_and_kept_on_both_ladders
         O7 -> test_the_quarter_comes_back_on_its_last_day
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

    def list_voice_notes(self, user_id, limit=20):
        return [{"text_clean": "Too many late calls again.", "created_at": "2026-11-12T08:00:00"},
                {"text_clean": "Lovely walk.", "created_at": "2026-11-20T08:00:00"}]

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
    ladder, noted, go_live = rows
    assert noted["body"] == "Noted. Your career goal is set."
    assert go_live["body"] == COPY["go_live"]
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


def test_a_clash_is_asked_once_and_kept_on_both_ladders(store, monkeypatch):
    db = _Db()
    career = lg.save_draft("u", None, "career", {**CAREER, "give": "My evenings."})
    lg.finish(db, "u", career["id"])
    home = lg.save_draft("u", None, "personal", {"goal": "Dinner with my family.",
                                                  "give": "Work after 7 pm."})
    _model(monkeypatch, {"other": 1, "line": "💼 Career wants your evenings. 🏡 Personal "
                                             "life gives up work after 7 pm."})
    clash = lg.check_clash(db, "u", home["id"])["clash"]
    assert clash["with"] == career["id"]
    assert [o["label"] for o in clash["options"]] == ["Personal life", "Career", "I decide each time"]

    kept = lg.answer_clash(db, "u", home["id"], career["id"], home["id"])
    assert kept["text"] == "🏡 Personal life wins"
    assert store.goals[career["id"]]["ladder"]["clashes"][0]["text"] == "🏡 Personal life wins"
    assert lg.check_clash(db, "u", home["id"]) == {"clash": None}  # asked once per pair

    rows = lg.finish(db, "u", home["id"])
    assert "WHEN THEY CLASH: 🏡 Personal life wins" in rows[0]["body"]
    shown = lg.answer_clash(db, "u", career["id"], home["id"], "each_time")
    assert shown["goal"]["ladder"]["clashes"][0]["text"] == "You decide each time"
    assert shown["goal"]["changes"]["clash"]["earlier"] == "🏡 Personal life wins"

    _model(monkeypatch, {"other": None, "line": ""})
    good = lg.save_draft("u", None, "good", {"goal": "Teach a free class."})
    assert lg.check_clash(db, "u", good["id"]) == {"clash": None}  # nothing in their words


def test_the_quarter_comes_back_on_its_last_day(store, monkeypatch):
    from datetime import date
    db = _Db()
    goal = lg.save_draft("u", None, "career", CAREER)
    lg.finish(db, "u", goal["id"])
    assert lg.quarter_due(db, "u", date(2026, 12, 30)) == []
    rows = lg.quarter_due(db, "u", date(2026, 12, 31))
    assert [r["body"] for r in rows] == ["The quarter ends today.",
                                         "💼 Ten paying teams. Did it move?"]
    assert rows[1]["metadata"]["offer"] == lg.QUARTER_OFFER
    assert lg.quarter_due(db, "u", date(2026, 12, 31)) == []  # once

    lg.answer_quarter(db, "u", goal["id"], "not_now")
    assert db.bodies()[-2:] == [COPY["not_now"], COPY["noted"]]

    _model(monkeypatch, {"notes": [1]})
    found = lg.quarter_notes(db, "u", goal["id"], "Late calls ate my evenings.")
    assert found == {"notes": [{"text": "Too many late calls again.", "on": "12 November"}]}

    shown = lg.review_quarter(db, "u", goal["id"], "moved", "Late calls.", "Twenty paying teams.")
    assert shown["ladder"]["quarter"] == {"text": "Twenty paying teams.", "by": "31 March",
                                          "next": False, "on": "2027-03-31"}
    assert shown["ladder"]["reviews"][-1]["outcome"] == "moved"
    assert shown["changes"]["quarter"]["earlier"] == "Ten paying teams."
    with pytest.raises(lg.GoalsError):
        lg.review_quarter(db, "u", goal["id"], "7/10")  # never a score

    rows = lg.quarter_due(db, "u", date(2027, 4, 2))
    assert rows[0]["body"] == "The quarter ended on 31 March."
