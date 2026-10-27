"""
STORY    As a coach, I want a speaker's plan to reach my queue when it needs me,
         so that I pick their level blind, or record my video for a level that
         hasn't moved, and the speaker's plan follows my answer.
OUTCOME
  O1  A plan reaches the queue on its speaker's card as a new plan, the
      speaker's ask, or a level three Takes without moving, the ask first;
      a speaker with no Take in the queue gets a card of their own; a coach
      who can't hear the speaker's language never sees it.
  O2  The pick is blind: the plan opens on the voice message, the key line
      and the five levels, never the plan's level; What happened comes with
      the pick: the coach's level, the machine's, the deadline, and stress
      and ready only when the speaker gave them.
  O3  The coach's answer takes the plan out of every coach's queue until the
      speaker asks again or the level is stuck again; "Change my answer"
      picks again; "Audio unclear" takes it out of this coach's queue only.
  O4  A stuck level opens on its name and the Take the coach's video goes
      on; once shared, the plan leaves the queue.
  O5  Only the voice message and the key line play to a coach.
PROVES   O1 -> test_a_plan_reaches_the_queue_on_its_speakers_card
         O2 -> test_the_pick_is_blind_and_what_happened_comes_with_it
         O3 -> test_an_answer_takes_the_plan_out_of_the_queue
         O4 -> test_a_stuck_level_is_answered_with_the_coachs_video
         O5 -> test_only_the_voice_message_and_the_key_line_play
WHY      The coach's side of the plan, built as the founder's prototype draws
         it (N213); the rules are frontend docs/flows/the-plan.md §1 C5, G10
         and H1, and docs/flows/coach-panel.md.
"""
from datetime import datetime, timedelta, timezone

import pytest

from services import plan_coach as C

COACH, OTHER_COACH = "c0000000-0000-0000-0000-000000000001", "c0000000-0000-0000-0000-000000000002"
LARK, WREN, FINCH = "u1", "u2", "u3"


def _at(minutes: int) -> str:
    return (datetime(2026, 10, 1, 8, tzinfo=timezone.utc) + timedelta(minutes=minutes)).isoformat()


class _Db:
    def __init__(self):
        self.plans, self.events, self.answers, self.audio = {}, [], [], {}

    def plan(self, pid, user, **row):
        self.plans[pid] = {"id": pid, "user_id": user, "status": "active", "level": "pauses",
                           "level_by": "machine", "facts": {"mode": "new", "language": "en", "key_line": "The window closes."},
                           "deadline": "2026-11-14", "created_at": _at(0), **row}

    def event(self, pid, reason, level="pauses", by="machine", at=1):
        self.events.append({"plan_id": pid, "user_id": self.plans[pid]["user_id"], "level": level,
                            "reason": reason, "by_who": by, "created_at": _at(at)})

    def list_waiting_plans(self):
        return [dict(p) for p in self.plans.values()
                if p["status"] in ("asking", "active") and p.get("level")]

    def get_plan_by_id(self, pid):
        return dict(self.plans[pid]) if pid in self.plans else None

    def list_plans_level_events(self, ids, reasons):
        return [e for e in self.events if e["plan_id"] in ids and e["reason"] in reasons]

    def list_plan_level_events(self, user_id, pid):
        return [e for e in self.events if e["plan_id"] == pid]

    def insert_plan_level_event(self, row):
        self.events.append({**row, "created_at": datetime.now(timezone.utc).isoformat()})
        return True

    def update_plan(self, user_id, pid, fields):
        self.plans[pid].update(fields)
        return dict(self.plans[pid])

    def list_plan_answers(self, user_id, pid):
        return [a for a in self.answers if a["plan_id"] == pid]

    def get_plan_answer_audio(self, user_id, answer_id):
        return self.audio.get(answer_id)


@pytest.fixture
def clock(monkeypatch):
    """The coach's answers happen at ``_at(clock.minutes)``."""
    class Clock:
        minutes = 10
    monkeypatch.setattr(C, "_now", lambda: datetime.fromisoformat(_at(Clock.minutes)))
    return Clock


def _items(db, rater=COACH, proficient=("en",), matched=(), queued=()):
    return C.queue_items(db, rater_id=rater, proficient=list(proficient),
                         matched_users=set(matched), queued_users=set(queued))


def _open(db, pid, rater=COACH, own_answer=False):
    return C.plan_for(db, db.get_plan_by_id(pid), rater_id=rater, proficient=["en"],
                      matched_users=set(), queued_users=set(), own_answer=own_answer)


def test_a_plan_reaches_the_queue_on_its_speakers_card():
    db = _Db()
    db.plan("p1", LARK)                                   # a new plan, no Take yet
    db.plan("p2", WREN, facts={"mode": "takes"})          # a plan from Takes, no key line: asked
    db.event("p2", "stuck", at=2)
    db.event("p2", "ask_coach", at=3)
    db.plan("p3", FINCH, level="key_line", facts={"mode": "takes"})
    db.event("p3", "stuck", level="key_line", at=4)
    db.plan("p4", "u4", facts={"key_line": "Okno się zamyka.", "language": "pl"})   # a language this coach lacks
    db.plan("p5", "u5", facts={"key_line": "The window closes.", "language": "en"})   # Takes only in other languages

    items = _items(db, matched=[WREN, FINCH], queued=[WREN, FINCH, "u5"])
    assert [(i["plan"]["id"], i["kind"]) for i in items] == [("p1", "new"), ("p2", "asked"), ("p3", "stuck")]

    heron = {"pseudonym": "Quiet Heron", "goal": None, "takes": [{"session_id": "t"}], "waiting": 4}
    wren = {"pseudonym": "Warm Wren", "goal": None, "takes": [{"session_id": "w"}], "waiting": 0}
    finch = {"pseudonym": "Bold Finch", "goal": None, "takes": [{"session_id": "f"}], "waiting": 0}
    names = {LARK: "Swift Lark", WREN: "Warm Wren", FINCH: "Bold Finch"}
    queue = C.with_plans([heron, wren, finch], items, pseudonym_for=names.get,
                         goal_for=lambda uid: "Win next year's budget from the board." if uid == LARK else None)
    assert [s["pseudonym"] for s in queue] == ["Swift Lark", "Warm Wren", "Bold Finch", "Quiet Heron"]
    lark = queue[0]
    assert lark["takes"] == [] and lark["goal"] == "Win next year's budget from the board."
    assert lark["plan"] == {"plan_id": "p1", "kind": "new", "since": _at(0), "deadline_short": "Sat 14 Nov"}
    assert queue[1]["plan"]["kind"] == "asked" and "level_name" not in queue[1]["plan"]
    assert queue[2]["plan"]["level_name"] == "Let your key line land"
    assert "plan" not in queue[3]


def test_the_pick_is_blind_and_what_happened_comes_with_it():
    db = _Db()
    db.plan("p1", LARK, facts={"mode": "new", "language": "en", "key_line": "The window closes.",
                               "key_answer_id": "a2"})
    db.event("p1", "diagnosis", at=0)
    db.answers += [{"id": "a1", "plan_id": "p1", "kind": "why", "duration_ms": 64000},
                   {"id": "a2", "plan_id": "p1", "kind": "key", "duration_ms": 6000},
                   {"id": "a3", "plan_id": "p1", "kind": "stress", "value": 7}]
    plan, kind = _open(db, "p1")
    shown = C.blind(db, plan, kind, pseudonym="Swift Lark")
    assert shown["why"] == {"answer_id": "a1", "duration_ms": 64000}
    assert shown["key_line"] == {"text": "The window closes.", "answer_id": "a2", "duration_ms": 6000}
    assert [lv["name"] for lv in shown["levels"]] == [
        "Say it once, and it lands", "Let your key line land", "Pauses that hold the room",
        "A voice that moves", "Make it yours"]
    assert "pauses" not in repr({k: v for k, v in shown.items() if k != "levels"})  # Never 2

    after = C.pick(db, plan, kind, "key_line", rater_id=COACH)
    assert after["you"]["name"] == "Let your key line land"
    assert after["machine"]["name"] == "Pauses that hold the room"
    assert after["deadline_short"] == "Sat 14 Nov"
    assert (after["stress"], after["ready"]) == (7, None)   # Ready not given: not shown
    assert db.plans["p1"]["level"] == "key_line" and db.plans["p1"]["level_by"] == "coach"
    assert db.events[-1]["reason"] == "coach" and db.events[-1]["by_who"] == "coach"
    with pytest.raises(C.CoachPlanError):
        C.pick(db, plan, kind, "louder", rater_id=COACH)


def test_an_answer_takes_the_plan_out_of_the_queue(clock):
    db = _Db()
    db.plan("p1", LARK)
    plan, kind = _open(db, "p1")
    C.pick(db, plan, kind, "say_once", rater_id=COACH)
    assert _items(db) == [] and _items(db, rater=OTHER_COACH) == []

    plan, kind = _open(db, "p1", own_answer=True)         # Change my answer
    assert kind is None
    C.pick(db, plan, kind, "voice_moves", rater_id=COACH)
    assert db.plans["p1"]["level"] == "voice_moves"
    with pytest.raises(C.CoachPlanError):
        _open(db, "p1", rater=OTHER_COACH, own_answer=True)

    db.event("p1", "ask_coach", by="speaker", at=20)      # the speaker asks again
    assert [i["kind"] for i in _items(db)] == ["asked"]
    plan, kind = _open(db, "p1")
    clock.minutes = 30
    C.unclear(db, plan, rater_id=COACH)
    assert _items(db) == [] and [i["kind"] for i in _items(db, rater=OTHER_COACH)] == ["asked"]


def test_a_stuck_level_is_answered_with_the_coachs_video(clock):
    db = _Db()
    db.plan("p3", FINCH, level="key_line", facts={"mode": "takes", "language": "en", "level_take": "take-6"})
    db.event("p3", "stuck", level="key_line", at=4)
    plan, kind = _open(db, "p3")
    shown = C.blind(db, plan, kind, pseudonym="Bold Finch")
    assert shown == {"plan_id": "p3", "kind": "stuck", "pseudonym": "Bold Finch",
                     "level_name": "Let your key line land", "take_session_id": "take-6"}
    with pytest.raises(C.CoachPlanError):
        C.pick(db, plan, kind, "pauses", rater_id=COACH)
    C.answered(db, plan, kind, rater_id=COACH)
    assert _items(db) == []
    db.plans["p3"]["level"] = "pauses"                    # a new level, stuck again
    db.event("p3", "stuck", level="pauses", at=20)
    assert [i["kind"] for i in _items(db)] == ["stuck"]


def test_only_the_voice_message_and_the_key_line_play():
    db = _Db()
    db.plan("p1", LARK, facts={"mode": "new", "key_line": "x", "key_answer_id": "a2"})
    db.answers += [{"id": "a1", "plan_id": "p1", "kind": "why"},
                   {"id": "a2", "plan_id": "p1", "kind": "key"},
                   {"id": "a3", "plan_id": "p1", "kind": "worry"}]
    db.audio = {a: {"content_type": "audio/webm", "audio": b"x"} for a in ("a1", "a2", "a3")}
    plan = db.get_plan_by_id("p1")
    assert C.answer_audio(db, plan, "a1")["audio"] == b"x"
    assert C.answer_audio(db, plan, "a2")["audio"] == b"x"
    with pytest.raises(C.CoachPlanError):
        C.answer_audio(db, plan, "a3")
