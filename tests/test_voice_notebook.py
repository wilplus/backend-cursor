"""
STORY    As the founder, I want to say or type a note into a private notebook
         in the Lounge, so that Will learns from what I think between Takes
         and nobody else reads it.
OUTCOME
  O1  Someone without the notebook types "#..." and the chat goes on as
      before, and the app is told the notebook is off (no mic).
  O2  The first note asks the signed question; Yes keeps the waiting note and
      answers "Noted."; Not now keeps nothing.
  O3  A voice note is transcribed under the caller's authorization, the
      hesitations taken out and every other word kept, the recording kept,
      and the thread shows "# " + the words, then "Noted.".
  O4  A note that sounds like a crisis is kept and answered at once with the
      chat's safety reply; before the question is answered it is never asked
      instead of that reply.
  O5  Will reads the notes, only once the person said Yes.
  O6  A tag the Life Panel owns is kept as a note, then left to the Life
      Panel to answer.
PROVES   O1 -> test_without_the_notebook_the_chat_is_unchanged
         O2 -> test_the_first_note_asks_and_yes_keeps_it
         O3 -> test_a_voice_note_is_cleaned_kept_and_shown_with_a_hash
         O4 -> test_a_crisis_note_gets_the_safety_reply
         O5 -> test_will_reads_the_notes_only_after_yes
         O6 -> test_a_life_panel_tag_is_kept_and_left_to_the_life_panel
WHY      Will learning plan, step 1 (founder 2026-10-20, "approved, start
         step 1"; words signed the same day).
"""
import pytest

from services import voice_notebook as nb
from services.voice_notebook import COPY


class _Db:
    def __init__(self):
        self.thread = {}
        self.notes = []
        self.audio = {}
        self.consent = {}

    def insert_lounge_messages(self, user_id, rows):
        for r in rows:
            self.thread.setdefault((user_id, r["client_id"]), {**r, "user_id": user_id})
        return [self.thread[(user_id, r["client_id"])] for r in rows]

    def get_lounge_messages_page(self, user_id, limit=50):
        mine = [r for (u, _), r in self.thread.items() if u == user_id]
        return list(reversed(mine))[:limit]

    def insert_voice_note(self, row):
        note = {**row, "id": f"n{len(self.notes) + 1}", "created_at": "2026-10-20T10:00:00"}
        self.notes.append(note)
        return note

    def insert_voice_note_audio(self, note_id, user_id, content_type, audio):
        self.audio[note_id] = audio
        return True

    def list_voice_notes(self, user_id, limit=20):
        return [n for n in self.notes if n["user_id"] == user_id][-limit:]

    def get_voice_notebook_consent(self, user_id):
        return self.consent.get(user_id)

    def save_voice_notebook_consent(self, user_id, decision):
        self.consent[user_id] = {"decision": decision}
        return True

    def bodies(self, user_id="u"):
        return [r["body"] for r in reversed(self.get_lounge_messages_page(user_id))]


class _Adapter:
    def __init__(self, text):
        self.text, self.calls = text, 0

    def transcribe_audio(self, audio, filename, **_):
        self.calls += 1
        return {"text": self.text, "language": "en"}


@pytest.fixture
def founder(monkeypatch):
    monkeypatch.setattr("services.rings.feature_is_on_for_user",
                        lambda feature, user, database=None: user == "u")


def _type(db, text, life_on=False):
    turn = nb.chat_turn(db, "u", text, life_on=life_on)
    if turn:  # what persist_chat_turn writes for the turn
        db.insert_lounge_messages("u", [
            {"client_id": f"me-{text}", "role": "user", "body": text, "metadata": None},
            {"client_id": f"bot-{text}", "role": "bot", "body": turn["answer"],
             "metadata": turn["row_metadata"]}])
    return turn


def test_without_the_notebook_the_chat_is_unchanged(founder):
    db = _Db()
    assert nb.chat_turn(db, "someone", "#an idea") is None
    assert nb.state(db, "someone")["enabled"] is False
    assert nb.chat_turn(db, "u", "how do I open my talk?") is None  # not a note
    assert not db.notes


def test_the_first_note_asks_and_yes_keeps_it(founder):
    db = _Db()
    turn = _type(db, "#I rush when the room is quiet")
    assert turn["answer"] == COPY["ask"] and not db.notes

    nb.decide(db, "u", "yes")
    assert [n["text_clean"] for n in db.notes] == ["#I rush when the room is quiet"]
    assert db.bodies()[-2:] == ["Yes", "Noted."]

    assert _type(db, "#second one")["answer"] == "Noted."  # asked once

    other = _Db()
    _type(other, "#a thought")
    nb.decide(other, "u", "not_now")
    assert not other.notes and other.bodies()[-1] == "Not now"


def test_a_voice_note_is_cleaned_kept_and_shown_with_a_hash(founder):
    db = _Db()
    nb.decide(db, "u", "yes")
    adapter = _Adapter("Um, I think the the opening needs a story, uh, first")
    rows = nb.add_voice_note(db, "u", adapter, b"webm", filename="n.webm",
                             content_type="audio/webm", duration_ms=9000)
    words = db.notes[0]["text_clean"]
    assert "Um" not in words and "uh" not in words and "the the" not in words
    assert "opening needs a story" in words
    assert db.audio[db.notes[0]["id"]] == b"webm"
    assert [r["body"] for r in rows] == [f"# {words}", "Noted."]

    with pytest.raises(nb.NotebookError):  # up to five minutes
        nb.add_voice_note(db, "u", adapter, b"x", filename="n.webm",
                          content_type="audio/webm", duration_ms=400_000)


def test_a_crisis_note_gets_the_safety_reply(founder):
    db = _Db()
    nb.decide(db, "u", "yes")
    turn = _type(db, "#I want to die before this talk")
    assert turn["answer"] != "Noted." and "emergency" in turn["answer"]
    assert db.notes  # kept, it is theirs

    before = _Db()  # not yet asked: the safety reply, never the question
    turn = nb.chat_turn(before, "u", "#I can't go on")
    assert "emergency" in turn["answer"] and not before.notes


def test_will_reads_the_notes_only_after_yes(founder):
    db = _Db()
    db.notes.append({"user_id": "u", "text_clean": "I rush the close",
                     "created_at": "2026-10-20"})
    assert nb.prompt_block(db, "u") == ""
    db.consent["u"] = {"decision": "yes"}
    assert "I rush the close" in nb.prompt_block(db, "u")


def test_a_life_panel_tag_is_kept_and_left_to_the_life_panel(founder):
    db = _Db()
    db.consent["u"] = {"decision": "yes"}
    assert nb.chat_turn(db, "u", "#mistake I skipped the pause", life_on=True) is None
    assert db.notes[0]["text_clean"] == "#mistake I skipped the pause"
