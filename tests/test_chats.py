"""
STORY    As the founder, I want my own chats with a colleague and a customer,
         apart from my chat with Will, where I answer with one of three emoji
         or a voice note, so that I can see the chats between people working
         before anyone else is in them.
OUTCOME
  O1  Without the ring row (chats, ring 6) every route answers 404 and
      nothing is written.
  O2  The demo makes Sarah's customer chat and Ariel's colleague chat once,
      however often it is asked; the list names each chat for the other
      person, with their line and the last thing said.
  O3  In my chat I read what was said, oldest first, mine marked; I send 👍,
      👀 or 🙏 with its meaning kept as a label (N311), and anything else is
      refused.
  O4  Someone not in a chat can neither read it, nor send to it, nor play
      its voice notes, not even through a chat of their own.
  O5  I send a voice note (N321 item 2) and the other person in the chat
      sees it, with its length, and plays my recording as I sent it.
  O6  A recording that is missing, empty, not audio or over two minutes is
      refused (400), one over 12 MB too (413), and nothing is written.
  O7  A voice note is a recording: it passes the processing authorization
      and the recording consent a Take asks for, after the chat's own 404;
      when they refuse, their refusal is the answer and nothing is written.
PROVES   O1 -> ChatsTest::test_without_the_ring_every_route_is_not_found
         O2 -> ChatsTest::test_the_demo_is_made_once_and_listed
         O3 -> ChatsTest::test_a_member_reads_and_sends_one_of_three_emoji
         O4 -> ChatsTest::test_someone_not_in_the_chat_is_refused
         O5 -> ChatsTest::test_a_voice_note_is_sent_and_the_other_member_plays_it
         O6 -> ChatsTest::test_a_recording_that_is_not_a_voice_note_is_refused
         O7 -> ChatsTest::test_the_processing_authorization_refuses_a_voice_note
WHY      The chats between people, first slice (founder 2026-10-31, N298 to
         N316; the three emoji N311; the mic N321 item 2). Every speaker's
         recording goes through the processing-authorization path (CLAUDE.md).
"""
from __future__ import annotations

import io
import os
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from services.canonical_product import OwnerPrincipal
from services.chats import MAX_VOICE_BYTES
from services.db import db
from services.processing_authorization import ProcessingAuthorizationService
from services.project_repository import ProjectRepository

ME = "11111111-1111-4111-8111-111111111111"
SOMEONE = "22222222-2222-4222-8222-222222222222"
#: Signed in, with the ring, in no chat of ours.
OTHER = "33333333-3333-4333-8333-333333333333"
GATE = "PLF1_PROCESSING_AUTHORIZATION_MODE"


class _Query:
    """One PostgREST call on an in-memory table: filters, order, limit."""

    def __init__(self, store: "_Store", name: str):
        self.store, self.name = store, name
        self.filters: list = []
        self.sort: tuple | None = None
        self.cap: int | None = None
        self.write: tuple | None = None

    def select(self, _columns):
        return self

    def eq(self, column, value):
        self.filters.append(lambda r: r.get(column) == value)
        return self

    def in_(self, column, values):
        self.filters.append(lambda r: r.get(column) in set(values))
        return self

    def order(self, column, desc=False):
        self.sort = (column, desc)
        return self

    def limit(self, n):
        self.cap = n
        return self

    def insert(self, payload):
        self.write = ("insert", payload if isinstance(payload, list) else [payload])
        return self

    def delete(self):
        self.write = ("delete", None)
        return self

    def execute(self):
        rows = self.store.tables.setdefault(self.name, [])
        if self.write and self.write[0] == "insert":
            made = [self.store.defaults(self.name, r) for r in self.write[1]]
            rows.extend(made)
            return _Result([dict(r) for r in made])
        hits = [r for r in rows if all(f(r) for f in self.filters)]
        if self.write:
            self.store.tables[self.name] = [r for r in rows if r not in hits]
            return _Result(hits)
        if self.sort:
            hits.sort(key=lambda r: r[self.sort[0]], reverse=self.sort[1])
        return _Result([dict(r) for r in hits[:self.cap]])


class _Result:
    def __init__(self, rows):
        self.data = rows


class _Store:
    """The three chat tables in memory, standing in for db.client."""

    def __init__(self):
        self.tables: dict[str, list[dict]] = {}
        self.clock = datetime.now(timezone.utc)

    def table(self, name):
        return _Query(self, name)

    def defaults(self, name, row):
        self.clock += timedelta(minutes=1)
        made = {"id": str(uuid.uuid4()), "created_at": self.clock.isoformat(), **row}
        if name == "chat_messages":
            made.setdefault("meta", {})
        return made

    def count(self, name):
        return len(self.tables.get(name, []))


class ChatsTest(unittest.TestCase):
    def setUp(self):
        from flask import Flask

        import auth
        from routes.v2 import register_domains
        from routes.v2.blueprint import v2_bp
        from services.rate_limits import limiter

        register_domains()
        if hasattr(limiter, "initialized"):
            self.addCleanup(setattr, limiter, "initialized", limiter.initialized)
            limiter.initialized = False
        app = Flask(__name__)
        app.register_blueprint(v2_bp, url_prefix="/v2")
        self.client = app.test_client()
        self.store = _Store()
        self.who = ME
        self.ring = {ME: True, SOMEONE: True, OTHER: True}
        # The processing-authorization path runs as written; only what it
        # reads from the database answers from here: the caller's principal,
        # the consent choices they hold and the authority in force. The gate
        # is off unless a test turns it on.
        self.choices = {"has_receipt": True, "personalised_practice": True,
                        "sensitive_information": True}
        self.authority = {"authorized": True, "pooled_learning_eligible": False}
        for p in (patch.object(auth, "verify_supabase_token", lambda t: {"sub": self.who}),
                  patch("services.rings.feature_is_on_for_user",
                        lambda feature, user, database=None:
                        feature == "chats" and self.ring.get(user, False)),
                  patch.object(db, "client", self.store),
                  patch.dict(os.environ, {GATE: "off"}),
                  patch.object(ProjectRepository, "owner_for_user",
                               lambda _repo, user: OwnerPrincipal(f"owner-{user}", user, False)),
                  patch.object(ProcessingAuthorizationService, "resolve_acquisition_principal",
                               lambda _service, owner, **_: owner),
                  patch.object(ProcessingAuthorizationService, "consent_choices",
                               lambda _service, _principal: dict(self.choices)),
                  patch.object(ProcessingAuthorizationService, "status",
                               lambda _service, _principal: dict(self.authority))):
            p.start()
            self.addCleanup(p.stop)

    def _get(self, path):
        return self.client.get(path, headers={"Authorization": "Bearer t"})

    def _post(self, path, body=None):
        return self.client.post(path, json=body, headers={"Authorization": "Bearer t"})

    def _chat(self, kind):
        chats = self._post("/v2/chats/demo").get_json()["chats"]
        return next(c for c in chats if c["kind"] == kind)

    def _shared_chat(self):
        """A chat between two accounts, ME and SOMEONE."""
        thread = self.store.table("chat_threads").insert(
            {"kind": "team", "title": "Ariel"}).execute().data[0]["id"]
        self.store.table("chat_members").insert([
            {"thread_id": thread, "user_id": ME, "display_name": "Artur"},
            {"thread_id": thread, "user_id": SOMEONE, "display_name": "Ariel",
             "subtitle": "Your colleague · Invita"}]).execute()
        return thread

    def _voice(self, thread, audio=b"OggS a voice note", kind="audio/webm;codecs=opus",
               ms="4200"):
        form = {} if ms is None else {"duration_ms": ms}
        if audio is not None:
            form["audio"] = (io.BytesIO(audio), "voice.webm", kind)
        return self.client.post(f"/v2/chats/{thread}/voice", data=form,
                                content_type="multipart/form-data",
                                headers={"Authorization": "Bearer t"})

    def _nothing_sent(self):
        self.assertEqual([m for m in self.store.tables.get("chat_messages", [])
                          if m["kind"] == "voice"], [])
        self.assertEqual(self.store.count("chat_message_audio"), 0)

    def test_without_the_ring_every_route_is_not_found(self):
        self.ring[ME] = False
        thread = str(uuid.uuid4())
        for res in (self._get("/v2/chats"), self._post("/v2/chats/demo"),
                    self._get(f"/v2/chats/{thread}/messages"),
                    self._post(f"/v2/chats/{thread}/messages", {"kind": "emoji", "body": "👍"}),
                    self._voice(thread),
                    self._get(f"/v2/chats/{thread}/messages/{uuid.uuid4()}/audio")):
            self.assertEqual((res.status_code, res.get_json()["code"]), (404, "NOT_FOUND"))
        self.assertEqual(self.store.tables, {})

    def test_the_demo_is_made_once_and_listed(self):
        first = self._post("/v2/chats/demo")
        self.assertEqual(first.status_code, 200)
        again = self._post("/v2/chats/demo").get_json()
        self.assertEqual(again, first.get_json())
        self.assertEqual(self._get("/v2/chats").get_json(), again)
        self.assertEqual([self.store.count(t) for t in
                          ("chat_threads", "chat_members", "chat_messages")], [2, 4, 3])
        shown = {c["kind"]: (c["title"], c["subtitle"], c["last"]["kind"], c["last"]["body"])
                 for c in again["chats"]}
        self.assertEqual(shown, {
            "customer": ("Sarah", "Customer · Invita", "text",
                         "Itchy for two months, thinning at the top. I wash every day. "
                         "What should I do?"),
            "team": ("Ariel", "Your colleague · Invita", "emoji", "👍"),
        })

    def test_a_member_reads_and_sends_one_of_three_emoji(self):
        ariel = self._chat("team")["id"]
        said = self._get(f"/v2/chats/{ariel}/messages").get_json()["messages"]
        self.assertEqual([(m["mine"], m["author"], m["kind"], m["body"]) for m in said], [
            (False, "Ariel", "text", "On slide 1: name the treatment and let it land."),
            (False, "Ariel", "emoji", "👍")])

        res = self._post(f"/v2/chats/{ariel}/messages", {"kind": "emoji", "body": "👀"})
        self.assertEqual(res.status_code, 200)
        sent = res.get_json()["message"]
        self.assertEqual((sent["mine"], sent["kind"], sent["body"], sent["meta"]),
                         (True, "emoji", "👀", {"label": "seen"}))
        for wrong in ({"kind": "emoji", "body": "✅"}, {"kind": "text", "body": "Thanks!"},
                      {"kind": "emoji", "body": "👍👍"}, None):
            res = self._post(f"/v2/chats/{ariel}/messages", wrong)
            self.assertEqual((res.status_code, res.get_json()["code"]), (400, "NOT_ALLOWED"))
        now = self._get(f"/v2/chats/{ariel}/messages").get_json()["messages"]
        self.assertEqual([m["body"] for m in now], ["On slide 1: name the treatment and let it land.",
                                                    "👍", "👀"])
        self.assertTrue(now[-1]["mine"])
        listed = {c["id"]: c["last"]["body"] for c in self._get("/v2/chats").get_json()["chats"]}
        self.assertEqual(listed[ariel], "👀")

    def test_someone_not_in_the_chat_is_refused(self):
        sarah = self._chat("customer")["id"]
        note = self._voice(sarah).get_json()["message"]["id"]
        self.who = SOMEONE
        self.assertEqual(self._get("/v2/chats").get_json(), {"chats": []})
        theirs = self._chat("team")["id"]
        for res in (self._get(f"/v2/chats/{sarah}/messages"),
                    self._post(f"/v2/chats/{sarah}/messages", {"kind": "emoji", "body": "🙏"}),
                    self._voice(sarah),
                    self._get(f"/v2/chats/{sarah}/messages/{note}/audio"),
                    # Not through a chat of their own either.
                    self._get(f"/v2/chats/{theirs}/messages/{note}/audio"),
                    self._get("/v2/chats/not-a-chat/messages")):
            self.assertEqual((res.status_code, res.get_json()["code"]), (404, "NOT_FOUND"))
        self.assertEqual([m["thread_id"] for m in self.store.tables["chat_messages"]
                          if m["kind"] == "voice"], [sarah])
        self.assertEqual(self.store.count("chat_message_audio"), 1)

    def test_a_voice_note_is_sent_and_the_other_member_plays_it(self):
        chat = self._shared_chat()
        res = self._voice(chat, audio=b"OggS what I said", ms="4200")
        self.assertEqual(res.status_code, 200)
        sent = res.get_json()["message"]
        self.assertEqual(set(sent), {"id", "mine", "author", "kind", "body", "meta", "created_at"})
        self.assertEqual((sent["mine"], sent["author"], sent["kind"], sent["body"], sent["meta"]),
                         (True, "Artur", "voice", "", {"duration_ms": 4200}))
        kept = self.store.tables["chat_message_audio"]
        self.assertEqual([(r["message_id"], r["thread_id"], r["user_id"], r["words"])
                          for r in kept], [(sent["id"], chat, ME, None)])

        self.who = SOMEONE
        said = self._get(f"/v2/chats/{chat}/messages").get_json()["messages"]
        self.assertEqual([(m["id"], m["mine"], m["author"], m["kind"], m["meta"]) for m in said],
                         [(sent["id"], False, "Artur", "voice", {"duration_ms": 4200})])
        self.assertEqual(self._get("/v2/chats").get_json()["chats"][0]["last"]["kind"], "voice")
        played = self._get(f"/v2/chats/{chat}/messages/{sent['id']}/audio")
        self.assertEqual((played.status_code, played.data, played.headers["Content-Type"],
                          played.headers["Cache-Control"]),
                         (200, b"OggS what I said", "audio/webm;codecs=opus",
                          "private, max-age=3600"))
        missing = self._get(f"/v2/chats/{chat}/messages/{uuid.uuid4()}/audio")
        self.assertEqual((missing.status_code, missing.get_json()["code"]), (404, "NOT_FOUND"))

    def test_a_recording_that_is_not_a_voice_note_is_refused(self):
        chat = self._shared_chat()
        for wrong, answer in (
                ({"ms": "120001"}, (400, "NOT_ALLOWED")),            # over two minutes
                ({"ms": "0"}, (400, "NOT_ALLOWED")),
                ({"ms": None}, (400, "NOT_ALLOWED")),
                ({"kind": "text/plain"}, (400, "NOT_ALLOWED")),      # not audio
                ({"audio": b""}, (400, "NOT_ALLOWED")),
                ({"audio": None}, (400, "NOT_ALLOWED")),
                ({"audio": b"x" * (MAX_VOICE_BYTES + 1)}, (413, "TOO_LARGE"))):
            res = self._voice(chat, **wrong)
            self.assertEqual((res.status_code, res.get_json()["code"]), answer, wrong.keys())
        self._nothing_sent()

    def test_the_processing_authorization_refuses_a_voice_note(self):
        chat = self._shared_chat()
        # The recording consent withdrawn: refused whether or not the gate is on.
        self.choices["sensitive_information"] = False
        res = self._voice(chat)
        self.assertEqual((res.status_code, res.get_json()["code"]),
                         (403, "PROCESSING_RECORDING_WITHDRAWN"))
        # The gate on, and no authority in force for the caller.
        self.choices["sensitive_information"] = True
        os.environ[GATE] = "enforce"
        self.authority = {"authorized": False, "code": "PROCESSING_AUTHORIZATION_REQUIRED"}
        res = self._voice(chat)
        self.assertEqual((res.status_code, res.get_json()["code"]),
                         (403, "PROCESSING_AUTHORIZATION_REQUIRED"))
        # Someone not in the chat meets its 404 first.
        self.who = OTHER
        self.assertEqual(self._voice(chat).status_code, 404)
        self._nothing_sent()


if __name__ == "__main__":
    unittest.main()
