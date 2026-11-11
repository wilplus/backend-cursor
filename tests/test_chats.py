"""
STORY    As the founder, I want my own chats with a colleague and a customer,
         apart from my chat with Will, where I answer with one of three emoji
         or a voice note, and start something new with a photo or a file, so
         that I can see the chats between people working before anyone else
         is in them.
OUTCOME
  O1  As a user, I have my chats with no ring at all: the list answers
      without the rings ever being read (N456; was ring 6 only). As a
      server, I answer nobody who is not signed in, and write nothing.
  O2  The demo makes Sarah's customer chat and Ariel's colleague chat once,
      however often it is asked; the list names each chat for the other
      person, with their line and the last thing said.
  O3  In my chat I read what was said, oldest first, mine marked; I send 👍,
      👀 or 🙏 with its meaning kept as a label (N311), and anything else is
      refused.
  O4  Someone not in a chat can neither read it, nor send to it (an emoji,
      a voice note, a photo or a file), nor play its voice notes, nor open
      its photos and files, not even through a chat of their own.
  O5  I send a voice note (N321 item 2) and the other person in the chat
      sees it, with its length, and plays my recording as I sent it.
  O6  A recording that is missing, empty, not audio or over two minutes is
      refused (400), one over 12 MB too (413), and nothing is written.
  O7  A voice note is a recording: it passes the processing authorization
      and the recording consent a Take asks for, after the chat's own 404;
      when they refuse, their refusal is the answer and nothing is written.
  O8  My voice note is turned into words (N324) under my own permit, before
      the transcriber hears it, and the words are kept with its recording,
      up to 20000 characters; the chat's members get them with the voice
      note, to open under its player (N331), and the list never shows them.
  O9  A voice note that cannot be turned into words (none heard, the
      transcriber failing, the permit refused) is sent all the same: the
      same answer, its message and recording kept, its words empty.
  O10 I send a photo and a file from the "+" (N351); the other person in the
      chat sees them, the list's last line has the file's own name, and the
      photo opens in place and the file downloads under its name, as I sent
      them, never sniffed as anything else.
  O11 My photo or file opens a new question for the other person (N341 item
      2): it is marked as one, and so is the voice note I send straight after
      it to say what I need (N337); a voice note that follows nothing of mine
      is not.
  O12 A photo that is not a raster image (text, SVG), an empty or missing
      file, or anything over 10 MB is refused (400, 413), and nothing is
      written.
  O13 An answer I recorded with "Record an answer" is sent into the chat as a
      voice message that plays my Take's own recording (N363): I see it with
      its Take; the other person gets just the answer, no Take (N336). An
      answer has no five-minute cap: a long one is sent (N486 item 4). A
      Take that is not mine, or a withdrawn recording consent, sends
      nothing.
  O14 Once my answer's Take has its words, both of us get them with the
      answer, slide by slide, and when each slide starts, for the strip that
      follows its voice (N355, N331); before that, no words and no slides.
  O15 Will reads a question that waits for an answer once its words are
      known (N361 item 1): asking about a product or a treatment, it carries
      his mark (record_answer), the one "Record an answer" waits for; his
      no is kept as no; anything else leaves no mark and the note is sent
      all the same. The demo customer's question carries it, an older
      seeded one too.
  O16 My answer waits on the server for what is left of its 5 seconds (N441
      item 3): until then the other person does not see it, the list does
      not show it and no push goes; Undo takes it back then, and Will says
      so in my chat with him, once, naming the other person (N441 item 5).
      Once its time is over Undo is refused and it reaches them; with no
      time left it goes at once. Nobody else can take my answer back.
  O17 A question I recorded with "Record your question" (N483 item 4) is
      sent and held as an answer is, and the other person gets it marked
      for them to answer ("Record your answer"), without its Take; Undo
      takes it back the same way.
  O18 "Not now" under a Take or a question someone asked me (N483 item 3,
      N493 item 3) tells nobody: no message is written. The system keeps it
      once, with whose it was, what and the flow (N504 item 2), and the
      founder reads how often and the newest; "Not now" on my own message,
      or on one that asks for nothing, is refused.
  O19 The list reads every chat's newest messages with the chats in one
      read, never one read per chat, and answers what the reads one per
      chat answer.
PROVES   O1 -> ChatsTest::test_as_a_user_I_have_my_chats_without_any_ring,
               ChatsTest::test_as_a_server_I_answer_nobody_who_is_not_signed_in
         O2 -> ChatsTest::test_the_demo_is_made_once_and_listed
         O3 -> ChatsTest::test_a_member_reads_and_sends_one_of_three_emoji
         O4 -> ChatsTest::test_someone_not_in_the_chat_is_refused
         O5 -> ChatsTest::test_a_voice_note_is_sent_and_the_other_member_plays_it
         O6 -> ChatsTest::test_a_recording_that_is_not_a_voice_note_is_refused
         O7 -> ChatsTest::test_the_processing_authorization_refuses_a_voice_note
         O8 -> ChatsTest::test_a_voice_note_is_turned_into_words_under_my_permit_and_its_members_read_them
         O9 -> ChatsTest::test_a_voice_note_without_words_is_sent_all_the_same
         O10 -> ChatsTest::test_a_photo_and_a_file_are_sent_and_the_other_member_opens_them
         O11 -> ChatsTest::test_my_photo_and_the_voice_note_after_it_are_a_question_for_the_other_person
         O12 -> ChatsTest::test_a_photo_that_is_not_one_or_anything_over_10_mb_is_refused
         O13 -> ChatsTest::test_an_answer_plays_my_take_and_the_other_member_gets_just_the_answer
         O14 -> ChatsTest::test_an_answer_carries_its_takes_words_and_slides_once_processed
         O15 -> ChatsTest::test_will_marks_a_question_about_a_product_or_a_treatment
         O16 -> ChatsTest::test_an_answer_waits_its_five_seconds_and_undo_takes_it_back
         O17 -> ChatsTest::test_my_question_is_sent_as_an_answer_is_and_marked_for_them_to_answer
         O18 -> ChatsTest::test_not_now_tells_nobody_and_is_kept_once_for_the_founder
         O19 -> ChatsTest::test_the_list_reads_every_chats_messages_in_one_read
WHY      The chats between people, first slice (founder 2026-10-31, N298 to
         N316; the three emoji N311; the mic N321 item 2; its words N324,
         shown under the player N331; the photos and files of the "+" N351;
         an answer recorded with "Record an answer" N336, N361, N363; a
         question recorded with "Record your question" N483 item 4, N498).
         Every speaker's recording and every provider call goes through the
         processing-authorization path (CLAUDE.md).
"""
from __future__ import annotations

import io
import os
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from services.canonical_product import OwnerPrincipal
from services.chats import MAX_FILE_BYTES, MAX_VOICE_BYTES
from services.db import db
from services.processing_authorization import (
    ProcessingAuthorizationError, ProcessingAuthorizationService,
)
from services.project_repository import ProjectRepository

ME = "11111111-1111-4111-8111-111111111111"
SOMEONE = "22222222-2222-4222-8222-222222222222"
#: Signed in, in no chat of ours.
OTHER = "33333333-3333-4333-8333-333333333333"
GATE = "PLF1_PROCESSING_AUTHORIZATION_MODE"


#: The foreign keys an embed follows: (parent table, embedded table) -> the
#: embedded table's column naming the parent's id.
_EMBEDS = {("chat_threads", "chat_messages"): "thread_id"}


class _Query:
    """One PostgREST call on an in-memory table: filters, order, limit, and
    an embedded table ordered and limited per parent row, as PostgREST does
    (``select("...,chat_messages(...)")`` with ``foreign_table=``)."""

    def __init__(self, store: "_Store", name: str):
        self.store, self.name = store, name
        self.filters: list = []
        self.sort: tuple | None = None
        self.cap: int | None = None
        self.write: tuple | None = None
        self.embed: str | None = None
        self.embed_sort: tuple | None = None
        self.embed_cap: int | None = None

    def select(self, columns="*"):
        for (parent, child) in _EMBEDS:
            if parent == self.name and f"{child}(" in str(columns):
                self.embed = child
        return self

    def eq(self, column, value):
        self.filters.append(lambda r: r.get(column) == value)
        return self

    def in_(self, column, values):
        self.filters.append(lambda r: r.get(column) in set(values))
        return self

    def gte(self, column, value):
        self.filters.append(lambda r: r.get(column) is not None and str(r.get(column)) >= str(value))
        return self

    def is_(self, column, value):
        # Only "null", the one IS the services use.
        self.filters.append(lambda r: r.get(column) is None)
        return self

    def order(self, column, desc=False, foreign_table=None):
        if foreign_table:
            self.embed_sort = (column, desc)
        else:
            self.sort = (column, desc)
        return self

    def limit(self, n, foreign_table=None):
        if foreign_table:
            self.embed_cap = n
        else:
            self.cap = n
        return self

    def range(self, start, end):
        # A page of rows, as PostgREST's range (start and end both in).
        self.span = (start, end)
        return self

    def insert(self, payload):
        self.write = ("insert", payload if isinstance(payload, list) else [payload])
        return self

    def delete(self):
        self.write = ("delete", None)
        return self

    def update(self, payload):
        self.write = ("update", payload)
        return self

    def execute(self):
        rows = self.store.tables.setdefault(self.name, [])
        if self.write and self.write[0] == "insert":
            made = [self.store.defaults(self.name, r) for r in self.write[1]]
            rows.extend(made)
            return _Result([dict(r) for r in made])
        hits = [r for r in rows if all(f(r) for f in self.filters)]
        if self.write and self.write[0] == "update":
            for r in hits:
                r.update(self.write[1])
            return _Result([dict(r) for r in hits])
        if self.write:
            self.store.tables[self.name] = [r for r in rows if r not in hits]
            return _Result(hits)
        if self.sort:
            hits.sort(key=lambda r: r[self.sort[0]], reverse=self.sort[1])
        span = getattr(self, "span", None)
        if span:
            hits = hits[span[0]:span[1] + 1]
        out = [dict(r) for r in hits[:self.cap]]
        if self.embed:
            key = _EMBEDS[(self.name, self.embed)]
            children = self.store.tables.get(self.embed, [])
            for row in out:
                mine = [dict(c) for c in children if c.get(key) == row.get("id")]
                if self.embed_sort:
                    mine.sort(key=lambda c: c[self.embed_sort[0]], reverse=self.embed_sort[1])
                row[self.embed] = mine[:self.embed_cap]
        self.store.reads.append(self.name)
        return _Result(out)


class _Result:
    def __init__(self, rows):
        self.data = rows


class _Store:
    """The three chat tables in memory, standing in for db.client."""

    def __init__(self):
        self.tables: dict[str, list[dict]] = {}
        self.clock = datetime.now(timezone.utc)
        self.reads: list[str] = []  # the tables read, one entry a read

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


class _Transcriber:
    """The transcriber behind the authorized adapter, stood in as the voice
    notebook's tests stand it in: it answers the test's ``said`` (the words,
    or the error it fails with) and notes what it heard."""

    client = True

    def __init__(self, test):
        self.test = test

    def transcribe_audio(self, audio, filename, **_):
        self.test.heard.append((audio.read(), filename))
        if isinstance(self.test.said, Exception):
            raise self.test.said
        return {"text": self.test.said, "language": "en"}


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
        # The processing-authorization path runs as written; only what it
        # reads from the database answers from here: the caller's principal,
        # the consent choices they hold and the authority in force. The gate
        # is off unless a test turns it on.
        self.choices = {"has_receipt": True, "personalised_practice": True,
                        "sensitive_information": True}
        self.authority = {"authorized": True, "pooled_learning_eligible": False}
        # The transcriber: what it hears, and the words it answers.
        self.heard: list = []
        self.said: object = ""
        for p in (patch("services.openai_service.OpenAIService", lambda: _Transcriber(self)),
                  patch.object(auth, "verify_supabase_token", lambda t: {"sub": self.who}),
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

    def _upload(self, thread, route, data=b"\x89PNG my screen", kind="image/png",
                name="Screenshot 1.png"):
        """A photo or a file from the "+" (N351), as the app posts it."""
        form = {} if data is None else {"file": (io.BytesIO(data), name, kind)}
        return self.client.post(f"/v2/chats/{thread}/{route}", data=form,
                                content_type="multipart/form-data",
                                headers={"Authorization": "Bearer t"})

    def _nothing_sent(self):
        self.assertEqual([m for m in self.store.tables.get("chat_messages", [])
                          if m["kind"] == "voice"], [])
        self.assertEqual(self.store.count("chat_message_audio"), 0)

    def test_as_a_user_I_have_my_chats_without_any_ring(self):
        # No ring row, and the rings never asked: the chats are everyone's (N456).
        def no_ring(*_args, **_kwargs):
            raise AssertionError("the chats asked the rings")
        with patch("services.rings.feature_is_on_for_user", no_ring):
            res = self._get("/v2/chats")
        self.assertEqual((res.status_code, res.get_json()), (200, {"chats": []}))

    def test_as_a_server_I_answer_nobody_who_is_not_signed_in(self):
        thread = str(uuid.uuid4())
        for res in (self.client.get("/v2/chats"),
                    self.client.get(f"/v2/chats/{thread}/messages"),
                    self.client.post(f"/v2/chats/{thread}/messages", json={"kind": "emoji", "body": "👍"})):
            self.assertEqual(res.status_code, 401)
        self.assertEqual(self.store.tables, {})

    def test_the_list_reads_every_chats_messages_in_one_read(self):
        from services import chats
        self._post("/v2/chats/demo")
        self.store.reads.clear()
        listed = self._get("/v2/chats").get_json()
        self.assertEqual(len(listed["chats"]), 2)
        self.assertNotIn("chat_messages", self.store.reads)
        self.assertEqual(self.store.reads.count("chat_threads"), 1)
        with patch.object(chats, "_threads_with_recent", lambda _db, _ids: None):
            self.store.reads.clear()
            one_per_chat = self._get("/v2/chats").get_json()
        self.assertEqual(self.store.reads.count("chat_messages"), 2)
        self.assertEqual(listed, one_per_chat)

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
        photo = self._upload(sarah, "photo").get_json()["message"]["id"]
        self.who = SOMEONE
        self.assertEqual(self._get("/v2/chats").get_json(), {"chats": []})
        theirs = self._chat("team")["id"]
        for res in (self._get(f"/v2/chats/{sarah}/messages"),
                    self._post(f"/v2/chats/{sarah}/messages", {"kind": "emoji", "body": "🙏"}),
                    self._voice(sarah), self._upload(sarah, "photo"),
                    self._upload(sarah, "file"),
                    self._get(f"/v2/chats/{sarah}/messages/{note}/audio"),
                    self._get(f"/v2/chats/{sarah}/messages/{photo}/file"),
                    # Not through a chat of their own either.
                    self._get(f"/v2/chats/{theirs}/messages/{note}/audio"),
                    self._get(f"/v2/chats/{theirs}/messages/{photo}/file"),
                    self._get("/v2/chats/not-a-chat/messages")):
            self.assertEqual((res.status_code, res.get_json()["code"]), (404, "NOT_FOUND"))
        self.assertEqual([m["thread_id"] for m in self.store.tables["chat_messages"]
                          if m["kind"] == "voice"], [sarah])
        self.assertEqual(self.store.count("chat_message_audio"), 1)
        self.assertEqual([r["message_id"] for r in self.store.tables["chat_message_files"]],
                         [photo])

    def test_a_voice_note_is_sent_and_the_other_member_plays_it(self):
        chat = self._shared_chat()
        res = self._voice(chat, audio=b"OggS what I said", ms="4200")
        self.assertEqual(res.status_code, 200)
        sent = res.get_json()["message"]
        self.assertEqual(set(sent), {"id", "mine", "author", "kind", "body", "meta", "created_at",
                                     "words"})
        self.assertEqual((sent["mine"], sent["author"], sent["kind"], sent["body"], sent["meta"],
                          sent["words"]),
                         (True, "Artur", "voice", "", {"duration_ms": 4200}, None))
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

    def test_a_voice_note_is_turned_into_words_under_my_permit_and_its_members_read_them(self):
        chat = self._shared_chat()
        os.environ[GATE] = "enforce"
        trail: list = []

        def permit(_service, **asked):
            trail.append(("permit", asked["acquisition_principal_id"],
                          asked["provider"], asked["operation_kind"]))
            return {"permit_id": f"permit-{len(trail)}"}
        self.said = "  On slide one, name the treatment and let it land.  "
        with patch.object(ProcessingAuthorizationService, "issue_provider_permit", permit), \
                patch.object(ProcessingAuthorizationService, "record_provider_event",
                             lambda _service, permit_id, kind, **_: trail.append((kind,))):
            res = self._voice(chat, audio=b"OggS what I said")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(trail, [("permit", f"owner-{ME}", "openai", "transcription"),
                                 ("started",), ("completed",)])
        self.assertEqual(self.heard, [(b"OggS what I said", "voice.webm")])
        sent = res.get_json()["message"]
        said = "On slide one, name the treatment and let it land."
        self.assertEqual([(r["message_id"], r["words"])
                          for r in self.store.tables["chat_message_audio"]],
                         [(sent["id"], said)])
        # The words come with the voice note, to me and to the other member
        # (N331), and never in the list.
        self.assertEqual(sent["words"], said)
        self.who = SOMEONE
        read = self._get(f"/v2/chats/{chat}/messages").get_json()["messages"]
        self.assertEqual([(m["id"], m["words"]) for m in read], [(sent["id"], said)])
        self.assertNotIn("name the treatment", self._get("/v2/chats").get_data(as_text=True))
        self.who = ME

        os.environ[GATE] = "off"
        self.said = "a" * 20001
        self._voice(chat)
        self.assertEqual(len(self.store.tables["chat_message_audio"][-1]["words"]), 20000)

    def test_a_voice_note_without_words_is_sent_all_the_same(self):
        chat = self._shared_chat()
        refused = ProcessingAuthorizationError("PROVIDER_PERMIT_DENIED", "No.", 403)
        for said, permit in (("   ", None), (TimeoutError("timed out"), None),
                             ("Never heard.", refused)):
            self.said = said
            with patch.object(ProcessingAuthorizationService, "issue_provider_permit",
                              return_value=None, side_effect=permit), \
                    self.assertLogs("services.chats", "WARNING") as logged:
                res = self._voice(chat, audio=b"OggS a voice note")
            self.assertEqual(res.status_code, 200)
            sent = res.get_json()["message"]
            self.assertEqual((sent["kind"], sent["meta"]), ("voice", {"duration_ms": 4200}))
            kept = self.store.tables["chat_message_audio"][-1]
            self.assertEqual((kept["message_id"], kept["words"]), (sent["id"], None))
            self.assertIn(sent["id"], logged.output[-1])
            self.assertNotIn("OggS", logged.output[-1])
        self.assertEqual(self.store.count("chat_message_audio"), 3)
        self.assertEqual(len([m for m in self.store.tables["chat_messages"]
                              if m["kind"] == "voice"]), 3)
        # The refused permit: the transcriber never heard the third.
        self.assertEqual(len(self.heard), 2)

    def test_a_photo_and_a_file_are_sent_and_the_other_member_opens_them(self):
        chat = self._shared_chat()
        photo = self._upload(chat, "photo", b"\x89PNG my screen", "image/png", "Screenshot 1.png")
        file = self._upload(chat, "file", b"%PDF the guidelines", "application/pdf",
                            "Newsroom AI guidelines.pdf")
        self.assertEqual((photo.status_code, file.status_code), (200, 200))
        photo, file = photo.get_json()["message"], file.get_json()["message"]
        self.assertEqual([(m["mine"], m["author"], m["kind"], m["body"]) for m in (photo, file)],
                         [(True, "Artur", "photo", ""),
                          (True, "Artur", "file", "Newsroom AI guidelines.pdf")])
        self.assertEqual([(r["message_id"], r["thread_id"], r["user_id"], r["file_name"])
                          for r in self.store.tables["chat_message_files"]],
                         [(photo["id"], chat, ME, "Screenshot 1.png"),
                          (file["id"], chat, ME, "Newsroom AI guidelines.pdf")])

        self.who = SOMEONE
        said = self._get(f"/v2/chats/{chat}/messages").get_json()["messages"]
        self.assertEqual([(m["id"], m["mine"], m["kind"], m["body"]) for m in said],
                         [(photo["id"], False, "photo", ""),
                          (file["id"], False, "file", "Newsroom AI guidelines.pdf")])
        last = self._get("/v2/chats").get_json()["chats"][0]["last"]
        self.assertEqual((last["kind"], last["body"]), ("file", "Newsroom AI guidelines.pdf"))
        shown = self._get(f"/v2/chats/{chat}/messages/{photo['id']}/file")
        self.assertEqual((shown.status_code, shown.data, shown.headers["Content-Type"],
                          shown.headers["X-Content-Type-Options"]),
                         (200, b"\x89PNG my screen", "image/png", "nosniff"))
        self.assertRegex(shown.headers["Content-Disposition"], r'^inline; filename="?Screenshot 1\.png')
        got = self._get(f"/v2/chats/{chat}/messages/{file['id']}/file")
        self.assertEqual((got.status_code, got.data, got.headers["Content-Type"],
                          got.headers["X-Content-Type-Options"]),
                         (200, b"%PDF the guidelines", "application/pdf", "nosniff"))
        self.assertRegex(got.headers["Content-Disposition"],
                         r'^attachment; filename="?Newsroom AI guidelines\.pdf')
        # A voice note is no file.
        self.who = ME
        note = self._voice(chat).get_json()["message"]["id"]
        missing = self._get(f"/v2/chats/{chat}/messages/{note}/file")
        self.assertEqual((missing.status_code, missing.get_json()["code"]), (404, "NOT_FOUND"))

    def test_my_photo_and_the_voice_note_after_it_are_a_question_for_the_other_person(self):
        chat = self._shared_chat()
        before = self._voice(chat).get_json()["message"]
        photo = self._upload(chat, "photo").get_json()["message"]
        after = self._voice(chat).get_json()["message"]
        self.assertEqual([m["meta"] for m in (before, photo, after)],
                         [{"duration_ms": 4200}, {"question": True},
                          {"duration_ms": 4200, "question": True}])
        # The other person reads both as theirs to answer; their answer after
        # my file is not a question, nor is their voice note after it.
        self.who = SOMEONE
        said = self._get(f"/v2/chats/{chat}/messages").get_json()["messages"]
        self.assertEqual([(m["kind"], m["mine"], m["meta"].get("question")) for m in said],
                         [("voice", False, None), ("photo", False, True), ("voice", False, True)])
        self.who = ME
        self._upload(chat, "file", b"%PDF", "application/pdf", "Brief.pdf")
        self.who = SOMEONE
        reply = self._voice(chat).get_json()["message"]
        self.assertEqual(reply["meta"], {"duration_ms": 4200})

    def test_a_photo_that_is_not_one_or_anything_over_10_mb_is_refused(self):
        chat = self._shared_chat()
        for route, wrong, answer in (
                ("photo", {"kind": "text/plain"}, (400, "NOT_ALLOWED")),
                ("photo", {"kind": "image/svg+xml", "data": b"<svg/>"}, (400, "NOT_ALLOWED")),
                ("photo", {"data": b""}, (400, "NOT_ALLOWED")),
                ("file", {"data": None}, (400, "NOT_ALLOWED")),
                ("file", {"data": b"x" * (MAX_FILE_BYTES + 1)}, (413, "TOO_LARGE"))):
            res = self._upload(chat, route, **wrong)
            self.assertEqual((res.status_code, res.get_json()["code"]), answer, (route, wrong.keys()))
        self.assertEqual(self.store.tables.get("chat_messages", []), [])
        self.assertEqual(self.store.count("chat_message_files"), 0)


    def test_an_answer_plays_my_take_and_the_other_member_gets_just_the_answer(self):
        chat = self._shared_chat()
        mine, long_one, theirs = (str(uuid.uuid4()) for _ in range(3))
        self.store.table("recordings").insert([
            {"session_v2_id": mine, "user_id": ME, "duration": 52,
             "storage_path": "willab_lab/a/recording_1.webm"},
            {"session_v2_id": long_one, "user_id": ME, "duration": 1800,
             "storage_path": "willab_lab/b/recording_2.webm"},
            {"session_v2_id": theirs, "user_id": SOMEONE, "duration": 40,
             "storage_path": "willab_lab/c/recording_3.webm"}]).execute()

        def answer(take):
            return self._post(f"/v2/chats/{chat}/answer", {"take": take, "duration_ms": 52000})

        # Nothing sent: someone else's Take, no Take, and my recording consent
        # withdrawn.
        for take, code in ((theirs, (404, "NOT_FOUND")), (None, (400, "NOT_ALLOWED"))):
            res = answer(take)
            self.assertEqual((res.status_code, res.get_json()["code"]), code, take)
        self.choices["sensitive_information"] = False
        self.assertEqual(answer(mine).get_json()["code"], "PROCESSING_RECORDING_WITHDRAWN")
        self.assertEqual(self.store.tables.get("chat_messages", []), [])
        self.choices["sensitive_information"] = True

        sent = answer(mine).get_json()["message"]
        self.assertEqual((sent["mine"], sent["kind"], sent["meta"]),
                         (True, "voice", {"duration_ms": 52000, "answer": True, "take": mine}))

        self.who = SOMEONE
        said = self._get(f"/v2/chats/{chat}/messages").get_json()["messages"]
        self.assertEqual([(m["mine"], m["kind"], m["meta"]) for m in said],
                         [(False, "voice", {"duration_ms": 52000, "answer": True})])
        with patch("services.lab_audio_storage.get_lab_audio_bytes",
                   lambda key, **_: {"willab_lab/a/recording_1.webm": b"OggS my Take"}[key]):
            played = self._get(f"/v2/chats/{chat}/messages/{sent['id']}/audio")
        self.assertEqual((played.status_code, played.data, played.headers["Content-Type"]),
                         (200, b"OggS my Take", "audio/webm"))

        # A half-hour answer is sent too: an answer is a Take (N486 item 4).
        self.who = ME
        long_sent = answer(long_one)
        self.assertEqual(long_sent.status_code, 200, long_sent.get_json())
        self.assertEqual(long_sent.get_json()["message"]["meta"]["duration_ms"], 1_800_000)


    def test_an_answer_waits_its_five_seconds_and_undo_takes_it_back(self):
        chat = self._shared_chat()
        take, project = str(uuid.uuid4()), str(uuid.uuid4())
        self.store.table("recordings").insert(
            {"session_v2_id": take, "user_id": ME, "duration": 52,
             "storage_path": "willab_lab/a/recording_1.webm"}).execute()
        later: list = []
        pushed: list = []
        will: list = []
        for p in (patch("services.chats._after", lambda _s, then: later.append(then)),
                  patch("services.chats._tell", lambda _db, _me, m: pushed.append(m["id"])),
                  patch.object(db, "insert_lounge_messages",
                               lambda user, rows: will.extend((user, r) for r in rows) or rows)):
            p.start()
            self.addCleanup(p.stop)

        def answer(hold):
            return self._post(f"/v2/chats/{chat}/answer",
                              {"take": take, "duration_ms": 52000, "hold_ms": hold})

        def seen_by(who):
            self.who = who
            said = [m["id"] for m in self._get(f"/v2/chats/{chat}/messages").get_json()["messages"]]
            last = self._get("/v2/chats").get_json()["chats"][0]["last"]
            self.who = ME
            return said, last

        # Held: nobody sees it, no push; Undo takes it back and Will says so.
        held = answer(4000).get_json()["message"]
        self.assertEqual((seen_by(SOMEONE), seen_by(ME), pushed), (([], None), ([], None), []))
        undo = self._post(f"/v2/chats/{chat}/answer/undo", {"message": held["id"], "project": project})
        self.assertEqual((undo.status_code, undo.get_json()), (200, {"undone": True}))
        self.assertEqual(self._post(f"/v2/chats/{chat}/answer/undo",
                                    {"message": held["id"]}).status_code, 404)
        later.pop()()
        self.assertEqual(pushed, [])
        # Taken back before its message existed: the same one line.
        self._post(f"/v2/chats/{chat}/answer/undo", {"project": project})
        self.assertEqual({(user, r["client_id"], r["role"], r["kind"], r["body"]) for user, r in will},
                         {(ME, will[0][1]["client_id"], "bot", "text",
                           "You took this one back, so Ariel didn't hear it. "
                           "Here's what I noticed, for practice.")})

        # Its time over: Undo is refused, it reaches them, the push goes.
        kept = answer(4000).get_json()["message"]
        self.who = SOMEONE
        self.assertEqual(self._post(f"/v2/chats/{chat}/answer/undo",
                                    {"message": kept["id"]}).status_code, 404)
        self.who = ME
        with patch("services.chats._now", lambda: datetime.now(timezone.utc) + timedelta(seconds=8)):
            self.assertEqual(self._post(f"/v2/chats/{chat}/answer/undo",
                                        {"message": kept["id"]}).get_json()["code"], "ALREADY_SENT")
            self.assertEqual(seen_by(SOMEONE)[0], [kept["id"]])
        later.pop()()
        self.assertEqual(pushed, [kept["id"]])

        # No time left (Send again): it goes at once.
        now = answer(0).get_json()["message"]
        self.assertEqual((seen_by(SOMEONE)[0][-1], pushed[-1], "held_until" in now["meta"]),
                         (now["id"], now["id"], False))

    def test_my_question_is_sent_as_an_answer_is_and_marked_for_them_to_answer(self):
        chat = self._shared_chat()
        take = str(uuid.uuid4())
        self.store.table("recordings").insert(
            {"session_v2_id": take, "user_id": ME, "duration": 14,
             "storage_path": "willab_lab/q/recording_1.webm"}).execute()
        for p in (patch("services.chats._after", lambda _s, _then: None),
                  patch("services.chats._tell", lambda *_: None),
                  patch.object(db, "insert_lounge_messages", lambda _user, rows: rows)):
            p.start()
            self.addCleanup(p.stop)

        def ask(hold):
            return self._post(f"/v2/chats/{chat}/question",
                              {"take": take, "duration_ms": 14000, "hold_ms": hold})

        # Held, then taken back with the answer's Undo: nobody sees it.
        held = ask(4000).get_json()["message"]
        self.assertEqual(self._post(f"/v2/chats/{chat}/answer/undo",
                                    {"message": held["id"]}).get_json(), {"undone": True})
        # Sent: mine with its Take; theirs marked for them to answer.
        sent = ask(0).get_json()["message"]
        marks = {"duration_ms": 14000, "answer": True, "asked": True, "question": True,
                 "record_answer": True}
        self.assertEqual(sent["meta"], {**marks, "take": take})
        self.who = SOMEONE
        said = self._get(f"/v2/chats/{chat}/messages").get_json()["messages"]
        self.assertEqual([(m["mine"], m["kind"], m["meta"]) for m in said], [(False, "voice", marks)])

    def test_not_now_tells_nobody_and_is_kept_once_for_the_founder(self):
        from services.chat_not_now import for_person
        chat = self._shared_chat()
        members = {m["user_id"]: m["id"] for m in self.store.table("chat_members").select("*")
                   .eq("thread_id", chat).execute().data}
        rows = self.store.table("chat_messages").insert([
            {"thread_id": chat, "author_member_id": members[SOMEONE], "kind": "take", "body": "",
             "meta": {"take_index": 3, "project_title": "Q3 board pitch"}},
            {"thread_id": chat, "author_member_id": members[SOMEONE], "kind": "emoji", "body": "👍",
             "meta": {}},
            {"thread_id": chat, "author_member_id": members[ME], "kind": "take", "body": "",
             "meta": {"take_index": 4}}]).execute().data
        theirs, nothing, mine = (r["id"] for r in rows)
        said = len(self.store.table("chat_messages").select("*").execute().data)

        for _ in range(2):
            answer = self._post(f"/v2/chats/{chat}/messages/{theirs}/not-now")
            self.assertEqual((answer.status_code, answer.get_json()), (200, {"kept": True}))
        self.assertEqual(self._post(f"/v2/chats/{chat}/messages/{mine}/not-now").status_code, 400)
        self.assertEqual(self._post(f"/v2/chats/{chat}/messages/{nothing}/not-now").status_code, 400)
        self.assertEqual(len(self.store.table("chat_messages").select("*").execute().data), said)

        read = for_person(db, ME)
        self.assertEqual(read["count"], 1)
        self.assertEqual([(d["what"], d["flow"], d["asker"]) for d in read["declines"]],
                         [("take", "list", "Ariel")])
        self.assertEqual(for_person(db, SOMEONE), {"count": 0, "declines": []})

    def test_will_marks_a_question_about_a_product_or_a_treatment(self):
        chat = self._shared_chat()
        asked: list = []

        def will(word):
            def answer(**kwargs):
                asked.append((kwargs["surface"], kwargs["user"]))
                return type("Result", (), {"text": word})()
            return answer

        self.said = "Would the scalp treatment help with the itching?"
        for word, mark in (("Yes.", {"record_answer": True}), ("no", {"record_answer": False}),
                           ("maybe", {})):
            self._upload(chat, "photo")
            with patch("services.llm.chat_complete", will(word)):
                sent = self._voice(chat).get_json()["message"]
            self.assertEqual(sent["meta"], {"duration_ms": 4200, "question": True, **mark}, word)
        self.assertEqual(asked[0], ("question_kind",
                                    "Question: Would the scalp treatment help with the itching?"))
        # A voice note that is no question is not read.
        self._post(f"/v2/chats/{chat}/messages", {"kind": "emoji", "body": "👍"})
        with patch("services.llm.chat_complete", will("yes")):
            plain = self._voice(chat).get_json()["message"]
        self.assertEqual(plain["meta"], {"duration_ms": 4200})
        self.assertEqual(len(asked), 3)

        # The demo customer's question carries the mark, and so does one
        # seeded before the mark existed.
        sarah = self._chat("customer")
        said = self._get(f"/v2/chats/{sarah['id']}/messages").get_json()["messages"]
        self.assertEqual(said[-1]["meta"], {"record_answer": True})
        for row in self.store.tables["chat_messages"]:
            if row["thread_id"] == sarah["id"]:
                row["meta"] = {}
        said = self._get(f"/v2/chats/{sarah['id']}/messages").get_json()["messages"]
        self.assertEqual(said[-1]["meta"], {"record_answer": True})
    def test_an_answer_carries_its_takes_words_and_slides_once_processed(self):
        chat = self._shared_chat()
        take = str(uuid.uuid4())
        self.store.table("recordings").insert(
            {"session_v2_id": take, "user_id": ME, "duration": 30,
             "storage_path": "willab_lab/a/recording_1.webm"}).execute()
        sent = self._post(f"/v2/chats/{chat}/answer", {"take": take}).get_json()["message"]

        # Still processing: nothing to read yet.
        said = self._get(f"/v2/chats/{chat}/messages").get_json()["messages"]
        self.assertEqual([(m["id"], m["words"], m["slides"]) for m in said], [(sent["id"], None, [])])

        self.store.table("v2_sessions").insert({"id": take, "slide_transcripts": [
            {"index": 1, "transcript": " Always check the quote. ", "start_offset_ms": 21000,
             "duration_ms": 9000},
            {"index": 0, "transcript": "Yes, it can pick them.", "start_offset_ms": 0,
             "duration_ms": 21000}]}).execute()
        for who in (ME, SOMEONE):
            self.who = who
            said = self._get(f"/v2/chats/{chat}/messages").get_json()["messages"]
            self.assertEqual([(m["words"], m["slides"]) for m in said],
                             [("Yes, it can pick them.\n\nAlways check the quote.", [0, 21000])])


if __name__ == "__main__":
    unittest.main()
