"""Lend your ear, the one engine of the walk's other voices (founder
2026-10-07, Q-B11 A, N62), the licensed corpus and the delayed measure.

Pins: the Album share switch, the per-Take blind set it fed and Bold voices
are RETIRED, their service doors gone and their routes 404 whatever the
switches say, nothing written; the one consent path that admits a
speaker's moment to a peer queue is the per-Take community share
(services/communities.py, community_clips_live), read by the engine's
``other_voices`` and nothing else; at most three other voices per walk,
community first, then training clips; a blind stratified pick (build_set)
that never holds two clips of one pair; the payload carries only the id,
the kind and the sound; a peer label lands under lane game_peer through
the quorum's access rule; the measure's pair is the first valid attempt,
excludes fallbacks and rewrites, is judged after seven days, refuses the
speaker, the coach who handled the moment and an exposed rater, settles
only by quorum, and no longer has a door into any queue.
"""
from __future__ import annotations

import random
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from services import corpus_clips as cc
from services import delayed_measure as dm
from services import lend_your_ear as lye

ROOT = Path(__file__).resolve().parents[1]
PEER_ON = patch("config.Config.PEER_LANE_ENABLED", True)
#: An attempt the readiness gate counts valid (aligned words, a confidence
#: read, reliable audio): the measure's endpoint.
VALID_ATTEMPT = {"id": "a-1", "attempt_index": 1, "transcript": "the words here now",
                 "duration_ms": 2500, "audio_ref": "https://a/a-1.webm",
                 "acoustic_metrics": {"aligned_words": 4, "confidence": 0.3, "voiced_ratio": 0.8}}
MEASURE_ON = patch("config.Config.DELAYED_MEASURE_ENABLED", True)
PEER_OFF = patch("config.Config.PEER_LANE_ENABLED", False)
MEASURE_OFF = patch("config.Config.DELAYED_MEASURE_ENABLED", False)


def _snippet(sid, band=None, session="take-9"):
    row = {"id": sid, "session_id": session, "audio_segment_path": f"s/{sid}.webm",
           "duration_ms": 3000, "metrics": {}}
    if band:
        row["metrics"]["voice_confidence"] = {"band": band}
    return row


class _Status:
    """The Phase-1 authorization read, stubbed: on the stub's policy version."""
    def __init__(self, database):
        self.db = database
    def user_acquisition_principal(self, user_id):
        return f"principal-{user_id}"
    def status(self, principal):
        user = principal.replace("principal-", "")
        version = self.db.accepted.get(user)
        return {"authorized": bool(version), "policy_version": version}


SERVICE = patch("services.processing_authorization.ProcessingAuthorizationService", _Status)


class _Db:
    def __init__(self):
        self.shares: dict = {}
        # Q4-A (founder 2026-10-02): whose authorization is on the policy
        # version that names the switch: {user_id: policy_version}.
        self.accepted = {"owner-1": "phase1-2026-11-01"}
        self.album = {("arc-1", "snip-a")}
        self.sets: list = []
        self.answers: list = []
        self.labels: dict = {}
        self.ratings: list = []
        self.corpus: list = []
        self.pairs: list = []
        self.votes: list = []
        self.live: list = []
        self.landed = True
        self.steps: list = []

    def get_snippet_by_id(self, sid):
        return _snippet(sid)

    def get_snippets_by_ids(self, ids):
        return [_snippet(i, band={"snip-c": "delivery_signal_high",
                                  "snip-w": "delivery_signal_low"}.get(i)) for i in ids]

    def v2_get_session_by_id(self, sid):
        return {"id": sid, "user_id": "owner-1", "arc_id": "arc-1"} if sid in ("take-1", "take-9") else None

    def voice_album_has(self, arc_id, snippet_id):
        return (arc_id, snippet_id) in self.album

    def set_voice_album_share(self, **kwargs):
        self.shares[kwargs["snippet_id"]] = {**kwargs, "revoked_at": None if kwargs["shared"] else "now"}
        return self.shares[kwargs["snippet_id"]]

    def list_shared_clips_live(self):
        return list(self.live)


    def list_corpus_clips_active(self):
        return [c for c in self.corpus if c.get("active", True)]

    def list_corpus_clips(self, *, active_only=True):
        return list(self.corpus)

    def insert_corpus_clip(self, row):
        self.corpus.append({"id": f"corp-{len(self.corpus) + 1}", "active": True, **row})
        return self.corpus[-1]

    def set_corpus_clip_coach_value(self, *, clip_id, coach_id, value):
        row = next((c for c in self.corpus if c["id"] == clip_id), None)
        if row:
            row["coach_value"] = value
        return row

    def get_confidence_labels_by_snippet_ids(self, ids):
        return {i: self.labels.get(i, []) for i in ids}

    def list_lend_your_ear_answered_clip_ids(self, listener):
        return [a["clip_id"] for a in self.answers if a["listener_user_id"] == listener]

    def get_lend_your_ear_set_for_take(self, take):
        return next((self._set(s) for s in self.sets if s["take_session_id"] == take), None)

    def get_lend_your_ear_set(self, set_id, listener):
        return next((self._set(s) for s in self.sets
                     if s["id"] == set_id and s["listener_user_id"] == listener), None)

    def _set(self, s):
        return {**s, "answered_clip_ids": [a["clip_id"] for a in self.answers if a["set_id"] == s["id"]]}

    def insert_lend_your_ear_set(self, row):
        self.sets.append({"id": f"set-{len(self.sets) + 1}", **row})
        return self.sets[-1]

    def insert_lend_your_ear_answer(self, row):
        if any(a["listener_user_id"] == row["listener_user_id"] and a["clip_id"] == row["clip_id"]
               for a in self.answers):
            return None
        self.answers.append({"id": f"ans-{len(self.answers) + 1}", **row})
        return self.answers[-1]

    def list_recent_pair_ids_for_listener(self, listener, *, days):
        return []

    def list_landed_practices_for_take(self, take, owner):
        return [{"id": "p-1"}] if self.landed else []

    def mark_after_practice_step(self, **kwargs):
        self.steps.append(kwargs["step"])
        return True

    def upsert_state_rating(self, **kwargs):
        self.ratings.append(kwargs)
        return True

    # the measure
    def insert_delayed_measure_pair(self, row):
        if any(p["practice_id"] == row["practice_id"] for p in self.pairs):
            return None
        self.pairs.append({"id": f"pair-{len(self.pairs) + 1}", "status": "open", **row})
        return self.pairs[-1]

    def get_delayed_measure_pair(self, pair_id):
        return next((p for p in self.pairs if p["id"] == pair_id), None)

    def list_delayed_measure_pairs_open(self):
        return list(self.pairs)

    def insert_delayed_measure_vote(self, row):
        if any(v["pair_id"] == row["pair_id"] and v["clip"] == row["clip"]
               and v["rater_id"] == row["rater_id"] for v in self.votes):
            return None
        self.votes.append(row)
        return row

    def list_delayed_measure_votes(self, pair_id):
        return [v for v in self.votes if v["pair_id"] == pair_id]

    def list_delayed_measure_votes_by_rater(self, rater):
        return [v for v in self.votes if v["rater_id"] == rater]

    def coach_handled_moment(self, coach_id, take, snippet):
        return coach_id == "coach-handled"

    def get_confident_voice_practice_attempt(self, aid):
        return {"id": aid, "audio_ref": "https://a/x.webm", "duration_ms": 2500}

    def list_confident_voice_practice_attempts(self, pid):
        return [VALID_ATTEMPT]

    def get_confident_voice_exercise_assignment(self, take, snip):
        return {"id": "asg-1"}

    def get_exercise_match_trace(self, aid):
        return {"fallback": None}


@PEER_OFF
@MEASURE_OFF
class OffTests(unittest.TestCase):
    """The coach's corpus tool and the measure, with both switches patched
    off: nothing is served or written."""
    def test_off_nothing_is_served_or_written(self):
        db = _Db()
        self.assertEqual(cc.list_clips(db)[0], 404)
        self.assertIsNone(dm.enrol(db, {"id": "p-1", "kind": "exercise"}))
        self.assertEqual(dm.vote(db, pair_id="p", clip="before", rater_id="r",
                                 rater_kind="peer", value="yes")[0], 404)
        self.assertEqual(dm.clips_for_listener(db, listener_id="x"), [])
        self.assertEqual((db.shares, db.sets, db.answers, db.pairs, db.votes), ({}, [], [], [], []))


class _Refuses:
    """A database no retired door may touch."""
    def __getattr__(self, name):
        raise AssertionError(f"retired door read the database: {name}")


RETIRED_ROUTES = {
    "v2_voice_album_share": ("/user/voice-album/<snippet_id>/share", "PUT", ("snip-a",)),
    "v2_lend_your_ear": ("/user/takes/<take_session_id>/lend-your-ear", "GET", ("take-1",)),
    "v2_lend_your_ear_answer": ("/user/lend-your-ear/<set_id>/answers", "POST", ("set-1",)),
}


class RetiredTests(unittest.TestCase):
    """Q-B11 A (N62): the Album share switch, the per-Take set it fed and
    Bold voices are retired. No service door, and the routes answer 404
    whatever the switches say, before any read."""
    def test_the_service_doors_are_gone(self):
        for door in ("set_share", "open_set", "answer", "others_for_bold_voices",
                     "_candidates", "_shared_candidates", "_set_payload"):
            self.assertFalse(hasattr(lye, door), door)
        self.assertEqual(lye.SOURCES, ("community", "training"))
        self.assertEqual(lye.OTHER_VOICES_MAX, 3)

    @PEER_ON
    @MEASURE_ON
    @patch("config.Config.COMMUNITIES_ENABLED", True)
    @patch("config.Config.PEER_SHARE_POLICY_VERSION", "phase1-2026-11-01", create=True)
    def test_the_routes_answer_404_whatever_the_switches_say(self):
        from flask import Flask, request
        import routes.v2.lend_your_ear as route
        app = Flask(__name__)
        source = (ROOT / "routes/v2/lend_your_ear.py").read_text()
        with patch.object(route, "db", _Refuses()):
            for name, (path, method, args) in RETIRED_ROUTES.items():
                self.assertIn(f'@v2_bp.route("{path}", methods=["{method}"])', source)
                with app.test_request_context("/v2/x", method=method,
                                              json={"shared": True, "clip_id": "x", "value": "yes"}):
                    request.user_id = "owner-1"
                    response, status = getattr(route, name).__wrapped__(*args)
                self.assertEqual(status, 404, name)
                self.assertEqual(response.get_json()["code"], "NOT_FOUND", name)
        # Nothing in the engine or the communities reads the retired share.
        for name in ("services/lend_your_ear.py", "services/communities.py"):
            text = (ROOT / name).read_text()
            for retired in ("list_shared_clips_live", "voice_album_shares", "shared_clips_live",
                            "set_voice_album_share", "insert_lend_your_ear_set",
                            "insert_lend_your_ear_answer", "clips_for_listener",
                            "mark_after_practice_step"):
                self.assertNotIn(f"database.{retired}(", text, (name, retired))
                self.assertNotIn(f"{retired}(database", text, (name, retired))

    def test_the_measure_has_no_door_into_any_queue(self):
        # The pair rode the Album share (Q3-A); with the share retired, no
        # queue reads the measure's clips.
        source = (ROOT / "services").glob("*.py")
        callers = [f.name for f in source
                   if "clips_for_listener(" in f.read_text() and f.name != "delayed_measure.py"]
        self.assertEqual(callers, [])


class SetTests(unittest.TestCase):
    def test_the_set_is_stratified_random_and_at_most_three(self):
        cands = [{"clip_id": f"c{i}", "stratum": s, "pair_id": None}
                 for i, s in enumerate(["weak", "weak", "confident", "unknown", "confident"])]
        chosen = lye.build_set(cands, recent_pairs=[], rng=random.Random(1))
        self.assertEqual(len(chosen), 3)
        self.assertEqual({c["stratum"] for c in chosen}, {"confident", "weak", "unknown"})
        two = lye.build_set(cands[:2], recent_pairs=[], rng=random.Random(1))
        self.assertEqual(len(two), 2)
        self.assertEqual(lye.build_set([], recent_pairs=[]), [])

    def test_never_both_clips_of_one_pair_and_never_a_pair_heard_within_the_gap(self):
        cands = [{"clip_id": "p1:before", "stratum": "unknown", "pair_id": "p1"},
                 {"clip_id": "p1:after", "stratum": "unknown", "pair_id": "p1"},
                 {"clip_id": "p2:before", "stratum": "unknown", "pair_id": "p2"},
                 {"clip_id": "s", "stratum": "weak", "pair_id": None}]
        for seed in range(6):
            chosen = lye.build_set(cands, recent_pairs=["p2"], rng=random.Random(seed))
            pairs = [c["pair_id"] for c in chosen if c["pair_id"]]
            self.assertEqual(len(pairs), len(set(pairs)), seed)
            self.assertNotIn("p2", pairs, seed)
            self.assertLessEqual(len(chosen), 2, seed)

    def test_the_stratum_is_the_machine_s_read_never_surfaced(self):
        self.assertEqual(lye.stratum(_snippet("x", band="delivery_signal_high")), "confident")
        self.assertEqual(lye.stratum(_snippet("x", band="delivery_signal_low")), "weak")
        self.assertEqual(lye.stratum(_snippet("x")), "unknown")
        self.assertEqual(lye.stratum(None), "unknown")


class _Community(_Db):
    """The engine's reads: the per-Take community share (the one consent
    path), the corpus, and, as a trap, an Album share and a ripe measure
    pair that must never be served."""
    def __init__(self):
        super().__init__()
        self.community_live: list = []
        self.community_answers: list = []
        self.general = {"id": "general-1", "kind": "general", "closed_at": None}

    def get_general_community(self):
        return self.general

    def list_community_memberships(self, user_id):
        return []

    def get_communities_by_ids(self, ids):
        return []

    def list_community_clips_live(self, community_ids):
        return [r for r in self.community_live if r["community_id"] in community_ids]

    def list_community_answered_clip_ids(self, listener):
        return [a for a in self.community_answers]

    def get_snippet_by_id(self, sid):
        return {**_snippet(sid), "user_id": "other" if sid != "snip-mine" else "owner-1",
                "start_offset_ms": 10}


class OneConsentPathTests(unittest.TestCase):
    """Only the per-Take community share admits a speaker's moment to the
    walk's queue; the Album share and the measure's pair never do."""
    def _world(self):
        db = _Community()
        # The trap: lent through the retired switch, and a ripe pair.
        db.live = [{"snippet_id": "snip-album", "owner_user_id": "other"}]
        db.pairs = [{"id": "pair-1", "owner_user_id": "other", "take_session_id": "t",
                     "before_snippet_id": "snip-album", "after_attempt_id": "a-9", "status": "open",
                     "practice_closed_at": (datetime.now(timezone.utc) - timedelta(days=9)).isoformat()}]
        db.corpus = [{"id": f"corp-{i}", "audio_url": f"https://c/{i}.mp3", "duration_ms": 2000,
                      "machine_stratum": s, "active": True}
                     for i, s in enumerate(("confident", "weak", "unknown", "unknown"), start=1)]
        return db

    @MEASURE_ON
    @PEER_ON
    def test_an_album_share_and_a_measure_pair_never_reach_the_queue(self):
        db = self._world()
        voices = lye.other_voices(db, listener_id="owner-1", rng=random.Random(3))
        self.assertEqual([v["source"] for v in voices], ["training"] * 3)
        self.assertEqual(db.sets, [])
        self.assertEqual(db.answers, [])

    def test_a_take_shared_with_a_community_is_the_one_door(self):
        db = self._world()
        db.community_live = [
            {"snippet_id": "snip-c", "take_session_id": "take-9", "community_id": "general-1",
             "owner_user_id": "other"},
            {"snippet_id": "snip-mine", "take_session_id": "take-1", "community_id": "general-1",
             "owner_user_id": "owner-1"},
        ]
        voices = lye.other_voices(db, listener_id="owner-1", rng=random.Random(3))
        self.assertEqual([v["source"] for v in voices], ["community", "training", "training"])
        self.assertEqual(voices[0]["clip_id"], "snip-c")
        self.assertNotIn("snip-mine", {v["clip_id"] for v in voices})
        self.assertNotIn("snip-album", {v["clip_id"] for v in voices})

    def test_at_most_three_community_first_and_audio_only(self):
        db = self._world()
        db.community_live = [
            {"snippet_id": f"snip-{i}", "take_session_id": f"take-{i}", "community_id": "general-1",
             "owner_user_id": "other"} for i in range(5)]
        voices = lye.other_voices(db, listener_id="owner-1", rng=random.Random(3))
        self.assertEqual(len(voices), 3)
        self.assertEqual([v["source"] for v in voices], ["community"] * 3)
        for clip in voices:
            self.assertEqual(set(clip), {"clip_id", "source", "audio_ref", "start_offset_ms",
                                         "duration_ms"})
        self.assertEqual(lye.other_voices(db, listener_id="owner-1", limit=0), [])
        # Answered clips leave the queue, community and training alike.
        db.community_answers = ["snip-0", "snip-1", "snip-2", "snip-3", "snip-4", "corp-1", "corp-2"]
        voices = lye.other_voices(db, listener_id="owner-1", rng=random.Random(3))
        self.assertEqual(sorted(v["clip_id"] for v in voices), ["corp-3", "corp-4"])
        self.assertEqual([v["source"] for v in voices], ["training", "training"])

    def test_a_peer_label_lands_under_lane_game_peer_through_the_quorum(self):
        db = self._world()
        label_id, outcome = lye._peer_label(db, listener_id="owner-1", snippet_id="snip-c",
                                            row={"state_id": "confidence", "value": "in_between"})
        self.assertEqual((label_id, outcome), ("written", "new"))
        self.assertEqual(db.ratings[0]["lane"], "game_peer")
        self.assertFalse(db.ratings[0]["self_report"])
        self.assertEqual(db.ratings[0]["rater_id"], "owner-1")


@PEER_ON
class CorpusToolTests(unittest.TestCase):
    def test_the_corpus_tool(self):
        class _File:
            filename = "clip.mp3"
            content_type = "audio/mpeg"

            def read(self):
                return b"abc"
        db = _Db()
        with patch("services.journal_media.put_object_bytes",
                   return_value={"public_url": "https://c/x.mp3", "key": "k"}):
            status, payload = cc.create_clip(db, coach_id="c", licence="CC BY, the Foo archive",
                                             passage="a line", media_file=_File(), max_mb=10)
        self.assertEqual(status, 201)
        self.assertEqual(cc.label_clip(db, coach_id="c", clip_id="corp-1", value="yes")[1]["clip"]["coach_value"], "yes")
        self.assertEqual(cc.label_clip(db, coach_id="c", clip_id="corp-1", value="maybe")[0], 400)
        self.assertEqual(cc.create_clip(db, coach_id="c", licence="", passage="a", media_file=_File(), max_mb=10)[0], 400)


class PairTests(unittest.TestCase):
    def test_the_pair_is_the_first_valid_attempt_and_excludes_what_it_should(self):
        attempts = [VALID_ATTEMPT]
        practice = {"id": "p-1", "kind": "exercise", "snippet_id": "snip-a", "owner_user_id": "o",
                    "take_session_id": "take-1", "exercise_id": "ex", "closed_at": "2026-10-01T00:00:00+00:00"}
        pair, why = dm.pair_for_practice(practice, attempts, {"fallback": None})
        self.assertIsNone(why)
        self.assertEqual((pair["after_attempt_id"], pair["before_snippet_id"], pair["measure_version"]),
                         ("a-1", "snip-a", dm.MEASURE_VERSION))
        self.assertEqual(dm.pair_for_practice({**practice, "kind": "rewrite"}, attempts, {})[1], "not_an_exercise")
        self.assertEqual(dm.pair_for_practice(practice, attempts, {"fallback": "general"})[1], "fallback")
        self.assertEqual(dm.pair_for_practice(practice, [], {})[1], "no_valid_attempt")

    def test_the_horizon_is_seven_days(self):
        now = datetime(2026, 10, 10, tzinfo=timezone.utc)
        self.assertTrue(dm.ripe({"practice_closed_at": "2026-10-02T00:00:00+00:00"}, now=now))
        self.assertFalse(dm.ripe({"practice_closed_at": "2026-10-05T00:00:00+00:00"}, now=now))
        self.assertFalse(dm.ripe({"practice_closed_at": None}, now=now))

    def test_the_outcome_settles_only_by_quorum(self):
        def v(clip, value, rater, kind="peer"):
            return {"clip": clip, "value": value, "rater_id": rater, "rater_kind": kind, "blind": True}
        self.assertEqual(dm.pair_outcome([v("before", "no", "r1")]), "pending")
        votes = [v("before", "no", "r1"), v("before", "no", "r2", "coach"),
                 v("after", "yes", "r3"), v("after", "yes", "r4")]
        self.assertEqual(dm.pair_outcome(votes), "better")
        votes[2]["value"] = votes[3]["value"] = "no"
        self.assertEqual(dm.pair_outcome(votes), "same")
        votes[0]["value"] = votes[1]["value"] = "yes"
        self.assertEqual(dm.pair_outcome(votes), "worse")
        # A disagreement is not settled; a non-blind vote never counts.
        self.assertEqual(dm.pair_outcome([v("before", "no", "r1"), v("before", "yes", "r2"),
                                          v("after", "yes", "r3"), v("after", "yes", "r4")]), "pending")
        self.assertIsNone(dm.settled_value([{**v("after", "yes", "r3"), "blind": False},
                                            v("after", "yes", "r4")]))


@MEASURE_ON
class MeasureTests(unittest.TestCase):
    def test_enrol_once_and_refuse_the_wrong_raters(self):
        db = _Db()
        practice = {"id": "p-1", "kind": "exercise", "snippet_id": "snip-a", "owner_user_id": "owner-1",
                    "take_session_id": "take-1", "exercise_id": "ex",
                    "closed_at": (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()}
        self.assertIsNotNone(dm.enrol(db, practice))
        self.assertIsNone(dm.enrol(db, practice))
        self.assertEqual(len(db.pairs), 1)
        pair_id = db.pairs[0]["id"]
        self.assertEqual(dm.vote(db, pair_id=pair_id, clip="before", rater_id="owner-1",
                                 rater_kind="peer", value="yes")[1]["reason"], "own_clip")
        self.assertEqual(dm.vote(db, pair_id=pair_id, clip="before", rater_id="coach-handled",
                                 rater_kind="coach", value="yes")[1]["reason"], "handled_the_moment")
        self.assertEqual(dm.vote(db, pair_id=pair_id, clip="before", rater_id="peer-1",
                                 rater_kind="peer", value="yes"), (200, {"recorded": True}))
        self.assertEqual(dm.vote(db, pair_id=pair_id, clip="before", rater_id="peer-1",
                                 rater_kind="peer", value="no")[1]["code"], "ALREADY_VOTED")
        self.assertEqual(dm.vote(db, pair_id=pair_id, clip="sideways", rater_id="peer-1",
                                 rater_kind="peer", value="no")[0], 400)

    def test_an_exposed_rater_never_votes(self):
        class _Exposed(_Db):
            def rater_exposed_to(self, rater_id, clip_ids):
                return rater_id == "peer-seen"
        db = _Exposed()
        db.pairs = [{"id": "pair-1", "owner_user_id": "o", "take_session_id": "t",
                     "before_snippet_id": "s", "after_attempt_id": "a", "status": "open"}]
        self.assertEqual(dm.vote(db, pair_id="pair-1", clip="after", rater_id="peer-seen",
                                 rater_kind="peer", value="yes")[1]["reason"], "exposed")

    @MEASURE_ON
    def test_the_pair_s_clips_are_listed_only_under_the_retired_share_and_reach_no_queue(self):
        db = _Db()
        db.pairs = [{"id": "pair-1", "owner_user_id": "other", "take_session_id": "t",
                     "before_snippet_id": "snip-b", "after_attempt_id": "a-9", "status": "open",
                     "practice_closed_at": (datetime.now(timezone.utc) - timedelta(days=9)).isoformat()}]
        # Q3-A (founder 2026-10-02): the pair rode the original's Album
        # share; unshared, nobody hears either clip.
        self.assertEqual(dm.clips_for_listener(db, listener_id="owner-1"), [])
        db.live = [{"snippet_id": "snip-b", "owner_user_id": "other"}]
        cands = dm.clips_for_listener(db, listener_id="owner-1")
        self.assertEqual({c["clip_id"] for c in cands}, {"pair-1:before", "pair-1:after"})
        self.assertEqual(dm.clips_for_listener(db, listener_id="other"), [])
        # Q-B11 A retired that share, and with it the measure's only door
        # into a queue: the engine never reads these candidates.
        self.assertEqual(lye.other_voices(_Community(), listener_id="owner-1"), [])
        self.assertEqual(db.votes, [])

    def test_the_report_counts_per_exercise(self):
        db = _Db()
        db.pairs = [{"id": "pair-1", "exercise_id": "ex", "status": "open"},
                    {"id": "pair-2", "exercise_id": "ex", "status": "open"}]
        db.votes = [{"pair_id": "pair-1", "clip": "before", "value": "no", "rater_id": "r1", "rater_kind": "peer", "blind": True},
                    {"pair_id": "pair-1", "clip": "before", "value": "no", "rater_id": "r2", "rater_kind": "peer", "blind": True},
                    {"pair_id": "pair-1", "clip": "after", "value": "yes", "rater_id": "r3", "rater_kind": "coach", "blind": True},
                    {"pair_id": "pair-1", "clip": "after", "value": "yes", "rater_id": "r4", "rater_kind": "peer", "blind": True}]
        out = dm.report(db)
        self.assertEqual(out["exercises"]["ex"], {"enrolled": 2, "settled": 1, "better": 1, "same": 0, "worse": 0})


class WiringTests(unittest.TestCase):
    def test_the_measure_is_written_before_data_and_the_wiring_is_in_place(self):
        spec = (ROOT / "docs/MEASURE-exercise-human-delayed-v1.md").read_text()
        for needle in ("written before any data", "signed by the founder on 2026-10-02", "first valid attempt", "seven days",
                       "coach who handled the moment", "No training"):
            self.assertIn(needle, spec)
        contract = (ROOT / "docs/CANONICAL_PRODUCT_CONTRACT.md").read_text()
        self.assertIn("29d. **Lend your ear and the share**", contract)
        self.assertIn("29e. **The delayed blind human measure**", contract)
        config = (ROOT / "config.py").read_text()
        # Off again from 2026-10-03 (F1 Repair Plan Phase 0, N29): no screen
        # renders the share switch or Lend your ear yet.
        self.assertIn("PEER_LANE_ENABLED = False", config)
        self.assertIn("DELAYED_MEASURE_ENABLED = False", config)
        self.assertIn("PEER_SHARE_POLICY_VERSION: str | None = \"phase1-2026-10-02\"", config)
        sql = (ROOT / "migrations/a_moment_may_be_lent_an_ear.sql").read_text()
        for table in ("voice_album_shares", "corpus_clips", "lend_your_ear_sets",
                      "lend_your_ear_answers", "delayed_measure_pairs", "delayed_measure_votes"):
            self.assertIn(f"CREATE TABLE IF NOT EXISTS public.{table}", sql)
        self.assertIn("CREATE OR REPLACE VIEW public.shared_clips_live", sql)
        self.assertIn('"lend_your_ear"', (ROOT / "routes/v2/__init__.py").read_text())
        # Q-B11 A: the communities' queue is served by the engine.
        self.assertIn("from services.lend_your_ear import other_voices",
                      (ROOT / "services/communities.py").read_text())
        self.assertIn("enrol(database, result[\"practice_row\"])",
                      (ROOT / "services/practice_adoption.py").read_text())
        self.assertIn("enrol(db, updated)", (ROOT / "routes/v2/user_sessions.py").read_text())
        from services.data_purge_registry import DEPENDENCIES
        by = {d.relation: (d.selector_column, d.locator_kind) for d in DEPENDENCIES}
        self.assertEqual(by["voice_album_shares"], ("take_session_id", "take"))
        self.assertEqual(by["lend_your_ear_answers"], ("listener_user_id", "user"))
        self.assertEqual(by["delayed_measure_votes"], ("rater_id", "user"))

    def test_nothing_trains_on_it(self):
        for name in ("services/lend_your_ear.py", "services/delayed_measure.py"):
            source = (ROOT / name).read_text()
            self.assertNotIn("fine_tune", source)
            self.assertNotIn("training_corpus", source)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
