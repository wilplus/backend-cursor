"""
STORY    As the founder, I want Will to write me one case about my week on
         Sunday evening, in my own form, so that I see which bug drove it,
         whether I knew it, and can keep the principle it teaches.
OUTCOME
  O1  The note comes on Sunday from 6 pm in my own time zone, once a week;
      not before, and not again that week.
  O2  It is in my form: the case, which of the four bugs it was and why,
      the principles I applied, reflections, a new principle. No numbers.
  O3  Old or New is kept; a new principle follows; Add principle puts it
      among my active Life Panel principles and says "Noted."; Not now
      keeps it out; a second tap changes nothing.
  O4  Typing "sunday note" writes one now; for anyone without the
      notebook nothing changes.
  O5  Will reads last week's case in the chat.
PROVES   O1 -> test_it_is_due_on_sunday_evening_in_my_time_and_once_a_week
         O2 -> test_the_note_is_in_my_form_without_numbers
         O3 -> test_old_or_new_then_the_principle_only_on_my_yes
         O4 -> test_asking_writes_one_now_and_nobody_else_is_touched
         O5 -> test_will_reads_last_weeks_case
WHY      Will learning plan, step 2 (founder 2026-10-20, "start step 2"; the
         form is the founder's own).
"""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from services import sunday_note as sn
from services import voice_notebook

WEEK = {"case": "You rewrote the opening three times and never tested it on anyone.",
        "pattern": "hubris", "why": "You trusted your own read over a listener.",
        "applied": "Radical open-mindedness, weighed below speed this week.",
        "reflections": "Your talk goal needs a listener's ears, not your own.",
        "new_principle": "Test an opening on one person before rewriting it."}


class _Db:
    def __init__(self):
        self.thread = {}
        self.notes = {}
        self.consent = {"u": {"decision": "yes", "time_zone": "Europe/Warsaw"}}

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
        return [{"text_clean": "I rush the close", "created_at": "2026-10-19T09:00:00+00:00"}]

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
        note = {**row, "id": f"s{len(self.notes) + 1}", "status": "claimed"}
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
    monkeypatch.setattr("services.rings.feature_is_on_for_user",
                        lambda feature, user, database=None: user == "u")
    monkeypatch.setattr(sn, "_under_authority", lambda db, user, key, write: write())
    monkeypatch.setattr("services.llm.chat_complete",
                        lambda **_: SimpleNamespace(text="{}", parsed=dict(WEEK)))
    held = []
    monkeypatch.setattr("services.life_store.principles", lambda user, limit=500: list(held))
    monkeypatch.setattr("services.life_store.insert_item",
                        lambda user, fields: held.append({**fields, "id": "p1"}) or held[-1])
    return held


def test_it_is_due_on_sunday_evening_in_my_time_and_once_a_week(founder, monkeypatch):
    # 16:30 UTC on Sunday 2026-10-25 is 17:30 in Warsaw: not yet.
    assert sn.due_week(datetime(2026, 10, 25, 16, 30, tzinfo=timezone.utc), "Europe/Warsaw") is None
    week = sn.due_week(datetime(2026, 10, 25, 17, 5, tzinfo=timezone.utc), "Europe/Warsaw")
    assert str(week) == "2026-10-19"  # that week's Monday
    assert sn.due_week(datetime(2026, 10, 26, 9, 0, tzinfo=timezone.utc), "Europe/Warsaw") is None

    db = _Db()
    queued = []
    monkeypatch.setattr("services.db.db", db, raising=False)
    monkeypatch.setattr("services.job_queue.enqueue",
                        lambda path, *args, **_: queued.append(args) or sn.run_sunday(*args) or True)
    sunday_evening = datetime(2026, 10, 25, 17, 5, tzinfo=timezone.utc)
    assert sn.sweep_due(db, sunday_evening) == 1
    assert sn.sweep_due(db, sunday_evening) == 0  # once a week
    assert db.bodies()[-1].startswith(sn.HEADINGS["case"])


def test_the_note_is_in_my_form_without_numbers(founder):
    body, pattern, principle = sn.render(dict(WEEK))
    heads = [line for line in body.splitlines() if line.isupper() or line.endswith("⚜️")]
    assert heads == [sn.HEADINGS[k] for k in ("case", "which", "applied", "reflections", "new")]
    assert "👾 Hubris: You trusted your own read over a listener." in body
    assert all(label in body for label in sn.PATTERNS.values())
    assert pattern == "hubris" and principle == WEEK["new_principle"]

    with_number = sn.render({**WEEK, "case": "You practised 3 times."})[0]
    assert "3" not in with_number and sn.HEADINGS["case"] not in with_number


def test_old_or_new_then_the_principle_only_on_my_yes(founder):
    db = _Db()
    note = sn.compose(db, "u", source="asked", week_start=datetime(2026, 10, 19).date(),
                      zone_name="Europe/Warsaw")

    rows = sn.mark(db, "u", note["id"], "old")
    assert [r["body"] for r in rows] == ["Old", f"⚜️ {WEEK['new_principle']}"]
    assert db.notes[note["id"]]["pattern_known"] == "old"
    assert sn.mark(db, "u", note["id"], "new") == []  # a second tap changes nothing
    assert founder == []  # nothing added before the founder says so

    rows = sn.principle(db, "u", note["id"], "add")
    assert [r["body"] for r in rows] == ["Add principle", "Noted."]
    assert founder[0]["status"] == "active" and founder[0]["title"] == WEEK["new_principle"]
    assert sn.principle(db, "u", note["id"], "add") == []

    other = sn.compose(db, "u", source="asked", week_start=datetime(2026, 10, 19).date(),
                       zone_name=None)
    sn.mark(db, "u", other["id"], "new")
    sn.principle(db, "u", other["id"], "not_now")
    assert len(founder) == 1


def test_asking_writes_one_now_and_nobody_else_is_touched(founder):
    db = _Db()
    turn = sn.chat_turn(db, "u", "Sunday note")
    assert turn["answer"].startswith(sn.HEADINGS["case"])
    assert turn["row_metadata"]["offer"] == sn.OFFER

    assert sn.chat_turn(db, "someone", "sunday note") is None
    assert sn.chat_turn(db, "u", "what about my sunday note from last week?") is None


def test_will_reads_last_weeks_case(founder):
    db = _Db()
    note = sn.compose(db, "u", source="asked", week_start=datetime(2026, 10, 19).date(),
                      zone_name=None)
    sn.mark(db, "u", note["id"], "new")
    block = voice_notebook.prompt_block(db, "u")
    assert "hubris (a new bug)" in block
