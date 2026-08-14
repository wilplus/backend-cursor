"""Engine 5 — the key-moments game. Pure service tests + Flask-skip routes.

Run: python3 -m unittest test_game_engine
"""
from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock, patch

_ORIG_SERVICES_DB = None


def setUpModule():
    global _ORIG_SERVICES_DB
    _ORIG_SERVICES_DB = sys.modules.get("services.db")
    stub = types.ModuleType("services.db")
    stub.db = MagicMock()
    sys.modules["services.db"] = stub


def tearDownModule():
    if _ORIG_SERVICES_DB is not None:
        sys.modules["services.db"] = _ORIG_SERVICES_DB
    else:
        sys.modules.pop("services.db", None)


def _snip(sid, transcript="a strong line", offset=0, session_id="s1", **over):
    base = {"id": sid, "session_id": session_id, "transcript": transcript,
            "audio_segment_path": "https://x/parent.webm",
            "start_offset_ms": offset, "duration_ms": 1500,
            "metrics": {"wpm": 140, "pause_ratio": 0.2}}
    base.update(over)
    return base


def _two_labels():
    """The founder's admission ticket (2026-08-10): two distinct raters
    with committed answers — coach + owner, the current n=2."""
    return [
        {"rater_id": "coach1", "lane": "coach", "value": "yes"},
        {"rater_id": "u1", "lane": "game_owner", "value": "no"},
    ]


class _FakeDB:
    def __init__(self, sessions, snips, labels, drafts=None,
                 conf_labels=None):
        self._sessions = sessions
        self._snips = snips
        self._labels = labels
        self._drafts = drafts or {}
        # Default: every snippet is twice-labelled (eligible). Tests for
        # the gate pass their own map.
        self._conf_labels = conf_labels
        self.peer_labels: list = []
        self.state_ratings: list = []

    def get_arc_sessions(self, arc_id):
        return list(self._sessions)

    def get_snippets_by_session(self, sid):
        return list(self._snips.get(sid, []))

    def get_training_labels(self, sid):
        return list(self._labels.get(sid, []))

    def get_confidence_labels_by_snippet_ids(self, ids):
        if self._conf_labels is not None:
            return {i: self._conf_labels.get(i, []) for i in ids}
        return {i: _two_labels() for i in ids}

    def get_coach_snippet_drafts(self, sid):
        return list(self._drafts.get(sid, []))

    def insert_snippet_peer_label(self, **kw):
        self.peer_labels.append(kw)
        return True

    def upsert_state_rating(self, **kw):
        self.state_ratings.append(kw)
        return True

    # user_patterns wrapper reads
    def v2_list_user_lab_sessions(self, uid, limit=30):
        return list(self._sessions)


def _db(drafts=None, conf_labels=None):
    sessions = [{"id": "s1", "user_id": "u1"}]
    snips = {"s1": [
        _snip("k1", "The strongest close.", 8000),
        _snip("k2", "Another key line.", 2000),
        _snip("d1", "A neutral aside.", 4000),
        _snip("d2", "Some filler talk.", 6000),
        _snip("t1", "A shaky nervous open.", 0),
    ]}
    labels = {"s1": [
        {"snippet_id": "k1", "value": "challenge"},
        {"snippet_id": "k2", "value": "challenge"},
        {"snippet_id": "t1", "value": "threat"},
    ]}
    return _FakeDB(sessions, snips, labels, drafts=drafts,
                   conf_labels=conf_labels)


class BuildRoundsTests(unittest.TestCase):

    def _rounds(self, db=None, first=None):
        from services.game_engine import build_game_rounds
        return build_game_rounds(db or _db(), "arc1", "u1",
                                 first_snippet=first)

    def test_mixes_keys_and_decoys_without_truth(self):
        rounds = self._rounds()
        ids = {r["snippet_id"] for r in rounds}
        self.assertIn("k1", ids)
        self.assertIn("k2", ids)
        # equal decoy count (2 keys → 2 decoys from {d1, d2, t1})
        self.assertEqual(len(rounds), 4)
        for r in rounds:
            self.assertNotIn("truth", str(sorted(r.keys())))
            self.assertNotIn("is_key", str(sorted(r.keys())))
            self.assertTrue(r["transcript"])
            self.assertEqual(r["audio_ref"], "https://x/parent.webm")

    def test_deterministic_order(self):
        a = [r["snippet_id"] for r in self._rounds()]
        b = [r["snippet_id"] for r in self._rounds()]
        self.assertEqual(a, b)

    def test_audio_falls_back_to_storage_path(self):
        """Ear-first rounds (FE close-out 2026-07-28): audio_ref is
        load-bearing — a snippet carrying only storage_path (the
        pieces-canonical shape) must still yield a playable round, same
        fallback chain as the breakthroughs list."""
        from services.game_engine import build_game_rounds
        db = _FakeDB(
            [{"id": "s1"}],
            {"s1": [_snip("k1", audio_segment_path=None, audio_ref=None,
                          storage_path="https://x/take-1.webm")]},
            {"s1": [{"snippet_id": "k1", "value": "challenge"}]},
        )
        rounds = build_game_rounds(db, "arc1", "u1")
        self.assertEqual(rounds[0]["audio_ref"], "https://x/take-1.webm")

    def test_round_id_is_the_snippet_id(self):
        # The FE reads round_id and echoes it back on answer — it MUST be the
        # snippet id the answer route resolves against (else every answer 404s).
        for r in self._rounds():
            self.assertEqual(r["round_id"], r["snippet_id"])

    def test_deep_link_pins_first(self):
        rounds = self._rounds(first="k1")
        self.assertEqual(rounds[0]["snippet_id"], "k1")

    def test_unknown_deep_link_ignored(self):
        rounds = self._rounds(first="nope")
        self.assertEqual(len(rounds), 4)

    def test_no_key_moments_no_game(self):
        db = _db()
        db._labels = {"s1": []}
        self.assertEqual(self._rounds(db=db), [])

    def test_threat_moment_is_a_decoy_not_a_key(self):
        self._rounds()
        # t1 (threat) may appear — but only as a decoy; answering it "key"
        # must be wrong (covered in AnswerTests).
        from services.game_engine import _arc_moments
        keys, decoys, _, _sess = _arc_moments(_db(), "arc1")
        self.assertNotIn("t1", keys)
        self.assertIn("t1", decoys)


class QueueSourceOrderTests(unittest.TestCase):
    """Founder queue order (2026-08-14, unparked): the player's OWN voice
    → consented app users → the coach-labelled YouTube corpus
    (source='training_import'). Class ranks the order only — selection
    stays sha1-deterministic, and the deep-link pin beats everything."""

    def _db(self):
        sessions = [
            {"id": "yt", "user_id": "corpus-import",
             "source": "training_import"},
            {"id": "peer", "user_id": "u2"},
            {"id": "own", "user_id": "u1"},
        ]
        snips = {
            "yt": [_snip("y1", "a corpus key line", 0, session_id="yt"),
                   _snip("y2", "a corpus aside", 1000, session_id="yt")],
            "peer": [_snip("p1", "a peer key line", 0, session_id="peer"),
                     _snip("p2", "a peer aside", 1000, session_id="peer")],
            "own": [_snip("o1", "my key line", 0, session_id="own"),
                    _snip("o2", "my aside", 1000, session_id="own")],
        }
        labels = {
            "yt": [{"snippet_id": "y1", "value": "challenge"}],
            "peer": [{"snippet_id": "p1", "value": "challenge"}],
            "own": [{"snippet_id": "o1", "value": "challenge"}],
        }
        return _FakeDB(sessions, snips, labels)

    def _rounds(self, uid="u1", first=None):
        from services.game_engine import build_game_rounds
        return build_game_rounds(self._db(), "arc1", uid,
                                 first_snippet=first)

    def test_own_then_app_users_then_youtube(self):
        rounds = self._rounds()
        self.assertEqual(len(rounds), 6)   # 3 keys + 3 decoys, all classes
        rank = {"o": 0, "p": 1, "y": 2}
        ranks = [rank[r["snippet_id"][0]] for r in rounds]
        self.assertEqual(ranks, sorted(ranks))
        self.assertEqual({r["snippet_id"] for r in rounds[:2]},
                         {"o1", "o2"})
        self.assertEqual({r["snippet_id"] for r in rounds[-2:]},
                         {"y1", "y2"})

    def test_own_means_the_player_not_the_arc_owner(self):
        # A peer playing this arc hears THEIR voice first; the corpus
        # stays last for everyone.
        rounds = self._rounds(uid="u2")
        self.assertEqual({r["snippet_id"] for r in rounds[:2]},
                         {"p1", "p2"})
        self.assertEqual({r["snippet_id"] for r in rounds[-2:]},
                         {"y1", "y2"})

    def test_class_order_is_deterministic(self):
        a = [r["snippet_id"] for r in self._rounds()]
        b = [r["snippet_id"] for r in self._rounds()]
        self.assertEqual(a, b)

    def test_deep_link_pin_beats_class_order(self):
        rounds = self._rounds(first="y1")
        self.assertEqual(rounds[0]["snippet_id"], "y1")


class TwiceLabelledGateTests(unittest.TestCase):
    """Founder 2026-08-10: "min twice labelled voice snippet goes to the
    game." The gate lives in _arc_moments, so serving and answering close
    together."""

    def _conf(self, **per_snip):
        base = {s: _two_labels()
                for s in ("k1", "k2", "d1", "d2", "t1")}
        base.update(per_snip)
        return base

    def test_an_under_labelled_snippet_never_enters_rounds(self):
        from services.game_engine import build_game_rounds
        db = _db(conf_labels=self._conf(
            k1=[{"rater_id": "coach1", "lane": "coach", "value": "yes"}]))
        ids = {r["snippet_id"] for r in build_game_rounds(db, "arc1", "u1")}
        self.assertNotIn("k1", ids)
        self.assertIn("k2", ids)

    def test_an_under_labelled_snippet_is_not_answerable_either(self):
        """A stale open tab must not post a junk label — the same edit
        gates serving AND answer validation."""
        from services.game_engine import answer_round
        db = _db(conf_labels=self._conf(k1=[]))
        self.assertIsNone(answer_round(db, "arc1", "u1", "k1", True))

    def test_two_abstentions_are_not_two_labels(self):
        from services.game_engine import _twice_labelled
        db = _db(conf_labels={"k1": [
            {"rater_id": "a", "lane": "coach", "unrateable": True},
            {"rater_id": "b", "lane": "game_owner", "unrateable": True},
        ]})
        self.assertEqual(_twice_labelled(db, ["k1"]), set())

    def test_bootstrap_rows_do_not_count(self):
        from services.game_engine import _twice_labelled
        db = _db(conf_labels={"k1": [
            {"rater_id": "a", "lane": "bootstrap", "value": "yes"},
            {"rater_id": "b", "lane": "coach", "value": "no"},
        ]})
        self.assertEqual(_twice_labelled(db, ["k1"]), set())

    def test_one_rater_twice_is_one_label(self):
        from services.game_engine import _twice_labelled
        db = _db(conf_labels={"k1": [
            {"rater_id": "a", "lane": "coach", "value": "yes"},
            {"rater_id": "a", "lane": "game_owner", "value": "no"},
        ]})
        self.assertEqual(_twice_labelled(db, ["k1"]), set())

    def test_a_read_miss_admits_nothing(self):
        from services.game_engine import _twice_labelled

        class _Broken:
            def get_confidence_labels_by_snippet_ids(self, ids):
                raise RuntimeError("boom")
        self.assertEqual(_twice_labelled(_Broken(), ["k1"]), set())

    def test_legacy_boolean_rows_still_count(self):
        from services.game_engine import _twice_labelled
        db = _db(conf_labels={"k1": [
            {"rater_id": "a", "lane": "coach", "confident": True},
            {"rater_id": "b", "lane": "game_owner", "confident": False},
        ]})
        self.assertEqual(_twice_labelled(db, ["k1"]), {"k1"})


class AnswerTests(unittest.TestCase):

    def _answer(self, snippet_id, answer, db=None):
        from services.game_engine import answer_round
        d = db or _db()
        return d, answer_round(d, "arc1", "u1", snippet_id, answer)

    def test_correct_key_answer(self):
        db, out = self._answer("k1", True)
        self.assertTrue(out["correct"])
        self.assertTrue(out["truth_is_key"])

    def test_wrong_on_neutral(self):
        db, out = self._answer("d1", True)
        self.assertFalse(out["correct"])
        self.assertFalse(out["truth_is_key"])

    def test_threat_is_not_a_key_moment(self):
        db, out = self._answer("t1", True)
        self.assertFalse(out["correct"])

    def test_answer_persists_second_order_label(self):
        db, out = self._answer("k1", True)
        self.assertEqual(len(db.peer_labels), 1)
        row = db.peer_labels[0]
        self.assertEqual(row["snippet_id"], "k1")
        self.assertEqual(row["label"], "key_moment")
        self.assertEqual(row["source"], "game")
        self.assertEqual(row["rater_id"], "u1")

    def test_unknown_snippet_returns_none(self):
        db, out = self._answer("ghost", True)
        self.assertIsNone(out)
        self.assertEqual(db.peer_labels, [])

    def test_verdict_shape_is_fe_aligned(self):
        # FE (services/api/arcGame.ts): why = FLAT string array, video_ref
        # TOP-LEVEL, correct boolean.
        db, out = self._answer("k1", True)
        self.assertIsInstance(out["why"], list)
        self.assertIn("video_ref", out)
        self.assertIsInstance(out["correct"], bool)

    def test_why_carries_coach_video_top_level(self):
        drafts = {"s1": [{"snippet_id": "k1",
                          "breakthrough_video_ref": "https://v/clip.mp4"}]}
        db, out = self._answer("k1", True, db=_db(drafts=drafts))
        self.assertEqual(out["video_ref"], "https://v/clip.mp4")

    def test_why_paragraphs_qualitative_and_capped(self):
        db, out = self._answer("k1", False)
        self.assertLessEqual(len(out["why"]), 3)
        for p in out["why"]:
            self.assertNotRegex(p, r"\d")  # AC-9 — no numbers reach the user

    def test_every_answer_writes_the_confidence_corpus(self):
        """The game IS a labelling lane (founder 2026-08-10): same ternary
        instrument as the coach lanes, in the game's own lane — the owner
        answering their own take lands game_owner."""
        db, out = self._answer("k1", True)
        self.assertEqual(len(db.state_ratings), 1)
        row = db.state_ratings[0]
        self.assertEqual(row["snippet_id"], "k1")
        self.assertEqual(row["row"]["value"], "yes")
        self.assertEqual(row["lane"], "game_owner")
        self.assertEqual(row["rater_id"], "u1")

    def test_a_peer_answer_lands_the_peer_lane(self):
        from services.game_engine import answer_round
        db = _db()
        answer_round(db, "arc1", "u2", "k1", False)
        self.assertEqual(db.state_ratings[0]["lane"], "game_peer")
        self.assertEqual(db.state_ratings[0]["row"]["value"], "no")

    def test_idk_is_a_label_but_not_a_guess(self):
        """'neutral' (the founder's missing idk): the confidence corpus
        gets the row; the key-moment peer table gets NOTHING — an idk is
        not a guess, and a fabricated neutral would be indistinguishable
        from a real one. No win/lose verdict either."""
        db, out = self._answer("k1", "neutral")
        self.assertIsNone(out["correct"])
        self.assertTrue(out["truth_is_key"])
        self.assertEqual(db.peer_labels, [])
        self.assertEqual(db.state_ratings[0]["row"]["value"], "neutral")

    def test_ternary_strings_work_as_answers(self):
        db, out = self._answer("k1", "yes")
        self.assertTrue(out["correct"])
        db2, out2 = self._answer("k1", "no")
        self.assertFalse(out2["correct"])

    def test_a_malformed_answer_returns_none(self):
        db, out = self._answer("k1", "maybe")
        self.assertIsNone(out)
        self.assertEqual(db.peer_labels, [])
        self.assertEqual(db.state_ratings, [])


class BuildWhyTests(unittest.TestCase):

    def test_keywords_prefer_say_it_stronger_originals(self):
        from services.game_engine import build_why
        snip = _snip("k1", say_it_stronger={
            "upgrades": [{"original": "holds it tightly", "upgrade": "x",
                          "kind": "upgrade", "reason": None}]})
        why = build_why(snip, [], True)
        self.assertEqual(why["keywords"], ["holds it tightly"])
        # keyword is **-wrapped INLINE so the FE tints it (arcGame.ts).
        self.assertIn("**holds it tightly**", why["paragraphs"][0])

    def test_pattern_statement_matches_verdict_kind(self):
        from services.game_engine import build_why
        patterns = [
            {"kind": "negative", "statement": "neg pattern", "feature": "pace"},
            {"kind": "positive", "statement": "pos pattern", "feature": "pace"},
        ]
        why_key = build_why(_snip("k1"), patterns, True)
        self.assertIn("pos pattern", why_key["paragraphs"])
        self.assertNotIn("neg pattern", why_key["paragraphs"])
        why_neutral = build_why(_snip("d1"), patterns, False)
        self.assertIn("neg pattern", why_neutral["paragraphs"])

    def test_empty_inputs_safe(self):
        from services.game_engine import build_why
        why = build_why({"id": "x", "transcript": ""}, [], False)
        self.assertIsInstance(why["paragraphs"], list)


# ── Routes (Flask-skip locally, run in CI) ─────────────────────────────────

try:
    from flask import Flask, request as _rq
    from routes import v2_routes as _v2
    _ROUTE_ERR = None
except Exception as _e:  # pragma: no cover
    Flask = None
    _rq = None
    _v2 = None
    _ROUTE_ERR = _e


@unittest.skipIf(_ROUTE_ERR is not None, f"needs app deps: {_ROUTE_ERR}")
class GameRouteTests(unittest.TestCase):

    _SNIP = "22222222-2222-4222-8222-222222222222"

    def setUp(self):
        self.app = Flask(__name__)
        self._p = [
            patch("routes.v2.arcs._arc_owned_by_caller", lambda a: (True, [])),
        ]
        for p_ in self._p:
            p_.start()

    def tearDown(self):
        for p_ in self._p:
            p_.stop()

    def test_game_get_serves_rounds(self):
        rounds = [{"round": 0, "snippet_id": "x", "transcript": "t",
                   "audio_ref": "a", "start_offset_ms": 0, "duration_ms": 1}]
        with patch("services.game_engine.build_game_rounds",
                   return_value=rounds):
            with self.app.test_request_context():
                _rq.user_id = "u1"
                resp, status = _v2.v2_arc_game.__wrapped__("a1")
        self.assertEqual(status, 200)
        self.assertEqual(resp.get_json()["rounds"], rounds)

    def test_game_get_empty_state_reason(self):
        with patch("services.game_engine.build_game_rounds", return_value=[]):
            with self.app.test_request_context():
                _rq.user_id = "u1"
                resp, status = _v2.v2_arc_game.__wrapped__("a1")
        self.assertEqual(status, 200)
        self.assertEqual(resp.get_json()["reason"], "NO_KEY_MOMENTS_YET")

    def test_answer_validates_body(self):
        # FE field names: round_id + answer. Ternary strings are VALID now
        # (founder 2026-08-10: yes / no / idk) — only garbage 400s.
        with self.app.test_request_context(json={"round_id": "nope",
                                                 "answer": True}):
            _rq.user_id = "u1"
            _, status = _v2.v2_arc_game_answer.__wrapped__("a1")
        self.assertEqual(status, 400)
        with self.app.test_request_context(json={"round_id": self._SNIP,
                                                 "answer": "maybe"}):
            _rq.user_id = "u1"
            _, status = _v2.v2_arc_game_answer.__wrapped__("a1")
        self.assertEqual(status, 400)

    def test_answer_accepts_the_ternary_instrument(self):
        with patch("services.game_engine.answer_round",
                   return_value={"correct": None, "truth_is_key": True,
                                 "why": [], "keywords": [],
                                 "video_ref": None}):
            with self.app.test_request_context(json={
                    "round_id": self._SNIP, "answer": "neutral"}):
                _rq.user_id = "u1"
                resp, status = _v2.v2_arc_game_answer.__wrapped__("a1")
        self.assertEqual(status, 200)
        self.assertIsNone(resp.get_json()["correct"])

    def test_answer_round_trip_fe_shape(self):
        # The FE sends { round_id, answer } and reads { correct, why[],
        # video_ref } — assert the whole verdict passes through.
        result = {"correct": True, "truth_is_key": True,
                  "why": ["**word** matters."], "keywords": ["word"],
                  "video_ref": "https://v/clip.mp4"}
        captured = {}

        def _capture(db, arc, uid, snip, ans):
            captured["snip"] = snip
            captured["ans"] = ans
            return result

        with patch("services.game_engine.answer_round", side_effect=_capture):
            with self.app.test_request_context(json={
                    "round_id": self._SNIP, "answer": True}):
                _rq.user_id = "u1"
                resp, status = _v2.v2_arc_game_answer.__wrapped__("a1")
        self.assertEqual(status, 200)
        body = resp.get_json()
        self.assertTrue(body["correct"])
        self.assertEqual(body["why"], ["**word** matters."])
        self.assertEqual(body["video_ref"], "https://v/clip.mp4")
        self.assertEqual(captured["snip"], self._SNIP)  # round_id → snippet id
        self.assertIs(captured["ans"], True)

    def test_answer_accepts_legacy_aliases(self):
        # snippet_id / answer_is_key still work (belt-and-braces).
        with patch("services.game_engine.answer_round",
                   return_value={"correct": False, "truth_is_key": False,
                                 "why": [], "keywords": [], "video_ref": None}):
            with self.app.test_request_context(json={
                    "snippet_id": self._SNIP, "answer_is_key": False}):
                _rq.user_id = "u1"
                _, status = _v2.v2_arc_game_answer.__wrapped__("a1")
        self.assertEqual(status, 200)

    def test_answer_unknown_snippet_404s(self):
        with patch("services.game_engine.answer_round", return_value=None):
            with self.app.test_request_context(json={
                    "round_id": self._SNIP, "answer": True}):
                _rq.user_id = "u1"
                _, status = _v2.v2_arc_game_answer.__wrapped__("a1")
        self.assertEqual(status, 404)

    def test_save_and_list(self):
        saves = []
        with patch.object(_v2.db, "insert_game_save",
                          lambda uid, arc: saves.append((uid, arc)) or True), \
             patch.object(_v2.db, "list_game_saves",
                          lambda uid: [{"id": "g1", "arc_id": "a1",
                                        "saved_date": "2026-07-11",
                                        "saved_at": "2026-07-11",
                                        "created_at": "t"}]):
            with self.app.test_request_context():
                _rq.user_id = "u1"
                resp, status = _v2.v2_arc_game_save.__wrapped__("a1")
                self.assertEqual(status, 200)
                resp2, status2 = _v2.v2_user_game_sessions.__wrapped__()
        self.assertEqual(saves, [("u1", "a1")])
        self.assertEqual(status2, 200)
        sess0 = resp2.get_json()["sessions"][0]
        self.assertEqual(sess0["arc_id"], "a1")
        self.assertEqual(sess0["saved_at"], "2026-07-11")  # FE reads this first


if __name__ == "__main__":
    unittest.main()
