"""STORY As a speaker practising in chat, I can hear and revisit the same
         recording after sending or retrying an edited caption.
OUTCOME
  O1  The receipt binds the original speech to the exact owner's audio and
      message. Only Send keeps the audio, full evidence, and playback.
  O2  A retry keeps one clip and reads its existing evidence. Other owners
      and erased messages cannot play it or use its analysis.
PROVES O1, O2 -> test_prepared_clip_is_attached_once_with_its_own_private_analysis
"""
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock

from flask import Flask, request
import inspect
import pytest

from config import Config
from routes.v2 import coaching, voice_notebook
from services import chat_voice_attempt, lounge_voice_reply, voice_confidence, will_question
from services.refusal import Refusal

USER = "4d47fce5-e3a1-4aaf-9a8b-637c4d810a78"
TURN = "7ccfa012-e3e1-42be-ae2b-5a226ed830d7"
ARC = "6fe7cbdd-fe65-4bf1-8e75-2a67a7d11fbe"
TAKE = "f0b1c92f-ab19-4439-90b9-b9b367b35ee9"
RAW = b"a short recording"
SPOKEN = "Um, here is how I would open the pitch."


class _AttachmentTable:
    def __init__(self):
        self.rows = {}
        self.query = None

    def select(self, fields):
        self.query = ("select", fields)
        return self

    def eq(self, field, message_id):
        assert field == "message_id"
        self.message_id = message_id
        return self

    def limit(self, _number):
        return self

    def upsert(self, data, *, on_conflict, ignore_duplicates):
        assert on_conflict == "message_id"
        assert ignore_duplicates is True
        self.query = ("insert", data)
        return self

    def execute(self):
        operation, value = self.query
        if operation == "select":
            row = self.rows.get(self.message_id)
            return SimpleNamespace(data=[{key: row[key] for key in value.split(",")}] if row else [])
        key = value["message_id"]
        if key in self.rows:
            return SimpleNamespace(data=[])
        self.rows[key] = value
        return SimpleNamespace(data=[value])


def test_prepared_clip_is_attached_once_with_its_own_private_analysis(monkeypatch):
    monkeypatch.setattr(Config, "SUPABASE_JWT_SECRET", "test-only-voice-signer")
    adapter = Mock()
    timing = {"word": "Um", "start": 0.01, "end": 0.22}
    transcribe = Mock(return_value=(SPOKEN, 1800, {"language": "en", "words": [timing]}))
    monkeypatch.setattr(will_question, "hear_answer_transcription", transcribe)
    measured = Mock(return_value={"wpm": 143, "f0_sd": 30})
    monkeypatch.setattr(chat_voice_attempt, "_measure", measured)
    confidence = {"band": "internal"}
    monkeypatch.setattr(voice_confidence, "resolve_confidence_baseline", Mock(return_value=({"reference": (1, 2)}, "user")))
    monkeypatch.setattr(voice_confidence, "read_for_piece", Mock(return_value=confidence))
    monkeypatch.setenv("VOICE_CONFIDENCE_ENABLED", "1")

    table = _AttachmentTable()
    message = {"id": "message-id", "role": "user", "body": "Edited caption",
               "metadata": {"voice_clip": True, "arc_id": ARC, "take_session_id": TAKE}}
    database = SimpleNamespace(
        client=SimpleNamespace(table=lambda _name: table),
        get_lounge_message_by_client_id=lambda user, turn: message if (user, turn) == (USER, TURN) else None,
    )
    prepared = chat_voice_attempt.hear(
        adapter, RAW, user=USER, filename="test.webm", duration=1800, turn=TURN, project=ARC, take=TAKE,
    )
    assert set(prepared) == {"text", "duration_ms", "voice_receipt"}
    assert table.rows == {}
    measured.assert_not_called()
    receipt = prepared["voice_receipt"]
    with pytest.raises(Refusal):
        lounge_voice_reply.save(database, USER, TURN, b"different audio", "audio/webm", receipt)
    monkeypatch.setattr(coaching, "db", database)
    monkeypatch.setattr(voice_notebook, "_adapter", lambda _user: adapter)
    app = Flask(__name__)
    with app.test_request_context(method="POST", data={
        "voice_receipt": receipt, "audio": (BytesIO(RAW), "test.webm", "audio/webm"),
    }):
        request.user_id = USER
        response, status = inspect.unwrap(coaching.v2_chat_voice_attach)(TURN)
        assert (response.get_json(), status) == ({"attached": True}, 200)

    assert lounge_voice_reply.save(database, USER, TURN, RAW, "audio/webm", receipt) == {"attached": True}
    transcribe.assert_called_once()
    measured.assert_called_once_with(RAW, SPOKEN)
    saved = lounge_voice_reply.read_analysis(database, USER, TURN, ARC)
    assert saved["transcript"] == SPOKEN
    assert saved["verbal_cues"]["words"] == [timing]
    assert saved["metrics"]["voice_confidence"] == confidence
    assert "natural rise and fall" in saved["delivery"]
    assert len(table.rows) == 1
    assert lounge_voice_reply.read(database, USER, TURN) == (RAW, "audio/webm")
    assert lounge_voice_reply.read_analysis(database, USER, TURN, "other-project") is None
    assert lounge_voice_reply.read_analysis(database, "other-user", TURN, ARC) is None
    message["chat_erased"] = True
    assert lounge_voice_reply.read_analysis(database, USER, TURN, ARC) is None
    with pytest.raises(Refusal):
        lounge_voice_reply.read(database, USER, TURN)
