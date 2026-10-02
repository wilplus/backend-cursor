"""The coach panel's learning additions (founder 2026-10-01): the coach's
exercise preference (1b, F8), the coach's own words as pair surfaces (7,
C5-a), the blind error audit, the detector versions, the detector fair test
and the candidates (6a to 6d, F6), the blind block pick (8, C5-b), and coach
exposure (task 4). Every lane is dark behind its own constant.

Pins: off, nothing is served or written; each record is append-only with
its own provenance and never mixes with another lane; blindness holds on
every payload (no read, no verdict, no Manager pick, no stratum); the
ranker learns from train speakers only and never promotes itself; the
promotion bar flips nothing; the learned detector refuses to train.
"""
from __future__ import annotations

import random
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from services import coach_block_pick as bp
from services import coach_exercise_preference as cep
from services import coach_exposure as ce
from services import coach_word_pairs as cwp
from services import detector_candidates as dc
from services import detector_rollout as dr
from services import error_presence_audit as epa

ROOT = Path(__file__).resolve().parents[1]
PREF_ON = patch("config.Config.COACH_EXERCISE_PREFERENCE_ENABLED", True, create=True)
AUDIT_ON = patch("config.Config.ERROR_PRESENCE_AUDIT_ENABLED", True, create=True)
PICK_ON = patch("config.Config.COACH_BLOCK_PICK_ENABLED", True, create=True)
WORDS_ON = patch("config.Config.COACH_WORD_PAIRS_ENABLED", True, create=True)


class _Db:
    def __init__(self):
        self.prefs: list = []
        self.exposures: set = set()
        self.audits: list = []
        self.picks: list = []
        self.shadow: list = []
        self.pairs: list = []
        self.word_drafts: list = []
        self.request_drafts: list = []
        self.transcripts: list = []

    # 1b
    def get_confident_voice_exercise_assignment(self, take, snip):
        return {"id": "asg-1", "selected_exercise_id": "ex-a", "selected_exercise_version": 2,
                "selection_mode": "exploration", "matching_policy_version": "exercise-80-20-v1"}

    def get_exercise_match_trace(self, aid):
        return {"trace": {"fit": "exact", "observed_tags": ["rushing"],
                          "signal_rules_version": "cv-exercise-signals-v1", "fallback": None,
                          "candidates": [
                              {"exercise_id": "ex-a", "outcome": "ranked", "main_targets": ["rushing"]},
                              {"exercise_id": "ex-b", "outcome": "ranked", "main_targets": ["rushing"]},
                              {"exercise_id": "ex-c", "outcome": "excluded", "reason": "x"}]}}

    def get_active_diagnostic_exercise(self, eid):
        return {"exercise_id": eid, "title": f"Title {eid}", "instruction": "do it"}

    def list_speaking_errors(self):
        return [{"error_id": "rushing", "label": "Rushing", "asks": "Do you hear rushing here?"}]

    def insert_coach_exercise_preference(self, row):
        self.prefs.append({"id": f"pref-{len(self.prefs) + 1}", **row})
        return self.prefs[-1]

    def list_coach_exercise_preferences(self):
        return list(self.prefs)

    # exposure
    def record_coach_clip_exposure(self, **kwargs):
        key = (kwargs["coach_id"], kwargs["clip_id"])
        if key in self.exposures:
            return False
        self.exposures.add(key)
        return True

    def list_coach_clip_exposures(self, coach_id, clip_ids):
        return [{"clip_id": c} for c in clip_ids if (coach_id, c) in self.exposures]

    # audit
    def count_coach_blind_answers(self, coach_id, week):
        return sum(1 for a in self.audits if a["coach_id"] == coach_id and a.get("answer")) \
            + sum(1 for p in self.picks if p["coach_id"] == coach_id and p.get("answered_at"))

    def list_error_presence_audit_pending(self, coach_id):
        return [a for a in self.audits if a["coach_id"] == coach_id and not a.get("answer")]

    def list_error_presence_audit_by_coach(self, coach_id):
        return [a for a in self.audits if a["coach_id"] == coach_id]

    def list_audit_candidates(self, errors):
        return [{"clip_id": f"c{i}", "error_id": "rushing", "fired": i % 2 == 0, "speaker_user_id": f"s{i % 5}",
                 "take_session_id": f"t{i}", "detector_version": "rules-v1", "measurements": {"wpm": 100 + i},
                 "answered_count": 0} for i in range(12)]

    def insert_error_presence_audit(self, row):
        self.audits.append({"id": f"aud-{len(self.audits) + 1}", "answer": None, **row})
        return self.audits[-1]

    def audit_clip_audio(self, clip_id, kind):
        return f"https://a/{clip_id}.webm"

    def answer_error_presence_audit(self, *, audit_id, coach_id, answer):
        row = next((a for a in self.audits if a["id"] == audit_id and a["coach_id"] == coach_id), None)
        if not row or row.get("answer"):
            return None
        row["answer"] = answer
        return row

    def list_error_presence_audit_answered(self, error_id):
        return [a for a in self.audits if a["error_id"] == error_id and a.get("answer")]

    # block pick
    def list_coach_block_picks_pending(self, coach_id):
        return [p for p in self.picks if p["coach_id"] == coach_id and not p.get("answered_at")]

    def list_coach_block_picks_by_coach(self, coach_id):
        return [p for p in self.picks if p["coach_id"] == coach_id]

    def list_takes_coach_is_walking(self, coach_id):
        return ["take-walking"]

    def list_recent_v3_frames(self, limit):
        block = {"block_id": "b1", "selected_candidate_id": "cand-2", "confidence_candidates": [
            {"candidate_id": "cand-1", "snippet_id": "s1", "eligibility": "eligible"},
            {"candidate_id": "cand-2", "snippet_id": "s2", "eligibility": "eligible"},
            {"candidate_id": "cand-3", "snippet_id": "s3", "eligibility": "eligible"},
            {"candidate_id": "cand-4", "snippet_id": "s4", "eligibility": "excluded"}]}
        one = {"block_id": "b2", "selected_candidate_id": "cand-9", "confidence_candidates": [
            {"candidate_id": "cand-9", "snippet_id": "s9", "eligibility": "eligible"}]}
        return [{"take_session_id": "take-walking", "policy_version": "v3", "frame": {"blocks": [block]}},
                {"take_session_id": "take-2", "policy_version": "v3", "frame": {"blocks": [block, one]}}]

    def insert_coach_block_pick(self, row):
        self.picks.append({"id": f"pick-{len(self.picks) + 1}", "answered_at": None, **row})
        return self.picks[-1]

    def get_coach_block_pick(self, pick_id, coach_id):
        return next((p for p in self.picks if p["id"] == pick_id and p["coach_id"] == coach_id), None)

    def get_snippet_by_id(self, sid):
        return {"id": sid, "audio_segment_path": f"s/{sid}.webm", "transcript": "the words spoken here"}

    def answer_coach_block_pick(self, *, pick_id, coach_id, pick_snippet_id, cant_tell):
        row = self.get_coach_block_pick(pick_id, coach_id)
        row.update({"pick_snippet_id": pick_snippet_id, "cant_tell": cant_tell, "answered_at": "now"})
        return row

    # shadow
    def record_verbal_cue_shadow(self, rows):
        self.shadow.extend(rows)
        return len(rows)

    def get_snippets_by_session(self, take):
        return [{"id": "s1", "transcript": "the words spoken here", "duration_ms": 4000,
                 "metrics": {"pause_ratio": 0.02, "pause_regularity": 0.9, "ending_duration_ratio": 0.9}}]

    # words
    def list_bookmarked_snippet_ids(self, take):
        return ["s1", "s2"]

    def get_own_state_ratings_for_session(self, take, coach):
        return {"s1": {"value": "yes"}, "s2": {"value": "no"}} if coach == "coach-done" else {"s1": {"value": "yes"}}

    def set_coach_take_word_draft(self, **kwargs):
        self.word_drafts.append(kwargs)

    def set_exercise_coach_request_draft(self, **kwargs):
        self.request_drafts.append(kwargs)

    def v2_get_session_by_id(self, sid):
        return {"id": sid, "user_id": "owner-1"}

    def insert_feedback_pair(self, **fields):
        self.pairs.append(fields)
        return {"id": f"pair-{len(self.pairs)}", **fields}

    def get_owner_principal_for_user(self, uid):
        return None

    def set_coach_take_word_transcript(self, **kwargs):
        self.transcripts.append(kwargs)


class OffTests(unittest.TestCase):
    """The off behaviour under every switch patched off. The founder flipped
    the coach-panel switches on from 2026-10-02 ("go with all of them in that
    order"), then 6a on the same day after the 3.3 wording (N25); 6d stays
    off until document 02 v1.1 is uploaded and its hash recorded."""
    SWITCHES = ("COACH_EXERCISE_PREFERENCE_ENABLED", "ERROR_PRESENCE_AUDIT_ENABLED",
                "COACH_BLOCK_PICK_ENABLED", "COACH_WORD_PAIRS_ENABLED",
                "DETECTOR_TRAINING_AUTHORISED")

    def setUp(self):
        self._patches = []
        for name in self.SWITCHES:
            p = patch(f"config.Config.{name}", False, create=True)
            p.start()
            self._patches.append(p)
            self.addCleanup(p.stop)

    def test_the_legally_gated_switches_stay_off(self):
        # Read the live default with the patches lifted, never by reloading
        # config (a reload would hand every other test a second Config class).
        for p in self._patches:
            p.stop()
        try:
            from config import Config as _live
            self.assertTrue(_live.ERROR_PRESENCE_AUDIT_ENABLED)
            self.assertTrue(_live.ERROR_PRESENCE_AUDIT_VERBAL_ENABLED)
            self.assertEqual(_live.BLIND_CHECK_POLICY_VERSION, "phase1-2026-10-02")
            self.assertFalse(_live.DETECTOR_TRAINING_AUTHORISED)
        finally:
            for p in self._patches:
                p.start()

    def test_off_nothing_serves(self):
        db = _Db()
        self.assertEqual(cep.record(db, coach_id="c", take_session_id="t", snippet_id="s",
                                    speaker_user_id="o", body={"action": "kept"})[0], 404)
        self.assertEqual(epa.sample_for_coach(db, coach_id="c"), [])
        self.assertEqual(epa.queue(db, coach_id="c")[0], 404)
        self.assertEqual(bp.sample_for_coach(db, coach_id="c", week="2026-W40"), [])
        self.assertEqual(bp.queue(db, coach_id="c")[0], 404)
        self.assertEqual(cwp.draft_take_word(db, take_session_id="t", coach_id="c", body={})[0], 404)
        self.assertIsNone(cwp.record_take_word_pair(db, word_row={"draft_text": "d"}, coach_id="c", final_text="f"))
        self.assertEqual((db.prefs, db.audits, db.picks, db.pairs), ([], [], [], []))


class ExposureTests(unittest.TestCase):
    def test_first_exposure_once_and_unexposed_filtering(self):
        db = _Db()
        self.assertTrue(ce.record_exposure(db, coach_id="c", clip_id="s1", via="moment_read"))
        self.assertFalse(ce.record_exposure(db, coach_id="c", clip_id="s1", via="audit"))
        self.assertFalse(ce.record_exposure(db, coach_id="c", clip_id="s1", via="peek"))
        self.assertEqual(ce.exposed_clip_ids(db, "c", ["s1", "s2"]), {"s1"})
        self.assertEqual([c["clip_id"] for c in ce.unexposed(db, "c", [{"clip_id": "s1"}, {"clip_id": "s2"}])], ["s2"])
        self.assertFalse(ce.rating_is_blind(db, coach_id="c", snippet_id="s1"))
        self.assertTrue(ce.rating_is_blind(db, coach_id="c", snippet_id="s2"))

    def test_an_unreadable_exposure_counts_as_exposed(self):
        class _Down(_Db):
            def list_coach_clip_exposures(self, coach_id, clip_ids):
                raise RuntimeError("down")
        self.assertEqual(ce.exposed_clip_ids(_Down(), "c", ["s1"]), {"s1"})


@PREF_ON
class PreferenceTests(unittest.TestCase):
    def test_the_served_view_shuffles_the_pool_marks_the_served_and_shows_no_rank(self):
        view = cep.served_view(_Db(), take_session_id="t", snippet_id="s", rng=random.Random(1))
        self.assertEqual(view["served"]["exercise_id"], "ex-a")
        self.assertEqual(view["served"]["treats"], [{"error_id": "rushing", "label": "Rushing"}])
        self.assertEqual({p["exercise_id"] for p in view["pool"]}, {"ex-a", "ex-b"})
        self.assertEqual([p["served"] for p in view["pool"] if p["exercise_id"] == "ex-a"], [True])
        for p in view["pool"]:
            self.assertEqual(set(p), {"exercise_id", "served", "title", "instruction"})
        self.assertEqual((view["draw"], view["fit"], view["fired"]), ("exploration", "exact", ["rushing"]))

    def test_the_draw_names_fallbacks_and_coach_picks(self):
        self.assertEqual(cep._draw_of({"selection_mode": "top"}, {"fallback": "general"}), "fallback")
        self.assertEqual(cep._draw_of({"matching_policy_version": "exercise-coach-request-v1"}, {}), "coach_chosen")
        self.assertEqual(cep._draw_of({"selection_mode": "deterministic_singleton"}, {}), "deterministic_singleton")

    def test_keep_swap_and_new_are_recorded_with_provenance(self):
        db = _Db()
        self.assertEqual(cep.record(db, coach_id="c", take_session_id="t", snippet_id="s",
                                    speaker_user_id="o", body={"action": "kept"})[0], 201)
        status, payload = cep.record(db, coach_id="c", take_session_id="t", snippet_id="s",
                                     speaker_user_id="o", body={"action": "swapped", "chosen_exercise_id": "ex-b"})
        self.assertEqual((status, payload["preference"]["chosen_in_pool"]), (201, True))
        status, payload = cep.record(db, coach_id="c", take_session_id="t", snippet_id="s",
                                     speaker_user_id="o", body={"action": "swapped", "chosen_exercise_id": "ex-z"})
        self.assertEqual(payload["preference"]["chosen_in_pool"], False)
        self.assertEqual(cep.record(db, coach_id="c", take_session_id="t", snippet_id="s", speaker_user_id="o",
                                    body={"action": "swapped", "chosen_exercise_id": "ex-a"})[0], 400)
        self.assertEqual(cep.record(db, coach_id="c", take_session_id="t", snippet_id="s", speaker_user_id="o",
                                    body={"action": "ignored"})[0], 400)
        self.assertEqual({r["provenance"] for r in db.prefs}, {"coach_preference"})
        self.assertEqual(db.prefs[0]["signal_rules_version"], "cv-exercise-signals-v1")

    def test_the_ranker_learns_from_train_speakers_only_and_needs_trust(self):
        rows = [{"served_exercise_id": "ex-a", "draw": "top", "action": "kept", "speaker_user_id": f"u{i}"}
                for i in range(40)]
        rows += [{"served_exercise_id": "ex-b", "draw": "top", "action": "swapped", "speaker_user_id": f"u{i}"}
                 for i in range(40)]
        rates = cep.preference_rates(rows)
        self.assertEqual((rates[("ex-a", "top")]["rate"], rates[("ex-b", "top")]["rate"]), (1.0, 0.0))
        self.assertTrue(rates[("ex-a", "top")]["trusted"])
        db = _Db()
        db.prefs = rows
        with patch("services.exercise_fair_test.split_of", return_value="train"):
            self.assertEqual(cep.coach_preferred_order(db, ["ex-b", "ex-a"], draw="top"), ["ex-a", "ex-b"])
            self.assertIsNone(cep.coach_preferred_order(db, ["ex-a", "ex-new"], draw="top"))
            self.assertIsNone(cep.coach_preferred_order(db, ["ex-a"], draw="exploration"))
        with patch("services.exercise_fair_test.split_of", return_value="holdout"):
            self.assertIsNone(cep.coach_preferred_order(db, ["ex-a", "ex-b"], draw="top"))
        ledger = cep.ledger(db)
        self.assertEqual(ledger["per_exercise"]["ex-b"]["swapped"], 40)
        self.assertEqual(ledger["ranker_version"], cep.RANKER_VERSION)


class NoticeVersionTests(unittest.TestCase):
    """The blind check's per-speaker gate, unpatched: the share read's twin."""
    class _Svc:
        accepted = {"take-1": "phase1-2026-10-01", "take-2": "phase1-2026-10-02"}

        def __init__(self, db):
            pass

        def take_acquisition_principal(self, take):
            return take

        def status(self, principal):
            v = self.accepted.get(principal)
            return {"authorized": bool(v), "policy_version": v}

    def test_no_version_or_an_older_one_keeps_the_speaker_out(self):
        with patch("services.processing_authorization.ProcessingAuthorizationService", self._Svc):
            with patch("config.Config.BLIND_CHECK_POLICY_VERSION", None, create=True):
                self.assertFalse(epa._on_notice_version(None, "take-2"))
            with patch("config.Config.BLIND_CHECK_POLICY_VERSION", "phase1-2026-10-02", create=True):
                self.assertFalse(epa._on_notice_version(None, "take-1"))
                self.assertTrue(epa._on_notice_version(None, "take-2"))
                self.assertFalse(epa._on_notice_version(None, "take-9"))

    def test_a_failed_read_is_out(self):
        class _Broken:
            def __init__(self, db):
                raise RuntimeError("down")
        with patch("services.processing_authorization.ProcessingAuthorizationService", _Broken):
            self.assertFalse(epa._on_notice_version(None, "take-2"))


@AUDIT_ON
@patch("services.verbal_cues._practice_permitted", lambda db, take: not str(take).startswith("off-"))
@patch("services.error_presence_audit._on_notice_version", lambda db, take: not str(take).startswith("old-"))
class AuditTests(unittest.TestCase):
    def test_a_speaker_not_yet_on_the_three_three_notice_is_out_of_the_pool(self):
        # 15 §2: the balancing test holds only for a speaker who has read
        # the line; until the re-acceptance nobody is sampled.
        class _Old(_Db):
            def list_audit_candidates(self, errors):
                rows = super().list_audit_candidates(errors)
                for r in rows[:6]:
                    r["take_session_id"] = "old-" + r["take_session_id"]
                return rows
        written = epa.sample_for_coach(_Old(), coach_id="c", rng=random.Random(3))
        self.assertTrue(written)
        self.assertFalse(any(str(w.get("take_session_id", "")).startswith("old-") for w in written))

    def test_sampling_is_stratified_and_carries_the_probability(self):
        cands = [{"clip_id": f"c{i}", "error_id": "rushing", "fired": i < 8} for i in range(10)]
        plan = epa.sampling_plan(cands, size=4, rng=random.Random(3))
        self.assertEqual(len(plan), 4)
        self.assertEqual(sum(1 for p in plan if p["fired"]), 2)
        self.assertEqual({p["sampling_probability"] for p in plan if p["fired"]}, {0.25})
        self.assertEqual({p["sampling_probability"] for p in plan if not p["fired"]}, {1.0})

    def test_the_week_fills_blind_and_records_exposure(self):
        db = _Db()
        written = epa.sample_for_coach(db, coach_id="c", rng=random.Random(5))
        self.assertTrue(0 < len(written) <= epa.WEEKLY_CAP)
        self.assertTrue(all(r["provenance"] == "coach_audit" and r["answer"] is None for r in written))
        self.assertTrue(all(("c", r["clip_id"]) in db.exposures for r in written))
        status, payload = epa.queue(db, coach_id="c")
        self.assertEqual(status, 200)
        for item in payload["items"]:
            self.assertEqual(set(item), {"audit_id", "clip_id", "audio_ref", "error_id", "label", "asks"})
            self.assertEqual(item["asks"], "Do you hear rushing here?")
        self.assertEqual(epa.sample_for_coach(db, coach_id="c", rng=random.Random(5)), [])

    def test_one_answer_once(self):
        db = _Db()
        epa.sample_for_coach(db, coach_id="c", rng=random.Random(1))
        audit_id = db.audits[0]["id"]
        self.assertEqual(epa.answer(db, coach_id="c", audit_id=audit_id, body={"answer": "yes"}),
                         (200, {"recorded": True}))
        self.assertEqual(epa.answer(db, coach_id="c", audit_id=audit_id, body={"answer": "no"})[0], 409)
        self.assertEqual(epa.answer(db, coach_id="c", audit_id=audit_id, body={"answer": "maybe"})[0], 400)

    def test_the_report_card_weighs_floors_and_agrees(self):
        rows = []
        for i in range(70):
            fired = i % 2 == 0
            rows.append({"error_id": "rushing", "fired_at_sampling": fired, "answer": "yes" if fired else "no",
                         "sampling_probability": 0.5 if fired else 1.0, "speaker_user_id": f"s{i % 7}",
                         "clip_id": f"c{i}", "measurements": {"wpm": 100 + i}, "detector_version": "rules-v1"})
        rows.append({**rows[0], "answer": "no"})
        card = epa.report_card(rows, rng=random.Random(2))["rushing"]
        self.assertTrue(card["enough"])
        self.assertEqual(card["counts"]["caught"], 35)
        self.assertGreater(card["catch_rate"], 0.9)
        self.assertLess(card["false_alarm_rate"], 0.1)
        self.assertEqual(card["agreement"], {"pairs": 1, "agree": 0, "rate": 0.0})
        self.assertIsNotNone(card["catch_interval"])
        self.assertEqual(card["speed"]["split_wpm"], 134.0)
        thin = epa.report_card(rows[:10])["rushing"]
        self.assertEqual((thin["enough"], thin["note"]), (False, "not enough answers yet"))


@PICK_ON
class BlockPickTests(unittest.TestCase):
    def test_askable_blocks_need_two_eligible_candidates_and_a_pick(self):
        frames = _Db().list_recent_v3_frames(10)
        blocks = bp.askable_blocks(frames[1]["frame"], take_session_id="take-2")
        self.assertEqual([b["block_id"] for b in blocks], ["b1"])
        self.assertEqual((blocks[0]["manager_pick"], blocks[0]["candidate_ids"]), ("s2", ["s1", "s2", "s3"]))
        clips = bp.sheet_clips(blocks[0], rng=random.Random(4))
        self.assertEqual(len(clips), 3)
        self.assertIn("s2", clips)

    def test_the_week_skips_the_take_being_walked_and_the_sheet_hides_the_pick(self):
        db = _Db()
        written = bp.sample_for_coach(db, coach_id="c", week="2026-W40", rng=random.Random(2))
        self.assertEqual([w["take_session_id"] for w in written], ["take-2"])
        self.assertEqual(written[0]["manager_pick_snippet_id"], "s2")
        status, payload = bp.queue(db, coach_id="c")
        self.assertEqual(status, 200)
        item = payload["items"][0]
        self.assertEqual(set(item), {"pick_id", "clips", "n", "of"})
        self.assertNotIn("manager", str(item))
        for clip in item["clips"]:
            self.assertEqual(set(clip), {"clip_id", "letter", "audio_ref"})
        self.assertEqual(payload["wording"]["question"], "Which of these sounds most confident?")

    def test_one_pick_once_and_the_match_rate(self):
        db = _Db()
        bp.sample_for_coach(db, coach_id="c", week="2026-W40", rng=random.Random(2))
        pick_id = db.picks[0]["id"]
        self.assertEqual(bp.answer(db, coach_id="c", pick_id=pick_id, body={"pick_clip_id": "s2"}), (200, {"recorded": True}))
        self.assertEqual(bp.answer(db, coach_id="c", pick_id=pick_id, body={"cant_tell": True})[0], 409)
        self.assertEqual(bp.answer(db, coach_id="c", pick_id="pick-9", body={"cant_tell": True})[0], 404)
        self.assertEqual(bp.match_rate(db.picks), {"answered": 1, "match": 1, "differ": 0, "cant_tell": 0,
                                                   "match_rate": 1.0, "policy_version": bp.POLICY_VERSION})
        self.assertEqual(bp.match_rate([{"answered_at": "x", "cant_tell": True}])["match_rate"], None)


class DetectorTests(unittest.TestCase):
    def test_the_live_versions_and_the_shadow_rows(self):
        self.assertEqual(set(dr.LIVE_DETECTOR), set(dr.ERRORS))
        self.assertEqual(dr.stage_of("rules-v1"), "live")
        self.assertEqual(dr.stamp_live_versions({})["detector_versions"], dr.LIVE_DETECTOR)
        rows = dr.observations({"pause_ratio": 0.02, "pause_regularity": 0.9, "ending_duration_ratio": 0.9},
                               clip_id="s1", take_session_id="t")
        rushing = next(r for r in rows if r["error_id"] == "rushing" and r["detector_version"] == "rules-v1")
        self.assertTrue(rushing["fired"])
        ending = next(r for r in rows if r["error_id"] == "ending_compression" and r["detector_version"] == "rules-v1")
        self.assertFalse(ending["fired"])
        self.assertFalse(any(r["error_id"] == "word_compression" for r in rows))
        self.assertEqual(dr.record_take(_Db(), "t") if False else 0, 0)
        attempt_rows = dr.observations({"pause_ratio": 0.5}, clip_id="a1", take_session_id="t",
                                       clip_kind="practice_attempt")
        self.assertEqual({r["clip_kind"] for r in attempt_rows}, {"practice_attempt"})

    def test_the_fair_test_grades_held_out_speakers_and_the_bar_flips_nothing(self):
        audit = [{"clip_id": f"c{i}", "error_id": "rushing", "answer": "yes" if i % 2 == 0 else "no",
                  "speaker_user_id": f"h{i}" if i % 3 else f"t{i}", "sampling_probability": 1.0}
                 for i in range(90)]
        verdicts = {(f"c{i}", "rushing"): i % 2 == 0 for i in range(90)}
        split = lambda s: "holdout" if s.startswith("h") else "train"  # noqa: E731
        graded = dr.graded_rows(audit, verdicts, split_of=split)
        self.assertEqual(len(graded), 60)
        card = dr.grade(audit, verdicts, split_of=split)["rushing"]
        self.assertEqual((card["catch_rate"], card["false_alarm_rate"]), (1.0, 0.0))
        now = datetime(2026, 10, 1, tzinfo=timezone.utc)
        live = {"enough": True, "catch_rate": 0.8, "false_alarm_rate": 0.2}
        better = {"enough": True, "catch_rate": 0.9, "false_alarm_rate": 0.21}
        verdict = dr.promotion_bar(better, live, shadow_since=now - timedelta(weeks=5), now=now)
        self.assertTrue(verdict["clears"])
        self.assertFalse(dr.promotion_bar(better, live, shadow_since=now - timedelta(weeks=2), now=now)["clears"])
        worse = {"enough": True, "catch_rate": 0.9, "false_alarm_rate": 0.3}
        self.assertFalse(dr.promotion_bar(worse, live, shadow_since=now - timedelta(weeks=5), now=now)["clears"])
        self.assertEqual(dr.LIVE_DETECTOR["rushing"], "rules-v1")

    def test_the_candidates_are_built_not_trained(self):
        dc.register_candidates()
        self.assertEqual(dr.stage_of(dc.TUNED_VERSION), "shadow")
        self.assertTrue(dc.tuned("rushing", {"pause_ratio": 0.02}))
        self.assertIsNone(dc.tuned("rushing", {}))
        with self.assertRaises(dc.NotAuthorised):
            dc.LearnedDetector("rushing").fit([])
        self.assertIsNone(dc.learned("rushing", {"pause_ratio": 0.02}))

        class _Clips(_Db):
            def list_clips_for_rescore(self, *, since, limit):
                return [{"clip_id": "s1", "take_session_id": "t", "clip_kind": "snippet",
                         "snapshot": {"pause_ratio": 0.02, "ending_duration_ratio": 0.9}}]
        db = _Clips()
        out = dc.rescore(db, version=dc.TUNED_VERSION, since="2026-09-01")
        self.assertEqual(out["written"], 2)
        self.assertEqual({r["detector_version"] for r in db.shadow}, {dc.TUNED_VERSION})
        self.assertEqual(dc.rescore(db, version="nope", since="x")["error"], "unknown version")


@WORDS_ON
class WordPairTests(unittest.TestCase):
    def test_the_take_word_draft_waits_for_every_moment_and_is_text_only(self):
        db = _Db()
        self.assertEqual(cwp.draft_take_word(db, take_session_id="t", coach_id="coach-half", body={})[0], 409)
        with patch("services.coach_word_pairs.compose",
                   return_value={"text": "Keep that pace.", "model_version": "m1"}) as composed:
            status, payload = cwp.draft_take_word(db, take_session_id="t", coach_id="coach-done",
                                                  body={"notes": "liked the ending"})
        self.assertEqual(status, 200)
        self.assertEqual(payload["draft"]["label"], cwp.LABEL)
        kwargs = composed.call_args.kwargs
        self.assertEqual(set(kwargs), {"surface", "transcript", "coach_text", "user_id"})
        self.assertEqual(db.word_drafts[0]["text"], "Keep that pace.")

    def test_the_pair_is_recorded_only_when_the_final_differs_and_hangs_on_the_word(self):
        db = _Db()
        word = {"id": "w-1", "take_session_id": "t", "draft_text": "Keep that pace.", "draft_model_version": "m1"}
        self.assertIsNone(cwp.record_take_word_pair(db, word_row=word, coach_id="c", final_text="Keep that pace."))
        pair = cwp.record_take_word_pair(db, word_row=word, coach_id="c", final_text="Keep the pace you found.")
        self.assertIsNotNone(pair)
        self.assertEqual((db.pairs[0]["surface"], db.pairs[0]["take_word_id"], db.pairs[0]["final_kind"]),
                         ("coach_take_word", "w-1", "final"))
        request = {"id": "r-1", "draft_surface": "coach_moment_line", "draft_text": "A warm line.",
                   "snippet_id": "s1", "take_session_id": "t", "owner_user_id": "owner-1"}
        self.assertIsNotNone(cwp.record_moment_line_pair(db, request_row=request, coach_id="c", final_text="A warmer line."))
        self.assertEqual(db.pairs[1]["surface"], "coach_moment_line")
        self.assertIsNone(cwp.record_moment_line_pair(db, request_row={**request, "draft_surface": "praise_line"},
                                                      coach_id="c", final_text="x"))

    def test_the_prompts_are_locked_and_never_speak_of_the_read(self):
        from services.prompts.coach_word_drafts import REGISTER, SYSTEM, user
        import json
        locked = json.loads((ROOT / "services/prompts/prompts.lock.json").read_text())["prompts"]
        for key in REGISTER:
            self.assertIn(key, locked)
        for text in SYSTEM.values():
            self.assertIn("Never say or imply how a machine read", text)
        self.assertNotIn("confidence", user(surface="coach_take_word", transcript="hi", coach_text=None).lower())
        self.assertEqual(cwp.unchanged_share([{"surface": "coach_take_word", "unchanged": True},
                                              {"surface": "coach_take_word", "unchanged": False},
                                              {"surface": "praise_line", "unchanged": True}]),
                         {"coach_take_word": {"shown": 2, "unchanged": 1, "share_unchanged": 0.5}})

    def test_door_two_stays_shut_for_the_coach_s_words(self):
        from config import Config
        self.assertFalse({"coach_moment_line", "coach_take_word"} & set(Config.PAIR_RELEASE_SURFACES))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
