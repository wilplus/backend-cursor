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
  O6  Every typed "#" is one note, as the small mic's: the Life Panel's old
      tags are notes too, and "#note" is read as "#" (N253).
  O7  While a note is said, its words so far come back, hesitations and
      all, and nothing is kept (N194).
  O8  A note the app sends twice under one key (the app closed mid-send)
      is kept and answered once (N194).
  O9  The person fixes a voice note's words: the note and its row in the
      thread change, Will does not answer again, and only their own voice
      note can be fixed (N194).
PROVES   O1 -> test_without_the_notebook_the_chat_is_unchanged
         O2 -> test_the_first_note_asks_and_yes_keeps_it
         O3 -> test_a_voice_note_is_cleaned_kept_and_shown_with_a_hash
         O4 -> test_a_crisis_note_gets_the_safety_reply
         O5 -> test_will_reads_the_notes_only_after_yes
         O6 -> test_every_typed_hash_is_one_note_as_the_mic
         O7 -> test_the_live_words_come_back_and_nothing_is_kept
         O8 -> test_a_note_sent_twice_is_kept_once
         O9 -> test_a_voice_note_is_fixed_in_the_notebook_and_the_thread
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

    def get_lounge_message_by_client_id(self, user_id, client_id):
        return self.thread.get((user_id, client_id))

    def rewrite_lounge_message(self, user_id, client_id, body, metadata, at=None):
        row = self.thread.get((user_id, client_id))
        if row:
            row.update(body=body, metadata=metadata)
        return row

    def update_voice_note_text(self, user_id, note_id, text):
        mine = [n for n in self.notes if n["id"] == note_id and n["user_id"] == user_id]
        for n in mine:
            n["text_clean"] = text
        return bool(mine)

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


def _type(db, text):
    turn = nb.chat_turn(db, "u", text)
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


def test_every_typed_hash_is_one_note_as_the_mic(founder):
    """N253: "#" is one note; the Life Panel's old tags are notes too, and
    the message box's "# note" is read as "#"."""
    db = _Db()
    db.consent["u"] = {"decision": "yes"}
    assert _type(db, "#mistake I skipped the pause")["answer"] == "Noted."
    assert _type(db, "#note The close needs a story")["answer"] == "Noted."
    assert [n["text_clean"] for n in db.notes] == [
        "#mistake I skipped the pause", "# The close needs a story"]


def _note(db, adapter, key=None):
    return nb.add_voice_note(db, "u", adapter, b"webm", filename="n.webm",
                             content_type="audio/webm", duration_ms=4000, key=key)


def test_the_live_words_come_back_and_nothing_is_kept(founder):
    db = _Db()
    nb.decide(db, "u", "yes")
    before = (len(db.notes), len(db.thread), len(db.audio))
    words = nb.preview(db, "u", _Adapter("um so the opening"), b"piece", filename="p.webm")
    assert words == "um so the opening"
    assert (len(db.notes), len(db.thread), len(db.audio)) == before
    with pytest.raises(nb.NotebookError):  # someone without the notebook
        nb.preview(db, "someone", _Adapter("x"), b"piece", filename="p.webm")


def test_a_note_sent_twice_is_kept_once(founder):
    db = _Db()
    nb.decide(db, "u", "yes")
    adapter = _Adapter("slow the first line")
    first = _note(db, adapter, key="note-1234-abcd")
    again = _note(db, adapter, key="note-1234-abcd")
    assert [r["client_id"] for r in again] == [r["client_id"] for r in first]
    assert len(db.notes) == 1 and adapter.calls == 1
    assert db.bodies().count("Noted.") == 1  # answered once
    _note(db, adapter, key="note-5678-efgh")
    assert len(db.notes) == 2


def test_a_voice_note_is_fixed_in_the_notebook_and_the_thread(founder):
    db = _Db()
    nb.decide(db, "u", "yes")
    mine, _ = _note(db, _Adapter("ask marta for the venue mike"))
    replies = db.bodies().count("Noted.")
    fixed = nb.fix_note(db, "u", mine["client_id"], "# Ask Marta for the venue mic")
    assert fixed["body"] == "# Ask Marta for the venue mic"
    assert db.notes[0]["text_clean"] == "Ask Marta for the venue mic"
    assert db.bodies().count("Noted.") == replies  # Will does not answer again
    noted = next(r for r in db.thread.values() if r["role"] == "bot" and r["body"] == "Noted.")
    for client_id in (noted["client_id"], "not-a-row"):
        with pytest.raises(nb.NotebookError):
            nb.fix_note(db, "u", client_id, "anything")
    with pytest.raises(nb.NotebookError):  # someone else's row
        nb.fix_note(db, "someone", mine["client_id"], "anything")
