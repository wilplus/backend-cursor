"""
STORY    As a speaker, I want to send my Take to the people I tick, each as my
         own message in my chat with them, so that the people I trust hear
         it and can answer me; as the person it is sent to, I want to hear
         it and read its words, and nothing else of it.
OUTCOME
  O1  While sending is off (TAKE_SEND_ENABLED, default off), the new routes
      answer {enabled: false}, the send 409 SENDING_OFF, and nothing is
      written.
  O2  The list is the other person of each of my chats with a real person:
      the one I sent to last first ("Last sent"), then my chats' order; no
      demo chat, no guest, nobody I blocked and nobody who blocked me
      (N466).
  O3  With no chat with a person at all, the founder is listed (Artur,
      speaking coach) with no chat yet; the chat is made on my first send,
      never on a read, and only once. The founder is the account with the
      admin email (ADMIN_EMAIL), no env var needed; FOUNDER_CHAT_USER_ID,
      when set, wins. Nobody has that email: nobody.
  O4  Sending is idempotent: sending again posts nothing twice and pushes
      nothing twice; adding people later only adds; nothing is unsent. The
      line under my recording keeps who it went to, and my last choice is
      read back. Only my own Take, and never an answer. A send that goes
      late, after my next Take's line is written, never adds its people to
      that newer line (N541 item 2).
  O5  Someone not in the chat cannot open a Take sent in it, not even
      through a chat of their own.
  O6  The person it is sent to sees "{name} sent you Take {n}", plays the
      Take and reads its words slide by slide (the list's last line says
      whose it is and its number), and never gets the Take's id, its Ideal
      Text, its feedback, moments or levels.
PROVES   O1 -> TakeSendsTest::test_while_sending_is_off_nothing_new_runs
         O2 -> TakeSendsTest::test_the_list_is_real_people_last_sent_first
         O3 -> TakeSendsTest::test_with_no_chat_with_a_person_the_founder_is_listed
         O3 -> TakeSendsTest::test_with_no_env_var_the_founder_is_the_admin_email_account
         O4 -> TakeSendsTest::test_sending_again_only_adds_people_and_is_kept_on_the_line
         O4 -> TakeSendsTest::test_a_late_send_never_changes_a_newer_takes_line
         O5 -> TakeSendsTest::test_someone_not_in_the_chat_cannot_open_the_take
         O6 -> TakeSendsTest::test_the_receiver_hears_the_take_and_reads_its_words_only
WHY      N470 and N479 (founder, the Claude Code chat, 4 November 2026): a
         Take goes to the people the speaker ticks; never a score or the
         machine's read to anyone (Never 1, 2). Built on tests/test_chats.py's
         in-memory chat tables.
"""
from __future__ import annotations

import unittest
import uuid
from unittest.mock import patch

from config import Config
from services import take_sends
from services.db import db
from tests import test_chats as base
from tests.test_chats import ME, OTHER, SOMEONE

MAYA = "44444444-4444-4444-8444-444444444444"
BLOCKER = "55555555-5555-4555-8555-555555555555"
FOUNDER = "66666666-6666-4666-8666-666666666666"
PROJECT = "77777777-7777-4777-8777-777777777777"


def _eq(self, column, value):
    """The fake's eq, also for a JSON field (``meta->>take``)."""
    if "->>" in column:
        field, key = column.split("->>", 1)
        self.filters.append(lambda r: str((r.get(field) or {}).get(key)) == str(value))
        return self
    self.filters.append(lambda r: r.get(column) == value)
    return self


class TakeSendsTest(unittest.TestCase):
    setUp_chats = base.ChatsTest.setUp
    _get = base.ChatsTest._get
    _post = base.ChatsTest._post

    def setUp(self):
        self.setUp_chats()
        self.lines: list[dict] = []
        self.pushes: list = []
        self.on = True
        self.accounts: dict[str, str] = {}
        take_sends._FOUNDER_IDS.clear()
        self.addCleanup(take_sends._FOUNDER_IDS.clear)

        def lines(user, limit=10):
            return [dict(r) for r in reversed(self.lines) if r["user_id"] == user][:limit]

        def rewrite(user, client_id, body, metadata, at=None):
            for r in self.lines:
                if r["user_id"] == user and r["client_id"] == client_id:
                    r.update(body=body, metadata=metadata)
                    return r
            return None

        for p in (patch.object(base._Query, "eq", _eq),
                  patch.object(Config, "TAKE_SEND_ENABLED", True),
                  patch.object(Config, "FOUNDER_CHAT_USER_ID", None),
                  patch.object(db, "v2_find_user_id_by_email",
                               lambda email: self.accounts.get(email)),
                  patch.object(db, "list_lounge_share_lines", lines, create=True),
                  patch.object(db, "rewrite_lounge_message", rewrite, create=True),
                  patch("services.push_devices.push_later",
                        lambda _db, user, **kw: self.pushes.append((user, kw["title"], kw["body"]))),
                  patch("services.snippet_audio_url.recording_playback_url",
                        lambda row, _db, _cfg: f"https://signed.example/{row['storage_path']}")):
            p.start()
            self.addCleanup(p.stop)

    # ── helpers ──────────────────────────────────────────────────────────

    def _chat_with(self, user, name, *, mine="Artur", subtitle=None):
        thread = self.store.table("chat_threads").insert(
            {"kind": "team", "title": name}).execute().data[0]["id"]
        self.store.table("chat_members").insert([
            {"thread_id": thread, "user_id": ME, "display_name": mine},
            {"thread_id": thread, "user_id": user, "display_name": name,
             "subtitle": subtitle}]).execute()
        return thread

    def _take(self, owner=ME, index=2):
        take = str(uuid.uuid4())
        self.store.table("recordings").insert(
            {"session_v2_id": take, "user_id": owner, "duration": 52,
             "storage_path": f"willab_lab/{take}/recording_{index}.webm"}).execute()
        self.store.table("v2_sessions").insert(
            {"id": take, "user_id": owner, "take_index": index, "project_id": PROJECT,
             "ideal_text": "Their Ideal Text", "feedback": {"score": 7},
             "slide_transcripts": [
                 {"index": 1, "transcript": " Always check the quote. ", "start_offset_ms": 21000},
                 {"index": 0, "transcript": "Yes, it can pick them.", "start_offset_ms": 0}]}
        ).execute()
        self.store.table("projects").insert({"id": PROJECT, "display_name": "Board pitch"}).execute()
        return take

    def _line(self, body="Maya", **meta):
        """The line under the recording, as the app writes it before a Take,
        stamped by the database's clock as it is stored (the Take's row is
        stamped by the same clock at its upload)."""
        self.lines.append(self.store.defaults("lounge_messages", {
            "user_id": ME, "client_id": str(uuid.uuid4()), "body": body,
            "metadata": {"step": "share", "author": "speaker", **meta}}))

    def _send(self, take, body):
        return self._post(f"/v2/user/takes/{take}/send", body)

    def _people(self):
        res = self._get("/v2/user/takes/send/people")
        self.assertEqual(res.status_code, 200)
        return res.get_json()

    def _messages(self, kind="take"):
        return [m for m in self.store.tables.get("chat_messages", []) if m["kind"] == kind]

    # ── O1 ───────────────────────────────────────────────────────────────

    def test_while_sending_is_off_nothing_new_runs(self):
        chat = self._chat_with(MAYA, "Maya")
        take = self._take()
        before = {k: [dict(r) for r in v] for k, v in self.store.tables.items()}
        with patch.object(Config, "TAKE_SEND_ENABLED", False):
            for path in ("/v2/user/takes/send/people", "/v2/user/takes/send/last",
                         f"/v2/chats/{chat}/messages/{uuid.uuid4()}/take"):
                res = self._get(path)
                self.assertEqual((res.status_code, res.get_json()), (200, {"enabled": False}), path)
            res = self._send(take, {"all": True, "user_ids": []})
            self.assertEqual((res.status_code, res.get_json()["code"]), (409, "SENDING_OFF"))
        self.assertEqual(self.store.tables, before)
        self.assertEqual(self.pushes, [])

    # ── O2 ───────────────────────────────────────────────────────────────

    def test_the_list_is_real_people_last_sent_first(self):
        self._post("/v2/chats/demo")
        maya = self._chat_with(MAYA, "Maya Lindqvist", subtitle="Your colleague")
        ariel = self._chat_with(SOMEONE, "Ariel")
        blocked = self._chat_with(OTHER, "Blocked by me")
        blocker = self._chat_with(BLOCKER, "Blocks me")
        guest = self._chat_with(None, "A guest")
        self.assertEqual(self._post(f"/v2/chats/{blocked}/block").status_code, 200)
        self.who = BLOCKER
        self.assertEqual(self._post(f"/v2/chats/{blocker}/block").status_code, 200)
        self.who = ME
        self.store.table("people_profiles").insert(
            {"user_id": SOMEONE, "name": "Ariel Stone", "role": "Sales lead",
             "photo_type": "image/png"}).execute()
        del guest

        # Before anything is sent: the list of chats' order, newest first.
        listed = self._people()
        self.assertEqual(listed["enabled"], True)
        self.assertEqual(listed["people"], [
            {"user_id": SOMEONE, "name": "Ariel Stone", "title": "Sales lead",
             "avatar_url": f"/api/v2/chats/{ariel}/profile/photo", "chat_id": ariel,
             "last_sent": False},
            {"user_id": MAYA, "name": "Maya Lindqvist", "title": "Your colleague",
             "avatar_url": None, "chat_id": maya, "last_sent": False}])

        # Sent to Maya, then Ariel's chat moves on: Maya stays on top.
        self.assertEqual(self._send(self._take(), {"all": False, "user_ids": [MAYA]}).status_code, 200)
        self._post(f"/v2/chats/{ariel}/messages", {"kind": "emoji", "body": "👍"})
        self.assertEqual([(p["user_id"], p["last_sent"]) for p in self._people()["people"]],
                         [(MAYA, True), (SOMEONE, False)])

        # Someone blocked, or not on the list, is never sent to.
        self._send(self._take(index=3), {"all": False, "user_ids": [OTHER, BLOCKER]})
        self.assertEqual({m["thread_id"] for m in self._messages()}, {maya})

    # ── O3 ───────────────────────────────────────────────────────────────

    def test_with_no_chat_with_a_person_the_founder_is_listed(self):
        self._post("/v2/chats/demo")
        self.assertEqual(self._people()["people"], [])
        with patch.object(Config, "FOUNDER_CHAT_USER_ID", FOUNDER):
            threads = self.store.count("chat_threads")
            self.assertEqual(self._people()["people"], [
                {"user_id": FOUNDER, "name": "Artur", "title": "speaking coach",
                 "avatar_url": None, "chat_id": None, "last_sent": False}])
            self.assertEqual(self.store.count("chat_threads"), threads)  # never on a read

            take = self._take()
            sent = self._send(take, {"all": True, "user_ids": []}).get_json()["sent"]
            again = self._send(take, {"all": True, "user_ids": []}).get_json()["sent"]
            self.assertEqual(again, sent)
            self.assertEqual(self.store.count("chat_threads"), threads + 1)
            chat = sent[0]["chat_id"]
            self.assertEqual(self._people()["people"][0]["chat_id"], chat)
            self.assertEqual(len(self._messages()), 1)
            self.assertEqual([p[0] for p in self.pushes], [FOUNDER])
            # The founder reads it in his chat with the speaker.
            self.who = FOUNDER
            said = self._get(f"/v2/chats/{chat}/messages").get_json()["messages"]
            self.assertEqual([m["kind"] for m in said], ["take"])

    def test_with_no_env_var_the_founder_is_the_admin_email_account(self):
        self._post("/v2/chats/demo")
        with patch.object(Config, "ADMIN_EMAIL", "Founder@Example.com"):
            self.assertEqual(self._people()["people"], [])  # nobody has that email
            take_sends._FOUNDER_IDS.clear()
            self.accounts["founder@example.com"] = FOUNDER
            self.assertEqual(self._people()["people"], [
                {"user_id": FOUNDER, "name": "Artur", "title": "speaking coach",
                 "avatar_url": None, "chat_id": None, "last_sent": False}])

        # ── O4 ───────────────────────────────────────────────────────────────

    def test_sending_again_only_adds_people_and_is_kept_on_the_line(self):
        maya = self._chat_with(MAYA, "Maya Lindqvist")
        ariel = self._chat_with(SOMEONE, "Ariel")
        self.assertEqual(self._get("/v2/user/takes/send/last").get_json(),
                         {"enabled": True, "choice": None})
        self._line()
        take = self._take()

        first = self._send(take, {"all": False, "user_ids": [MAYA]})
        self.assertEqual(first.status_code, 200)
        again = self._send(take, {"all": False, "user_ids": [MAYA]})
        self.assertEqual(again.get_json(), first.get_json())
        self.assertEqual(first.get_json()["sent"][0]["chat_id"], maya)
        self.assertEqual((len(self._messages()), len(self.pushes)), (1, 1))

        # Adding Ariel later adds; nothing of Maya's goes.
        self._send(take, {"all": False, "user_ids": [SOMEONE]})
        self.assertEqual(sorted(m["thread_id"] for m in self._messages()), sorted([maya, ariel]))
        self.assertEqual(self.lines[-1]["metadata"]["share"],
                         {"kind": "people", "all": False, "user_ids": [MAYA, SOMEONE],
                          "names": ["Maya Lindqvist", "Ariel"]})
        self.assertEqual(self.lines[-1]["body"], "Maya")
        self.assertEqual(self._get("/v2/user/takes/send/last").get_json(),
                         {"enabled": True, "choice": {"all": False, "user_ids": [MAYA, SOMEONE]}})

        # Not my Take, nothing chosen, or an answer's Take: nothing sent.
        theirs = self._take(owner=SOMEONE)
        self.assertEqual(self._send(theirs, {"all": True}).status_code, 404)
        self.assertEqual(self._send(take, {"all": False, "user_ids": []}).get_json()["code"],
                         "NOTHING_CHOSEN")
        answered = self._take(index=4)
        self._post(f"/v2/chats/{maya}/answer", {"take": answered})
        self.assertEqual(self._send(answered, {"all": True}).get_json()["code"], "NOT_ALLOWED")
        self.assertEqual(len(self._messages()), 2)

    def test_a_late_send_never_changes_a_newer_takes_line(self):
        self._chat_with(MAYA, "Maya Lindqvist")
        self._chat_with(SOMEONE, "Ariel")

        def people(*pairs):
            return {"kind": "people", "all": False,
                    "user_ids": [i for i, _ in pairs], "names": [n for _, n in pairs]}

        # Take 3 goes to Maya: its line, then its upload; its send fails.
        self._line(body="Maya Lindqvist", share=people((MAYA, "Maya Lindqvist")))
        take3 = self._take(index=3)
        # Take 4 goes to Ariel: its line, then its upload.
        self._line(body="Ariel", share=people((SOMEONE, "Ariel")))
        take4 = self._take(index=4)

        # At the next open Take 3's send goes through: Maya gets it, and
        # Take 4's line still names Ariel alone, as does the last choice.
        res = self._send(take3, {"all": False, "user_ids": [MAYA]})
        self.assertEqual(res.status_code, 200)
        self.assertEqual([m["meta"]["take_session_id"] for m in self._messages()], [take3])
        self.assertEqual([(line["body"], line["metadata"]["share"]) for line in self.lines], [
            ("Maya Lindqvist", people((MAYA, "Maya Lindqvist"))),
            ("Ariel", people((SOMEONE, "Ariel")))])
        self.assertEqual(self._get("/v2/user/takes/send/last").get_json(),
                         {"enabled": True, "choice": {"all": False, "user_ids": [SOMEONE]}})

        # Take 4's own send, after its line, is kept on it.
        self._send(take4, {"all": False, "user_ids": [SOMEONE, MAYA]})
        self.assertEqual(self.lines[-1]["metadata"]["share"],
                         people((SOMEONE, "Ariel"), (MAYA, "Maya Lindqvist")))

    # ── O5 ───────────────────────────────────────────────────────────────

    def test_someone_not_in_the_chat_cannot_open_the_take(self):
        maya = self._chat_with(MAYA, "Maya")
        sent = self._send(self._take(), {"all": True}).get_json()["sent"][0]
        self.who = OTHER
        res = self._get(f"/v2/chats/{maya}/messages/{sent['message_id']}/take")
        self.assertEqual(res.status_code, 404)
        # Not through a chat of their own either.
        own = self.store.table("chat_threads").insert({"kind": "team", "title": "x"}).execute().data[0]["id"]
        self.store.table("chat_members").insert({"thread_id": own, "user_id": OTHER,
                                                 "display_name": "Other"}).execute()
        res = self._get(f"/v2/chats/{own}/messages/{sent['message_id']}/take")
        self.assertEqual(res.status_code, 404)

    # ── O6 ───────────────────────────────────────────────────────────────

    def test_the_receiver_hears_the_take_and_reads_its_words_only(self):
        maya = self._chat_with(MAYA, "Maya")
        take = self._take(index=2)
        sent = self._send(take, {"all": True}).get_json()["sent"][0]
        self.assertEqual(self.pushes, [(MAYA, "Artur", "Artur sent you Take 2")])

        self.who = MAYA
        said = self._get(f"/v2/chats/{maya}/messages").get_json()["messages"]
        self.assertEqual([(m["mine"], m["author"], m["kind"], m["meta"]) for m in said],
                         [(False, "Artur", "take",
                           {"take_index": 2, "project_title": "Board pitch", "duration_ms": 52000})])
        self.assertEqual(self._get("/v2/chats").get_json()["chats"][0]["last"],
                         {"kind": "take", "body": "", "created_at": said[0]["created_at"],
                          "mine": False, "meta": {"take_index": 2}})
        opened = self._get(f"/v2/chats/{maya}/messages/{sent['message_id']}/take")
        self.assertEqual(opened.status_code, 200)
        self.assertEqual(opened.get_json(), {
            "audio_url": f"https://signed.example/willab_lab/{take}/recording_2.webm",
            "duration_ms": 52000,
            "slides": [{"index": 0, "title": None, "words": "Yes, it can pick them."},
                       {"index": 1, "title": None, "words": "Always check the quote."}]})
        with patch("services.lab_audio_storage.get_lab_audio_bytes", lambda key, **_: b"OggS my Take"):
            played = self._get(f"/v2/chats/{maya}/messages/{sent['message_id']}/audio")
        self.assertEqual((played.status_code, played.data), (200, b"OggS my Take"))


if __name__ == "__main__":
    unittest.main()
