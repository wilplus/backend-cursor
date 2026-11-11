"""
STORY    As a person with the chat builder, I want Will's chat to hold only
         my model, my chat's setup and what needs me, the speaking chat
         to hold everything about my Takes, and "Principles" the
         principles coaching, without anything being stored differently
         (N635, widened to three places).
OUTCOME
  O1  Every writer of the Lounge is named here, and each kind of row it
      writes is placed in exactly one chat; a new writer that this list
      does not name fails the test.
  O2  GET /v2/user/lounge/messages?place=speaking returns only the
      speaking chat's rows, ?place=principles only the principles chat's,
      ?place=will only Will's, and no place every
      row as before; each row says its place, and a place reads older
      pages until it has a page of its own.
  O3  A Take recorded in my chat with the speaking host (services/
      take_door.py) shows its rows in that chat, to me only: its Ideal
      Text card, the walk and its summary come back for ?chat=<that chat>,
      each placed "chat" with its chat_id, and are gone from
      ?place=speaking; my old Takes, made in the pinned speaking chat,
      stay in "speaking"; my own speaking rows with no Take (the plan, the
      feelings check) are in both, so nothing disappears. An arc's own
      rows go to the chat of the arc's latest Take. The host, a chat that is not mine, or a
      person off the ring row chat_builder get 404 for ?chat=, and off the
      ring every row is placed as before.
PROVES   O1 -> LoungePlaceTest::test_every_lounge_writer_places_its_rows
         O1 -> LoungePlaceTest::test_a_typed_turn_stays_in_the_chat_it_was_typed_in
         O2 -> LoungePlaceTest::test_the_read_returns_one_place
         O3 -> HostChatPlaceTest::test_a_take_made_in_the_hosts_chat_is_shown_there_to_me_only
WHY      services/lounge_messages.place_of is the one list (N635 item 4:
         the rows stay where they are written; each chat shows its own).
"""
from __future__ import annotations

import pathlib
import unittest
import uuid
from unittest.mock import patch
from urllib.parse import quote

from services.lounge_messages import PRINCIPLES, SPEAKING, WILL, place_of
from tests.test_chats import ME
from tests.test_take_sends import FOUNDER as HOST
from tests.test_take_sends import MAYA

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: Every module that writes the Lounge, with one row of each kind it writes
#: and the chat that row belongs to. A writer missing here fails O1.
WRITERS: dict[str, list[tuple[dict, str]]] = {
    "services/plan_flow.py": [  # the plan's questions, card, hellos; the way in (N590)
        ({"role": "bot", "kind": "text", "metadata": {"plan": "p1", "plan_ask": "voice"}}, SPEAKING),
        ({"role": "user", "kind": "text", "metadata": {"plan": "p1"}}, SPEAKING)],
    "services/after_take.py": [  # the goodbye after a Take, its bridge, its asks
        ({"role": "bot", "kind": "text", "metadata": {"arc_id": "a", "take_session_id": "t",
                                                       "first_take": True}}, SPEAKING),
        ({"role": "bot", "kind": "text", "metadata": {"bridge": True, "arc_id": "a"}}, SPEAKING)],
    "services/take_summary.py": [  # the cadence after a Take; the coach's word on a Take
        ({"role": "bot", "kind": "cadence", "metadata": {"arc_id": "a"}}, SPEAKING),
        ({"role": "bot", "kind": "walk_step", "metadata": {"step": "coachnote"}}, SPEAKING)],
    "services/arc_notifications.py": [  # "Your feedback is ready." and the Ideal Text bubbles
        ({"role": "bot", "kind": "ideal_text", "metadata": {"arc_id": "a"}}, SPEAKING),
        ({"role": "bot", "kind": "text", "metadata": {"arc_id": "a", "variant": "ready"}}, SPEAKING)],
    "services/feedback_check.py": [  # the feelings check
        ({"role": "user", "kind": "text", "metadata": {"feedback_check": "fine", "arc_id": "a"}}, SPEAKING),
        ({"role": "bot", "kind": "text", "metadata": {"offer": "feedback_check"}}, SPEAKING)],
    "services/feedback_digest.py": [
        ({"role": "bot", "kind": "text", "metadata": {"note": "feedback_digest", "week": "2026-W45"}}, SPEAKING)],
    "services/will_question.py": [  # Will's question on a Take
        ({"role": "bot", "kind": "text", "metadata": {"offer": "will_question", "will_question": "k",
                                                       "arc_id": "a", "take_session_id": "t"}}, SPEAKING)],
    "routes/v2/explore_ideal_text.py": [  # a Take's next steps
        ({"role": "bot", "kind": "cadence", "metadata": {"journey": True, "arc_id": "a"}}, SPEAKING)],
    "services/chat_query.py": [  # talking to Will; the latest Take's card; the WhatsApp ask
        ({"role": "user", "kind": "text", "metadata": None}, WILL),
        ({"role": "bot", "kind": "text", "metadata": {"intent": "help"}}, WILL),
        ({"role": "bot", "kind": "ideal_text", "metadata": {"arc_id": "a", "variant": "ready"}}, SPEAKING),
        ({"role": "bot", "kind": "text", "metadata": {"offer": "whatsapp"}}, SPEAKING)],
    "services/chat_setup.py": [({"role": "bot", "kind": "text", "metadata": {"chat_setup": {}}}, WILL)],
    "services/join_setup.py": [({"role": "bot", "kind": "text", "metadata": {"join_setup": {}}}, WILL)],
    "services/chats.py": [({"role": "bot", "kind": "text", "metadata": {"answer_taken_back": True}}, WILL)],
    "services/goal_history.py": [
        ({"role": "bot", "kind": "text", "metadata": {"card": "goal_change", "speaker": "S1"}}, SPEAKING)],
    "services/in_control.py": [({"role": "bot", "kind": "text", "metadata": {"in_control": "x"}},PRINCIPLES)],
    "services/life_goals.py": [
        ({"role": "bot", "kind": "text", "metadata": {"offer": "life_goals"}},PRINCIPLES),
        ({"role": "bot", "kind": "text", "metadata": {"life_goal_quarter": "g"}},PRINCIPLES)],
    "services/sales_framing.py": [
        ({"role": "bot", "kind": "text", "metadata": {"offer": "sales_step", "sales_note": "n"}},PRINCIPLES)],
    "services/strengths.py": [
        ({"role": "bot", "kind": "text", "metadata": {"offer": "strengths", "strength_id": "s"}},PRINCIPLES)],
    "services/sunday_note.py": [
        ({"role": "bot", "kind": "text", "metadata": {"offer": "sunday_note", "sunday_note_id": "n"}},PRINCIPLES)],
    "services/voice_notebook.py": [({"role": "bot", "kind": "text", "metadata": {"offer": "voice_notebook"}},PRINCIPLES)],
    "services/your_why.py": [({"role": "bot", "kind": "text", "metadata": {"offer": "your_why"}},PRINCIPLES)],
    # The app's own rows (POST /v2/user/lounge/messages): a Take's readout,
    # the walk's steps, a typed line to Will, an offer the app makes.
    "routes/v2/lounge.py": [
        ({"role": "system", "kind": "recording_summary", "metadata": {"session_id": "t"}}, SPEAKING),
        ({"role": "bot", "kind": "walk_step", "metadata": {"step": "end"}}, SPEAKING),
        ({"role": "user", "kind": "text", "metadata": None}, WILL),
        ({"role": "bot", "kind": "text", "metadata": {"offer": "joke"}}, SPEAKING)],
}
#: Not writers: the storage call itself and the POST's own validation.
NOT_WRITERS = {"services/db.py", "services/lounge_messages.py"}


def _writers_in_code() -> set[str]:
    found = set()
    for folder in ("services", "routes"):
        for path in (ROOT / folder).rglob("*.py"):
            if "insert_lounge_messages(" in path.read_text(encoding="utf-8"):
                found.add(str(path.relative_to(ROOT)))
    return found - NOT_WRITERS


class LoungePlaceTest(unittest.TestCase):
    def test_every_lounge_writer_places_its_rows(self):
        self.assertEqual(_writers_in_code(), set(WRITERS),
                         "a Lounge writer is new or gone: place its rows in services/lounge_messages.py "
                         "and name it here")
        for writer, rows in WRITERS.items():
            for row, place in rows:
                self.assertIn(place_of(row), (SPEAKING, PRINCIPLES, WILL))
                self.assertEqual(place_of(row), place, f"{writer}: {row}")

    def test_a_typed_turn_stays_in_the_chat_it_was_typed_in(self):
        """N635: a turn typed in a chat, written by the backend from the
        chat query, and Will's reply to it, stay in that chat: both rows
        carry ``metadata.place``; with no place, as before."""
        import uuid

        from services.chat_query import persist_chat_turn
        written: list[dict] = []

        class _Db:
            def insert_lounge_messages(self, _user, rows):
                written.extend(rows)
                return rows
        for place in (SPEAKING, PRINCIPLES, WILL):
            written.clear()
            persist_chat_turn(_Db(), "u1", "What did I note?", "You noted this.",
                              user_client_id=str(uuid.uuid4()), place=place,
                              row_metadata={"arc_id": "a"} if place == WILL else None)
            self.assertEqual([place_of(r) for r in written], [place, place], place)
        written.clear()
        persist_chat_turn(_Db(), "u1", "Hello", "Hi.", user_client_id=str(uuid.uuid4()))
        self.assertEqual([place_of(r) for r in written], [WILL, WILL])
        self.assertIsNone(written[0]["metadata"])

    def test_the_read_returns_one_place(self):
        from flask import Flask

        import auth
        from routes.v2 import register_domains
        from routes.v2.blueprint import v2_bp
        from services.db import db
        register_domains()
        app = Flask(__name__)
        app.register_blueprint(v2_bp, url_prefix="/v2")
        client = app.test_client()
        # 12 rows, newest last: speaking, will, will, speaking, ... by turns.
        rows = []
        for i in range(12):
            speaking = i % 3 == 0
            meta = {"plan": "p"} if speaking else {"offer": "sunday_note"} if i == 4 else {"chat_setup": {}}
            rows.append({"id": str(i), "client_id": f"c{i}", "role": "bot", "kind": "text",
                         "body": f"row {i}", "client_created_at": f"2026-11-10T10:00:{i:02d}+00:00",
                         "metadata": meta})

        def page(_user, *, limit, before=None):
            older = [r for r in rows if before is None or r["client_created_at"] < before]
            return list(reversed(older))[:limit + 1]
        with patch.object(auth, "verify_supabase_token", lambda _t: {"sub": "u1"}), \
                patch.object(db, "get_lounge_messages_page", page), \
                patch("services.lounge_clips.enrich_page", lambda *a, **k: None):
            def get(q):
                return client.get(f"/v2/user/lounge/messages?{q}", headers={"Authorization": "Bearer t"}).get_json()
            everything = get("limit=50")
            self.assertEqual(len(everything["messages"]), 12)
            self.assertEqual({m["place"] for m in everything["messages"]}, {SPEAKING, PRINCIPLES, WILL})
            speaking = get("place=speaking&limit=2")
            self.assertEqual([m["body"] for m in speaking["messages"]], ["row 6", "row 9"])
            self.assertTrue(speaking["has_more"])
            older = get(f"place=speaking&limit=2&before={quote(speaking['oldest_cursor'])}")
            self.assertEqual([m["body"] for m in older["messages"]], ["row 0", "row 3"])
            self.assertEqual([m["body"] for m in get("place=principles&limit=50")["messages"]], ["row 4"])
            will = get("place=will&limit=50")
            self.assertEqual(len(will["messages"]), 7)
            self.assertTrue(all(m["place"] == WILL for m in will["messages"]))
            self.assertEqual(client.get("/v2/user/lounge/messages?place=coach",
                                        headers={"Authorization": "Bearer t"}).status_code, 400)


class HostChatPlaceTest(unittest.TestCase):
    """O3, on the door's in-memory chat tables (tests/test_take_door.py)."""
    from tests.test_take_door import TakeDoorTest as _Door
    setUp, setUp_sends, setUp_chats = _Door.setUp, _Door.setUp_sends, _Door.setUp_chats
    _get, _post, _chat_with, _take, _tag, _messages = (
        _Door._get, _Door._post, _Door._chat_with, _Door._take, _Door._tag, _Door._messages)

    def _lounge(self, q):
        from services.db import db

        def page(_user, *, limit, before=None):
            older = [r for r in self.rows if before is None or r["client_created_at"] < before]
            return list(reversed(older))[:limit + 1]
        with patch.object(db, "get_lounge_messages_page", page), \
                patch("services.lounge_clips.enrich_page", lambda *a, **k: None):
            return self._get(f"/v2/user/lounge/messages?{q}")

    def _session(self, take, arc, at):
        for row in self.store.tables["v2_sessions"]:
            if row["id"] == take:
                row.update(arc_id=arc, created_at=at)

    def test_a_take_made_in_the_hosts_chat_is_shown_there_to_me_only(self):
        chat = self._chat_with(HOST, "Artur")
        maya = self._chat_with(MAYA, "Maya")
        here, elsewhere = self._take(), self._take(index=3)
        self._session(here, "arc-here", "2026-11-11T09:00:00+00:00")
        self._session(elsewhere, "arc-else", "2026-11-11T09:05:00+00:00")
        self.assertEqual(self._tag(chat, here).status_code, 200)
        metas = [("ideal_text", {"arc_id": "arc-here", "variant": "ready"}),   # the Ideal Text card
                 ("walk_step", {"step": "best", "take_session_id": here}),     # the walk
                 ("recording_summary", {"session_id": here}),                  # its summary
                 ("text", {"plan": "p1", "plan_ask": "voice"}),                # the plan
                 ("text", {"feedback_check": "fine"}),                         # the feelings check
                 ("ideal_text", {"arc_id": "arc-else", "variant": "ready"}),   # a Take made elsewhere
                 ("text", {"chat_setup": {}})]                                  # Will's chat
        self.rows = [{"id": str(i), "client_id": f"c{i}", "role": "bot", "kind": kind, "body": f"row {i}",
                      "client_created_at": f"2026-11-11T10:00:{i:02d}+00:00", "metadata": meta}
                     for i, (kind, meta) in enumerate(metas)]

        def bodies(q):
            res = self._lounge(q)
            self.assertEqual(res.status_code, 200, q)
            return res.get_json()["messages"]
        mine = bodies(f"chat={chat}")
        self.assertEqual([m["body"] for m in mine], ["row 0", "row 1", "row 2", "row 3", "row 4"])
        self.assertTrue(all((m["place"], m["chat_id"]) == ("chat", chat) for m in mine))
        # The plan and the feelings check stay too; the old Take stays.
        self.assertEqual([m["body"] for m in bodies("place=speaking")], ["row 3", "row 4", "row 5"])
        self.assertEqual([m["body"] for m in bodies("place=will")], ["row 6"])
        # Nothing of it is written into the chat the host reads.
        self.assertEqual([m["kind"] for m in self._messages()], ["take"])

        # The arc's latest Take was made elsewhere: its card goes back to speaking.
        later = self._take(index=4)
        self._session(later, "arc-here", "2026-11-11T09:30:00+00:00")
        self.assertEqual([m["body"] for m in bodies("place=speaking")], ["row 0", "row 3", "row 4", "row 5"])
        self.assertEqual([m["body"] for m in bodies(f"chat={chat}")], ["row 1", "row 2", "row 3", "row 4"])

        self.assertEqual(self._lounge(f"chat={maya}").status_code, 404)    # no Take made there
        self.assertEqual(self._lounge(f"chat={uuid.uuid4()}").status_code, 404)  # not a member
        self.assertEqual(self._lounge(f"chat={chat}&place=speaking").status_code, 400)
        self.who = HOST                                                     # the host
        self.assertEqual(self._lounge(f"chat={chat}").status_code, 404)
        self.who, self.ring = ME, {HOST}                                   # off the ring
        self.assertEqual(self._lounge(f"chat={chat}").status_code, 404)
        self.assertEqual([m["body"] for m in bodies("place=speaking")],
                         ["row 0", "row 1", "row 2", "row 3", "row 4", "row 5"])


if __name__ == "__main__":
    unittest.main()
