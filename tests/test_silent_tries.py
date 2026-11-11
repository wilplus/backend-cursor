"""
STORY    As the founder, I want "Catch more" or "Catch fewer" on one thing the
         walk notices to run silently beside the live setting first, so that
         I see what it would catch and what coaches say before anything a
         speaker sees changes (N647 item 3).
OUTCOME
  O1  One try per thing at a time; a second start is refused.
  O2  Re-scoring the last 20 stored recordings makes the result ready at
      once; it counts only the cases that differ from live, and only
      SETTLED coach answers (a singleton never counts).
  O3  "Use it" makes the candidate live, once, and only when the try is
      ready and at least 10 settled answers exist.
  O4  "Go back", or a try left for 60 days, changes nothing live.
  O5  A running try leaves every live verdict on a Take as it was; the
      candidate's verdicts go to the shadow log under their own version.
  O6  The re-score reads the last stored Takes again, and a case counts as
      agreed only once two coaches' blind answers match.
  O7  A case a try sees differently always reaches a second coach, and the
      coach's row never says a try is involved (Never 2).
  O8  After a value is made live, the blind audit still draws that cue's
      cases, old and new; it never draws a silent try's own verdicts.
  O9  Only the founder reaches the routes; what they return is the thing,
      the direction, counts and words, never a threshold, and below 10
      settled answers it says "Coaches haven't answered enough yet."
  O10 "Use it" is unreachable unless its switch is on; making a value live
      writes a new settings version and keeps the one it replaces.
PROVES   O1 -> test_one_try_per_thing
         O2 -> test_twenty_stored_recordings_give_the_result_at_once
         O3 -> test_use_it_needs_ten_settled_answers_then_goes_live
         O4 -> test_go_back_and_expiry_change_nothing_live
         O5 -> test_a_running_try_leaves_the_live_verdicts_as_they_were
         O6 -> test_the_rescore_counts_only_settled_answers
         O7 -> test_a_tried_case_gets_a_second_coach_blind
         O8 -> test_the_audit_keeps_drawing_a_cue_after_use_it
         O9 -> test_the_founder_routes_show_counts_and_words_never_a_threshold
         O10 -> test_use_it_is_off_unless_switched_on_and_keeps_the_old_setting
"""
from __future__ import annotations

import json
import random
import unittest
from unittest import mock
from datetime import datetime, timedelta, timezone

from services import error_presence_audit as epa
from services import silent_tries as st
from services import verbal_cues

T0 = datetime(2026, 11, 11, tzinfo=timezone.utc)


class FakeConfig:
    """runtime_config with its compare-and-swap, in memory."""

    def __init__(self):
        self.rows: dict[str, dict] = {}
        self.ticks = 0

    def get_runtime_configs(self, keys):
        return {k: (self.rows.get(k) or {}).get("value") for k in keys}

    def get_runtime_config_entry(self, key):
        row = self.rows.get(key)
        return dict(row) if row else None

    def put_runtime_config_entry(self, key, value, *, updated_by, expected_updated_at):
        row = self.rows.get(key)
        if (row is None) != (expected_updated_at is None):
            return False
        if row is not None and row["updated_at"] != expected_updated_at:
            return False
        self.ticks += 1
        self.rows[key] = {"value": value, "updated_at": f"t{self.ticks}"}
        return True


class FakeTakes(FakeConfig):
    """Takes with clips, the shadow log and the coaches' blind answers."""

    def __init__(self, takes):
        super().__init__()
        self.takes = takes  # take id -> [transcript, ...]
        self.shadow: list[dict] = []
        self.answers: list[dict] = []

    def get_snippets_by_session(self, take):
        return [{"id": f"{take}-{i}", "recording_id": f"r-{take}", "transcript": text}
                for i, text in enumerate(self.takes[take])]

    def get_recording(self, rid):
        return {"transcription_language": "en"}

    def record_verbal_cue_shadow(self, rows):
        self.shadow.extend(rows)
        return len(rows)

    def list_verbal_cue_shadow_observations(self, error_id, detector_version):
        return [dict(r, created_at=r["take_session_id"]) for r in self.shadow
                if r["error_id"] == error_id and r["detector_version"] == detector_version]

    def list_error_presence_audit_answered(self, error_id):
        return [a for a in self.answers if a["error_id"] == error_id]


class NoOverlap(random.Random):
    """A draw in which no ordinary case wins the 1-in-10 second coach."""

    def random(self):
        return 0.99


ONE_HEDGE = "I think we should ship the new plan this week"


CANDIDATES = {"hedging": {"verbal_cues.HEDGE_MIN_COUNT": 1},
              "filler_cluster": {"verbal_cues.FILLER_MIN_COUNT": 1}}


def start(db, thing="hedging", direction="more", at=T0):
    return st.start(db, thing=thing, direction=direction,
                    candidate=CANDIDATES[thing], candidate_version="dial-x",
                    live_version="defaults", started_by="founder", at=at)


def evaluate(clip, candidate):
    """Live fires at 2 hedges, the candidate at 1."""
    n = clip.get("count")
    if n is None:
        return None, None
    return n >= 2, n >= candidate["verbal_cues.HEDGE_MIN_COUNT"]


def clips(counts):
    return [{"snippet_id": f"c{i}", "count": n} for i, n in enumerate(counts)]


class Tries(unittest.TestCase):

    def test_one_try_per_thing(self):
        db = FakeConfig()
        start(db)
        with self.assertRaises(st.TryRefused) as refused:
            start(db, direction="fewer")
        self.assertEqual(refused.exception.reason, "try_in_progress")
        start(db, thing="filler_cluster")  # another thing may run beside it

    def test_twenty_stored_recordings_give_the_result_at_once(self):
        db = FakeConfig()
        start(db)
        # 12 clips with one hedge (candidate catches, live does not), 8 with
        # none, 2 unmeasurable (do not count), one repeated (counts once).
        stored = clips([1] * 12 + [0] * 8) + [{"snippet_id": "x1"}, {"snippet_id": "x2"}]
        self.assertEqual(st.add_recordings(db, "hedging", stored, evaluate, at=T0), 20)
        self.assertEqual(st.add_recordings(db, "hedging", stored[:1], evaluate, at=T0), 0)
        now = st.current(db, "hedging", at=T0)
        self.assertEqual(now["state"], st.READY)
        settled = {f"c{i}": "yes" for i in range(4)} | {"c4": "no", "c5": "in_between"}
        result = st.summarize(now, settled)
        self.assertEqual((result["seen"], result["changed"], result["settled"], result["agreed"]),
                         (20, 12, 6, 4))
        self.assertFalse(result["enough_answers"])
        self.assertEqual(sorted(st.differing_clips(now)), sorted(f"c{i}" for i in range(12)))

    def test_use_it_needs_ten_settled_answers_then_goes_live(self):
        db = FakeConfig()
        try_id = start(db)["id"]
        written = []
        st.add_recordings(db, "hedging", clips([1] * 12 + [0] * 8), evaluate, at=T0)
        few = {f"c{i}": "yes" for i in range(9)}
        with self.assertRaises(st.TryRefused) as refused:
            st.use(db, "hedging", try_id=try_id, settled=few,
                   write_live=lambda c, by: written.append(c), by="founder")
        self.assertEqual(refused.exception.reason, "not_enough_answers")
        self.assertEqual(written, [])
        enough = few | {"c9": "no"}
        done = st.use(db, "hedging", try_id=try_id, settled=enough,
                      write_live=lambda c, by: written.append(c), by="founder")
        self.assertEqual(written, [{"verbal_cues.HEDGE_MIN_COUNT": 1}])
        self.assertEqual((done["state"], done["result"]["agreed"]), (st.USED, 9))
        self.assertIsNone(st.current(db, "hedging"))
        self.assertNotIn("differing", st.history(db, "hedging")[-1])

    def test_go_back_and_expiry_change_nothing_live(self):
        db = FakeConfig()
        try_id = start(db)["id"]
        st.add_recordings(db, "hedging", clips([1] * 20), evaluate, at=T0)
        st.drop(db, "hedging", try_id=try_id, by="founder", at=T0)
        self.assertEqual(st.history(db, "hedging")[-1]["state"], st.DROPPED)
        self.assertIsNone(st.current(db, "hedging"))
        start(db, at=T0)  # a new try may start once the old one is gone
        later = T0 + timedelta(days=st.EXPIRES_AFTER_DAYS)
        self.assertIsNone(st.current(db, "hedging", at=later))
        self.assertEqual(st.history(db, "hedging")[-1]["state"], st.EXPIRED)
        # Nothing in this module can write a live setting except use().
        self.assertEqual([k for k in db.rows], ["silent_try:hedging"])


    def test_a_running_try_leaves_the_live_verdicts_as_they_were(self):
        db = FakeTakes({"t1": [ONE_HEDGE, "plain words here"], "t2": [ONE_HEDGE, "plain words here"]})
        permitted = mock.patch.object(verbal_cues, "_practice_permitted", return_value=True)
        with permitted:
            verbal_cues.record_take(db, "t1")
            before = [dict(r, take_session_id="t", recording_id="r", snippet_id=r["snippet_id"][-1])
                      for r in db.shadow]
            start(db, at=datetime.now(timezone.utc))
            db.shadow.clear()
            verbal_cues.record_take(db, "t2")
        live = [r for r in db.shadow if r["detector_version"] == verbal_cues.VERBAL_CUES_VERSION]
        tried = [r for r in db.shadow if r not in live]
        self.assertEqual([dict(r, take_session_id="t", recording_id="r", snippet_id=r["snippet_id"][-1]) for r in live],
                         before)
        self.assertEqual({r["error_id"] for r in tried}, {"hedging"})
        self.assertEqual([r["fired"] for r in tried], [True, False])
        self.assertEqual(st.current(db, "hedging")["seen"], 1)

    def test_the_rescore_counts_only_settled_answers(self):
        takes = {f"t{i:02d}": [ONE_HEDGE] for i in range(25)}
        db = FakeTakes(takes)
        with mock.patch.object(verbal_cues, "_practice_permitted", return_value=True):
            for take in takes:
                verbal_cues.record_take(db, take)
        start(db, at=datetime.now(timezone.utc))
        self.assertEqual(st.rescore(db, "hedging", permitted=lambda d, t: True), 20)
        db.answers = [
            {"clip_id": "t24-0", "error_id": "hedging", "coach_id": "a", "answer": "yes"},
            {"clip_id": "t24-0", "error_id": "hedging", "coach_id": "b", "answer": "yes"},
            {"clip_id": "t23-0", "error_id": "hedging", "coach_id": "a", "answer": "yes"},
            {"clip_id": "t22-0", "error_id": "hedging", "coach_id": "a", "answer": "yes"},
            {"clip_id": "t22-0", "error_id": "hedging", "coach_id": "b", "answer": "cant_tell"},
            {"clip_id": "t21-0", "error_id": "hedging", "coach_id": "a", "answer": "no"},
            {"clip_id": "t21-0", "error_id": "hedging", "coach_id": "b", "answer": "no"},
        ]
        found = st.result(db, "hedging")
        self.assertEqual((found["state"], found["seen"], found["changed"]), (st.READY, 20, 20))
        self.assertEqual((found["settled"], found["agreed"]), (2, 1))

    def test_a_tried_case_gets_a_second_coach_blind(self):
        class Audit(FakeConfig):
            audits: list = []

            def blind_line_cleared(self, *a):
                return False

            def count_coach_blind_answers(self, *a):
                return 0

            def list_error_presence_audit_pending(self, coach):
                return []

            def list_error_presence_audit_by_coach(self, coach):
                return []

            def list_audit_candidates(self, errors):
                return [{"clip_id": f"c{i}", "error_id": "hedging", "fired": False,
                         "speaker_user_id": f"s{i}", "take_session_id": f"t{i}",
                         "detector_version": "verbal-cues-v1", "measurements": {},
                         "answered_count": 1} for i in range(4)]

            def insert_error_presence_audit(self, row):
                self.audits.append(row)
                return row

        db = Audit()
        db.rows[st.key_for("hedging")] = {"updated_at": "t0", "value": json.dumps({
            "current": {"id": "x", "state": st.RUNNING, "direction": "more",
                        "differing": [{"snippet_id": "c2", "live": False, "candidate": True}]},
            "history": []})}
        with mock.patch.object(epa, "_still_permitted", lambda d, c: c), \
             mock.patch("services.coach_exposure.unexposed", lambda d, coach, c: c), \
             mock.patch("services.coach_exposure.record_exposure", lambda *a, **k: True):
            written = epa.sample_for_coach(db, coach_id="coach", rng=NoOverlap())
        self.assertEqual([r["clip_id"] for r in written if r["overlap"]], ["c2"])
        self.assertFalse(any("trial" in r or "silent" in json.dumps(r) for r in written))


    def test_the_audit_keeps_drawing_a_cue_after_use_it(self):
        from services import noticing_settings as ns
        from services.db import audit_candidate_rows
        from services.detector_rollout import LIVE_DETECTOR
        db = FakeTakes({"old": [ONE_HEDGE], "tried": [ONE_HEDGE], "new": [ONE_HEDGE]})
        with mock.patch.object(verbal_cues, "_practice_permitted", return_value=True):
            verbal_cues.record_take(db, "old")
            start(db, at=datetime.now(timezone.utc))
            verbal_cues.record_take(db, "tried")
            ns.use_reader(lambda: json.dumps({"values": {"verbal_cues.HEDGE_MIN_COUNT": 1}}))
            try:
                verbal_cues.record_take(db, "new")
            finally:
                ns.use_reader(lambda: None)
        newest_first = list(reversed(db.shadow))
        drawn = audit_candidate_rows(newest_first, LIVE_DETECTOR, verbal_cues.logged_live)
        hedging = {r["snippet_id"]: r for r in drawn if r["error_id"] == "hedging"}
        self.assertEqual(sorted(hedging), ["new-0", "old-0", "tried-0"])
        self.assertTrue(hedging["new-0"]["fired"])
        self.assertFalse(any(verbal_cues.TRY_MARK in str(r["detector_version"]) for r in drawn))


class Routes(unittest.TestCase):
    H = {"Authorization": "Bearer t"}

    def setUp(self):
        from flask import Flask

        import auth
        from routes.v2 import register_domains
        from routes.v2.blueprint import v2_bp
        register_domains()
        app = Flask(__name__)
        app.register_blueprint(v2_bp, url_prefix="/v2")
        self.client = app.test_client()
        self.founder = True
        self.db = FakeTakes({f"t{i:02d}": [ONE_HEDGE] for i in range(3)})
        with mock.patch.object(verbal_cues, "_practice_permitted", return_value=True):
            for take in self.db.takes:
                verbal_cues.record_take(self.db, take)
        payload = {"sub": "u-founder", "email": "f@example.com"}
        for p in (mock.patch.object(auth, "verify_supabase_token", lambda _t: payload),
                  mock.patch("routes.admin.is_admin", lambda _u: True),
                  mock.patch("routes.admin.is_founder_email", lambda _e: self.founder),
                  mock.patch("routes.v2.silent_tries.db", self.db),
                  mock.patch.object(verbal_cues, "_practice_permitted", return_value=True)):
            p.start()
            self.addCleanup(p.stop)

    def test_the_founder_routes_show_counts_and_words_never_a_threshold(self):
        self.founder = False
        self.assertEqual(self.client.get("/v2/build/notice/hedging/try", headers=self.H).status_code, 403)
        self.founder = True
        res = self.client.post("/v2/build/notice/hedging/try", json={"direction": "more"}, headers=self.H)
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertEqual((body["try"]["state"], body["try"]["seen"], body["try"]["changed"]),
                         (st.RUNNING, 3, 3))
        self.assertEqual(body["try"]["note"], "Coaches haven't answered enough yet.")
        self.assertNotIn("verbal_cues.", json.dumps(body))
        again = self.client.post("/v2/build/notice/hedging/try", json={"direction": "fewer"}, headers=self.H)
        self.assertEqual((again.status_code, again.get_json()["code"]), (409, "try_in_progress"))
        try_id = body["try"]["id"]
        gone = self.client.post(f"/v2/build/notice/hedging/try/{try_id}/drop", headers=self.H)
        self.assertEqual(gone.get_json()["try"], None)
        self.assertNotIn("noticing_settings", self.db.rows)

    def test_use_it_is_off_unless_switched_on_and_keeps_the_old_setting(self):
        with mock.patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop(st.USE_SWITCH, None)
            res = self.client.post("/v2/build/notice/hedging/try/x/use", headers=self.H)
        self.assertEqual(res.status_code, 404)
        from services import noticing_settings as ns
        before = ns.use_reader
        self.db.rows[ns.KEY] = {"updated_at": "t0", "value": json.dumps(
            {"version": "old", "values": {"verbal_cues.FILLER_MIN_COUNT": 3}})}
        try:
            version = st.make_live(self.db, {"verbal_cues.HEDGE_MIN_COUNT": 1}, by="founder")
        finally:
            ns.use_reader(lambda: None)
        record = json.loads(self.db.rows[ns.KEY]["value"])
        self.assertEqual(record["version"], version)
        self.assertEqual(record["values"], {"verbal_cues.HEDGE_MIN_COUNT": 1,
                                            "verbal_cues.FILLER_MIN_COUNT": 3})
        self.assertEqual(record["history"][-1]["values"], {"verbal_cues.FILLER_MIN_COUNT": 3})
        self.assertIs(ns.use_reader, before)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
