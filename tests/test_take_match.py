"""
STORY    As a speaker, after my Take, I want the page that chose who hears it
         to come back once with someone new who fits what I asked, so that
         the right person can answer; and as that person, I want to hear the
         Take before anyone knows who I am, so that answering is my yes
         (founder, 4 November 2026, N477, N478, N481, N485, N486, N493).
OUTCOME
  O1  With no ring row, or while sending a Take is off, nobody is ever
      suggested: the speaker's routes answer 404.
  O2  After a Take, one person is suggested: someone who shares a community
      with the speaker, has no chat with them, and fits what the Take is
      about; shown as a pseudonym made for this match and their role, never
      a name, never the name the coach queue gives them, and never what
      their own Takes are about. Asking again gives the same one; someone
      who fits nothing is never chosen.
  O3  Someone already in a chat with the speaker, or still waiting to be
      let in (N471), is never suggested, and nobody is suggested to the
      same speaker twice.
  O4  Send knocks: the one suggested gets a new asking chat in their list,
      under the speaker's pseudonym, their role and what it is about; never
      a card in Will's chat, no chat made, and the page does not come back.
  O5  The speaker's Not now tells nobody: no inquiry, no chat.
  O6  Before "Open Take" the one suggested sees only who is asking and
      about what: no name, no words, no recording, no answering. After it,
      the speaker's name and the Take, words slide by slide; their answer,
      a Take, makes the chat between the two, with the speaker's Take (a
      Take message) and the answer in it, under their names.
  O7  Nobody else can open or answer it, the one suggested cannot before it
      was sent, and a Take recorded before it reached them is no answer.
  O8  Once skills are on, the experiment's arm decides among people who
      know as much: someone at a similar level, or someone further along,
      progressing alike; the arm, what made the fit, whether the other arm
      would have chosen someone else and how likely the pick was are kept,
      never another person's id, and the speaker sees none of it.
  O9  Words that say nothing about the subject make no match: Polish
      function words ("dla", "się"), or words everyone in the community
      uses ("presentation", "speak").
  O10 Nobody is suggested who has not recorded a Take in two weeks, or who
      already has three Takes waiting for their answer or five suggestions
      this week.
  O11 Progress is counted within each talk (N494): someone who gets better
      Take by Take in each talk is progressing, even when a harder new talk
      starts lower; an answer, a talk of one Take, adds nothing; with fewer
      than five Takes in talks of two or more there is no progress yet.
  O12 The one suggested's Not now, before or after Open Take, removes the
      asking chat and tells nobody: Send still reads "sent" to the speaker.
      Who declined whose Take and when stays, and the two are never matched
      again, whichever of them asks.
  O13 An answer waits five seconds for Undo and nobody sees it: no chat,
      nothing in the speaker's list. Undo leaves no trace. Once the time is
      up the chat is made exactly once, even if the timer was lost, and
      Undo is too late.
PROVES   O1 -> TakeMatchTest::test_with_no_ring_nobody_is_suggested
         O2 -> TakeMatchTest::test_one_new_person_who_fits_is_suggested_as_a_pseudonym
         O3 -> TakeMatchTest::test_nobody_in_a_chat_waiting_or_suggested_before
         O4 -> TakeMatchTest::test_send_knocks_as_a_new_chat_not_through_will
         O5 -> TakeMatchTest::test_not_now_tells_nobody
         O6 -> TakeMatchTest::test_open_take_then_the_answer_opens_the_chat_for_both
         O7 -> TakeMatchTest::test_only_the_one_suggested_answers_once_sent
         O8 -> TakeMatchTest::test_the_arm_picks_by_speaking_skills_and_progress
         O9 -> TakeMatchTest::test_words_that_say_nothing_make_no_match
         O10 -> TakeMatchTest::test_nobody_quiet_or_already_asked_enough
         O11 -> TakeMatchTest::test_progress_is_counted_within_each_talk
         O12 -> TakeMatchTest::test_not_now_removes_it_tells_nobody_and_never_again
         O13 -> TakeMatchTest::test_an_answer_waits_for_undo_and_counts_once
WHY      Matching people happens in one place only, after the Take (N477);
         a knock in the chats, opened or turned down, anonymous until the
         answer, which alone opens the chats (N478, N485, N493);
         every answer is a Take, and the matching weighs how people speak
         and progress (N481).
"""
from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from services.db import db
from services.processing_authorization import ProcessingAuthorizationService
from services.project_repository import ProjectRepository
from tests.test_chats import _Store

AMIRA = "11111111-1111-4111-8111-111111111111"
LEA = "22222222-2222-4222-8222-222222222222"
TOMEK = "33333333-3333-4333-8333-333333333333"
TAKE = "44444444-4444-4444-8444-444444444444"
ANSWER = "55555555-5555-4555-8555-555555555555"
TEAM = "66666666-6666-4666-8666-666666666666"
MAYA = "77777777-7777-4777-8777-777777777777"
OLDER = "88888888-8888-4888-8888-888888888888"
NAMES = {AMIRA: "Amira Haddad", LEA: "Lea Brandt", TOMEK: "Tomek Nowak", MAYA: "Maya Lind"}
SENT_AT = "2026-11-04T10:30:00+00:00"


class TakeMatchTest(unittest.TestCase):
    def setUp(self):
        from flask import Flask

        import auth
        from routes.v2 import register_domains
        from routes.v2.blueprint import v2_bp
        from services.rate_limits import limiter
        from services.canonical_product import OwnerPrincipal

        register_domains()
        if hasattr(limiter, "initialized"):
            self.addCleanup(setattr, limiter, "initialized", limiter.initialized)
            limiter.initialized = False
        app = Flask(__name__)
        app.register_blueprint(v2_bp, url_prefix="/v2")
        self.client = app.test_client()
        self.store = _Store()
        self.who = AMIRA
        self.ring = True
        self.sending = True
        self.cards: list = []

        def payload(_token):
            return {"sub": self.who, "user_metadata": {"full_name": NAMES[self.who]}}

        for p in (patch.object(auth, "verify_supabase_token", payload),
                  patch.object(db, "client", self.store),
                  patch.object(db, "insert_lounge_messages",
                               lambda user, rows: self.cards.extend((user, r) for r in rows)),
                  patch("services.rings.feature_is_on_for_user",
                        lambda feature, user, **_: self.ring and feature == "take_match"),
                  patch("services.take_sends.is_on", lambda: self.sending),
                  patch("services.take_match.EXPLORE", (1.0,)),
                  patch("services.take_match._now", lambda: SENT_AT),
                  patch.dict(os.environ, {"PLF1_PROCESSING_AUTHORIZATION_MODE": "off"}),
                  patch.object(ProjectRepository, "owner_for_user",
                               lambda _repo, user: OwnerPrincipal(f"owner-{user}", user, False)),
                  patch.object(ProcessingAuthorizationService, "resolve_acquisition_principal",
                               lambda _service, owner, **_: owner),
                  patch.object(ProcessingAuthorizationService, "consent_choices",
                               lambda _service, _principal: {
                                   "has_receipt": True, "personalised_practice": True,
                                   "sensitive_information": True}),
                  patch.object(ProcessingAuthorizationService, "status",
                               lambda _service, _principal: {
                                   "authorized": True, "pooled_learning_eligible": False})):
            p.start()
            self.addCleanup(p.stop)
        t = self.store.tables
        t["community_members"] = [{"community_id": TEAM, "user_id": u} for u in (AMIRA, LEA, TOMEK)]
        t["people_profiles"] = [
            {"user_id": AMIRA, "name": None, "role": "Account executive",
             "about": "I sell software to banks."},
            {"user_id": LEA, "name": None, "role": "Speaking coach",
             "about": "I help founders open an investor pitch with numbers that stick."},
            {"user_id": TOMEK, "name": None, "role": "Accountant", "about": "Tax returns."}]
        t["v2_sessions"] = [
            {"id": TAKE, "user_id": AMIRA, "created_at": "2026-11-04T10:00:00Z",
             "intake_context": {"topic": "investor pitch"},
             "slide_transcripts": [
                 {"index": 0, "transcript": "Our investor pitch opens with the numbers.",
                  "start_offset_ms": 0, "title": "Open with one number"},
                 {"index": 1, "transcript": "The numbers that stick are revenue and growth.",
                  "start_offset_ms": 41000}]},
            {"id": ANSWER, "user_id": LEA, "created_at": "2026-11-04T11:00:00Z",
             "intake_context": {}, "slide_transcripts": []},
            {"id": OLDER, "user_id": LEA, "created_at": "2026-11-03T09:00:00Z",
             "intake_context": {"topic": "my wedding toast"}, "slide_transcripts": []}]
        t["recordings"] = [
            {"session_v2_id": TAKE, "user_id": AMIRA, "storage_path": "a/take.webm", "duration": 130},
            {"session_v2_id": ANSWER, "user_id": LEA, "storage_path": "l/answer.webm", "duration": 40},
            {"session_v2_id": OLDER, "user_id": LEA, "storage_path": "l/older.webm", "duration": 60}]

    def _as(self, who):
        self.who = who

    def _get(self, path):
        return self.client.get(path, headers={"Authorization": "Bearer t"})

    def _post(self, path, body=None):
        return self.client.post(path, json=body or {}, headers={"Authorization": "Bearer t"})

    def _suggested(self):
        response = self._get(f"/v2/takes/{TAKE}/match")
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()["match"]

    def test_with_no_ring_nobody_is_suggested(self):
        self.ring = False
        self.assertEqual(self._get(f"/v2/takes/{TAKE}/match").status_code, 404)
        self.ring, self.sending = True, False
        self.assertEqual(self._get(f"/v2/takes/{TAKE}/match").status_code, 404)
        self.assertEqual(self.store.count("take_matches"), 0)

    def test_one_new_person_who_fits_is_suggested_as_a_pseudonym(self):
        from services.coach_pseudonym import coach_pseudonym
        match = self._suggested()
        self.assertEqual(set(match), {"id", "pseudonym", "role"})
        self.assertEqual(match["role"], "Speaking coach")
        self.assertNotIn("Lea", str(match))
        self.assertNotIn("wedding", str(match))
        self.assertTrue(match["pseudonym"])
        self.assertNotEqual(match["pseudonym"], coach_pseudonym(LEA))
        row = self.store.tables["take_matches"][0]
        self.assertEqual((row["candidate_id"], row["status"], row["arm"]),
                         (LEA, "offered", "topics"))
        self.assertEqual(self._suggested()["id"], match["id"])
        self.assertEqual(self.store.count("take_matches"), 1)

    def test_nobody_in_a_chat_waiting_or_suggested_before(self):
        self.store.tables["chat_members"] = [{"id": "m1", "thread_id": "t1", "user_id": AMIRA},
                                             {"id": "m2", "thread_id": "t1", "user_id": LEA}]
        self.assertIsNone(self._suggested())
        self.store.tables["chat_members"] = []
        with patch("services.membership.is_member", lambda _db, user, **_: user != LEA):
            self.assertIsNone(self._suggested())
        self.store.tables["take_matches"] = [{"id": "x", "session_id": "older", "speaker_id": AMIRA,
                                              "candidate_id": LEA, "status": "closed"}]
        self.assertIsNone(self._suggested())

    def _sent(self):
        match = self._suggested()
        self.assertEqual(self._post(f"/v2/take-matches/{match['id']}/send").get_json()["match"]["status"],
                         "sent")
        return match["id"]

    def _inquiries(self):
        return self._get("/v2/take-matches/inquiries").get_json()["inquiries"]

    def test_send_knocks_as_a_new_chat_not_through_will(self):
        match = self._sent()
        self.assertEqual(self.cards, [])
        self._as(LEA)
        [knock] = self._inquiries()
        self.assertEqual((knock["id"], knock["state"], knock["role"], knock["about"]),
                         (match, "new", "Account executive", "investor pitch"))
        self.assertTrue(knock["pseudonym"])
        self.assertNotIn("name", knock)
        self.assertNotIn("Amira", str(knock))
        self.assertEqual(self.store.count("chat_threads"), 0)
        self._as(AMIRA)
        self.assertIsNone(self._suggested())

    def test_not_now_tells_nobody(self):
        match = self._suggested()
        self.assertEqual(self._post(f"/v2/take-matches/{match['id']}/close").status_code, 200)
        self.assertEqual(self.cards, [])
        self.assertEqual(self.store.tables["take_matches"][0]["status"], "closed")
        self._as(LEA)
        self.assertEqual(self._inquiries(), [])
        self.assertEqual(self.store.count("chat_threads"), 0)

    def test_open_take_then_the_answer_opens_the_chat_for_both(self):
        match = self._sent()
        self._as(LEA)
        outside = self._get(f"/v2/take-matches/{match}").get_json()["match"]
        self.assertEqual(outside["about"], "investor pitch")
        self.assertFalse({"name", "words", "slides"} & set(outside))
        self.assertNotIn("Amira", str(outside))
        self.assertEqual(self._get(f"/v2/take-matches/{match}/recording").status_code, 404)
        self.assertEqual(self._post(f"/v2/take-matches/{match}/answer",
                                    {"take": ANSWER, "hold_ms": 0}).status_code, 409)
        opened = self._post(f"/v2/take-matches/{match}/accept").get_json()["match"]
        self.assertEqual((opened["state"], opened["name"]), ("opened", "Amira"))
        self.assertIn("revenue and growth", opened["words"])
        self.assertEqual(opened["slides"], [0, 41000])
        self.assertEqual(opened["slide_titles"], ["Open with one number", None])
        self.assertEqual(self.store.count("chat_threads"), 0)
        made = self._post(f"/v2/take-matches/{match}/answer", {"take": ANSWER, "hold_ms": 0})
        self.assertEqual(made.status_code, 200, made.get_json())
        thread = made.get_json()["chat"]["id"]
        members = {m["user_id"]: m["display_name"] for m in self.store.tables["chat_members"]}
        self.assertEqual(members, {AMIRA: "Amira", LEA: "Lea"})
        messages = self.store.tables["chat_messages"]
        authors = {m["id"]: m["user_id"] for m in self.store.tables["chat_members"]}
        self.assertEqual([(authors[m["author_member_id"]], m["kind"],
                           m["meta"].get("take_session_id") or m["meta"].get("take"))
                          for m in messages],
                         [(AMIRA, "take", TAKE), (LEA, "voice", ANSWER)])
        self.assertEqual(self._inquiries(), [])
        self._as(AMIRA)
        chats = self._get("/v2/chats").get_json()["chats"]
        self.assertEqual([c["id"] for c in chats], [thread])
        self.assertEqual(self.store.tables["take_matches"][0]["status"], "answered")

    def test_only_the_one_suggested_answers_once_sent(self):
        match = self._suggested()
        self._as(LEA)
        self.assertEqual(self._get(f"/v2/take-matches/{match['id']}").status_code, 404)
        self.assertEqual(self._inquiries(), [])
        self._as(AMIRA)
        self._post(f"/v2/take-matches/{match['id']}/send")
        self._as(TOMEK)
        self.assertEqual(self._get(f"/v2/take-matches/{match['id']}").status_code, 404)
        self.assertEqual(self._post(f"/v2/take-matches/{match['id']}/accept").status_code, 404)
        self.assertEqual(self._post(f"/v2/take-matches/{match['id']}/answer",
                                    {"take": ANSWER}).status_code, 404)
        self._as(LEA)
        self._post(f"/v2/take-matches/{match['id']}/accept")
        self.assertEqual(self._post(f"/v2/take-matches/{match['id']}/answer",
                                    {"take": OLDER, "hold_ms": 0}).status_code, 400)
        self.assertEqual(self.store.count("chat_threads"), 0)

    def test_not_now_removes_it_tells_nobody_and_never_again(self):
        match = self._sent()
        self._as(LEA)
        self._post(f"/v2/take-matches/{match}/accept")
        self.assertEqual(self._post(f"/v2/take-matches/{match}/decline").get_json()["match"]["status"],
                         "declined")
        self.assertEqual(self._inquiries(), [])
        row = self.store.tables["take_matches"][0]
        self.assertEqual((row["status"], row["candidate_id"], row["speaker_id"]),
                         ("declined", LEA, AMIRA))
        self.assertTrue(row["declined_at"])
        self.assertEqual(self.store.count("chat_threads"), 0)
        self._as(AMIRA)
        self.assertEqual(self._post(f"/v2/take-matches/{match}/send").get_json()["match"]["status"],
                         "sent")
        # Lea's own Take about what Amira knows: Amira would fit, but the two
        # are never matched again, whichever of them asks.
        self.store.tables["v2_sessions"].append(
            {"id": "99999999-9999-4999-8999-999999999999", "user_id": LEA,
             "created_at": "2026-11-04T10:10:00Z",
             "intake_context": {"topic": "selling software to banks"},
             "slide_transcripts": [{"index": 0, "transcript": "How do I sell software to banks?",
                                    "start_offset_ms": 0}]})
        self._as(LEA)
        again = self._get("/v2/takes/99999999-9999-4999-8999-999999999999/match")
        self.assertEqual(again.get_json()["match"], None)

    def test_an_answer_waits_for_undo_and_counts_once(self):
        later: list = []
        match = self._sent()
        self._as(LEA)
        self._post(f"/v2/take-matches/{match}/accept")
        with patch("services.chats._after", lambda _s, then: later.append(then)):
            waiting = self._post(f"/v2/take-matches/{match}/answer", {"take": ANSWER, "hold_ms": 5000})
        self.assertTrue(waiting.get_json()["sending"]["due_at"])
        self.assertEqual(self._inquiries()[0]["state"], "sending")
        self.assertEqual(self.store.count("chat_threads"), 0)
        self._as(AMIRA)
        self.assertEqual(self._get("/v2/chats").get_json()["chats"], [])
        self._as(LEA)
        self.assertEqual(self._post(f"/v2/take-matches/{match}/undo").get_json()["match"]["status"],
                         "accepted")
        self.assertEqual(self._inquiries()[0]["state"], "opened")
        self.assertEqual(self.store.count("chat_threads"), 0)
        with patch("services.chats._after", lambda _s, then: later.append(then)):
            self._post(f"/v2/take-matches/{match}/answer", {"take": ANSWER, "hold_ms": 5000})
        with patch("services.take_match._now", lambda: "2026-11-04T10:31:00+00:00"):
            self._as(AMIRA)
            self._get(f"/v2/takes/{TAKE}/match")
            for then in later:
                then()
            chats = self._get("/v2/chats").get_json()["chats"]
            self.assertEqual(len(chats), 1)
            self._as(LEA)
            self.assertEqual(self._post(f"/v2/take-matches/{match}/undo").status_code, 409)
        self.assertEqual(self.store.count("chat_threads"), 1)
        kinds = [m["kind"] for m in self.store.tables["chat_messages"]]
        self.assertEqual(kinds, ["take", "voice"])

    def test_the_arm_picks_by_speaking_skills_and_progress(self):
        t = self.store.tables
        t["community_members"].append({"community_id": TEAM, "user_id": MAYA})
        t["people_profiles"].append(
            {"user_id": MAYA, "name": None, "role": "Pitch trainer",
             "about": "I help founders open an investor pitch with numbers that stick."})
        t["v4_willfidence_takes"] = []
        # Amira 0.40 -> 0.44; Lea at her level, alike; Maya further along, alike.
        for who, start in ((AMIRA, 0.40), (LEA, 0.43), (MAYA, 0.56)):
            for i in range(3):
                take = f"{who[:8]}-0000-4000-8000-00000000000{i}"
                t["v2_sessions"].append({"id": take, "user_id": who,
                                         "created_at": f"2026-10-2{i + 5}T09:00:00Z",
                                         "intake_context": {}, "slide_transcripts": []})
                t["v4_willfidence_takes"].append({
                    "take_session_id": take, "read_version": "willfidence-v1-machine",
                    "status": "measured", "willfidence": round(start + 0.02 * i, 2)})
        with patch.dict(os.environ, {"TAKE_MATCH_SKILLS": "1"}):
            for arm, chosen in (("similar_level", LEA), ("further_along", MAYA)):
                t["take_matches"] = []
                with patch("services.take_match.draw_arm", lambda arm=arm: arm):
                    match = self._suggested()
                self.assertEqual(set(match), {"id", "pseudonym", "role"})
                row = t["take_matches"][0]
                self.assertEqual((row["candidate_id"], row["arm"]), (chosen, arm))
                kept = row["signals"]
                self.assertTrue({"knowledge", "skill", "pace", "rank", "propensity"} <= set(kept))
                self.assertTrue(kept["other_arm_differs"])
                self.assertEqual((kept["rank"], kept["propensity"]), (1, 1.0))
                self.assertNotIn(LEA, json.dumps(kept))
                self.assertNotIn(MAYA, json.dumps(kept))

    def _only_take(self, topic, words):
        self.store.tables["v2_sessions"][0].update(
            {"intake_context": {"topic": topic},
             "slide_transcripts": [{"index": 0, "transcript": words, "start_offset_ms": 0}]})

    def _person(self, who, role, about, active=True):
        t = self.store.tables
        t["community_members"].append({"community_id": TEAM, "user_id": who})
        t["people_profiles"].append({"user_id": who, "name": None, "role": role, "about": about})
        t["v2_sessions"].append({"id": f"{who[:8]}-1111-4111-8111-{who[-12:]}", "user_id": who,
                                 "created_at": "2026-11-03T08:00:00Z" if active else
                                 "2026-09-01T08:00:00Z", "intake_context": {},
                                 "slide_transcripts": []})

    def test_words_that_say_nothing_make_no_match(self):
        t = self.store.tables
        t["community_members"] = [{"community_id": TEAM, "user_id": AMIRA}]
        self._only_take("prezentacja dla inwestorów",
                        "Nasza prezentacja zaczyna się od liczb, które zapadają w pamięć.")
        self._person(TOMEK, "Księgowa", "Zajmuję się podatkami dla firm i jest to dla mnie ważne.")
        self.assertIsNone(self._suggested())

        t["community_members"] = [{"community_id": TEAM, "user_id": AMIRA}]
        t["take_matches"] = []
        self._only_take("presentation", "I want to speak about my presentation with confidence.")
        for i in range(24):
            self._person(f"{i:08d}-2222-4222-8222-222222222222", "Speaker",
                         "I speak at events and give a presentation with confidence.")
        self.assertIsNone(self._suggested())

    def test_nobody_quiet_or_already_asked_enough(self):
        t = self.store.tables
        for row in t["v2_sessions"]:
            if row["user_id"] == LEA:
                row["created_at"] = "2026-09-01T08:00:00Z"
        self.assertIsNone(self._suggested())
        t["v2_sessions"][1]["created_at"] = "2026-11-04T11:00:00Z"
        others = [f"{i:08d}-3333-4333-8333-333333333333" for i in range(5)]
        t["take_matches"] = [{"id": f"m{i}", "session_id": f"s{i}", "speaker_id": who,
                              "candidate_id": LEA, "status": "sent",
                              "offered_at": "2026-11-03T08:00:00+00:00"}
                             for i, who in enumerate(others[:3])]
        self.assertIsNone(self._suggested())
        for row in t["take_matches"]:
            row["status"] = "offered"
        t["take_matches"] += [{"id": f"n{i}", "session_id": f"q{i}", "speaker_id": who,
                               "candidate_id": LEA, "status": "offered",
                               "offered_at": "2026-11-02T08:00:00+00:00"}
                              for i, who in enumerate(others[3:])]
        self.assertIsNone(self._suggested())
        t["take_matches"] = []
        self.assertEqual(self._suggested()["role"], "Speaking coach")


    def test_progress_is_counted_within_each_talk(self):
        from services import take_match_signals
        t = self.store.tables
        t["v4_willfidence_takes"] = []
        talks = (("pitch", (0.40, 0.45, 0.50)), ("keynote", (0.30, 0.35, 0.40)), ("answer", (0.20,)))
        n = 0
        for talk, values in talks:
            for i, value in enumerate(values):
                n += 1
                take = f"77777777-0000-4000-8000-{n:012d}"
                t["v2_sessions"].append({"id": take, "user_id": TOMEK, "project_id": talk,
                                         "take_index": i + 1, "intake_context": {},
                                         "created_at": f"2026-10-{10 + n:02d}T09:00:00Z"})
                t["v4_willfidence_takes"].append({
                    "take_session_id": take, "read_version": "willfidence-v1-machine",
                    "status": "measured", "willfidence": value})
        pace = take_match_signals.of(db, [TOMEK])[TOMEK]["pace"]
        self.assertGreater(pace, 0)
        t["v2_sessions"] = [r for r in t["v2_sessions"] if r.get("project_id") != "keynote"]
        self.assertIsNone(take_match_signals.of(db, [TOMEK])[TOMEK]["pace"])


if __name__ == "__main__":
    unittest.main()
