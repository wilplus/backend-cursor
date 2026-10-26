"""
STORY    As the founder, I want Will to write me one case about my week when I
         ask for it, from my own # notes only, in my own form, so that I see
         which bug drove it and can keep the principle it teaches.
OUTCOME
  O1  Nothing comes on a schedule: the worker's sweep has no Sunday job, and
      typing "sunday note" writes one now; for anyone without the notebook
      nothing changes.
  O2  It is in my form: the case, which of the four bugs it was and why,
      the principles I applied, reflections, a new principle. No numbers.
  O3  Only my # notes are evidence: my talk goal and the principles I hold
      are context; the Lounge thread, a Take's summary and Will's note on me
      never reach it.
  O4  A week without a # note gets no case.
  O5  A new case asks no Old or New: Not now | Add principle comes under it
      when there is a new principle; Add principle puts it among my active
      Life Panel principles and says "Noted."; Not now keeps it out; a
      second tap changes nothing. Without a new principle the case is a
      plain bubble.
  O6  A case written before the change still answers Old or New.
  O7  Will reads last week's case in the chat.
PROVES   O1 -> test_nothing_comes_on_a_schedule_and_asking_writes_one_now
         O2 -> test_the_note_is_in_my_form_without_numbers
         O3 -> test_only_my_hash_notes_are_evidence
         O4 -> test_a_week_without_a_hash_note_gets_no_case
         O5 -> test_no_old_or_new_and_the_principle_only_on_my_yes
         O6 -> test_a_case_written_before_still_answers_old_or_new
         O7 -> test_will_reads_last_weeks_case
WHY      Will learning plan, step 2 (founder 2026-10-20, "start step 2"; the
         form is the founder's own), narrowed by the founder 2026-10-26: the
         principle comes from the # notes only ("Takes are separate from
         this"), only when asked ("If not asked, no answer from Will"), and
         Old | New is dropped (the user could not tell what it asked).
"""
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from services import sunday_note as sn
from services import voice_notebook

WEEK = {"case": "You rewrote the opening three times and never tested it on anyone.",
        "pattern": "hubris", "why": "You trusted your own read over a listener.",
        "applied": "Radical open-mindedness, weighed below speed this week.",
        "reflections": "Your talk goal needs a listener's ears, not your own.",
        "new_principle": "Test an opening on one person before rewriting it."}
MONDAY = date(2026, 10, 19)


class _Db:
    def __init__(self):
        self.thread = {}
        self.notes = {}
        self.consent = {"u": {"decision": "yes", "time_zone": "Europe/Warsaw"}}
        self.voice = [{"text_clean": "#I rush the close",
                       "created_at": datetime.now(timezone.utc).isoformat()}]

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
        return {"note": "WILLS OWN NOTE ON THEM"}

    # sunday_notes
    def insert_sunday_note(self, row):
        note = {**row, "id": f"s{len(self.notes) + 1}", "status": "claimed"}
        self.notes[note["id"]] = note
        return note

    def update_sunday_note(self, note_id, fields):
        self.notes[note_id].update(fields)
        return True

    def get_sunday_note(self, user_id, note_id):
        note = self.notes.get(note_id)
        return note if note and note["user_id"] == user_id else None

    def latest_sunday_note(self, user_id):
        written = [n for n in self.notes.values() if n["status"] == "written"]
        return written[-1] if written else None


@pytest.fixture
def founder(monkeypatch):
    monkeypatch.setattr("services.rings.feature_is_on_for_user",
                        lambda feature, user, database=None: user == "u")
    monkeypatch.setattr(sn, "_under_authority", lambda db, user, key, write: write())
    seen = []

    def complete(**kwargs):
        seen.append(kwargs)
        return SimpleNamespace(text="{}", parsed=dict(WEEK))

    monkeypatch.setattr("services.llm.chat_complete", complete)
    held = []
    monkeypatch.setattr("services.life_store.principles", lambda user, limit=500: list(held))
    monkeypatch.setattr("services.life_store.insert_item",
                        lambda user, fields: held.append({**fields, "id": "p1"}) or held[-1])
    return SimpleNamespace(held=held, seen=seen)


def test_nothing_comes_on_a_schedule_and_asking_writes_one_now(founder):
    assert not hasattr(sn, "sweep_due") and not hasattr(sn, "run_sunday")
    worker = Path(__file__).resolve().parents[1] / "services" / "pipeline_jobs.py"
    assert "sunday_note" not in worker.read_text(encoding="utf-8")

    db = _Db()
    turn = sn.chat_turn(db, "u", "Sunday note")
    assert turn["answer"].startswith(sn.HEADINGS["case"])
    assert sn.chat_turn(db, "u", "#sunday")["answer"].startswith(sn.HEADINGS["case"])

    assert sn.chat_turn(db, "someone", "sunday note") is None
    assert sn.chat_turn(db, "u", "what about my sunday note from last week?") is None


def test_the_note_is_in_my_form_without_numbers(founder):
    body, pattern, principle = sn.render(dict(WEEK))
    heads = [line for line in body.splitlines() if line.isupper() or line.endswith("⚜️")]
    assert heads == [sn.HEADINGS[k] for k in ("case", "which", "applied", "reflections", "new")]
    assert "👾 Hubris: You trusted your own read over a listener." in body
    assert all(label in body for label in sn.PATTERNS.values())
    assert pattern == "hubris" and principle == WEEK["new_principle"]

    with_number = sn.render({**WEEK, "case": "You practised 3 times."})[0]
    assert "3" not in with_number and sn.HEADINGS["case"] not in with_number


def test_only_my_hash_notes_are_evidence(founder):
    db = _Db()
    stamp = datetime.now(timezone.utc).isoformat()
    db.insert_lounge_messages("u", [
        {"client_id": "t1", "role": "bot", "body": "TAKE SUMMARY: you sped up on slide two",
         "metadata": {"summary": True}, "client_created_at": stamp},
        {"client_id": "t2", "role": "user", "body": "LOUNGE WORDS about my Take",
         "metadata": {}, "client_created_at": stamp},
    ])
    founder.held.append({"title": "Ask, do not assume"})

    read = sn.gather(db, "u", sn._since(MONDAY, "Europe/Warsaw"))
    assert "#I rush the close" in read
    assert "They book a demo" in read and "Ask, do not assume" in read
    for absent in ("TAKE SUMMARY", "LOUNGE WORDS", "WILLS OWN NOTE"):
        assert absent not in read

    sn.compose(db, "u", source="asked", week_start=MONDAY, zone_name="Europe/Warsaw")
    sent = founder.seen[-1]["user"]
    assert "#I rush the close" in sent and "TAKE SUMMARY" not in sent
    assert "Takes are not part of this" in founder.seen[-1]["system"]


def test_a_week_without_a_hash_note_gets_no_case(founder):
    db = _Db()
    db.voice = [{"text_clean": "#an old note", "created_at": "2026-10-01T09:00:00+00:00"}]
    assert sn.compose(db, "u", source="asked", week_start=MONDAY, zone_name=None) is None
    assert db.notes == {} and founder.seen == []  # no claim, no model call
    assert sn.chat_turn(db, "u", "sunday note") is None  # Will answers as usual


def test_no_old_or_new_and_the_principle_only_on_my_yes(founder):
    db = _Db()
    turn = sn.chat_turn(db, "u", "sunday note")
    assert turn["row_metadata"]["offer"] == sn.PRINCIPLE_OFFER  # never sn.OFFER
    note_id = turn["row_metadata"]["sunday_note_id"]
    assert founder.held == []  # nothing added before the founder says so

    rows = sn.principle(db, "u", note_id, "add")
    assert [r["body"] for r in rows] == ["Add principle", "Noted."]
    assert founder.held[0]["status"] == "active"
    assert founder.held[0]["title"] == WEEK["new_principle"]
    assert sn.principle(db, "u", note_id, "add") == []

    other = sn.compose(db, "u", source="asked", week_start=MONDAY, zone_name=None)
    sn.principle(db, "u", other["id"], "not_now")
    assert len(founder.held) == 1

    plain = sn.note_meta({"id": "s9", "new_principle": None})
    assert plain == {"sunday_note_id": "s9"}


def test_a_case_written_before_still_answers_old_or_new(founder):
    db = _Db()
    note = sn.compose(db, "u", source="asked", week_start=MONDAY, zone_name=None)
    rows = sn.mark(db, "u", note["id"], "old")
    assert [r["body"] for r in rows] == ["Old", f"⚜️ {WEEK['new_principle']}"]
    assert db.notes[note["id"]]["pattern_known"] == "old"
    assert sn.mark(db, "u", note["id"], "new") == []  # a second tap changes nothing


def test_will_reads_last_weeks_case(founder):
    db = _Db()
    sn.compose(db, "u", source="asked", week_start=MONDAY, zone_name=None)
    block = voice_notebook.prompt_block(db, "u")
    assert "hubris" in block
