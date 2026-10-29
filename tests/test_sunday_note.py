"""
STORY    As the founder, I want Will to show me one pattern from my own # notes
         of the last seven days, on Sunday evening when there is one and
         whenever I ask in my own words, and to walk me through it in a lens,
         so that I name the bug myself, see the principle I had, write my own
         reflection and keep the principle it teaches only if I say so.
OUTCOME
  O1  On Sunday from 6 pm in my time zone, once, the case comes by itself
      only when my notes show a pattern, and not again within seven days;
      with nothing to find, nothing is sent.
  O2  Will reads only my # notes of the last seven days (the talk goal and
      my principles as context), and the case is one sentence, no numbers.
  O3  Asked in my own words, "We spotted a pattern!" and the case come with
      Not now | Investigate; with nothing to find, one bubble says so, and
      a # note or anyone else is left alone.
  O4  The lens asks, in order, which bug (four, or my own new one), which of
      the two likely principles I had (or None yet), my reflection (or
      Skip), then Will's new principle; only Accept or my edited wording
      adds it to my Life Panel; every step is a row of the one thread, a
      repeat tap writes nothing, and the lens reopens where it stands.
  O5  Not now under the case lands as my bubble, then "Noted.".
  O6  Will reads my last case in the chat.
  O7  A week whose notes show sales stalling asks "Which step was it?" with
      the sale's four steps (or my own) in place of the bugs, only where the
      sales framing is on; without it, the bugs as before (N241 P3).
PROVES   O1 -> test_sunday_brings_a_case_only_when_my_notes_show_one
         O2 -> test_only_my_notes_of_the_last_seven_days_are_read
         O3 -> test_asked_in_my_own_words
         O4 -> test_the_lens_walks_me_through_it_and_adds_only_on_my_yes
         O5 -> test_not_now_under_the_case
         O6 -> test_will_reads_my_last_case
         O7 -> test_a_sales_week_asks_the_step_not_the_bug
WHY      Will learning plan, step 2: the Sunday note as a lens (locked
         2026-10-26, N158, N170; rules in the frontend's principles.md §1 L).
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from services import sunday_note as sn
from services import voice_notebook

CASE = {"case": "Twice this week you put off calling the client because you did not feel like it.",
        "principles": [2, 1], "new_principle": "Make the call before you feel ready."}
HELD = [{"id": "h1", "title": "Reach out first"}, {"id": "h2", "title": "Ask, do not assume"},
        {"id": "h3", "title": "Sleep on big decisions"}]


def _note(text, *, days):
    at = datetime.now(timezone.utc) - timedelta(days=days)
    return {"text_clean": text, "created_at": at.isoformat()}


class _Db:
    def __init__(self):
        self.thread = {}
        self.notes = {}
        self.consent = {"u": {"decision": "yes", "time_zone": "Europe/Warsaw"}}
        self.voice = [_note("I don't feel like calling the client today", days=5),
                      _note("Postponed the call again", days=2),
                      _note("An old note, from two weeks back", days=14)]

    # lounge
    def insert_lounge_messages(self, user_id, rows):
        for r in rows:
            self.thread.setdefault((user_id, r["client_id"]), {**r, "user_id": user_id})
        return [self.thread[(user_id, r["client_id"])] for r in rows]

    def get_lounge_messages_page(self, user_id, limit=50):
        mine = [r for (u, _), r in self.thread.items() if u == user_id]
        return list(reversed(mine))[:limit]

    # notebook
    def get_voice_notebook_consent(self, user_id):
        return self.consent.get(user_id)

    def list_voice_notebook_consents(self):
        return [{"user_id": u, **c} for u, c in self.consent.items() if c["decision"] == "yes"]

    def list_voice_notes(self, user_id, limit=20):
        return list(self.voice)

    def get_user_profile(self, user_id):
        return {"goal": "They book a demo"}

    def get_speaker_memory(self, user_id):
        return None

    # sunday_notes
    def insert_sunday_note(self, row):
        if row["source"] == "sunday" and any(
                n["source"] == "sunday" and n["user_id"] == row["user_id"]
                and n["week_start"] == row["week_start"] for n in self.notes.values()):
            return None
        note = {**row, "id": f"s{len(self.notes) + 1}", "status": "claimed",
                "created_at": datetime.now(timezone.utc).isoformat()}
        self.notes[note["id"]] = note
        return note

    def update_sunday_note(self, note_id, fields):
        self.notes[note_id].update(fields)
        return True

    def get_sunday_note(self, user_id, note_id):
        note = self.notes.get(note_id)
        return note if note and note["user_id"] == user_id else None

    def get_sunday_note_for_week(self, user_id, week_start):
        return next((n for n in self.notes.values() if n["source"] == "sunday"
                     and n["user_id"] == user_id and n["week_start"] == week_start), None)

    def latest_sunday_note(self, user_id):
        written = [n for n in self.notes.values() if n["status"] == "written"]
        return written[-1] if written else None

    def bodies(self, user_id="u"):
        return [r["body"] for r in reversed(self.get_lounge_messages_page(user_id, 500))]


@pytest.fixture
def founder(monkeypatch):
    seen = {"case": dict(CASE), "users": []}
    monkeypatch.setattr("services.rings.feature_is_on_for_user",
                        lambda feature, user, database=None: user == "u")
    monkeypatch.setattr(sn, "_under_authority", lambda db, user, key, write: write())

    def model(**kw):
        if "Decide whether" in kw["system"]:
            return SimpleNamespace(text="{}", parsed={"asks": "pattern" in kw["user"]})
        seen["users"].append(kw["user"])
        return SimpleNamespace(text="{}", parsed=dict(seen["case"]))
    monkeypatch.setattr("services.llm.chat_complete", model)
    held = list(HELD)
    monkeypatch.setattr("services.life_store.principles", lambda user, limit=500: list(held))
    monkeypatch.setattr("services.life_store.insert_item",
                        lambda user, fields: held.append({**fields, "id": "p9"}) or held[-1])
    seen["held"] = held
    return seen


def _asked(db):
    turn = sn.chat_turn(db, "u", "do you see a pattern?")
    db.insert_lounge_messages("u", [sn._row("asked-head", "bot", turn["answer"],
                                            turn["row_metadata"], "2026-10-26T10:00:00")])
    sn.after_head(db, "u", turn["case"])
    return turn["case"]


def test_sunday_brings_a_case_only_when_my_notes_show_one(founder, monkeypatch):
    # 16:30 UTC on Sunday 2026-10-25 is 17:30 in Warsaw: not yet.
    assert sn.due_week(datetime(2026, 10, 25, 16, 30, tzinfo=timezone.utc), "Europe/Warsaw") is None
    assert str(sn.due_week(datetime(2026, 10, 25, 17, 5, tzinfo=timezone.utc),
                           "Europe/Warsaw")) == "2026-10-19"
    assert sn.due_week(datetime(2026, 10, 26, 9, 0, tzinfo=timezone.utc), "Europe/Warsaw") is None

    db = _Db()
    monkeypatch.setattr("services.db.db", db, raising=False)
    monkeypatch.setattr("services.job_queue.enqueue",
                        lambda path, *args, **_: sn.run_sunday(*args) or True)
    sunday_evening = datetime(2026, 10, 25, 17, 5, tzinfo=timezone.utc)
    sn.run_sunday("u", datetime.now(timezone.utc).isoformat())
    assert db.bodies()[-2:] == [sn.COPY["head"], CASE["case"]]
    assert sn.sweep_due(db, sunday_evening) == 1
    assert db.bodies().count(sn.COPY["head"]) == 1  # not again within seven days

    quiet = _Db()
    monkeypatch.setattr("services.db.db", quiet, raising=False)
    founder["case"] = {"case": "", "principles": [], "new_principle": ""}
    sn.run_sunday("u", datetime.now(timezone.utc).isoformat())
    assert quiet.bodies() == []  # nothing to find: nothing is sent on Sunday


def test_only_my_notes_of_the_last_seven_days_are_read(founder):
    db = _Db()
    found, note = sn.compose(db, "u", source="asked", now=datetime.now(timezone.utc),
                             zone_name="Europe/Warsaw")
    read = founder["users"][-1]
    assert found == "case" and note["body"] == CASE["case"]
    assert "Postponed the call again" in read and "two weeks back" not in read
    assert "1. Reach out first" in read and "Talk goal: They book a demo" in read
    assert [p["title"] for p in note["likely"]] == ["Ask, do not assume", "Reach out first"]

    founder["case"] = {**CASE, "case": "You called 3 times."}
    assert sn.compose(db, "u", source="asked", now=datetime.now(timezone.utc),
                      zone_name=None)[0] == "nothing"  # a number is never shown


def test_asked_in_my_own_words(founder):
    db = _Db()
    _asked(db)
    assert db.bodies()[-2:] == [sn.COPY["head"], CASE["case"]]
    case_row = db.get_lounge_messages_page("u", 1)[0]
    assert case_row["metadata"]["offer"] == sn.OFFER

    founder["case"] = {"case": "", "principles": [], "new_principle": ""}
    assert sn.chat_turn(db, "u", "any pattern this week?")["answer"] == sn.COPY["nothing"]
    db.voice = []
    assert sn.chat_turn(db, "u", "Sunday note")["answer"] == sn.COPY["no_notes"]
    assert sn.chat_turn(db, "u", "# a note about a pattern") is None  # a note stays a note
    assert sn.chat_turn(db, "u", "how do I slow down my opening?") is None
    assert sn.chat_turn(db, "someone", "sunday note") is None


def test_the_lens_walks_me_through_it_and_adds_only_on_my_yes(founder):
    db = _Db()
    note = _asked(db)
    nid = str(note["id"])
    sn.answer(db, "u", nid, "open")
    sn.answer(db, "u", nid, "open")  # opened again: asked once
    assert sn.state(db, "u", nid)["step"] == "bug"
    assert sn.answer(db, "u", nid, "reflection", "out of turn")["step"] == "bug"

    sn.answer(db, "u", nid, "bug", "Fear of rejection")
    shown = sn.answer(db, "u", nid, "applied", "h2")
    assert [p["id"] for p in shown["likely"]] == ["h2", "h1"]
    shown = sn.answer(db, "u", nid, "reflection", "")
    assert shown["step"] == "principle"
    assert [r["body"] for r in shown["rows"]] == [
        sn.COPY["which"], "👾 Fear of rejection", sn.COPY["applied"], "⚜️ Ask, do not assume",
        sn.COPY["reflections"], sn.COPY["skip"], sn.COPY["suggests"],
        f"⚜️ {CASE['new_principle']}"]
    assert len(founder["held"]) == 3  # nothing added before I say so

    shown = sn.answer(db, "u", nid, "principle", {"choice": "edit", "text": "Call first, feel later."})
    assert shown["step"] == "done" and shown["rows"][-1]["body"] == sn.COPY["added"]
    assert founder["held"][-1]["title"] == "Call first, feel later."
    sn.answer(db, "u", nid, "principle", "accept")  # a repeat tap writes nothing
    assert len(founder["held"]) == 4

    other = _asked(db)
    oid = str(other["id"])
    for step, value in (("open", None), ("bug", "hubris"), ("applied", "none"),
                        ("reflection", "I wait for a mood that never comes."),
                        ("principle", "not_now")):
        sn.answer(db, "u", oid, step, value)
    assert db.notes[oid]["pattern"] == "hubris" and len(founder["held"]) == 4


def test_not_now_under_the_case(founder):
    db = _Db()
    note = _asked(db)
    shown = sn.answer(db, "u", str(note["id"]), "dismiss")
    assert db.bodies()[-2:] == [sn.COPY["not_now"], sn.COPY["noted"]]
    assert shown["step"] == "closed"


def test_will_reads_my_last_case(founder):
    db = _Db()
    note = _asked(db)
    sn.answer(db, "u", str(note["id"]), "open")
    sn.answer(db, "u", str(note["id"]), "bug", "hubris")
    block = voice_notebook.prompt_block(db, "u")
    assert CASE["case"] in block and "They named it hubris." in block


def test_a_sales_week_asks_the_step_not_the_bug(founder, monkeypatch):
    founder["case"] = {**CASE, "kind": "sales",
                       "case": "Your deals went quiet after the proposal: Acme, Nordic and Bauer.",
                       "new_principle": "Book the next call before you send the proposal."}
    db = _Db()
    nid = str(_asked(db)["id"])
    sn.answer(db, "u", nid, "open")
    shown = sn.answer(db, "u", nid, "bug", "follow_up")
    assert shown["kind"] == "sales"
    assert [r["body"] for r in shown["rows"]] == [
        sn.COPY["which_step"], "📨 The follow-up", sn.COPY["applied"]]
    assert db.notes[nid].get("pattern") is None  # a step is not a bug

    other = str(_asked(db)["id"])
    sn.answer(db, "u", other, "open")
    assert sn.answer(db, "u", other, "bug", "Pricing")["rows"][1]["body"] == "Pricing"

    monkeypatch.setattr("services.rings.feature_is_on_for_user",
                        lambda feature, user, database=None: user == "u" and feature != "sales_framing")
    plain = str(_asked(db)["id"])
    sn.answer(db, "u", plain, "open")
    shown = sn.answer(db, "u", plain, "bug", "hubris")
    assert shown["kind"] == "self" and shown["rows"][0]["body"] == sn.COPY["which"]
