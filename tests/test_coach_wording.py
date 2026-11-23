"""
STORY    As a speaker, I can save the exact words in a coaching reply and
         reopen the line in the project at my next recording.
OUTCOME  O1 The project retains one wording entry from an explicitly saved
            reply, even when the request is sent again.
         O2 Wording is scoped to the project and Take in the offer and the
            current actor's access to the source.
PROVES   O1 -> test_a_reply_saves_exactly_once_and_is_read_for_the_next_take
         O2 -> test_only_the_owned_project_and_current_source_can_save_or_read
WHY      Speaking Coach Codex decision, 2026-11-23.
"""
from services import coach_wording

_OWNER = "speaker"
_ARC = "pilot"
_TAKE = "pilot-take"
_REPLY = "bot-reply"
_WORDS = "Jeśli dostaniemy zgodę, kto z was chciałby poprowadzić pilotaż?"
_SESSION = {"id": _TAKE, "arc_id": _ARC, "user_id": _OWNER}


class FakeDB:
    client = None

    def __init__(self):
        self.saved = {}
        self.reply = {
            "role": "bot", "client_created_at": "2026-11-23T17:00:00+00:00",
            "metadata": {coach_wording.META: {"words": _WORDS, "arc_id": _ARC, "take_session_id": _TAKE}},
        }

    def get_lounge_message_by_client_id(self, user, client_id):
        return self.reply if (user, client_id) == (_OWNER, _REPLY) else None

    def insert_lounge_messages(self, user, rows):
        assert user == _OWNER
        return [self.saved.setdefault(row["client_id"], row) for row in rows]

    def get_saved_coach_wording(self, user, arc):
        return [row for row in self.saved.values() if user == _OWNER and row["metadata"]["arc_id"] == arc]


def test_a_reply_saves_exactly_once_and_is_read_for_the_next_take():
    db = FakeDB()
    first = coach_wording.save(db, _OWNER, _ARC, [_SESSION], _REPLY)
    assert first == coach_wording.save(db, _OWNER, _ARC, [_SESSION], _REPLY)
    assert first[1] == 200
    assert first[0]["wording"]["words"] == _WORDS
    assert len(db.saved) == 1
    new_take = {**_SESSION, "id": "next-take"}
    assert coach_wording.read(db, _OWNER, _ARC, [_SESSION, new_take]) == [first[0]["wording"]]


def test_only_the_owned_project_and_current_source_can_save_or_read(monkeypatch):
    db = FakeDB()
    assert coach_wording.save(db, "other", _ARC, [_SESSION], _REPLY)[1] == 404
    assert coach_wording.save(db, _OWNER, "another", [_SESSION], _REPLY)[1] == 404
    assert not db.saved
    assert coach_wording.save(db, _OWNER, _ARC, [_SESSION], _REPLY)[1] == 200
    monkeypatch.setattr("services.speaker_lookup._takes_in_force", lambda *_: set())
    assert coach_wording.read(db, _OWNER, _ARC, [_SESSION]) == []
    assert coach_wording.save(db, _OWNER, _ARC, [_SESSION], _REPLY)[1] == 404
