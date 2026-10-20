"""
STORY    As a speaker, I want each practice try judged by the machine as Good
         job or try again with a word of encouragement, up to three tries,
         without numbers, so that practice moves me forward.
OUTCOME
  O1  decide returns praise, again or moved_on with a line key; a "not yet"
      names the cue that went the wrong way; a rewrite is judged on its
      voice alone; a voice only a little surer is not yet a Good job, one
      surer by the lock's margin is (N84).
  O2  The loop takes up to three tries, a later praise moves the landing
      try, a fourth try is refused (409).
  O3  The check route answers the speaker with the outcome and the line key
      only: no lane, cue value or measured index (Never-1: no scores,
      numbers or verdicts shown to speakers).
  O4  The machine's decision is never written as the speaker's own answer
      (L3).
PROVES   O1 -> test_a_not_yet_names_the_reading_that_went_the_wrong_way,
               test_a_clearer_version_try_is_checked_on_its_voice_alone,
               test_a_good_job_only_when_the_voice_is_clearly_surer
         O2 -> test_a_good_job_no_longer_ends_the_loop_the_speaker_may_try_until_three
         O3 -> test_the_route_answers_in_a_key_never_a_measure
         O4 -> test_the_route_answers_in_a_key_never_a_measure
WHY      Founder lock 2026-10-06 (the Feedback walk; decisions log N52.3).
"""
from __future__ import annotations

import inspect
import json
import re
from unittest.mock import patch


# ── the decision ──────────────────────────────────────────────────────────

def _try(original: dict, attempt: dict, index: int = 1) -> dict:
    return {"id": f"a{index}", "attempt_index": index,
            "comparison": {"cues": {"original": original, "attempt": attempt}}}


def test_a_not_yet_names_the_reading_that_went_the_wrong_way():
    """Option A (founder 2026-10-13): the cue that dropped most against the
    original names the line; none clearly moved is the general one. The
    screen still sees only the outcome and the key (AC-9)."""
    from services.practice_check import decide, public_check
    practice = {"kind": "exercise"}
    # The pitch sat much higher than the original; the pace dipped a little.
    tried = _try({"mean_pitch": 0.4, "speech_rate": 0.2}, {"mean_pitch": -0.9, "speech_rate": -0.4})
    check = decide(practice, [tried], "a1")
    assert (check["next"], check["key"]) == ("again", "miss:settled_pitch")
    assert public_check(check) == {"next": "again", "key": "miss:settled_pitch"}
    calm = _try({"mean_pitch": 0.1}, {"mean_pitch": 0.0})
    assert decide(practice, [calm], "a1")["key"] == "effort"


def test_a_clearer_version_try_is_checked_on_its_voice_alone():
    """Founder 2026-10-18, "words first, then voice": the accepted words are
    new, so only the delivery counts, against the original clip. Better is
    a Good job and no AI clip; flat is not yet (the AI clip comes); a try
    with no sound read is never pushed to the AI clip."""
    from services.practice_check import decide
    practice = {"kind": "rewrite"}
    better = _try({"mean_pitch": -0.6}, {"mean_pitch": 0.4})
    assert decide(practice, [better], "a1")["next"] == "praise"
    flat = _try({"mean_pitch": 0.1}, {"mean_pitch": 0.0})
    assert decide(practice, [flat], "a1")["next"] == "again"
    unheard = {"id": "a1", "attempt_index": 1, "comparison": {}}
    assert decide(practice, [unheard], "a1")["next"] == "praise"
    third = [_try({}, {}, 1), _try({}, {}, 2), _try({"mean_pitch": 0.1}, {"mean_pitch": 0.0}, 3)]
    assert decide(practice, third, "a3")["next"] == "moved_on"


def test_a_good_job_only_when_the_voice_is_clearly_surer():
    """N84 (founder 2026-10-20, "Good job means clearly better, as locked"):
    the voice-confidence composite must rise by the lock's margin; a rise
    smaller than that is not yet, and the AI clip gets its turn."""
    from services.after_practice import GOOD_JOB_MARGIN
    from services.practice_check import decide
    practice = {"kind": "exercise", "acoustic_evidence": {"snapshot": {"confidence": 0.20}}}

    def tried(confidence: float) -> dict:
        return {"id": "a1", "attempt_index": 1, "comparison": {},
                "acoustic_metrics": {"confidence": confidence}}
    assert decide(practice, [tried(0.20 + GOOD_JOB_MARGIN / 2)], "a1")["next"] == "again"
    clearly = decide(practice, [tried(0.20 + GOOD_JOB_MARGIN + 0.01)], "a1")
    assert (clearly["next"], clearly["key"]) == ("praise", "more_assured")


# ── the loop ──────────────────────────────────────────────────────────────


class _PracticeDb:
    """One practice row and its tries, as the checker reads and writes them."""

    def __init__(self, practice):
        self.practice, self.attempts = practice, []

    def list_confident_voice_practice_attempts(self, _practice_id):
        return list(self.attempts)

    def update_confident_voice_practice(self, _practice_id, _owner, fields):
        self.practice = {**self.practice, **fields}
        return self.practice


def test_a_good_job_no_longer_ends_the_loop_the_speaker_may_try_until_three(monkeypatch):
    """Founder 2026-10-16 (the Exercise screen as one thread): after a Good
    job the speaker may still practise, up to three tries in all. A later
    praise is the try the practice lands on; a later "not yet" leaves the
    earlier praise standing, so the helper words tapped from it stay; a
    fourth try is refused."""
    from services import practice_check
    answers = {"a1": "praise", "a2": "again", "a3": "praise"}
    monkeypatch.setattr(practice_check, "decide", lambda _p, _a, i: {
        "next": answers[i], "key": "effort", "lane": "none", "attempt_id": i,
        "attempt_index": int(i[1:]), "rule_version": "t", "decided_by": "machine"})
    db = _PracticeDb({"id": "p", "kind": "exercise", "status": "open"})

    def tried(n):
        db.attempts.append({"id": f"a{n}", "attempt_index": n, "transcript": "the window closes once"})
        return practice_check.check_attempt(db, db.practice, f"a{n}", "owner")

    status, body = tried(1)
    assert (status, body["outcome"], db.practice["selected_attempt_id"]) == (200, "done", "a1")
    assert practice_check.machine_closed(db.practice)
    assert practice_check.takes_more_tries(db.practice, len(db.attempts))
    status, body = tried(2)
    assert (status, body["outcome"]) == (200, "again")
    assert db.practice["selected_attempt_id"] == "a1" and practice_check.machine_closed(db.practice)
    status, body = tried(3)
    assert (status, body["outcome"], db.practice["selected_attempt_id"]) == (200, "done", "a3")
    assert not practice_check.takes_more_tries(db.practice, len(db.attempts))
    assert tried(4)[0] == 409


# ── the route ─────────────────────────────────────────────────────────────

def test_the_route_answers_in_a_key_never_a_measure():
    from flask import Flask, request

    from routes.v2 import user_sessions
    pid, aid = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"
    db = _PracticeDb({"id": pid, "kind": "exercise", "status": "open"})
    db.attempts.append({
        **_try({"mean_pitch": -0.6, "speech_rate": -0.5},
               {"mean_pitch": 0.6, "speech_rate": 0.4}),
        "id": aid, "transcript": "the window closes once",
    })
    written = []

    def update(practice_id, owner, fields):
        written.append(fields)
        return _PracticeDb.update_confident_voice_practice(db, practice_id, owner, fields)

    route = inspect.unwrap(user_sessions.v2_check_confident_voice_practice_attempt)
    with Flask(__name__).test_request_context(method="POST"), \
            patch.object(user_sessions.db, "get_confident_voice_practice",
                         side_effect=lambda *_: db.practice), \
            patch.object(user_sessions.db, "list_confident_voice_practice_attempts",
                         side_effect=db.list_confident_voice_practice_attempts), \
            patch.object(user_sessions.db, "update_confident_voice_practice",
                         side_effect=update):
        request.user_id = "owner"
        resp, status = route(pid, aid)
        body = resp.get_json()

    assert status == 200
    # What the speaker gets: the outcome, the line key and their own words.
    assert body["outcome"] == "done"
    assert set(body["check"]) == {"next", "key"} and body["check"]["next"] == "praise"
    assert body["check"]["key"]
    assert body["practice"]["after_practice"] == body["check"]
    assert body["attempt_transcript"] == "the window closes once"
    # What it must not get: the lane, the rule, the cues or any measure.
    raw = json.dumps({"check": body["check"], "after": body["practice"]["after_practice"]})
    assert re.search(r"\d", raw) is None
    for hidden in ("lane", "rule_version", "decided_by", "mean_pitch", "comparison"):
        assert hidden not in json.dumps(body)
    # L3: the machine's praise is stored as its own decision, never as an answer.
    assert written and written[-1]["after_practice"]["decided_by"] == "machine"
    for fields in written:
        assert not {"user_answer", "final_user_answer"} & set(fields)
    assert body["practice"]["final_user_answer"] is None
