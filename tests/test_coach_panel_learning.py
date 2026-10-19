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

import json
import random
import re
import unittest
from unittest.mock import patch

from services import error_presence_audit as epa


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


@patch("services.verbal_cues._practice_permitted", lambda db, take: not str(take).startswith("off-"))
@patch("services.error_presence_audit._on_notice_version", lambda db, take: not str(take).startswith("old-"))
@patch("services.error_presence_audit._objected", lambda db, take: str(take).startswith("obj-"))
class AuditTests(unittest.TestCase):


    def test_one_answer_once(self):
        db = _Db()
        epa.sample_for_coach(db, coach_id="c", rng=random.Random(1))
        audit_id = db.audits[0]["id"]
        self.assertEqual(epa.answer(db, coach_id="c", audit_id=audit_id, body={"answer": "yes"}),
                         (200, {"recorded": True}))
        self.assertEqual(epa.answer(db, coach_id="c", audit_id=audit_id, body={"answer": "no"})[0], 409)
        self.assertEqual(epa.answer(db, coach_id="c", audit_id=audit_id, body={"answer": "maybe"})[0], 400)


# Incident: a Take has one frame per policy version sharing block ids, and an
# insert refused by coach_block_pick_once (a 500) emptied the coach's queue.
@patch("services.pair_consent.take_may_reach_a_coach_sheet", lambda db, take: True)
def test_a_refused_block_pick_is_skipped_and_the_rest_are_written():
    from services import coach_block_pick as bp
    db = _Db()
    frames = [f for f in _Db().list_recent_v3_frames(200) if f["take_session_id"] == "take-2"]
    other = json.loads(re.sub(r'"s(\d)"', r'"t\1"', json.dumps(frames))
                       .replace("take-2", "take-3").replace('"b1"', '"b3"'))
    db.list_recent_v3_frames = lambda limit=200: frames + [
        {**f, "policy_version": "v3-older"} for f in frames] + other
    plain = db.insert_coach_block_pick

    def once(row):
        if row["take_session_id"] == "take-2":  # another writer got there first
            raise RuntimeError("duplicate key value violates coach_block_pick_once")
        return plain(row)

    db.insert_coach_block_pick = once
    written = bp.sample_for_coach(db, coach_id="coach-1", week="w", rng=random.Random(2))
    assert [(w["take_session_id"], w["block_id"]) for w in written] == [("take-3", "b3")]

if __name__ == "__main__":  # pragma: no cover
    unittest.main()
