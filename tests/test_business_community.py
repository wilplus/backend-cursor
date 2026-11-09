"""
STORY    As a newcomer who came by the link of someone at a business, I want
         to be offered that business's community once, while my first Take
         is processed, so that people there can be suggested to me and I to
         them; and as a speaker, I want someone new after a Take to come only
         from my business (founder, 9 November 2026, N559 item 1, N572).
OUTCOME
  O1  A newcomer whose inviter is in a business's community is offered it
      once, with the inviter's first name; asked again it is the same offer
      until answered, and never after. Join makes them a member.
  O2  Not now is kept and the offer never comes back on its own; the
      newcomer is not in the community. An offer never made cannot be
      answered.
  O3  Someone who came by no member's link, or by a link whose owner is in
      no community, is offered nothing; a failure is no offer, never an
      error, so the wait for Take 1 goes on.
  O4  Only people in the speaker's business community are suggested as
      someone new, never someone outside it, and never from the retired
      passcode communities.
  O5  Only the founder makes a business's community; its owner is its
      first member.
  O6  When the inviter's account is erased, their id goes from the
      newcomer's offer; the newcomer's offer and answer stay theirs.
PROVES   O1 -> BusinessCommunityTest::test_a_newcomer_is_offered_once_and_join_makes_them_a_member
         O2 -> BusinessCommunityTest::test_not_now_is_never_asked_again
         O3 -> BusinessCommunityTest::test_no_member_link_no_offer
         O4 -> BusinessCommunityTest::test_someone_new_comes_from_the_speakers_business
         O5 -> BusinessCommunityTest::test_only_the_founder_makes_a_community
         O6 -> test_erasing_the_inviter_clears_them_from_the_offer
WHY      N559 item 1: the business is the pool; joining is how a person
         belongs to it.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from tests import test_take_match as matching
from tests.test_take_match import AMIRA, LEA, TEAM, TOMEK

NEW = "99999999-1111-4111-8111-999999999999"
BIZ = "abababab-abab-4bab-8bab-abababababab"


class BusinessCommunityTest(unittest.TestCase):
    setUp = matching.TakeMatchTest.setUp
    _as = matching.TakeMatchTest._as
    _get = matching.TakeMatchTest._get
    _post = matching.TakeMatchTest._post
    _suggested = matching.TakeMatchTest._suggested

    def _came_by(self, inviter, newcomer=NEW):
        t = self.store.tables
        t.setdefault("chat_links", []).append(
            {"id": "link-" + inviter[:4], "user_id": inviter, "display_name": "Amira"})
        t.setdefault("chat_threads", []).append(
            {"id": "thread-" + newcomer[:4], "link_id": "link-" + inviter[:4],
             "created_at": "2026-11-09T10:00:00Z"})
        t.setdefault("chat_members", []).extend([
            {"id": "m-a", "thread_id": "thread-" + newcomer[:4], "user_id": inviter,
             "display_name": "Amira Haddad"},
            {"id": "m-n", "thread_id": "thread-" + newcomer[:4], "user_id": newcomer,
             "display_name": "Nina"}])

    def _offer(self):
        response = self._get("/v2/me/community-offer")
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()["offer"]

    def test_a_newcomer_is_offered_once_and_join_makes_them_a_member(self):
        self._came_by(AMIRA)
        self._as(NEW)
        with patch.dict("tests.test_take_match.NAMES", {NEW: "Nina Ross"}):
            offer = self._offer()
            self.assertEqual(offer, {"id": TEAM, "name": "Ember Air", "inviter": "Amira"})
            self.assertEqual(self._offer(), offer)
            joined = self._post("/v2/me/community-offer", {"id": TEAM, "answer": "join"})
            self.assertEqual(joined.get_json(), {"offer": None, "joined": True})
            self.assertIsNone(self._offer())
        members = {m["user_id"] for m in self.store.tables["business_community_members"]}
        self.assertIn(NEW, members)

    def test_not_now_is_never_asked_again(self):
        self._came_by(AMIRA)
        self._as(NEW)
        with patch.dict("tests.test_take_match.NAMES", {NEW: "Nina Ross"}):
            self.assertEqual(self._post("/v2/me/community-offer",
                                        {"id": TEAM, "answer": "not_now"}).status_code, 404)
            self.assertEqual(self._offer()["id"], TEAM)
            said = self._post("/v2/me/community-offer", {"id": TEAM, "answer": "not_now"})
            self.assertEqual(said.get_json(), {"offer": None, "joined": False})
            self.assertIsNone(self._offer())
        members = {m["user_id"] for m in self.store.tables["business_community_members"]}
        self.assertNotIn(NEW, members)

    def test_no_member_link_no_offer(self):
        self._as(NEW)
        with patch.dict("tests.test_take_match.NAMES", {NEW: "Nina Ross"}):
            self.assertIsNone(self._offer())
            self.store.tables["business_community_members"] = []
            self._came_by(AMIRA)
            self.assertIsNone(self._offer())
            with patch("services.business_community._inviters", side_effect=RuntimeError("down")):
                self.store.tables["business_community_members"] = [
                    {"community_id": TEAM, "user_id": AMIRA, "joined_at": "2026-11-01T00:00:00Z"}]
                self.assertIsNone(self._offer())

    def test_someone_new_comes_from_the_speakers_business(self):
        t = self.store.tables
        # Lea fits, but is in another business; the retired passcode
        # community the two share counts for nothing.
        t["business_communities"].append({"id": BIZ, "owner_id": LEA, "name": "Other"})
        t["business_community_members"] = [
            m for m in t["business_community_members"] if m["user_id"] != LEA] + [
            {"community_id": BIZ, "user_id": LEA, "joined_at": "2026-11-01T00:00:00Z"}]
        t["community_members"] = [{"community_id": "old", "user_id": u} for u in (AMIRA, LEA)]
        self.assertIsNone(self._suggested())
        t["business_community_members"].append(
            {"community_id": TEAM, "user_id": LEA, "joined_at": "2026-11-02T00:00:00Z"})
        self.assertEqual(t["take_matches"], [])
        self.assertEqual(self._suggested()["role"], "Speaking coach")
        self.assertEqual(t["take_matches"][0]["candidate_id"], LEA)

    def test_only_the_founder_makes_a_community(self):
        body = {"owner_id": TOMEK, "name": "Tomek & Co"}
        with patch("routes.admin.is_admin", lambda _user: False):
            self.assertEqual(self._post("/v2/admin/business-communities", body).status_code, 404)
        with patch("routes.admin.is_admin", lambda _user: True):
            made = self._post("/v2/admin/business-communities", body).get_json()["community"]
        self.assertEqual(made["name"], "Tomek & Co")
        self.assertIn({"community_id": made["id"], "user_id": TOMEK},
                      [{k: m[k] for k in ("community_id", "user_id")}
                       for m in self.store.tables["business_community_members"]])


def test_erasing_the_inviter_clears_them_from_the_offer():
    from tests.test_purge_user_locators import PurgeDb, erase
    database = PurgeDb({"business_community_offers": [
        {"id": "o1", "user_id": "newcomer", "community_id": TEAM, "inviter_id": "user-1",
         "answer": "joined"},
        {"id": "o2", "user_id": "other", "community_id": TEAM, "inviter_id": "user-2",
         "answer": None}]})
    erase(database)
    rows = {r["id"]: r for r in database.tables["business_community_offers"]}
    assert (rows["o1"]["user_id"], rows["o1"]["inviter_id"], rows["o1"]["answer"]) == (
        "newcomer", None, "joined")
    assert rows["o2"]["inviter_id"] == "user-2"
    assert database.target("business_community_offers_inviter")["state"] == "deleted"


if __name__ == "__main__":
    unittest.main()
