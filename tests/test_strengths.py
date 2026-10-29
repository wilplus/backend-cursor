"""
STORY    As a speaker, I want Will to notice a strength that shows in my notes
         on two different days, let me keep it in my own words, gather the
         notes that show it, and bring one back the day before my talk, so
         that I go on stage remembering what I am good at.
OUTCOME
  O1  A trait in my newest note and on another day (or in my life goals
      answer) is suggested once: "We spotted a strength!" with Not now |
      Look; never from one day alone, never one I keep, one at a time (N2).
  O2  In the lens I see the notes it came from with their days; Accept or my
      own words keep it ("Noted. Added to your strengths."); Not now keeps
      nothing and it is not suggested again (N2).
  O3  A later note that shows a kept strength gets "That's your 💪 … again."
      once, and the note is kept under it; the Life Panel lists every note,
      newest first; only I archive one, and it stays (N1, N3, N5).
  O4  The first open of the day before a talk (the plan's deadline or a date
      a note named) brings back one kept strength with its note, once; no
      date, nothing (N4).
  O5  Without the ring row, or for a crisis note, nothing is read or shown.
PROVES   O1 -> test_a_trait_on_two_days_is_suggested_once
         O2 -> test_i_keep_it_in_my_words_or_not_at_all
         O3 -> test_a_kept_strength_gathers_its_notes_and_only_i_archive_it
         O4 -> test_the_day_before_my_talk_one_strength_comes_back
         O5 -> test_without_the_ring_or_in_a_crisis_nothing
WHY      Linear WIL-112; founder 2026-10-28, N241; words signed N258.
"""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from services import strengths as st


class _Db:
    def __init__(self):
        self.thread = {}
        self.notes = []
        self.plan = None

    def insert_lounge_messages(self, user_id, rows):
        for r in rows:
            self.thread.setdefault((user_id, r["client_id"]), {**r, "user_id": user_id})
        return [self.thread[(user_id, r["client_id"])] for r in rows]

    def get_lounge_messages_page(self, user_id, limit=50):
        mine = [r for (u, _), r in self.thread.items() if u == user_id]
        return list(reversed(mine))[:limit]

    def list_voice_notes(self, user_id, limit=20):
        return [n for n in self.notes if n["user_id"] == user_id][-limit:]

    def get_voice_notebook_consent(self, user_id):
        return {"decision": "yes", "time_zone": "UTC"}

    def get_open_plan(self, user_id):
        return self.plan

    def note(self, text, on, user_id="u"):
        self.notes.append({"id": f"n{len(self.notes) + 1}", "user_id": user_id,
                           "text_clean": text, "created_at": f"{on}T10:00:00"})

    def bodies(self):
        return [r["body"] for r in self.thread.values()]


class _Store:
    def __init__(self):
        self.strengths, self.notes, self.talks, self.goals = [], [], {}, []

    def list_goals(self, user_id, status="active"):
        return list(self.goals)

    def list_strengths(self, user_id):
        return [dict(s) for s in self.strengths]

    def insert_strength(self, user_id, fields):
        self.strengths.append({"id": f"s{len(self.strengths) + 1}", **fields})
        return dict(self.strengths[-1])

    def update_strength(self, user_id, sid, fields):
        for s in self.strengths:
            if s["id"] == sid:
                s.update(fields)
                return dict(s)
        return None

    def insert_strength_note(self, user_id, sid, fields):
        self.notes.append({"strength_id": sid, **fields})
        return self.notes[-1]

    def strength_notes(self, user_id):
        return sorted(self.notes, key=lambda n: n["noted_on"])

    def save_talk_date(self, user_id, on, note_id):
        self.talks.setdefault(on, {"talk_on": on, "note_id": note_id, "reminded_at": None})
        return self.talks[on]

    def talk_dates(self, user_id):
        return list(self.talks.values())

    def mark_talk_reminded(self, user_id, on):
        self.talks.setdefault(on, {"talk_on": on})["reminded_at"] = "now"
        return True


@pytest.fixture
def me(monkeypatch):
    store = _Store()
    for name in ("list_goals", "list_strengths", "insert_strength", "update_strength",
                 "insert_strength_note", "strength_notes", "save_talk_date", "talk_dates",
                 "mark_talk_reminded"):
        monkeypatch.setattr(f"services.life_store.{name}", getattr(store, name))
    monkeypatch.setattr("services.rings.feature_is_on_for_user",
                        lambda feature, user, database=None: user == "u")
    monkeypatch.setattr("services.plan_flow.onboarding", lambda database, user: False)
    reads, seen = [], []

    def model(**kw):
        seen.append(kw["user"])
        return SimpleNamespace(parsed=reads.pop(0) if reads else {})
    monkeypatch.setattr("services.llm.chat_complete", model)
    return store, reads, seen


CALM = {"kept": None, "talk_on": None,
        "suggest": {"title": "Calm when it goes wrong",
                    "sentence": "This week you stayed steady when things went wrong.",
                    "others": [1]}}


def test_a_trait_on_two_days_is_suggested_once(me):
    store, reads, seen = me
    db = _Db()
    db.note("# Client shouted on the call. I stayed calm and we fixed it", "2026-10-26")
    db.note("# The demo crashed and I just kept talking", "2026-10-28")
    reads.append(CALM)
    rows = st.after_note(db, "u")
    assert [r["body"] for r in rows] == ["We spotted a strength!", CALM["suggest"]["sentence"]]
    assert rows[-1]["metadata"]["offer"] == "strengths"
    assert [n["noted_on"] for n in store.notes] == ["2026-10-26", "2026-10-28"]
    assert "1. (2026-10-26)" in seen[-1]

    db.note("# Kept my head again in the board meeting", "2026-10-29")
    reads.append({**CALM, "suggest": {**CALM["suggest"], "title": "Steady"}})
    assert st.after_note(db, "u") == []  # one suggestion open at a time

    same_day = _Db()
    same_day.note("# Stayed calm", "2026-10-28")
    same_day.note("# Stayed calm again", "2026-10-28")
    store.strengths.clear()
    reads.append(CALM)
    assert st.after_note(same_day, "u") == []  # never from one day alone


def test_i_keep_it_in_my_words_or_not_at_all(me):
    store, reads, _ = me
    store.goals.append({"created_at": "2026-10-20T09:00:00",
                        "ladder": {"answers": {"nature": "I see what people could become, and I don't give up."}}})
    db = _Db()
    db.note("# Third try with the bank. I'm not letting go", "2026-10-27")
    reads.append({"kept": None, "talk_on": None,
                  "suggest": {"title": "Staying with it", "sentence": "You said it, and you did it.",
                              "others": [0]}})
    rows = st.after_note(db, "u")
    sid = rows[0]["metadata"]["strength_id"]
    lens = st.suggestion(db, "u", sid)
    assert [n["label"] for n in lens["notes"]] == ["Your life goals answer", None]
    assert lens["notes"][0]["on_label"] == "20 October"
    assert [r["body"] for r in st.decide(db, "u", sid, "edit", "Not letting go")] == [
        "Noted. Added to your strengths."]
    assert store.strengths[0]["title"] == "Not letting go" and store.strengths[0]["status"] == "kept"
    assert st.decide(db, "u", sid, "accept") == []  # decided once

    db.note("# Calm again today", "2026-10-29")
    db.note("# Calm when the slides died", "2026-10-30")
    reads.append({**CALM, "suggest": {**CALM["suggest"], "others": [2]}})
    sid2 = st.after_note(db, "u")[0]["metadata"]["strength_id"]
    assert [r["body"] for r in st.answer_ask(db, "u", sid2, "not_now")] == ["Not now", "Noted."]
    assert store.strengths[1]["status"] == "not_now"


def test_a_kept_strength_gathers_its_notes_and_only_i_archive_it(me):
    store, reads, _ = me
    store.strengths.append({"id": "s1", "title": "Calm when it goes wrong", "status": "kept",
                            "kept_at": "2026-10-28T10:00:00"})
    store.notes.append({"strength_id": "s1", "body": "The demo crashed", "noted_on": "2026-10-28",
                        "source": "note"})
    db = _Db()
    db.note("# Board meeting went sideways. I slowed down and walked them through it", "2026-11-03")
    reads.append({"kept": "K1", "suggest": None, "talk_on": None})
    rows = st.after_note(db, "u")
    assert [r["body"] for r in rows] == ["That's your 💪 Calm when it goes wrong again."]
    listed = st.listing(db, "u")["kept"][0]
    assert [n["on"] for n in listed["notes"]] == ["2026-11-03", "2026-10-28"]
    archived = st.archive(db, "u", "s1")
    assert not archived["kept"] and archived["archived"][0]["notes"]


def test_the_day_before_my_talk_one_strength_comes_back(me):
    store, reads, _ = me
    store.strengths.append({"id": "s1", "title": "Calm when it goes wrong", "status": "kept"})
    store.notes.append({"strength_id": "s1", "body": "The demo crashed and I kept talking",
                        "noted_on": "2026-10-28", "source": "note"})
    db = _Db()
    on_10 = datetime(2026, 11, 10, 7, 0, tzinfo=timezone.utc)
    assert st.today(db, "u", now=on_10) == []  # no date, no reminder
    db.note("# Pitch to Nordic on 11 November", "2026-11-05")
    reads.append({"kept": None, "suggest": None, "talk_on": "2099-11-11"})
    st.after_note(db, "u")
    assert "2099-11-11" in store.talks
    db.plan = {"deadline": "2026-11-11"}
    rows = st.today(db, "u", now=on_10)
    assert [r["body"] for r in rows] == ["Your talk is tomorrow.", "Remember your 💪 Calm when it goes wrong:",
                                         "“The demo crashed and I kept talking”"]
    assert st.today(db, "u", now=on_10) == []  # once


def test_without_the_ring_or_in_a_crisis_nothing(me):
    store, reads, seen = me
    db = _Db()
    db.note("# I want to die before this talk", "2026-10-28")
    assert st.after_note(db, "u") == []
    db.note("# Stayed calm", "2026-10-29", user_id="someone")
    assert st.after_note(db, "someone") == [] and st.today(db, "someone") == []
    assert not seen
    with pytest.raises(st.StrengthError):
        st.listing(db, "someone")
