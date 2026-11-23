"""
STORY    As a visitor in a host's chat, I get an answer in the host's words,
         or a plain line when the host must see it first. A recording comes
         back as a walk I can tap. A score about me, or a feeling, never does.
OUTCOME
  O1  The prompt is built from what the host does, their first line, their
      questions, taps, taught answers, a photo and a document.
  O2  Only the host answers when they said so. Shadow, and health, law or
      money, stay a draft. An assistant waits for 20 answers, then sends.
  O3  A score or a feeling about the person is removed. A photo over 4 MB,
      a file that cannot be read, and a recording over 5 minutes or 25 MB
      are refused before a provider is called.
  O4  A recording's walk is a clear stretch, one place to say again, helper
      words, and the Ideal Text only when the host chose it. The facts name
      a pause at its time and no feeling.
PROVES   O1 -> ChatBuilderReplyTest::test_the_prompt_uses_the_hosts_setup
         O2 -> ChatBuilderReplyTest::test_who_answers_chooses_silence_wait_draft_or_send
         O3 -> ChatBuilderReplyTest::test_a_score_or_a_feeling_is_removed_and_a_huge_file_is_refused
         O4 -> ChatBuilderReplyTest::test_a_recording_returns_a_walk_the_visitor_can_tap
WHY      The chat builder's visitor try (frontend PR 1427). The reply is
         POST /v2/chats/<id>/reply. Health, law or money stays a draft.
"""
from __future__ import annotations

import base64
import io
import math
import os
import struct
import unittest
import wave
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from postgrest.exceptions import APIError
from services import chat_builder_reply as reply
from services import chat_structure, chat_voice
from services.chat_builder_reply import (
    complete, reply_act, strip_feelings, strip_person_scores,
)
from tests.test_chats import _Store


HOST = "11111111-1111-1111-1111-111111111111"


class ChatArtifactSaveTest(unittest.TestCase):
    def test_a_rolling_deploy_acknowledges_only_an_artifact_it_saved(self):
        database = MagicMock()
        execute = database.client.rpc.return_value.execute
        turn = {"client_id": HOST, "question": "Do you have time?", "answer": "Friday."}
        artifact = {"version": 1, "title": "Appointment", "output": "Friday."}
        turn_with_artifact = {**turn, "artifact": {**artifact, "extra": "ignored", "moment": "nul\x00"}}
        execute.side_effect = [APIError({"code": "PGRST202", "message": "Not in cache"}),
                               SimpleNamespace(data=True), SimpleNamespace(data=True)]

        self.assertEqual(chat_structure.keep_turn(database, HOST, "main", turn_with_artifact),
                         ({"code": "ARTIFACT_STORAGE_UNAVAILABLE"}, 503))
        self.assertEqual(chat_structure.keep_turn(database, HOST, "main", turn_with_artifact),
                         ({"saved": True, "artifact_saved": True}, 200))
        self.assertEqual(database.client.rpc.call_args.args[0], "append_owner_chat_section_v2")
        self.assertEqual(database.client.rpc.call_args.args[1]["p_artifact"], artifact)
        self.assertEqual(chat_structure.keep_turn(database, HOST, "main", turn), ({"saved": True}, 200))
        self.assertEqual(database.client.rpc.call_args.args[0], "append_owner_chat_section_v1")


def _recipe(**over) -> dict:
    recipe = {
        "v": 2, "spec": "Trichologist", "hello": "Show me the spot.",
        "questions": [{"q": "How long has it itched?"}],
        "taps": ["Dry scalp", "Something else"], "out": "answer",
        "who": "assistant", "sensitive": False, "care": False,
        "models": [{"q": "Is this a dry scalp?", "opts": ["Yes", "No"], "gives": "pick"}],
    }
    recipe.update(over)
    return recipe


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _wav(seconds: float = 0.4, rate: int = 16000, hz: float = 220.0) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        frames = bytearray()
        for i in range(int(seconds * rate)):
            frames += struct.pack("<h", int(0.2 * 32767 * math.sin(2 * math.pi * hz * i / rate)))
        handle.writeframes(bytes(frames))
    return buf.getvalue()


class _Db:
    def __init__(self):
        self.client = _Store()


class ChatBuilderReplyTest(unittest.TestCase):
    def _reply(self, payload, recipe=None, answers=20, said="Use a mild wash."):
        database = _Db()
        self.prompts: list[str] = []
        self.images: list = []

        def fake_complete(prompt, image, mime, user_id):
            self.prompts.append(prompt)
            self.images.append(image)
            return said

        with patch.object(reply, "complete", fake_complete):
            body, status = reply.reply(
                database, HOST, "own-abc", payload, recipe=recipe or _recipe(),
                host_answers=answers)
        body["_status"] = status
        body["_db"] = database
        return body

    def test_the_prompt_uses_the_hosts_setup(self):
        database = _Db()
        database.client.table("chat_reply_examples").insert(
            {"host_id": HOST, "chat_id": "own-abc", "ask": "Is this a dry scalp?",
             "answer": "It looks dry. Use a mild wash."}).execute()
        note = _b64(b"The note says the itch started in May.")
        captured = {}

        def fake_complete(prompt, image, mime, user_id):
            captured["prompt"] = prompt
            return "Use a mild wash."

        with patch.object(reply, "complete", fake_complete):
            body, status = reply.reply(
                database, HOST, "own-abc",
                {"text": "It itches.", "kind": "file", "data": note, "name": "note.txt"},
                recipe=_recipe(), host_answers=20)
        prompt = captured["prompt"]
        self.assertEqual(status, 200)
        self.assertIn("Trichologist", prompt)
        self.assertIn("Show me the spot.", prompt)
        self.assertIn("How long has it itched?", prompt)
        self.assertIn("Dry scalp", prompt)
        self.assertIn("Answer in the host's own words", prompt)
        self.assertIn("Person: Is this a dry scalp?", prompt)
        self.assertIn("Host: It looks dry. Use a mild wash.", prompt)
        self.assertIn("Is this a dry scalp? Options: Yes, No.", prompt)
        self.assertIn("The note says the itch started in May.", prompt)
        self.assertIn("Never give a score", prompt)
        self.assertIn("Do not name a feeling", prompt)
        self.assertIn("The person sent: It itches.", prompt)
        self.assertEqual(body["shown"], True)
        self.assertEqual(body["reply"], "Use a mild wash.")
        from io import BytesIO
        from pypdf import PdfWriter
        from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
        writer = PdfWriter()
        page = writer.add_blank_page(width=300, height=300)
        font = DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        })
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
        })
        stream = DecodedStreamObject()
        stream.set_data(b"BT /F1 12 Tf 20 100 Td (Dry scalp note) Tj ET")
        page[NameObject("/Contents")] = stream
        buf = BytesIO()
        writer.write(buf)
        self.assertIn("Dry scalp note", reply.pdf_text(buf.getvalue()))

    def test_who_answers_chooses_silence_wait_draft_or_send(self):
        self.assertEqual(reply_act("you", True, 20), "none")
        self.assertEqual(reply_act("shadow", False, 20), "draft")
        self.assertEqual(reply_act("assistant", True, 20), "draft")
        self.assertEqual(reply_act("assistant", False, 19), "wait")
        self.assertEqual(reply_act("assistant", False, 20), "send")

        quiet = self._reply({"text": "Hello", "kind": "text"}, _recipe(who="you"), said="secret")
        self.assertEqual(quiet["quiet"], True)
        self.assertIsNone(quiet["reply"])
        self.assertEqual(self.prompts, [])

        waiting = self._reply({"text": "Hello", "kind": "text"}, answers=19)
        self.assertEqual(waiting["wait"], True)
        self.assertEqual(self.prompts, [])

        held = self._reply(
            {"text": "Hello", "kind": "text"},
            _recipe(who="assistant", sensitive=True, care=True), said="secret")
        self.assertEqual(held["held"], True)
        self.assertIsNone(held["reply"])
        self.assertNotIn("secret", str({k: held[k] for k in held if k != "_db"}))
        drafts = held["_db"].client.table("chat_reply_drafts").select("*").execute().data
        self.assertEqual(drafts[0]["answer"], "secret")
        self.assertEqual(drafts[0]["status"], "draft")

        sent = reply.send_kept_draft(held["_db"], HOST, drafts[0]["id"], {"body": "Use a mild wash."})
        self.assertEqual(sent["message"]["body"], "Use a mild wash.")
        taught = held["_db"].client.table("chat_reply_examples").select("ask, answer").execute().data
        self.assertEqual([(row["ask"], row["answer"]) for row in taught],
                         [("Hello", "Use a mild wash.")])
        self.assertEqual(
            held["_db"].client.table("chat_reply_drafts").select("status").execute().data[0]["status"],
            "sent")

    def test_a_score_or_a_feeling_is_removed_and_a_huge_file_is_refused(self):
        self.assertEqual(strip_person_scores("You are an 8/10. Score is 7. Try this."),
                         "You are an. Try this.")
        self.assertEqual(strip_person_scores("About 90% sure."), "About sure.")
        self.assertEqual(strip_feelings("You sound confident. Try this."), "Try this.")

        photo = self._reply({
            "text": "Look", "kind": "photo", "mime": "image/jpeg",
            "data": _b64(b"x" * (reply.PHOTO_MAX + 1)),
        })
        self.assertEqual((photo["_status"], photo["error"]), (200, "too-big"))
        self.assertEqual(self.prompts, [])

        unread = self._reply({
            "text": "Look", "kind": "photo", "mime": "image/svg+xml",
            "data": _b64(b"<svg></svg>"),
        })
        self.assertEqual(unread["error"], "unreadable")

        seen = {}

        def fake(**kwargs):
            seen["model"] = kwargs["spec"].model
            return SimpleNamespace(text="You are an 8/10. You sound calm. Try this.")

        with patch.dict(os.environ, {"OPENAI_MODEL": "gpt-4o-mini"}), \
                patch("services.llm.chat_complete", fake):
            self.assertEqual(complete("Hi", None, "image/jpeg", HOST), "You are an. Try this.")
        self.assertEqual(seen["model"], "gpt-4o-mini")

    def test_a_recording_returns_a_walk_the_visitor_can_tap(self):
        import numpy as np
        rate = 16000
        audio = np.full(rate, 0.1, dtype=np.float32)
        audio[rate // 2:] = 0.5
        words = [{"word": "hello", "start": 39.2, "end": 41},
                 {"word": "there", "start": 44, "end": 45}]
        found = chat_voice.measures(audio, rate, words)
        self.assertEqual(found["pauses"], [{"at": 41, "seconds": 3}])
        self.assertEqual(found["loudness"], "moves")
        joined = " ".join(chat_voice.facts(found))
        self.assertIn("You paused for 3 seconds at 0:41.", joined)
        self.assertNotRegex(joined, r"confident|nervous|anxious|happy|sad|angry|calm|emotion|arousal")
        beats = chat_voice.walk_from(
            chat_voice.measures(np.zeros(2 * 8000, dtype=np.float32), 8000, [
                {"word": "one", "start": 0.2, "end": 0.5},
                {"word": "two", "start": 1.8, "end": 2.0},
            ]),
            ["best", "fix", "words"], True)
        self.assertEqual([beat["key"] for beat in beats], ["best", "fix", "words", "ideal"])
        self.assertEqual(beats[1]["at"], 0.5)
        self.assertIn("0:01", beats[1]["text"])

        loaded = chat_voice.decode(_wav(), "talk.wav")
        self.assertIsNotNone(loaded)
        samples, sample_rate = loaded
        self.assertEqual(sample_rate, 16000)
        self.assertGreater(len(samples), 1000)

        self.assertTrue(chat_voice.too_long(chat_voice.AUDIO_MAX_SECONDS + 1))
        self.assertFalse(chat_voice.too_long(chat_voice.AUDIO_MAX_SECONDS))
        with patch.object(chat_voice, "decode") as decode:
            got = chat_voice.prepare(_b64(b"x" * (chat_voice.AUDIO_MAX + 1)), "talk.webm")
        self.assertEqual(got["error"], "too-big")
        decode.assert_not_called()

        prepared = {"raw": b"abc", "audio": audio, "rate": rate, "seconds": 1.0, "name": "talk.webm"}
        heard = {"transcript": "hello there", "facts": ["You paused for 3 seconds at 0:41."],
                 "measures": found, "words": words}
        with patch("services.chat_voice.prepare", return_value=prepared), \
                patch("services.chat_voice.hear", return_value=heard), \
                patch.object(reply, "complete", return_value="Here is what you said."):
            body, status = reply.reply(
                _Db(), HOST, "own-abc",
                {"text": "A recording", "kind": "rec", "data": _b64(b"abc"), "name": "talk.webm"},
                recipe=_recipe(walk={"steps": ["best", "fix", "words"], "out": "ideal_text"}),
                host_answers=20)
        self.assertEqual(status, 200)
        self.assertEqual(body["shown"], True)
        self.assertEqual([beat["key"] for beat in body["walk"]], ["best", "fix", "words", "ideal"])
        self.assertTrue(body["reply"])


class ChatBuilderReplyRouteTest(unittest.TestCase):
    def setUp(self):
        from flask import Flask

        import auth
        from routes.v2 import register_domains
        from routes.v2.blueprint import v2_bp
        from services.db import db
        from services.rate_limits import limiter

        register_domains()
        if hasattr(limiter, "initialized"):
            self.addCleanup(setattr, limiter, "initialized", limiter.initialized)
            limiter.initialized = False
        app = Flask(__name__)
        app.register_blueprint(v2_bp, url_prefix="/v2")
        self.client = app.test_client()
        self.store = _Store()
        for item in (
            patch.object(auth, "verify_supabase_token", lambda _t: {"sub": HOST}),
            patch.object(db, "client", self.store),
            patch("services.assistants.on", return_value=True),
            patch("services.chat_recipes.mine", return_value=_recipe()),
            patch("services.chat_replies.own_answers", return_value=20),
            patch("services.chat_builder_reply.complete", return_value="Use a mild wash."),
        ):
            item.start()
            self.addCleanup(item.stop)

    def test_the_route_answers_in_the_shape_the_visitor_reads(self):
        missing = self.client.post("/v2/chats/own-abc/reply", json={"text": "Hi", "kind": "text"})
        self.assertEqual(missing.status_code, 401)

        got = self.client.post(
            "/v2/chats/own-abc/reply", json={"text": "It itches.", "kind": "text"},
            headers={"Authorization": "Bearer t"})
        self.assertEqual(got.status_code, 200)
        self.assertEqual(got.get_json(), {"shown": True, "reply": "Use a mild wash."})

        bad = self.client.post(
            "/v2/chats/not.ok/reply", json={"text": "Hi", "kind": "text"},
            headers={"Authorization": "Bearer t"})
        self.assertEqual(bad.status_code, 404)

    def test_no_recipe_keeps_the_screens_preview(self):
        with patch("services.chat_recipes.mine", return_value=None):
            got = self.client.post(
                "/v2/chats/own-abc/reply", json={"text": "Hi", "kind": "text"},
                headers={"Authorization": "Bearer t"})
        self.assertEqual(got.status_code, 404)


if __name__ == "__main__":
    unittest.main()
